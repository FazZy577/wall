"""Exact Decimal regressions for resale economics."""

from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal, getcontext

import pytest

from domain.entities.resale_economics import ResaleEconomicPolicy


def policy(**overrides: Decimal) -> ResaleEconomicPolicy:
    values = {
        "quick_sale_discount_per_item": Decimal("3"),
        "selling_fee_rate": Decimal("0.10"),
        "fixed_selling_cost_per_item": Decimal("1"),
        "acquisition_overhead": Decimal("2"),
        "safety_buffer_rate": Decimal("0.05"),
    }
    values.update(overrides)
    return ResaleEconomicPolicy(**values)


def test_required_individual_economic_breakdown() -> None:
    breakdown = policy().calculate([Decimal("20")], Decimal("10"), "EUR")
    assert breakdown.expected_sale_revenue == Decimal("17")
    assert breakdown.selling_fees == Decimal("1.70")
    assert breakdown.fixed_selling_costs == Decimal("1")
    assert breakdown.safety_buffer == Decimal("0.85")
    assert breakdown.total_acquisition_cost == Decimal("12")
    assert breakdown.net_expected_proceeds == Decimal("13.45")
    assert breakdown.net_profit == Decimal("1.45")
    assert breakdown.break_even_sale_revenue == Decimal("13") / Decimal("0.85")


def test_binary_artifact_case_is_exact() -> None:
    breakdown = ResaleEconomicPolicy(
        Decimal("0.10"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    ).calculate([Decimal("0.30")], Decimal("0.10"), "EUR")
    assert breakdown.expected_sale_revenue == Decimal("0.20")
    assert breakdown.net_profit == Decimal("0.10")


def test_required_lot_example() -> None:
    breakdown = ResaleEconomicPolicy(
        Decimal("3"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
    ).calculate(
        [Decimal("15"), Decimal("20"), Decimal("10")], Decimal("40"), "EUR"
    )
    assert breakdown.expected_item_sale_prices == (
        Decimal("12"), Decimal("17"), Decimal("7")
    )
    assert breakdown.reference_market_value == Decimal("45")
    assert breakdown.expected_sale_revenue == Decimal("36")
    assert breakdown.net_profit == Decimal("-4")


def test_quick_sale_discount_is_capped_at_zero() -> None:
    breakdown = policy(
        selling_fee_rate=Decimal("0"),
        fixed_selling_cost_per_item=Decimal("0"),
        acquisition_overhead=Decimal("0"),
        safety_buffer_rate=Decimal("0"),
    ).calculate([Decimal("2")], Decimal("0"), "EUR")
    assert breakdown.expected_item_sale_prices == (Decimal("0"),)


def test_breakdown_invariants_and_asdict_preserve_decimal() -> None:
    breakdown = policy().calculate(
        [Decimal("20"), Decimal("2")], Decimal("10"), "EUR"
    )
    assert breakdown.reference_market_value - breakdown.expected_sale_revenue == breakdown.quick_sale_discount_total
    assert breakdown.expected_sale_revenue - breakdown.selling_fees - breakdown.fixed_selling_costs - breakdown.safety_buffer == breakdown.net_expected_proceeds
    assert breakdown.net_expected_proceeds - breakdown.total_acquisition_cost == breakdown.net_profit
    assert breakdown.total_acquisition_cost == breakdown.acquisition_price + breakdown.acquisition_overhead
    assert breakdown.item_count == len(breakdown.expected_item_sale_prices)
    assert isinstance(asdict(breakdown)["net_profit"], Decimal)


@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_decimal_policy_values_are_rejected(value: Decimal) -> None:
    with pytest.raises(ValueError):
        policy(quick_sale_discount_per_item=value)


def test_policy_rejects_float() -> None:
    with pytest.raises(TypeError, match="must be Decimal"):
        ResaleEconomicPolicy(3.0, Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))  # type: ignore[arg-type]


def test_calculation_rejects_float_inputs() -> None:
    with pytest.raises(TypeError, match="must be Decimal"):
        policy().calculate([Decimal("20")], 10.0, "EUR")  # type: ignore[arg-type]


def test_combined_rates_must_leave_positive_revenue() -> None:
    with pytest.raises(ValueError, match="must be less than 1"):
        policy(selling_fee_rate=Decimal("0.6"), safety_buffer_rate=Decimal("0.4"))


def test_policy_and_breakdown_are_immutable_and_context_is_untouched() -> None:
    precision = getcontext().prec
    economic_policy = policy()
    breakdown = economic_policy.calculate([Decimal("20")], Decimal("10"), "EUR")
    assert getcontext().prec == precision
    with pytest.raises(FrozenInstanceError):
        economic_policy.selling_fee_rate = Decimal("0")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        breakdown.net_profit = Decimal("99")  # type: ignore[misc]
