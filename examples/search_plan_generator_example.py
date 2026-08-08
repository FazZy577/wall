"""Deterministic offline example from search-plan generation to opportunities."""

import asyncio
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from application.interfaces.search_orchestrator import SearchOrchestrationResult
from application.interfaces.search_plan_generator import (
    GameSearchTarget,
    SearchPlanGenerationRequest,
    SearchPlanGenerationResult,
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
from application.use_cases.default_search_plan_generator import (
    DefaultSearchPlanGenerator,
)
from domain.entities.detected_game import Platform
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.collectors.wallapop_price_collector import (
    WallapopPriceCollector,
)
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
from infrastructure.marketplaces.wallapop.adapter import (
    WallapopCandidateSearchAdapter,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.rankers.default_opportunity_ranker import (
    DefaultOpportunityRanker,
)
from infrastructure.statistics.default_price_statistics import (
    DefaultPriceStatistics,
)

_LATITUDE = 40.4168
_LONGITUDE = -3.7038
_MAX_RESULTS = 10
_MAX_QUERIES = 10
_GTA_KEYWORDS = "Grand Theft Auto V PS4"
_RDR2_KEYWORDS = "Red Dead Redemption 2 PS4"


class _OfflineMarketplaceSearch(IMarketplaceSearch):
    """Manual in-memory implementation of the raw marketplace search port."""

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


def _comparables(
    prefix: str,
    title: str,
    prices: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        _raw_listing(
            f"{prefix}-{index}",
            title,
            price,
            description="Comparable individual offline",
        )
        for index, price in enumerate(prices * 4)
    ]


def _marketplace_responses() -> dict[str, Sequence[dict[str, Any]]]:
    gta_candidate = _raw_listing(
        "generator-example-gta",
        "GTA V PS4 juego individual",
        "5.00",
        description="Juego individual de PS4",
    )
    rdr2_candidate = _raw_listing(
        "generator-example-rdr2",
        "RDR2 PS4 juego individual",
        "8.00",
        description="Juego individual de PS4",
    )
    lot_candidate = _raw_listing(
        "generator-example-lot",
        "Lote GTA V y RDR2 PS4",
        "10.00",
        description="Dos videojuegos completos de PS4",
    )
    return {
        _GTA_KEYWORDS: [gta_candidate, lot_candidate],
        _RDR2_KEYWORDS: [rdr2_candidate],
        "gta v": _comparables(
            "generator-example-gta-comparable",
            "GTA V PS4 juego",
            ("18", "19", "20", "21", "22"),
        ),
        "rdr2": _comparables(
            "generator-example-rdr2-comparable",
            "Red Dead Redemption 2 PS4 juego",
            ("24", "25", "26", "27", "28"),
        ),
    }


def _build_orchestrator(
    marketplace_search: IMarketplaceSearch,
    catalog: PackagedGameCatalog,
) -> DefaultSearchOrchestrator:
    detector = FuzzyGameDetector(catalog)
    collector = WallapopPriceCollector(
        marketplace_search=marketplace_search,
        game_detector=detector,
        comparable_filter=RuleBasedComparableFilter(),
    )
    dataset_builder = DefaultPriceDatasetBuilder()
    statistics = DefaultPriceStatistics()
    outlier_removal = DefaultOutlierRemoval()
    market_estimator = DefaultMarketPriceEstimator()
    economic_policy = ResaleEconomicPolicy.neutral()

    individual_scanner = DefaultOpportunityScanner(
        game_detector=detector,
        price_collector=collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        arbitrage_detector=DefaultArbitrageOpportunityDetector(economic_policy),
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    lot_scanner = DefaultLotOpportunityScanner(
        game_detector=detector,
        price_collector=collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        lot_analyzer=DefaultLotOpportunityAnalyzer(economic_policy),
    )
    return DefaultSearchOrchestrator(
        candidate_search=WallapopCandidateSearchAdapter(marketplace_search),
        game_detector=detector,
        candidate_eligibility_policy=RuleBasedCandidateEligibilityPolicy(),
        opportunity_scanner=individual_scanner,
        lot_opportunity_scanner=lot_scanner,
    )


def _generation_request() -> SearchPlanGenerationRequest:
    return SearchPlanGenerationRequest(
        targets=(
            GameSearchTarget("Grand Theft Auto V", Platform.PS4),
            GameSearchTarget("Red Dead Redemption 2", Platform.PS4),
            GameSearchTarget("  grand   theft auto v  ", Platform.PS4),
        ),
        latitude=_LATITUDE,
        longitude=_LONGITUDE,
        max_results=_MAX_RESULTS,
        max_queries=_MAX_QUERIES,
    )


def _print_generation_report(result: SearchPlanGenerationResult) -> None:
    print("SEARCH PLAN GENERATION REPORT")
    print()
    print("Targets:")
    print(f"- received: {result.targets_received}")
    print()
    print("Queries:")
    print(f"- generated: {result.queries_generated}")
    print(f"- duplicates removed: {result.duplicate_queries_removed}")
    print(f"- maximum allowed: {_MAX_QUERIES}")
    print()
    print("Generated search plan:")
    for query in result.plan.queries:
        print(
            f"- keywords: {query.keywords} | "
            f"latitude: {query.latitude} | "
            f"longitude: {query.longitude} | "
            f"max results: {query.max_results}"
        )


def _print_orchestration_report(result: SearchOrchestrationResult) -> None:
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
                f"- game: {opportunity.game.canonical_name} | "
                f"listing price: {opportunity.listing_price:.2f} "
                f"{opportunity.currency} | "
                f"market value: {opportunity.market_price:.2f} "
                f"{opportunity.currency} | "
                f"net profit: {opportunity.net_profit:.2f} "
                f"{opportunity.currency} | "
                f"ROI: {opportunity.net_roi_percentage:.2f}% | "
                f"recommendation: {opportunity.recommendation.upper()} | "
                f"opportunity score: {opportunity.opportunity_score:.1f}"
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
            f"- listing: {lot_result.listing.listing_id} | "
            f"games detected: {game_names} | "
            f"games valued: {lot_result.successfully_valued_games} | "
            f"failures: {lot_result.failed_games} | "
            f"recommendation: {recommendation}"
        )
    print()
    print("Failures:")
    print(f"- query failures: {len(result.query_failures)}")
    print(f"- item failures: {len(result.item_failures)}")
    print(f"- routing failures: {len(result.routing_failures)}")
    print()
    print(f"Processing time: {result.processing_time:.6f} seconds")


async def main() -> None:
    """Generate a canonical plan and execute it through the offline pipeline."""
    catalog = PackagedGameCatalog()
    generator = DefaultSearchPlanGenerator(catalog)
    generation = generator.generate(_generation_request())

    marketplace_search = _OfflineMarketplaceSearch(_marketplace_responses())
    orchestrator = _build_orchestrator(marketplace_search, catalog)
    execution = await orchestrator.execute(generation.plan)

    _print_generation_report(generation)
    print()
    _print_orchestration_report(execution)


if __name__ == "__main__":
    asyncio.run(main())
