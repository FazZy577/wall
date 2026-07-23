"""Offline integration coverage for the unified lot analysis flow."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.resale_economics import (
    ResaleAbsoluteCosts,
    ResaleEconomicPolicy,
)
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def _game(name: str) -> DetectedGame:
    return DetectedGame(
        canonical_name=name,
        matched_text=name,
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


class _Detector:
    def __init__(self, games: list[DetectedGame]) -> None:
        self.games = games

    def detect_games(self, listing_text: object) -> list[DetectedGame]:
        del listing_text
        return self.games


class _Collector:
    prices = {
        "GTA V": Decimal("15.0"),
        "RDR2": Decimal("20.0"),
        "FIFA 24": Decimal("10.0"),
    }

    def __init__(self, candidate_id: str, currency: str = "EUR") -> None:
        self.candidate_id = candidate_id
        self.currency = currency
        self.calls: list[DetectedGame] = []

    async def collect_comparables(
        self,
        game: DetectedGame,
        latitude: float,
        longitude: float,
        max_results: int | None = None,
    ) -> list[ComparableListing]:
        del latitude, longitude, max_results
        self.calls.append(game)
        price = self.prices[game.canonical_name]
        identifiers = [self.candidate_id, *(f"{game.canonical_name}-{i}" for i in range(20))]
        return [
            ComparableListing(
                listing_id=identifier,
                title=game.canonical_name,
                description="",
                price=Decimal("40.0") if identifier == self.candidate_id else price,
                currency=self.currency,
                detected_game=game,
                url=f"https://example.test/{identifier}",
                raw_listing={"kind": "comparable"},
            )
            for identifier in identifiers
        ]


@pytest.mark.asyncio
async def test_real_offline_lot_pipeline_uses_one_candidate_and_three_valuations() -> None:
    games = [_game("GTA V"), _game("RDR2"), _game("FIFA 24")]
    candidate = CandidateListing(
        listing_id="lot-123",
        title="Lote GTA V, RDR2 y FIFA 24 para PS4",
        description="Tres juegos",
        price=Decimal("40.0"),
        currency="EUR",
        url="https://example.test/lot-123",
        raw_listing={"kind": "candidate"},
    )
    collector = _Collector(candidate.listing_id)
    builder = Mock(wraps=DefaultPriceDatasetBuilder())
    analyzer = Mock(wraps=DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral()))
    scanner = DefaultLotOpportunityScanner(
        game_detector=_Detector(games),
        price_collector=collector,
        dataset_builder=builder,
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        lot_analyzer=analyzer,
    )

    result = await scanner.scan_lot(candidate)

    assert result.total_detected_games == 3
    assert len(result.game_valuations) == 3
    assert result.opportunity is not None
    assert result.opportunity.reference_market_value == 45.0
    assert result.opportunity.lot_price == 40.0
    opportunity_state = (
        result.opportunity.game_valuations,
        result.opportunity.aggregate_confidence_score,
        result.opportunity.economic_breakdown.item_count,
        result.opportunity.reference_market_value,
        result.opportunity.net_profit,
    )
    result.game_valuations.clear()
    assert (
        result.opportunity.game_valuations,
        result.opportunity.aggregate_confidence_score,
        result.opportunity.economic_breakdown.item_count,
        result.opportunity.reference_market_value,
        result.opportunity.net_profit,
    ) == opportunity_state
    assert isinstance(result.opportunity.game_valuations, tuple)
    assert len(collector.calls) == 3
    analyzer.analyze.assert_called_once()
    assert all(
        candidate.listing_id not in [item.listing_id for item in call.args[0]]
        for call in builder.build.call_args_list
    )
    assert candidate.raw_listing == {"kind": "candidate"}


@pytest.mark.asyncio
async def test_lot_pipeline_creates_valuation_from_zero_iqr_game() -> None:
    game = _game("GTA V")
    candidate = CandidateListing("zero-iqr-lot", "GTA V", "", Decimal("5"), "EUR", "url")
    collector = Mock()
    collector.collect_comparables = Mock()

    async def collect(**_kwargs: object) -> list[ComparableListing]:
        prices = [Decimal("10")] * 6 + [Decimal("100")]
        return [
            ComparableListing(str(index), "GTA V", "", price, "EUR", game, "url")
            for index, price in enumerate(prices)
        ]

    collector.collect_comparables.side_effect = collect
    outlier_results: list[object] = []
    outliers = Mock()

    def remove_outliers(dataset: object, statistics: object) -> object:
        result = DefaultOutlierRemoval().remove_outliers(dataset, statistics)  # type: ignore[arg-type]
        outlier_results.append(result)
        return result

    outliers.remove_outliers.side_effect = remove_outliers
    analyzer = Mock(wraps=DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral()))
    scanner = DefaultLotOpportunityScanner(
        game_detector=_Detector([game]),
        price_collector=collector,
        dataset_builder=DefaultPriceDatasetBuilder(),
        statistics=DefaultPriceStatistics(),
        outlier_removal=outliers,
        market_estimator=DefaultMarketPriceEstimator(),
        lot_analyzer=analyzer,
    )

    result = await scanner.scan_lot(candidate)

    removal = outlier_results[0]
    assert removal.removed_count == 0
    assert removal.clean_dataset.sample_size == 7
    assert len(result.game_valuations) == 1
    assert result.game_valuations[0].currency == "EUR"
    analyzer.analyze.assert_called_once()


@pytest.mark.asyncio
async def test_lot_pipeline_uses_unique_comparable_identities_per_game() -> None:
    gta = _game("GTA V")
    rdr2 = _game("RDR2")
    candidate = CandidateListing("deduplicated-lot", "GTA V + RDR2", "", Decimal("5"), "EUR", "url")
    collector = Mock()

    async def collect(
        game: DetectedGame,
        **_kwargs: object,
    ) -> list[ComparableListing]:
        if game.canonical_name == "GTA V":
            return [
                ComparableListing("G1", "GTA V", "", Decimal("10"), "EUR", game, "url"),
                ComparableListing("G1", "GTA V", "", Decimal("99"), "EUR", game, "url"),
                ComparableListing("G2", "GTA V", "", Decimal("20"), "EUR", game, "url"),
            ]
        return [
            ComparableListing("R1", "RDR2", "", Decimal("30"), "EUR", game, "url"),
            ComparableListing("R2", "RDR2", "", Decimal("40"), "EUR", game, "url"),
        ]

    collector.collect_comparables.side_effect = collect
    real_builder = DefaultPriceDatasetBuilder()
    dataset_ids: list[list[str]] = []
    builder = Mock()

    def build(comparables: list[object], currency: str) -> object:
        dataset = real_builder.build(comparables, currency)
        dataset_ids.append([item.listing_id for item in dataset.observations])
        return dataset

    builder.build.side_effect = build
    analyzer = Mock(wraps=DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral()))
    scanner = DefaultLotOpportunityScanner(
        game_detector=_Detector([gta, rdr2]),
        price_collector=collector,
        dataset_builder=builder,
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        lot_analyzer=analyzer,
    )

    result = await scanner.scan_lot(candidate)

    assert dataset_ids == [["G1", "G2"], ["R1", "R2"]]
    assert [valuation.observations_used for valuation in result.game_valuations] == [2, 2]
    assert result.successfully_valued_games == 2
    analyzer.analyze.assert_called_once()


def _currency_scanner(
    candidate: CandidateListing,
    game: DetectedGame,
    analyzer: DefaultLotOpportunityAnalyzer,
) -> DefaultLotOpportunityScanner:
    return DefaultLotOpportunityScanner(
        game_detector=_Detector([game]),
        price_collector=_Collector(candidate.listing_id, candidate.currency),
        dataset_builder=DefaultPriceDatasetBuilder(),
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        lot_analyzer=analyzer,
    )


@pytest.mark.asyncio
async def test_lot_scanner_uses_injected_usd_threshold_offline() -> None:
    game = _game("GTA V")
    candidate = CandidateListing(
        "usd-lot", "GTA V lot", "", Decimal("5"), "USD", "url"
    )
    analyzer = DefaultLotOpportunityAnalyzer(
        ResaleEconomicPolicy.neutral("USD"),
        min_net_profit_by_currency={"EUR": Decimal("10"), "USD": Decimal("8")},
    )
    scanner = _currency_scanner(candidate, game, analyzer)

    result = await scanner.scan_lot(candidate)

    assert len(result.game_valuations) == 1
    assert result.game_valuations[0].currency == "USD"
    assert result.opportunity is not None
    assert result.opportunity.currency == "USD"
    assert result.opportunity.net_profit == Decimal("10")
    assert result.opportunity.recommendation.value == "buy"


@pytest.mark.asyncio
async def test_lot_scanner_selects_distinct_cost_bundles_by_currency() -> None:
    policy = ResaleEconomicPolicy(
        {
            "EUR": ResaleAbsoluteCosts(Decimal("3"), Decimal("1"), Decimal("2")),
            "USD": ResaleAbsoluteCosts(Decimal("2"), Decimal("0.5"), Decimal("1")),
            "GBP": ResaleAbsoluteCosts(Decimal("4"), Decimal("2"), Decimal("3")),
        },
        Decimal("0"),
        Decimal("0"),
    )
    analyzer = DefaultLotOpportunityAnalyzer(
        policy,
        min_net_profit_by_currency={
            "EUR": Decimal("0"),
            "USD": Decimal("0"),
            "GBP": Decimal("0"),
        },
    )
    expected_profit = {
        "EUR": Decimal("4"),
        "USD": Decimal("6.5"),
        "GBP": Decimal("1"),
    }

    for currency in ("EUR", "USD", "GBP"):
        game = _game("GTA V")
        candidate = CandidateListing(
            f"{currency}-lot", "GTA V lot", "", Decimal("5"), currency, "url"
        )
        result = await _currency_scanner(candidate, game, analyzer).scan_lot(candidate)

        assert result.opportunity is not None
        assert result.opportunity.currency == currency
        assert result.opportunity.net_profit == expected_profit[currency]
        assert result.opportunity.economic_breakdown.item_count == 1


@pytest.mark.asyncio
async def test_lot_scanner_preserves_unstructured_missing_threshold_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    game = _game("GTA V")
    candidate = CandidateListing(
        "usd-unconfigured", "GTA V lot", "", Decimal("5"), "USD", "url"
    )
    analyzer = DefaultLotOpportunityAnalyzer(
        ResaleEconomicPolicy.neutral("USD"),
        min_net_profit_by_currency={"EUR": Decimal("10")},
    )
    scanner = _currency_scanner(candidate, game, analyzer)

    result = await scanner.scan_lot(candidate)

    assert len(result.game_valuations) == 1
    assert result.game_valuations[0].currency == "USD"
    assert result.opportunity is None
    assert result.failures == []
    assert (
        "No minimum lot net profit threshold configured for currency USD"
        in caplog.text
    )


@pytest.mark.asyncio
async def test_lot_scanner_preserves_unstructured_missing_cost_bundle_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    game = _game("GTA V")
    candidate = CandidateListing(
        "usd-costs-unconfigured", "GTA V lot", "", Decimal("5"), "USD", "url"
    )
    analyzer = DefaultLotOpportunityAnalyzer(
        ResaleEconomicPolicy.neutral(),
        min_net_profit_by_currency={"USD": Decimal("8")},
    )
    scanner = _currency_scanner(candidate, game, analyzer)

    result = await scanner.scan_lot(candidate)

    assert len(result.game_valuations) == 1
    assert result.game_valuations[0].currency == "USD"
    assert result.opportunity is None
    assert result.failures == []
    assert "No resale absolute costs configured for currency USD" in caplog.text
