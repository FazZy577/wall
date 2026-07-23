"""P1.12 single-currency invariants across the monetary pipeline."""

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest

from domain.currency import CurrencyMismatchError, validate_currency_code
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.game_valuation import GameValuation
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    MarketPriceEstimate,
    ReasonCode,
)
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
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def game(name: str = "GTA V") -> DetectedGame:
    return DetectedGame(name, name, Platform.PS4, 1.0, DetectionMethod.EXACT_MATCH)


def candidate(currency: str = "EUR") -> CandidateListing:
    return CandidateListing("candidate", "GTA V", "", Decimal("10"), currency, "url")


def comparable(identifier: str, amount: str, currency: str) -> ComparableListing:
    return ComparableListing(
        identifier, "GTA V", "", Decimal(amount), currency, game(), "url"
    )


def estimate(currency: str) -> MarketPriceEstimate:
    return MarketPriceEstimate(
        Decimal("20"), currency, 0.8, ConfidenceLevel.HIGH,
        EstimationStrategy.MEDIAN, ReasonCode.NORMAL, 2, 0, 0.0,
        Decimal("10"), Decimal("20"), Decimal("1"), Decimal("2"), 0.05,
        game(), datetime.now(UTC),
    )


@pytest.mark.parametrize("code", ["EUR", "USD", "GBP"])
def test_canonical_currency_codes_are_accepted(code: str) -> None:
    assert validate_currency_code(code) == code
    assert candidate(code).currency == code


@pytest.mark.parametrize(
    "code", ["", " ", "eur", " EUR", "EUR ", "€", "EURO", "12", None, 123, True]
)
def test_domain_rejects_noncanonical_currency_codes(code: object) -> None:
    with pytest.raises((TypeError, ValueError), match="currency"):
        candidate(code)  # type: ignore[arg-type]


def test_dataset_rejects_mixed_or_wrong_target_currency() -> None:
    builder = DefaultPriceDatasetBuilder()
    with pytest.raises(CurrencyMismatchError, match="expected EUR, got USD"):
        builder.build(
            [comparable("eur", "10", "EUR"), comparable("usd", "20", "USD")],
            "EUR",
        )
    with pytest.raises(CurrencyMismatchError, match="expected EUR, got USD"):
        builder.build([comparable("usd", "20", "USD")], "EUR")


def test_currency_is_preserved_through_statistics_outliers_and_estimate() -> None:
    dataset = DefaultPriceDatasetBuilder().build(
        [comparable("a", "10", "EUR"), comparable("b", "20", "EUR")], "EUR"
    )
    statistics = DefaultPriceStatistics().calculate(dataset)
    outliers = DefaultOutlierRemoval().remove_outliers(dataset, statistics)
    clean_statistics = DefaultPriceStatistics().calculate(outliers.clean_dataset)
    market = DefaultMarketPriceEstimator().estimate(
        outliers.clean_dataset, clean_statistics, outliers.removed_count
    )
    valuation = GameValuation.from_market_estimate(game(), market)

    assert dataset.currency == statistics.currency == outliers.currency == "EUR"
    assert market.currency == valuation.currency == "EUR"


def test_outliers_and_estimator_reject_mismatched_statistics() -> None:
    dataset = DefaultPriceDatasetBuilder().build(
        [comparable("a", "10", "EUR"), comparable("b", "20", "EUR")], "EUR"
    )
    statistics = DefaultPriceStatistics().calculate(dataset)
    statistics.currency = "USD"
    with pytest.raises(CurrencyMismatchError, match="OutlierRemoval"):
        DefaultOutlierRemoval().remove_outliers(dataset, statistics)
    with pytest.raises(CurrencyMismatchError, match="MarketPriceEstimator"):
        DefaultMarketPriceEstimator().estimate(dataset, statistics, 0)


def test_detector_rejects_candidate_estimate_currency_mismatch() -> None:
    detector = DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral())
    with pytest.raises(CurrencyMismatchError, match="expected EUR, got USD"):
        detector.detect(candidate("EUR"), estimate("USD"))


def test_lot_analyzer_rejects_mixed_valuations() -> None:
    valuations = [
        GameValuation.from_market_estimate(game("GTA V"), estimate("EUR")),
        GameValuation.from_market_estimate(game("RDR2"), estimate("USD")),
    ]
    analyzer = DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral())
    with pytest.raises(CurrencyMismatchError, match="expected EUR, got USD"):
        analyzer.analyze(candidate("EUR"), valuations, 2)


def test_policy_and_opportunity_preserve_currency_and_asdict() -> None:
    breakdown = ResaleEconomicPolicy.neutral().calculate(
        [Decimal("20")], Decimal("10"), "EUR"
    )
    opportunity = DefaultArbitrageOpportunityDetector(
        ResaleEconomicPolicy.neutral()
    ).detect(candidate("EUR"), estimate("EUR"))
    assert breakdown.currency == opportunity.currency == "EUR"
    assert asdict(opportunity)["economic_breakdown"]["currency"] == "EUR"
    assert isinstance(asdict(opportunity)["economic_breakdown"]["net_profit"], Decimal)


def test_wallapop_collector_normalizes_external_currency_and_rejects_missing() -> None:
    detector = Mock()
    detector.detect_games.return_value = [game()]
    comparable_filter = Mock()
    comparable_filter.is_valid_comparable.return_value = True
    collector = WallapopPriceCollector(Mock(), detector, comparable_filter)
    raw = {"id": "1", "title": "GTA V", "price": "12.99", "currency": " eur "}
    result = collector._process_listing(raw, game())
    assert result is not None and result.currency == "EUR"
    assert collector._process_listing({"id": "2", "title": "GTA V", "price": 10}, game()) is None
