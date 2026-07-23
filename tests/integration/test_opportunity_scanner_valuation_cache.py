"""Offline regression test for execution-scoped comparable collection reuse."""

from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.opportunity_scanner import PipelineStage
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.arbitrage_opportunity_detector import Recommendation
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
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def _game() -> DetectedGame:
    return DetectedGame(
        "Grand Theft Auto V",
        "GTA V",
        Platform.PS4,
        1.0,
        DetectionMethod.ALIAS_MATCH,
    )


def _candidate(
    identifier: str,
    price: float,
    currency: str = "EUR",
    title: str = "GTA V PS4",
) -> CandidateListing:
    return CandidateListing(
        listing_id=identifier,
        title=title,
        description="",
        price=Decimal(str(price)),
        currency=currency,
        url=f"https://example.test/{identifier}",
        raw_listing={"kind": "candidate", "id": identifier},
    )


def _comparable(
    identifier: str,
    price: float,
    currency: str = "EUR",
    detected_game: DetectedGame | None = None,
) -> ComparableListing:
    return ComparableListing(
        listing_id=identifier,
        title="GTA V PS4",
        description="",
        price=Decimal(str(price)),
        currency=currency,
        detected_game=detected_game or _game(),
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


@pytest.mark.asyncio
async def test_scanner_uses_injected_detector_with_explicit_zero_threshold() -> None:
    collector = Mock()
    collector.collect_comparables = AsyncMock(
        return_value=[_comparable(f"comparable-{index}", 18.0) for index in range(20)]
    )
    configured_detector = Mock(
        wraps=DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("0")},
        )
    )
    ranker = Mock(wraps=DefaultOpportunityRanker())
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=collector,
        dataset_builder=DefaultPriceDatasetBuilder(),
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        arbitrage_detector=configured_detector,
        opportunity_ranker=ranker,
    )

    result = await scanner.scan_multiple([_candidate("configured-zero", 12.0)])

    assert len(result.opportunities) == 1
    assert result.opportunities[0].recommendation is Recommendation.BUY
    assert result.opportunities[0].net_profit == Decimal("6.0")
    configured_detector.detect.assert_called_once()
    ranker.rank.assert_called_once()
    collector.collect_comparables.assert_awaited_once()
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 0)


@pytest.mark.asyncio
async def test_real_pipeline_reuses_collection_but_preserves_per_candidate_formulas() -> None:
    collector = _OfflineCollector()
    estimator = Mock(wraps=DefaultMarketPriceEstimator())
    detector = Mock(wraps=DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral()))
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
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    candidates = [_candidate("candidate-5", 5.0), _candidate("candidate-25", 25.0)]

    result = await scanner.scan_multiple(candidates)

    assert collector.calls == 1
    assert estimator.estimate.call_count == 2
    assert detector.detect.call_count == 2
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 1)
    assert [opportunity.market_price for opportunity in result.opportunities] == [30.0, 30.0]
    assert [opportunity.net_profit for opportunity in result.opportunities] == [25.0, 5.0]
    assert [opportunity.net_roi_percentage for opportunity in result.opportunities] == [500.0, 20.0]
    assert result.opportunities[0].recommendation != result.opportunities[1].recommendation
    assert result.opportunities[0].listing is candidates[0]
    assert result.opportunities[0].listing.raw_listing["kind"] == "candidate"


@pytest.mark.asyncio
async def test_candidate_lot_price_never_enters_comparable_dataset() -> None:
    candidate = CandidateListing(
        listing_id="lot-30",
        title="Lote GTA V + RDR2",
        description="",
        price=Decimal("30.0"),
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
        arbitrage_detector=DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral()),
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    scanner.price_collector.collect_comparables = AsyncMock(return_value=comparables)

    opportunity = await scanner.scan_listing(candidate)

    dataset_input = builder.build.call_args.args[0]
    assert dataset_input == comparables
    assert all(isinstance(item, ComparableListing) for item in dataset_input)
    assert candidate not in dataset_input
    assert [item.price for item in dataset_input] == [12.0, 15.0, 18.0]
    assert opportunity is not None
    assert opportunity.listing is candidate
    assert opportunity.listing_price == 30.0
    assert opportunity.market_price == 15.0
    assert opportunity.net_profit == -15.0
    assert opportunity.listing.raw_listing == {"kind": "candidate", "price": 30.0}
    assert comparables[0].raw_listing == {"kind": "comparable", "id": "gta-12"}


@pytest.mark.asyncio
async def test_individual_pipeline_keeps_complete_heterogeneous_zero_iqr_dataset() -> None:
    candidate = _candidate("zero-iqr", 5.0)
    comparables = [_comparable(f"ten-{index}", 10.0) for index in range(6)] + [
        _comparable("extreme", 100.0)
    ]
    collector = Mock()
    collector.collect_comparables = AsyncMock(return_value=comparables)
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    outlier_results: list[object] = []
    outliers = Mock()

    def remove_outliers(dataset: object, statistics: object) -> object:
        result = DefaultOutlierRemoval().remove_outliers(dataset, statistics)  # type: ignore[arg-type]
        outlier_results.append(result)
        return result

    outliers.remove_outliers.side_effect = remove_outliers
    estimator = Mock(wraps=DefaultMarketPriceEstimator())
    detector = Mock(wraps=DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral()))
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=collector,
        dataset_builder=DefaultPriceDatasetBuilder(),
        statistics=DefaultPriceStatistics(),
        outlier_removal=outliers,
        market_estimator=estimator,
        arbitrage_detector=detector,
        opportunity_ranker=DefaultOpportunityRanker(),
    )

    opportunity = await scanner.scan_listing(candidate)

    result = outlier_results[0]
    assert result.removed_count == 0
    assert result.lower_bound == Decimal("10.0")
    assert result.upper_bound == Decimal("100.0")
    assert result.clean_dataset.sample_size == 7
    assert estimator.estimate.call_args.kwargs["dataset"] is result.clean_dataset
    assert opportunity is not None
    detector.detect.assert_called_once()
    assert opportunity.currency == "EUR"


@pytest.mark.asyncio
async def test_shared_raw_collection_is_deduplicated_per_candidate_without_mutation() -> None:
    raw_comparables = [
        _comparable("A", 10.0),
        _comparable("A", 99.0),
        _comparable("B", 20.0),
        _comparable("C", 30.0),
        _comparable("C", 88.0),
    ]
    collector = Mock()
    collector.collect_comparables = AsyncMock(return_value=raw_comparables)
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    real_builder = DefaultPriceDatasetBuilder()
    built_datasets: list[object] = []
    builder = Mock()

    def build(comparables: list[object], currency: str) -> object:
        dataset = real_builder.build(comparables, currency)
        built_datasets.append(dataset)
        return dataset

    builder.build.side_effect = build
    estimator = Mock(wraps=DefaultMarketPriceEstimator())
    detector = Mock(wraps=DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral()))
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=collector,
        dataset_builder=builder,
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=estimator,
        arbitrage_detector=detector,
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    candidates = [_candidate(f"candidate-{index}", 5.0) for index in range(5)]

    result = await scanner.scan_multiple(candidates)

    assert collector.collect_comparables.await_count == 1
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 4)
    assert builder.build.call_count == 5
    assert estimator.estimate.call_count == 5
    assert detector.detect.call_count == 5
    assert [dataset.sample_size for dataset in built_datasets] == [3] * 5
    assert [item.listing_id for item in raw_comparables] == ["A", "A", "B", "C", "C"]
    assert [item.price for item in raw_comparables] == [10.0, 99.0, 20.0, 30.0, 88.0]


@pytest.mark.asyncio
async def test_candidate_exclusion_is_specific_before_local_deduplication() -> None:
    raw_comparables = [
        _comparable("A", 10.0),
        _comparable("A", 11.0),
        _comparable("B", 20.0),
        _comparable("B", 21.0),
        _comparable("C", 30.0),
    ]
    collector = Mock()
    collector.collect_comparables = AsyncMock(return_value=raw_comparables)
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    real_builder = DefaultPriceDatasetBuilder()
    dataset_ids: list[list[str]] = []
    builder = Mock()

    def build(comparables: list[object], currency: str) -> object:
        dataset = real_builder.build(comparables, currency)
        dataset_ids.append([item.listing_id for item in dataset.observations])
        return dataset

    builder.build.side_effect = build
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=collector,
        dataset_builder=builder,
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        arbitrage_detector=DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral()),
        opportunity_ranker=DefaultOpportunityRanker(),
    )

    result = await scanner.scan_multiple([_candidate("A", 5.0), _candidate("B", 5.0)])

    assert dataset_ids == [["B", "C"], ["A", "C"]]
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 1)
    assert collector.collect_comparables.await_count == 1
    assert [item.listing_id for item in raw_comparables] == ["A", "A", "B", "B", "C"]


def _scanner_for_currencies(
    game_detector: Mock,
    collector: Mock,
    detector: DefaultArbitrageOpportunityDetector,
) -> DefaultOpportunityScanner:
    return DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=collector,
        dataset_builder=DefaultPriceDatasetBuilder(),
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        arbitrage_detector=detector,
        opportunity_ranker=DefaultOpportunityRanker(),
    )


@pytest.mark.asyncio
async def test_scanner_uses_currency_specific_thresholds_offline() -> None:
    eur_game = _game()
    usd_game = DetectedGame(
        "Red Dead Redemption 2",
        "RDR2",
        Platform.PS4,
        1.0,
        DetectionMethod.ALIAS_MATCH,
    )
    game_detector = Mock()
    game_detector.detect_games.side_effect = [[eur_game], [usd_game]]
    collector = Mock()

    async def collect(game: DetectedGame, *args: object, **kwargs: object):
        del args, kwargs
        currency = "EUR" if game is eur_game else "USD"
        return [
            _comparable(f"{currency}-{index}", 20.0, currency, game)
            for index in range(20)
        ]

    collector.collect_comparables = AsyncMock(side_effect=collect)
    scanner = _scanner_for_currencies(
        game_detector,
        collector,
        DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={
                "EUR": Decimal("10"),
                "USD": Decimal("8"),
            },
        ),
    )

    result = await scanner.scan_multiple(
        [
            _candidate("candidate-eur", 10.0, "EUR"),
            _candidate("candidate-usd", 10.0, "USD", "RDR2 PS4"),
        ]
    )

    assert result.successful == 2
    assert result.failed == 0
    assert [opportunity.currency for opportunity in result.opportunities] == [
        "EUR",
        "USD",
    ]
    assert all(
        opportunity.recommendation is Recommendation.BUY
        for opportunity in result.opportunities
    )
    assert collector.collect_comparables.await_count == 2


@pytest.mark.asyncio
async def test_batch_isolates_missing_currency_threshold_as_detection_failure() -> None:
    eur_game = _game()
    usd_game = DetectedGame(
        "Red Dead Redemption 2",
        "RDR2",
        Platform.PS4,
        1.0,
        DetectionMethod.ALIAS_MATCH,
    )
    game_detector = Mock()
    game_detector.detect_games.side_effect = [[eur_game], [usd_game], [eur_game]]
    collector = Mock()

    async def collect(game: DetectedGame, *args: object, **kwargs: object):
        del args, kwargs
        currency = "EUR" if game is eur_game else "USD"
        return [
            _comparable(f"{currency}-{index}", 20.0, currency, game)
            for index in range(20)
        ]

    collector.collect_comparables = AsyncMock(side_effect=collect)
    detector = DefaultArbitrageOpportunityDetector(
        ResaleEconomicPolicy.neutral(),
        min_net_profit_by_currency={"EUR": Decimal("10")},
    )
    scanner = _scanner_for_currencies(game_detector, collector, detector)
    candidates = [
        _candidate("A", 10.0, "EUR"),
        _candidate("B", 10.0, "USD", "RDR2 PS4"),
        _candidate("C", 10.0, "EUR"),
    ]

    result = await scanner.scan_multiple(candidates)

    assert (result.successful, result.failed) == (2, 1)
    assert [opportunity.listing.listing_id for opportunity in result.opportunities] == [
        "A",
        "C",
    ]
    assert result.failures[0].listing_id == "B"
    assert result.failures[0].stage is PipelineStage.OPPORTUNITY_DETECTION
    assert result.failures[0].error_message == (
        "No minimum net profit threshold configured for currency USD"
    )
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (2, 1)
    assert collector.collect_comparables.await_count == 2

    game_detector.detect_games.side_effect = None
    game_detector.detect_games.return_value = [usd_game]
    assert await scanner.scan_listing(candidates[1]) is None
