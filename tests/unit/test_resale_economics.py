"""Exact Decimal regressions for resale economics."""

from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal, getcontext

import pytest

from domain.entities.resale_economics import (
    ResaleAbsoluteCosts,
    ResaleEconomicPolicy,
)


def policy(**overrides: Decimal) -> ResaleEconomicPolicy:
    values: dict[str, Decimal] = {
        "quick_sale_discount_per_item": Decimal("3"),
        "fixed_selling_cost_per_item": Decimal("1"),
        "acquisition_overhead": Decimal("2"),
    }
    absolute_names = set(values)
    values.update({key: value for key, value in overrides.items() if key in absolute_names})
    return ResaleEconomicPolicy(
        {"EUR": ResaleAbsoluteCosts(**values)},
        overrides.get("selling_fee_rate", Decimal("0.10")),
        overrides.get("safety_buffer_rate", Decimal("0.05")),
    )


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
        {"EUR": ResaleAbsoluteCosts(Decimal("0.10"), Decimal("0"), Decimal("0"))},
        Decimal("0"),
        Decimal("0"),
    ).calculate([Decimal("0.30")], Decimal("0.10"), "EUR")
    assert breakdown.expected_sale_revenue == Decimal("0.20")
    assert breakdown.net_profit == Decimal("0.10")


def test_required_lot_example() -> None:
    breakdown = ResaleEconomicPolicy(
        {"EUR": ResaleAbsoluteCosts(Decimal("3"), Decimal("0"), Decimal("0"))},
        Decimal("0"),
        Decimal("0"),
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
        ResaleAbsoluteCosts(3.0, Decimal("0"), Decimal("0"))  # type: ignore[arg-type]


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


@pytest.mark.parametrize(
    "value", [Decimal("0"), Decimal("1"), Decimal("999999999999")]
)
def test_absolute_cost_value_object_accepts_valid_decimals(value: Decimal) -> None:
    costs = ResaleAbsoluteCosts(value, value, value)
    assert costs == ResaleAbsoluteCosts(value, value, value)
    assert "0x" not in repr(costs)


@pytest.mark.parametrize(
    "value", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 1.0, True]
)
def test_absolute_cost_value_object_rejects_invalid_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ResaleAbsoluteCosts(value, Decimal("0"), Decimal("0"))  # type: ignore[arg-type]


@pytest.mark.parametrize("currency", ["EUR", "USD", "GBP"])
def test_neutral_configures_only_requested_currency(currency: str) -> None:
    economic_policy = ResaleEconomicPolicy.neutral(currency)
    zero_costs = ResaleAbsoluteCosts(Decimal("0"), Decimal("0"), Decimal("0"))

    assert economic_policy.absolute_costs_by_currency == {currency: zero_costs}
    assert economic_policy.selling_fee_rate == Decimal("0")
    assert economic_policy.safety_buffer_rate == Decimal("0")
    breakdown = economic_policy.calculate([Decimal("20")], Decimal("5"), currency)
    assert breakdown.net_profit == Decimal("15")
    for other in {"EUR", "USD", "GBP"} - {currency}:
        with pytest.raises(
            ValueError,
            match=f"No resale absolute costs configured for currency {other}",
        ):
            economic_policy.calculate([Decimal("20")], Decimal("5"), other)


def test_neutral_defaults_only_to_eur() -> None:
    economic_policy = ResaleEconomicPolicy.neutral()
    assert set(economic_policy.absolute_costs_by_currency) == {"EUR"}
    with pytest.raises(ValueError, match="currency USD"):
        economic_policy.calculate([Decimal("20")], Decimal("5"), "USD")


@pytest.mark.parametrize(
    "currency", ["", "eur", " EUR", "EUR ", "€", "EURO", None, 123, True]
)
def test_policy_rejects_invalid_currency_keys(currency: object) -> None:
    costs = ResaleAbsoluteCosts(Decimal("0"), Decimal("0"), Decimal("0"))
    with pytest.raises((TypeError, ValueError), match="absolute_costs_by_currency key"):
        ResaleEconomicPolicy(
            {currency: costs},  # type: ignore[dict-item]
            Decimal("0"),
            Decimal("0"),
        )


@pytest.mark.parametrize(
    "value", [{}, (), [], None, Decimal("0"), object(), True]
)
def test_policy_rejects_non_value_object_mapping_values(value: object) -> None:
    with pytest.raises(
        TypeError,
        match="absolute_costs_by_currency values must be ResaleAbsoluteCosts",
    ):
        ResaleEconomicPolicy(
            {"EUR": value},  # type: ignore[dict-item]
            Decimal("0"),
            Decimal("0"),
        )


def test_empty_mapping_constructs_but_cannot_calculate() -> None:
    economic_policy = ResaleEconomicPolicy({}, Decimal("0"), Decimal("0"))
    with pytest.raises(ValueError, match="currency EUR"):
        economic_policy.calculate([Decimal("20")], Decimal("5"), "EUR")


def test_policy_copies_absolute_cost_mapping_defensively() -> None:
    original = ResaleAbsoluteCosts(Decimal("3"), Decimal("1"), Decimal("2"))
    costs = {"EUR": original}
    economic_policy = ResaleEconomicPolicy(costs, Decimal("0"), Decimal("0"))
    costs["EUR"] = ResaleAbsoluteCosts(Decimal("999"), Decimal("999"), Decimal("999"))
    costs["USD"] = ResaleAbsoluteCosts(Decimal("1"), Decimal("1"), Decimal("1"))

    assert economic_policy.absolute_costs_by_currency == {"EUR": original}
    with pytest.raises(TypeError):
        economic_policy.absolute_costs_by_currency["EUR"] = original  # type: ignore[index]
    with pytest.raises(ValueError, match="currency USD"):
        economic_policy.calculate([Decimal("20")], Decimal("5"), "USD")


def test_currency_specific_absolute_cost_bundles_are_exact() -> None:
    economic_policy = ResaleEconomicPolicy(
        {
            "EUR": ResaleAbsoluteCosts(Decimal("3"), Decimal("1"), Decimal("2")),
            "USD": ResaleAbsoluteCosts(Decimal("2"), Decimal("0.50"), Decimal("1")),
            "GBP": ResaleAbsoluteCosts(Decimal("4"), Decimal("2"), Decimal("3")),
        },
        Decimal("0"),
        Decimal("0"),
    )
    expected = {
        "EUR": (Decimal("17"), Decimal("1"), Decimal("7"), Decimal("16"), Decimal("9"), Decimal("8")),
        "USD": (Decimal("18"), Decimal("0.50"), Decimal("6"), Decimal("17.50"), Decimal("11.50"), Decimal("6.50")),
        "GBP": (Decimal("16"), Decimal("2"), Decimal("8"), Decimal("14"), Decimal("6"), Decimal("10")),
    }

    for currency, values in expected.items():
        breakdown = economic_policy.calculate([Decimal("20")], Decimal("5"), currency)
        assert (
            breakdown.expected_sale_revenue,
            breakdown.fixed_selling_costs,
            breakdown.total_acquisition_cost,
            breakdown.net_expected_proceeds,
            breakdown.net_profit,
            breakdown.break_even_sale_revenue,
        ) == values


def test_per_item_and_per_operation_semantics_are_unchanged() -> None:
    economic_policy = ResaleEconomicPolicy(
        {"EUR": ResaleAbsoluteCosts(Decimal("2"), Decimal("1"), Decimal("3"))},
        Decimal("0"),
        Decimal("0"),
    )
    one = economic_policy.calculate([Decimal("20")], Decimal("5"), "EUR")
    two = economic_policy.calculate(
        [Decimal("20"), Decimal("30")], Decimal("5"), "EUR"
    )

    assert (one.item_count, one.quick_sale_discount_total, one.fixed_selling_costs, one.acquisition_overhead) == (
        1, Decimal("2"), Decimal("1"), Decimal("3")
    )
    assert (two.item_count, two.quick_sale_discount_total, two.fixed_selling_costs, two.acquisition_overhead) == (
        2, Decimal("4"), Decimal("2"), Decimal("3")
    )
