"""Offline integration tests for complete comparable game identity."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.game_detector import ListingText
from domain.interfaces.price_dataset_builder import PriceDataset
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector
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


def _game(name: str, platform: Platform) -> DetectedGame:
    return DetectedGame(name, name, platform, 1.0, DetectionMethod.EXACT_MATCH)


class _TextDetector:
    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        title = listing_text.title
        name = "FIFA 24" if "FIFA" in title else "Grand Theft Auto V"
        if "PS5" in title:
            platform = Platform.PS5
        elif "Xbox One" in title:
            platform = Platform.XBOX_ONE
        else:
            platform = Platform.PS4
        return [_game(name, platform)]


class _AcceptComparable:
    def is_valid_comparable(self, target_game: object, listing: object) -> bool:
        del target_game, listing
        return True


class _Search:
    def __init__(self, listings: list[dict[str, object]]) -> None:
        self.listings = listings
        self.calls = 0

    async def search_listings(self, **kwargs: object) -> list[dict[str, object]]:
        del kwargs
        self.calls += 1
        return self.listings


def _raw(identifier: str, title: str, price: str) -> dict[str, object]:
    return {
        "id": identifier,
        "title": title,
        "description": "",
        "price": price,
        "currency": "EUR",
    }


def _candidate(identifier: str, title: str) -> CandidateListing:
    return CandidateListing(identifier, title, "", Decimal("5"), "EUR", "")


def _collector(search: _Search) -> WallapopPriceCollector:
    return WallapopPriceCollector(search, _TextDetector(), _AcceptComparable())


def _individual_scanner(
    collector: WallapopPriceCollector,
    builder: object,
    estimator: object,
) -> DefaultOpportunityScanner:
    return DefaultOpportunityScanner(
        game_detector=_TextDetector(),
        price_collector=collector,
        dataset_builder=builder,  # type: ignore[arg-type]
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=estimator,  # type: ignore[arg-type]
        arbitrage_detector=DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral()
        ),
        opportunity_ranker=DefaultOpportunityRanker(),
    )


@pytest.mark.asyncio
async def test_individual_pipeline_keeps_ps5_out_of_ps4_cache_and_datasets() -> None:
    raw = [_raw(f"ps5-{index}", "GTA V PS5", "99") for index in range(5)]
    raw.extend([_raw("ps4-1", "GTA V PS4", "12"), _raw("ps4-2", "GTA V PS4", "18")])
    search = _Search(raw)
    real_builder = DefaultPriceDatasetBuilder()
    datasets: list[PriceDataset] = []
    builder = Mock()

    def build(comparables: list[object], currency: str) -> object:
        dataset = real_builder.build(comparables, currency)
        datasets.append(dataset)
        return dataset

    builder.build.side_effect = build
    estimator = Mock(wraps=DefaultMarketPriceEstimator())
    scanner = _individual_scanner(_collector(search), builder, estimator)
    candidates = [_candidate(f"candidate-{index}", "GTA V PS4") for index in range(5)]

    result = await scanner.scan_multiple(candidates)

    assert search.calls == 1
    assert (result.comparable_cache_misses, result.comparable_cache_hits) == (1, 4)
    assert estimator.estimate.call_count == 5
    assert all(dataset.game.platform == Platform.PS4 for dataset in datasets)
    assert all(
        [observation.price for observation in dataset.observations]
        == [Decimal("12"), Decimal("18")]
        for dataset in datasets
    )
    assert all(opportunity.game.platform == Platform.PS4 for opportunity in result.opportunities)
    assert raw[0]["title"] == "GTA V PS5"


@pytest.mark.asyncio
async def test_individual_pipeline_reports_no_comparables_when_only_ps5_exists() -> None:
    search = _Search([_raw("ps5-only", "GTA V PS5", "20")])
    builder = Mock(wraps=DefaultPriceDatasetBuilder())
    scanner = _individual_scanner(_collector(search), builder, DefaultMarketPriceEstimator())

    result = await scanner.scan_multiple([_candidate("candidate", "GTA V PS4")])

    assert result.opportunities == []
    assert len(result.failures) == 1
    assert result.failures[0].listing_id == "candidate"
    assert "No comparable listings" in result.failures[0].reason
    builder.build.assert_not_called()


@pytest.mark.asyncio
async def test_lot_pipeline_keeps_each_game_on_its_requested_platform() -> None:
    search = _Search(
        [
            _raw("gta-ps5", "GTA V PS5", "90"),
            _raw("gta-ps4", "GTA V PS4", "15"),
            _raw("fifa-ps4", "FIFA 24 PS4", "80"),
            _raw("fifa-ps5", "FIFA 24 PS5", "25"),
        ]
    )
    collector = _collector(search)
    games = [_game("Grand Theft Auto V", Platform.PS4), _game("FIFA 24", Platform.PS5)]
    detector = Mock()
    detector.detect_games.return_value = games
    real_builder = DefaultPriceDatasetBuilder()
    datasets: list[PriceDataset] = []
    builder = Mock()

    def build(comparables: list[object], currency: str) -> object:
        dataset = real_builder.build(comparables, currency)
        datasets.append(dataset)
        return dataset

    builder.build.side_effect = build
    analyzer = Mock(wraps=DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral()))
    scanner = DefaultLotOpportunityScanner(
        game_detector=detector,
        price_collector=collector,
        dataset_builder=builder,
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        lot_analyzer=analyzer,
    )

    result = await scanner.scan_lot(_candidate("lot", "GTA V PS4 + FIFA 24 PS5"))

    assert search.calls == 2
    assert [dataset.game.platform for dataset in datasets] == [Platform.PS4, Platform.PS5]
    assert [[item.price for item in dataset.observations] for dataset in datasets] == [
        [Decimal("15")],
        [Decimal("25")],
    ]
    assert [valuation.game.platform for valuation in result.game_valuations] == [
        Platform.PS4,
        Platform.PS5,
    ]
    analyzer.analyze.assert_called_once()
