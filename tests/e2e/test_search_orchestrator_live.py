"""Opt-in smoke test for the production search orchestration pipeline."""

import os
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import pytest

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.search_orchestrator import SearchPlan
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
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
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
from infrastructure.marketplaces.wallapop.playwright_client import (
    WallapopPlaywrightClient,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


class _BoundedMarketplaceSearch(IMarketplaceSearch):
    """Keep the live smoke test within the requested comparable limit."""

    def __init__(self, client: WallapopPlaywrightClient, limit: int) -> None:
        self._client = client
        self._limit = limit

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        return await self._client.search_listings(
            keywords=keywords,
            latitude=latitude,
            longitude=longitude,
            max_results=min(max_results, self._limit),
        )


@pytest.mark.live
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_orchestrator_live_smoke() -> None:
    """Run one bounded, sequential orchestration execution against Wallapop."""
    if os.environ.get("RUN_LIVE_WALLAPOP_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_WALLAPOP_TESTS=1 to run the live smoke test")

    client = WallapopPlaywrightClient(
        timeout_ms=15_000,
        max_pages=1,
        request_delay=0,
        headless=False,
    )
    marketplace_search = _BoundedMarketplaceSearch(client, limit=10)
    catalog = PackagedGameCatalog()
    candidate_detector = FuzzyGameDetector(catalog)
    comparable_detector = FuzzyGameDetector(catalog)
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
    opportunity_scanner = DefaultOpportunityScanner(
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
    orchestrator = DefaultSearchOrchestrator(
        candidate_search=WallapopCandidateSearchAdapter(marketplace_search),
        game_detector=candidate_detector,
        candidate_eligibility_policy=RuleBasedCandidateEligibilityPolicy(),
        opportunity_scanner=opportunity_scanner,
        lot_opportunity_scanner=lot_scanner,
    )

    query = SearchQuery(
        keywords="gta 5 ps4",
        latitude=40.4168,
        longitude=-3.7038,
        max_results=1,
    )
    async with client:
        result = await orchestrator.execute(SearchPlan((query,)))

        assert result.total_queries == 1
        assert result.executed_queries == 1
        assert result.duplicate_queries == 0
        assert result.query_failures == ()
        assert 0 <= result.total_items_received <= 1
        assert (
            result.unique_candidates
            == result.valid_candidates_received - result.duplicate_candidates
        )
        assert (
            result.individual_candidates
            + result.lot_candidates
            + result.undetected_candidates
            + len(result.ignored_candidates)
            + len(result.ambiguous_candidates)
            == result.unique_candidates
        )
        assert any(
            urlsplit(url).path == WallapopPlaywrightClient.API_PATH
            for url in client.last_response_urls
        )

        if result.individual_result is not None:
            for opportunity in result.individual_result.opportunities:
                assert 0.0 <= opportunity.confidence_score <= 1.0
                assert all(
                    isinstance(amount, Decimal)
                    for amount in (
                        opportunity.market_price,
                        opportunity.listing_price,
                        opportunity.net_profit,
                        opportunity.expected_sale_revenue,
                        opportunity.break_even_sale_revenue,
                    )
                )
                assert opportunity.currency

        for lot_result in result.lot_results:
            assert (
                lot_result.successfully_valued_games + lot_result.failed_games
                == lot_result.total_detected_games
            )
            assert lot_result.total_detected_games >= 0

    assert not client.is_open
