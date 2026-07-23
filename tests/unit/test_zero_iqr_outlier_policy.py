"""P1.13 conservative and deterministic zero-IQR behavior."""

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from domain.currency import CurrencyMismatchError
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.interfaces.price_dataset_builder import PriceDataset, PriceObservation
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def dataset(prices: list[str], currency: str = "EUR") -> PriceDataset:
    game = DetectedGame("GTA V", "GTA V", Platform.PS4, 1.0, DetectionMethod.EXACT_MATCH)
    observations = [
        PriceObservation(
            Decimal(price), currency, str(index), "GTA V", "PS4", "test", {}
        )
        for index, price in enumerate(prices)
    ]
    return PriceDataset(
        observations, game, datetime.now(UTC), len(observations), currency
    )


@pytest.mark.parametrize(
    ("prices", "expected_min", "expected_max"),
    [
        (["10.00"] * 4, Decimal("10.00"), Decimal("10.00")),
        (["10"] * 6 + ["11"], Decimal("10"), Decimal("11")),
        (["10"] * 6 + ["100"], Decimal("10"), Decimal("100")),
    ],
)
def test_zero_iqr_keeps_every_observation_with_effective_bounds(
    prices: list[str], expected_min: Decimal, expected_max: Decimal
) -> None:
    original = dataset(prices)
    original_order = list(original.observations)
    statistics = DefaultPriceStatistics().calculate(original)
    assert statistics.iqr == Decimal("0")

    first = DefaultOutlierRemoval().remove_outliers(original, statistics)
    second = DefaultOutlierRemoval().remove_outliers(original, statistics)

    assert first.lower_bound == expected_min
    assert first.upper_bound == expected_max
    assert first.removed_observations == []
    assert first.removed_count == 0
    assert first.kept_count == original.sample_size
    assert len(first.clean_dataset.observations) == original.sample_size
    assert first.clean_dataset.observations == original_order
    assert first.clean_dataset.observations is not original.observations
    assert original.observations == original_order
    assert first.currency == original.currency == statistics.currency == "EUR"
    assert all(
        first.lower_bound <= observation.price <= first.upper_bound
        for observation in first.clean_dataset.observations
    )
    assert (
        first.lower_bound,
        first.upper_bound,
        first.removed_observations,
        first.clean_dataset.observations,
    ) == (
        second.lower_bound,
        second.upper_bound,
        second.removed_observations,
        second.clean_dataset.observations,
    )


def test_positive_iqr_keeps_existing_tukey_fences_and_order() -> None:
    original = dataset(["10", "11", "12", "13", "14", "15", "100"])
    statistics = DefaultPriceStatistics().calculate(original)
    result = DefaultOutlierRemoval().remove_outliers(original, statistics)

    assert statistics.q1 == Decimal("11")
    assert statistics.q3 == Decimal("15")
    assert statistics.iqr == Decimal("4")
    assert result.lower_bound == Decimal("5.0")
    assert result.upper_bound == Decimal("21.0")
    assert [item.price for item in result.clean_dataset.observations] == [
        Decimal(value) for value in ("10", "11", "12", "13", "14", "15")
    ]
    assert [item.price for item in result.removed_observations] == [Decimal("100")]
    assert (result.kept_count, result.removed_count) == (6, 1)


@pytest.mark.parametrize("prices", [["10"], ["10", "11"], ["10", "10", "11"]])
def test_small_datasets_keep_current_no_removal_contract(prices: list[str]) -> None:
    original = dataset(prices)
    statistics = DefaultPriceStatistics().calculate(original)
    result = DefaultOutlierRemoval().remove_outliers(original, statistics)
    assert result.removed_count == 0
    assert result.kept_count == len(prices)
    assert result.lower_bound == min(map(Decimal, prices))
    assert result.upper_bound == max(map(Decimal, prices))


def test_currency_mismatch_precedes_zero_iqr_branch() -> None:
    original = dataset(["10"] * 4)
    statistics = DefaultPriceStatistics().calculate(original)
    statistics.currency = "USD"
    with pytest.raises(CurrencyMismatchError, match="expected EUR, got USD"):
        DefaultOutlierRemoval().remove_outliers(original, statistics)


def test_estimator_receives_complete_heterogeneous_zero_iqr_dataset() -> None:
    original = dataset(["10"] * 6 + ["100"])
    statistics = DefaultPriceStatistics().calculate(original)
    result = DefaultOutlierRemoval().remove_outliers(original, statistics)
    clean_statistics = DefaultPriceStatistics().calculate(result.clean_dataset)
    estimate = DefaultMarketPriceEstimator().estimate(
        result.clean_dataset, clean_statistics, result.removed_count
    )
    assert estimate.sample_size == 7
    assert estimate.observations_removed == 0
    assert estimate.outlier_percentage == 0.0
    assert estimate.minimum_price == Decimal("10")
    assert estimate.maximum_price == Decimal("100")
    assert estimate.estimated_price == Decimal("10")


def test_outlier_module_has_one_explicit_zero_iqr_branch_and_no_fallback() -> None:
    source = Path("src/infrastructure/outliers/default_outlier_removal.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    zero_comparisons = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and "statistics.iqr" in ast.unparse(node)
        and "Decimal('0')" in ast.unparse(node)
    ]
    assert len(zero_comparisons) == 1
    lowered = source.casefold()
    assert all(
        token not in lowered
        for token in ("median_absolute", "zscore", "z_score", "isclose", "epsilon", "quantize", "getcontext")
    )
