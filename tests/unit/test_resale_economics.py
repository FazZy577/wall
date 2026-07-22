"""Tests for the canonical resale economic policy and breakdown."""

from dataclasses import FrozenInstanceError
from math import inf, nan

import pytest

from domain.entities.resale_economics import ResaleEconomicPolicy


def policy(**overrides: float) -> ResaleEconomicPolicy:
    values = {
        "quick_sale_discount_per_item": 3.0,
        "selling_fee_rate": 0.10,
        "fixed_selling_cost_per_item": 1.0,
        "acquisition_overhead": 2.0,
        "safety_buffer_rate": 0.05,
    }
    values.update(overrides)
    return ResaleEconomicPolicy(**values)


def test_required_individual_economic_breakdown() -> None:
    breakdown = policy().calculate([20.0], 10.0)

    assert breakdown.reference_market_value == 20.0
    assert breakdown.expected_item_sale_prices == (17.0,)
    assert breakdown.expected_sale_revenue == 17.0
    assert breakdown.quick_sale_discount_total == 3.0
    assert breakdown.selling_fees == pytest.approx(1.70)
    assert breakdown.fixed_selling_costs == 1.0
    assert breakdown.safety_buffer == pytest.approx(0.85)
    assert breakdown.total_acquisition_cost == 12.0
    assert breakdown.net_expected_proceeds == pytest.approx(13.45)
    assert breakdown.net_profit == pytest.approx(1.45)
    assert breakdown.break_even_sale_revenue == pytest.approx(13 / 0.85)
    assert breakdown.item_count == 1


def test_quick_sale_discount_is_capped_per_item_at_zero() -> None:
    breakdown = policy(
        selling_fee_rate=0.0,
        fixed_selling_cost_per_item=0.0,
        acquisition_overhead=0.0,
        safety_buffer_rate=0.0,
    ).calculate([2.0], 0.0)

    assert breakdown.expected_item_sale_prices == (0.0,)
    assert breakdown.quick_sale_discount_total == 2.0


def test_required_lot_and_neutral_examples() -> None:
    quick_sale = ResaleEconomicPolicy(3.0, 0.0, 0.0, 0.0, 0.0).calculate(
        [15.0, 20.0, 10.0], 40.0
    )
    neutral_individual = ResaleEconomicPolicy.neutral().calculate([20.0], 10.0)
    neutral_lot = ResaleEconomicPolicy.neutral().calculate(
        [15.0, 20.0, 10.0], 40.0
    )

    assert quick_sale.expected_item_sale_prices == (12.0, 17.0, 7.0)
    assert quick_sale.reference_market_value == 45.0
    assert quick_sale.expected_sale_revenue == 36.0
    assert quick_sale.quick_sale_discount_total == 9.0
    assert quick_sale.net_expected_proceeds == 36.0
    assert quick_sale.net_profit == -4.0
    assert neutral_individual.net_profit == 10.0
    assert neutral_lot.net_profit == 5.0


def test_empty_prices_keep_acquisition_cost_and_negative_profit() -> None:
    breakdown = policy().calculate([], 40.0)

    assert breakdown.item_count == 0
    assert breakdown.reference_market_value == 0
    assert breakdown.expected_sale_revenue == 0
    assert breakdown.selling_fees == 0
    assert breakdown.fixed_selling_costs == 0
    assert breakdown.safety_buffer == 0
    assert breakdown.total_acquisition_cost == 42.0
    assert breakdown.net_profit == -42.0


def test_breakdown_invariants() -> None:
    breakdown = policy().calculate([20.0, 2.0], 10.0)

    assert breakdown.reference_market_value - breakdown.expected_sale_revenue == pytest.approx(
        breakdown.quick_sale_discount_total
    )
    assert (
        breakdown.expected_sale_revenue
        - breakdown.selling_fees
        - breakdown.fixed_selling_costs
        - breakdown.safety_buffer
    ) == pytest.approx(breakdown.net_expected_proceeds)
    assert breakdown.net_expected_proceeds - breakdown.total_acquisition_cost == pytest.approx(
        breakdown.net_profit
    )
    assert breakdown.total_acquisition_cost == (
        breakdown.acquisition_price + breakdown.acquisition_overhead
    )
    assert breakdown.item_count == len(breakdown.expected_item_sale_prices)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quick_sale_discount_per_item", -1.0),
        ("selling_fee_rate", -0.1),
        ("selling_fee_rate", 1.0),
        ("fixed_selling_cost_per_item", -1.0),
        ("acquisition_overhead", -1.0),
        ("safety_buffer_rate", -0.1),
        ("safety_buffer_rate", 1.0),
        ("quick_sale_discount_per_item", nan),
        ("selling_fee_rate", inf),
    ],
)
def test_invalid_policy_values_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        policy(**{field: value})


def test_combined_percentage_costs_must_leave_positive_revenue() -> None:
    with pytest.raises(ValueError, match="must be less than 1"):
        policy(selling_fee_rate=0.6, safety_buffer_rate=0.4)


@pytest.mark.parametrize("price", [-1.0, nan, inf])
def test_invalid_acquisition_price_is_rejected(price: float) -> None:
    with pytest.raises(ValueError):
        policy().calculate([20.0], price)


@pytest.mark.parametrize("price", [-1.0, nan, inf])
def test_invalid_reference_price_is_rejected(price: float) -> None:
    with pytest.raises(ValueError):
        policy().calculate([price], 10.0)


def test_policy_and_breakdown_are_immutable() -> None:
    economic_policy = policy()
    breakdown = economic_policy.calculate([20.0], 10.0)

    with pytest.raises(FrozenInstanceError):
        economic_policy.selling_fee_rate = 0.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        breakdown.net_profit = 99.0  # type: ignore[misc]
