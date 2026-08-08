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
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.game_catalog import IGameCatalog
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
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.filters.rule_based_comparable_filter import (
    RuleBasedComparableFilter,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def _game(name: str, platform: Platform) -> DetectedGame:
    return DetectedGame(name, name, platform, 1.0, DetectionMethod.EXACT_MATCH)


class _TextDetector:
    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        title = listing_text.title
        if "RDR2" in title:
            name = "Red Dead Redemption 2"
        elif "FIFA" in title:
            name = "FIFA 24"
        else:
            name = "Grand Theft Auto V"
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


class _Catalog(IGameCatalog):
    def __init__(self, entries: tuple[GameCatalogEntry, ...]) -> None:
        self._entries = entries

    def list_games(self) -> tuple[GameCatalogEntry, ...]:
        return self._entries


def _entry(
    name: str,
    platform: Platform,
    *aliases: str,
) -> GameCatalogEntry:
    return GameCatalogEntry(name, platform, aliases)


def _identity_catalog() -> _Catalog:
    entries = tuple(
        _entry("Grand Theft Auto V", platform, "GTA V", "GTA5")
        for platform in (
            Platform.PS3,
            Platform.PS4,
            Platform.PS5,
            Platform.XBOX_360,
            Platform.XBOX_ONE,
        )
    )
    return _Catalog(
        entries
        + (_entry("Red Dead Redemption 2", Platform.PS4, "RDR2"),)
        + tuple(
            _entry("Halo Test", platform, "Halo")
            for platform in (
                Platform.XBOX,
                Platform.XBOX_360,
                Platform.XBOX_ONE,
                Platform.XBOX_SERIES,
            )
        )
    )


def _real_collector(search: _Search) -> WallapopPriceCollector:
    return WallapopPriceCollector(
        search,
        FuzzyGameDetector(_identity_catalog()),
        RuleBasedComparableFilter(),
    )


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
            _raw("rdr-ps4", "RDR2 PS4", "80"),
            _raw("rdr-ps5", "RDR2 PS5", "25"),
        ]
    )
    collector = _collector(search)
    games = [
        _game("Grand Theft Auto V", Platform.PS4),
        _game("Red Dead Redemption 2", Platform.PS5),
    ]
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

    result = await scanner.scan_lot(_candidate("lot", "GTA V PS4 + RDR2 PS5"))

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


@pytest.mark.asyncio
async def test_real_ps4_market_excludes_every_cross_identity_comparable() -> None:
    search = _Search(
        [
            _raw("ps3", "GTA V PS3", "30"),
            _raw("ps4", "GTA V PS4", "12"),
            _raw("ps5", "GTA V PS5", "40"),
            _raw("x360", "GTA V Xbox 360", "22"),
            _raw("xone", "GTA V Xbox One", "25"),
            _raw("ambiguous", "GTA V PS4 y PS5", "18"),
            _raw("other-game", "RDR2 PS4", "20"),
            {
                **_raw("compatible", "GTA V PS4", "15"),
                "description": "Compatible con PS5",
            },
        ]
    )
    target = _game("Grand Theft Auto V", Platform.PS4)

    comparables = await _real_collector(search).collect_comparables(
        target,
        latitude=40.0,
        longitude=-3.0,
    )
    dataset = DefaultPriceDatasetBuilder().build(list(comparables), "EUR")

    assert [item.listing_id for item in comparables] == ["ps4", "compatible"]
    assert [item.listing_id for item in dataset.observations] == [
        "ps4",
        "compatible",
    ]
    assert dataset.game.platform is Platform.PS4
    assert all(item.platform is Platform.PS4 for item in dataset.observations)


@pytest.mark.asyncio
async def test_real_ps5_market_is_not_hardcoded_to_ps4() -> None:
    search = _Search(
        [
            _raw("ps4", "GTA V PS4", "12"),
            _raw("ps5", "GTA V PS5", "30"),
        ]
    )
    target = _game("Grand Theft Auto V", Platform.PS5)

    comparables = await _real_collector(search).collect_comparables(
        target,
        latitude=40.0,
        longitude=-3.0,
    )
    dataset = DefaultPriceDatasetBuilder().build(list(comparables), "EUR")

    assert [item.listing_id for item in comparables] == ["ps5"]
    assert dataset.game.platform is Platform.PS5
    assert [item.platform for item in dataset.observations] == [Platform.PS5]


@pytest.mark.asyncio
async def test_real_xbox_360_market_isolated_within_xbox_family() -> None:
    search = _Search(
        [
            {
                **_raw("xbox", "Halo Test Xbox", "10"),
                "description": "Juego fisico",
            },
            {
                **_raw("x360", "Halo Test Xbox 360", "20"),
                "description": "Juego fisico",
            },
            {
                **_raw("xone", "Halo Test Xbox One", "30"),
                "description": "Juego fisico",
            },
            {
                **_raw("xseries", "Halo Test Xbox Series", "40"),
                "description": "Juego fisico",
            },
        ]
    )
    target = _game("Halo Test", Platform.XBOX_360)

    comparables = await _real_collector(search).collect_comparables(
        target,
        latitude=40.0,
        longitude=-3.0,
    )
    dataset = DefaultPriceDatasetBuilder().build(list(comparables), "EUR")

    assert [item.listing_id for item in comparables] == ["x360"]
    assert dataset.game.platform is Platform.XBOX_360
    assert [item.platform for item in dataset.observations] == [Platform.XBOX_360]
