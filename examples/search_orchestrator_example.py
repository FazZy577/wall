"""Deterministic offline example for the complete search orchestration flow."""

import asyncio
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.search_orchestrator import (
    SearchOrchestrationResult,
    SearchPlan,
)
from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from application.use_cases.default_opportunity_scanner import (
    DefaultOpportunityScanner,
)
from application.use_cases.default_search_orchestrator import (
    DefaultSearchOrchestrator,
)
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.filters.rule_based_comparable_filter import (
    RuleBasedComparableFilter,
)
from infrastructure.marketplaces.wallapop.adapter import WallapopCandidateSearchAdapter
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics

_LATITUDE = 40.4168
_LONGITUDE = -3.7038
_MAX_RESULTS = 10


class _OfflineMarketplaceSearch(IMarketplaceSearch):
    """Small in-memory implementation of the raw marketplace search port."""

    def __init__(self, responses: Mapping[str, Sequence[dict[str, Any]]]) -> None:
        self._responses = {
            self._normalize(keywords): tuple(deepcopy(list(items)))
            for keywords, items in responses.items()
        }

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Return a fresh bounded response without network access."""
        del latitude, longitude
        response = deepcopy(list(self._responses.get(self._normalize(keywords), ())))
        return response[:max_results]

    @staticmethod
    def _normalize(keywords: str) -> str:
        return " ".join(keywords.strip().casefold().split())


def _raw_listing(
    listing_id: str,
    title: str,
    price: str,
    *,
    description: str,
) -> dict[str, Any]:
    return {
        "id": listing_id,
        "title": title,
        "description": description,
        "price": price,
        "currency": "EUR",
        "web_slug": listing_id,
    }


def _candidate_responses() -> dict[str, Sequence[dict[str, Any]]]:
    """Build candidate and comparable responses for the offline plan."""
    individual = _raw_listing(
        "offline-individual",
        "GTA V PS4 individual",
        "5.00",
        description="Juego individual de PS4",
    )
    repeated_individual = _raw_listing(
        "offline-individual",
        "GTA V PS4 repeated result",
        "8.00",
        description="Second appearance of the same listing",
    )
    lot = _raw_listing(
        "offline-lot",
        "Lote GTA V y RDR2 PS4",
        "10.00",
        description="Dos videojuegos completos",
    )
    gta_comparables = [
        _raw_listing(
            f"offline-gta-comparable-{index}",
            "GTA V PS4 juego",
            str(price),
            description="Comparable individual de GTA V",
        )
        for index, price in enumerate(range(18, 38))
    ]
    rdr2_comparables = [
        _raw_listing(
            f"offline-rdr2-comparable-{index}",
            "Red Dead Redemption 2 PS4 juego",
            str(price),
            description="Comparable individual de RDR2",
        )
        for index, price in enumerate(range(24, 44))
    ]
    return {
        "individual": [individual],
        "lot": [lot],
        "repeat": [repeated_individual],
        "gta v": gta_comparables,
        "rdr2": rdr2_comparables,
    }


def _build_orchestrator() -> DefaultSearchOrchestrator:
    """Wire production components to the deterministic offline port."""
    marketplace_search = _OfflineMarketplaceSearch(_candidate_responses())
    candidate_detector = FuzzyGameDetector()
    comparable_detector = FuzzyGameDetector()
    price_collector = WallapopPriceCollector(
        marketplace_search=marketplace_search,
        game_detector=comparable_detector,
        comparable_filter=RuleBasedComparableFilter(),
    )
    dataset_builder = DefaultPriceDatasetBuilder()
    statistics = DefaultPriceStatistics()
    outlier_removal = DefaultOutlierRemoval()
    market_estimator = DefaultMarketPriceEstimator()
    economic_policy = ResaleEconomicPolicy.neutral()

    individual_scanner = DefaultOpportunityScanner(
        game_detector=candidate_detector,
        price_collector=price_collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        arbitrage_detector=DefaultArbitrageOpportunityDetector(economic_policy),
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    lot_scanner = DefaultLotOpportunityScanner(
        game_detector=candidate_detector,
        price_collector=price_collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        lot_analyzer=DefaultLotOpportunityAnalyzer(economic_policy),
    )
    return DefaultSearchOrchestrator(
        candidate_search=WallapopCandidateSearchAdapter(marketplace_search),
        game_detector=candidate_detector,
        candidate_eligibility_policy=RuleBasedCandidateEligibilityPolicy(),
        opportunity_scanner=individual_scanner,
        lot_opportunity_scanner=lot_scanner,
    )


def _query(keywords: str) -> SearchQuery:
    return SearchQuery(
        keywords=keywords,
        latitude=_LATITUDE,
        longitude=_LONGITUDE,
        max_results=_MAX_RESULTS,
    )


def _print_report(result: SearchOrchestrationResult) -> None:
    """Print only data exposed by the orchestration result contracts."""
    print("SEARCH ORCHESTRATION REPORT")
    print()
    print("Queries:")
    print(f"- total: {result.total_queries}")
    print(f"- executed: {result.executed_queries}")
    print(f"- duplicates: {result.duplicate_queries}")
    print()
    print("Candidates:")
    print(f"- received: {result.valid_candidates_received}")
    print(f"- duplicates: {result.duplicate_candidates}")
    print(f"- unique: {result.unique_candidates}")
    print(f"- individual: {result.individual_candidates}")
    print(f"- lots: {result.lot_candidates}")
    print(f"- undetected: {result.undetected_candidates}")
    print()
    print("Individual opportunities:")
    if result.individual_result is None:
        print("- none")
    else:
        for opportunity in result.individual_result.opportunities:
            print(
                f"- {opportunity.game.canonical_name} | "
                f"listing price {opportunity.listing_price:.2f} EUR | "
                f"market value {opportunity.market_price:.2f} EUR | "
                f"net profit {opportunity.net_profit:.2f} EUR | "
                f"ROI {opportunity.net_roi_percentage:.2f}% | "
                f"recommendation {opportunity.recommendation.upper()} | "
                f"opportunity score {opportunity.opportunity_score:.1f}"
            )
    print()
    print("Lot results:")
    if not result.lot_results:
        print("- none")
    for lot_result in result.lot_results:
        game_names = ", ".join(
            game.canonical_name for game in lot_result.detected_games
        )
        recommendation = (
            lot_result.opportunity.recommendation.upper()
            if lot_result.opportunity is not None
            else "none"
        )
        print(
            f"- listing {lot_result.listing.listing_id} | "
            f"games detected {game_names} | "
            f"games valued {lot_result.successfully_valued_games} | "
            f"failures {lot_result.failed_games} | "
            f"recommendation {recommendation}"
        )
    print()
    print("Failures:")
    print(f"- query failures: {len(result.query_failures)}")
    print(f"- item failures: {len(result.item_failures)}")
    print(f"- routing failures: {len(result.routing_failures)}")
    print()
    print(f"Processing time: {result.processing_time:.6f} seconds")


async def main() -> None:
    """Run the complete offline orchestration pipeline."""
    orchestrator = _build_orchestrator()
    plan = SearchPlan(
        (
            _query("individual"),
            _query("lot"),
            _query("repeat"),
            _query(" INDIVIDUAL "),
        )
    )
    result = await orchestrator.execute(plan)
    _print_report(result)


if __name__ == "__main__":
    asyncio.run(main())
