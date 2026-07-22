"""P1.11 Decimal type, boundary, and architecture protections."""

import ast
from dataclasses import asdict, fields
from decimal import Decimal, getcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.market_price_estimator import MarketPriceEstimate
from domain.interfaces.price_dataset_builder import PriceDataset, PriceObservation
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector
from infrastructure.estimators.default_market_price_estimator import DefaultMarketPriceEstimator
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def game() -> DetectedGame:
    return DetectedGame("GTA V", "GTA V", Platform.PS4, 1.0, DetectionMethod.EXACT_MATCH)


def comparable(price: Decimal) -> ComparableListing:
    return ComparableListing("id", "GTA V", "", price, "EUR", game(), "url")


@pytest.mark.parametrize("model", ["candidate", "comparable"])
def test_listing_models_reject_float_prices(model: str) -> None:
    with pytest.raises(TypeError, match="price must be Decimal"):
        if model == "candidate":
            CandidateListing("id", "GTA V", "", 10.0, "EUR", "url")  # type: ignore[arg-type]
        else:
            ComparableListing("id", "GTA V", "", 10.0, "EUR", game(), "url")  # type: ignore[arg-type]


@pytest.mark.parametrize("external_price", ["12.99", 1299, 12.99])
def test_wallapop_external_prices_are_normalized_once(
    external_price: str | int | float,
) -> None:
    detector = Mock()
    detector.detect_games.return_value = [game()]
    comparable_filter = Mock()
    comparable_filter.is_valid_comparable.return_value = True
    collector = WallapopPriceCollector(Mock(), detector, comparable_filter)
    result = collector._process_listing(
        {
            "id": "id",
            "title": "GTA V",
            "description": "",
            "price": external_price,
            "currency": "EUR",
        },
        game(),
    )
    assert result is not None
    expected = Decimal("1299") if external_price == 1299 else Decimal("12.99")
    assert result.price == expected


def test_decimal_statistics_outliers_and_estimate_preserve_types() -> None:
    observations = [
        PriceObservation(value, "EUR", str(index), "GTA V", "PS4", "test", {})
        for index, value in enumerate(
            [Decimal("0.10"), Decimal("0.20"), Decimal("0.30")]
        )
    ]
    dataset = PriceDataset(observations, game(), Mock(), 3)
    statistics = DefaultPriceStatistics().calculate(dataset)
    outliers = DefaultOutlierRemoval().remove_outliers(dataset, statistics)
    estimate = DefaultMarketPriceEstimator().estimate(dataset, statistics, 0)
    assert statistics.mean_price == Decimal("0.20")
    assert statistics.median_price == Decimal("0.20")
    assert isinstance(outliers.lower_bound, Decimal)
    assert isinstance(outliers.upper_bound, Decimal)
    assert estimate.estimated_price == Decimal("0.20")
    assert all(isinstance(item.price, Decimal) for item in dataset.observations)


def test_real_cent_statistics_remain_decimal() -> None:
    values = [Decimal("12.99"), Decimal("13.49"), Decimal("14.01")]
    dataset = PriceDataset(
        [PriceObservation(value, "EUR", str(i), "G", "PS4", "test", {}) for i, value in enumerate(values)],
        game(),
        Mock(),
        3,
    )
    result = DefaultPriceStatistics().calculate(dataset)
    assert result.mean_price == sum(values, Decimal("0")) / Decimal("3")
    assert result.median_price == Decimal("13.49")


def test_asdict_keeps_nested_decimal_values() -> None:
    breakdown = ResaleEconomicPolicy.neutral().calculate(
        [Decimal("20")], Decimal("10")
    )
    serialized = asdict(breakdown)
    assert isinstance(serialized["net_profit"], Decimal)
    assert isinstance(serialized["expected_item_sale_prices"][0], Decimal)


def test_canonical_monetary_fields_and_scores_have_expected_types() -> None:
    assert {field.name: field.type for field in fields(CandidateListing)}[
        "price"
    ] is Decimal
    estimate_types = {field.name: field.type for field in fields(MarketPriceEstimate)}
    assert estimate_types["estimated_price"] is Decimal
    assert estimate_types["confidence_score"] is float


def test_no_direct_decimal_float_or_global_context_mutation_in_production() -> None:
    source_root = Path(__file__).parents[2] / "src"
    precision = getcontext().prec
    violations: list[str] = []
    for source_file in source_root.rglob("*.py"):
        source = source_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Decimal"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, float)
            ):
                violations.append(str(source_file))
        assert "getcontext().prec" not in source
    assert violations == []
    assert getcontext().prec == precision


def test_no_money_value_object_exists() -> None:
    source_root = Path(__file__).parents[2] / "src"
    definitions = []
    for source_file in source_root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        definitions.extend(
            node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "Money"
        )
    assert definitions == []
