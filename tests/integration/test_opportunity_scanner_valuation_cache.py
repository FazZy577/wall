"""Offline regression test for execution-scoped market valuation reuse."""

from unittest.mock import Mock

from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from domain.interfaces.price_collector import ComparableListing
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.scanners.default_opportunity_scanner import DefaultOpportunityScanner
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def _game() -> DetectedGame:
    return DetectedGame(
        "Grand Theft Auto V",
        "GTA V",
        Platform.PS4,
        1.0,
        DetectionMethod.ALIAS_MATCH,
    )


def _listing(identifier: str, price: float) -> ComparableListing:
    return ComparableListing(
        listing_id=identifier,
        title="GTA V PS4",
        description="",
        price=price,
        currency="EUR",
        detected_game=_game(),
        url=f"https://example.test/{identifier}",
    )


class _OfflineCollector:
    def __init__(self) -> None:
        self.calls = 0

    async def collect_comparables(
        self,
        game: DetectedGame,
        latitude: float,
        longitude: float,
        max_results: int | None = None,
    ) -> list[ComparableListing]:
        del game, latitude, longitude, max_results
        self.calls += 1
        return [_listing(f"comparable-{index}", 30.0) for index in range(20)]


def test_real_pipeline_reuses_estimate_but_preserves_per_candidate_formulas() -> None:
    collector = _OfflineCollector()
    estimator = Mock(wraps=DefaultMarketPriceEstimator())
    detector = Mock(wraps=DefaultArbitrageOpportunityDetector())
    scanner = DefaultOpportunityScanner(
        game_detector=Mock(),
        price_collector=collector,
        dataset_builder=DefaultPriceDatasetBuilder(),
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=estimator,
        arbitrage_detector=detector,
    )
    candidates = [_listing("candidate-5", 5.0), _listing("candidate-25", 25.0)]

    result = scanner.scan_multiple(candidates)

    assert collector.calls == 1
    assert estimator.estimate.call_count == 1
    assert detector.detect.call_count == 2
    assert (result.valuation_cache_misses, result.valuation_cache_hits) == (1, 1)
    assert [opportunity.market_price for opportunity in result.opportunities] == [30.0, 30.0]
    assert [opportunity.estimated_profit for opportunity in result.opportunities] == [25.0, 5.0]
    assert [opportunity.roi_percentage for opportunity in result.opportunities] == [500.0, 20.0]
    assert result.opportunities[0].recommendation != result.opportunities[1].recommendation
