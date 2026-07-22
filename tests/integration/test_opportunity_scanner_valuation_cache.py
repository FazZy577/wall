"""Offline regression test for execution-scoped market valuation reuse."""

from unittest.mock import Mock

from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
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


def _candidate(identifier: str, price: float) -> CandidateListing:
    return CandidateListing(
        listing_id=identifier,
        title="GTA V PS4",
        description="",
        price=price,
        currency="EUR",
        url=f"https://example.test/{identifier}",
        raw_listing={"kind": "candidate", "id": identifier},
    )


def _comparable(identifier: str, price: float) -> ComparableListing:
    return ComparableListing(
        listing_id=identifier,
        title="GTA V PS4",
        description="",
        price=price,
        currency="EUR",
        detected_game=_game(),
        url=f"https://example.test/{identifier}",
        raw_listing={"kind": "comparable", "id": identifier},
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
        return [_comparable(f"comparable-{index}", 30.0) for index in range(20)]


def test_real_pipeline_reuses_estimate_but_preserves_per_candidate_formulas() -> None:
    collector = _OfflineCollector()
    estimator = Mock(wraps=DefaultMarketPriceEstimator())
    detector = Mock(wraps=DefaultArbitrageOpportunityDetector())
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=collector,
        dataset_builder=DefaultPriceDatasetBuilder(),
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=estimator,
        arbitrage_detector=detector,
    )
    candidates = [_candidate("candidate-5", 5.0), _candidate("candidate-25", 25.0)]

    result = scanner.scan_multiple(candidates)

    assert collector.calls == 1
    assert estimator.estimate.call_count == 1
    assert detector.detect.call_count == 2
    assert (result.valuation_cache_misses, result.valuation_cache_hits) == (1, 1)
    assert [opportunity.market_price for opportunity in result.opportunities] == [30.0, 30.0]
    assert [opportunity.estimated_profit for opportunity in result.opportunities] == [25.0, 5.0]
    assert [opportunity.roi_percentage for opportunity in result.opportunities] == [500.0, 20.0]
    assert result.opportunities[0].recommendation != result.opportunities[1].recommendation
    assert result.opportunities[0].listing is candidates[0]
    assert result.opportunities[0].listing.raw_listing["kind"] == "candidate"


def test_candidate_lot_price_never_enters_comparable_dataset() -> None:
    candidate = CandidateListing(
        listing_id="lot-30",
        title="Lote GTA V + RDR2",
        description="",
        price=30.0,
        currency="EUR",
        url="https://example.test/lot-30",
        raw_listing={"kind": "candidate", "price": 30.0},
    )
    comparables = [
        _comparable("gta-12", 12.0),
        _comparable("gta-15", 15.0),
        _comparable("gta-18", 18.0),
    ]
    collector = Mock()
    builder = Mock(wraps=DefaultPriceDatasetBuilder())
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=collector,
        dataset_builder=builder,
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        arbitrage_detector=DefaultArbitrageOpportunityDetector(),
    )
    scanner._run_async = Mock(return_value=comparables)

    opportunity = scanner.scan_listing(candidate)

    dataset_input = builder.build.call_args.args[0]
    assert dataset_input == comparables
    assert all(isinstance(item, ComparableListing) for item in dataset_input)
    assert candidate not in dataset_input
    assert [item.price for item in dataset_input] == [12.0, 15.0, 18.0]
    assert opportunity is not None
    assert opportunity.listing is candidate
    assert opportunity.listing_price == 30.0
    assert opportunity.market_price == 15.0
    assert opportunity.estimated_profit == -15.0
    assert opportunity.listing.raw_listing == {"kind": "candidate", "price": 30.0}
    assert comparables[0].raw_listing == {"kind": "comparable", "id": "gta-12"}
