"""Opt-in end-to-end test for the minimal real price pipeline."""

import pytest

from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.filters.rule_based_comparable_filter import (
    RuleBasedComparableFilter,
)
from infrastructure.marketplaces.wallapop.playwright_client import (
    WallapopPlaywrightClient,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


@pytest.mark.live
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_real_price_estimation_pipeline() -> None:
    """Run one controlled Wallapop search through market price estimation."""
    game = DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta 5 ps4",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )
    client = WallapopPlaywrightClient(max_pages=2, request_delay=0, headless=False)
    collector = WallapopPriceCollector(
        marketplace_search=client,
        game_detector=FuzzyGameDetector(PackagedGameCatalog()),
        comparable_filter=RuleBasedComparableFilter(),
    )

    async with client:
        comparables = await collector.collect_comparables(
            game=game,
            latitude=40.4168,
            longitude=-3.7038,
            max_results=3,
        )

        assert comparables
        assert len(comparables) <= 3

        dataset = DefaultPriceDatasetBuilder(source="wallapop-live").build(
            comparables,
            comparables[0].currency,
        )
        assert dataset.sample_size > 0

        statistics_calculator = DefaultPriceStatistics()
        initial_statistics = statistics_calculator.calculate(dataset)
        outlier_result = DefaultOutlierRemoval().remove_outliers(
            dataset,
            initial_statistics,
        )
        clean_statistics = statistics_calculator.calculate(outlier_result.clean_dataset)
        estimate = DefaultMarketPriceEstimator().estimate(
            dataset=outlier_result.clean_dataset,
            statistics=clean_statistics,
            observations_removed=outlier_result.removed_count,
        )

        assert estimate.estimated_price > 0
        assert estimate.currency == comparables[0].currency
        assert 0 <= estimate.confidence_score <= 1

    assert not client.is_open
