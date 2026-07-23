"""Explicit Decimal-based economic policy and auditable resale calculation."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from types import MappingProxyType

from domain._decimal import require_decimal
from domain.currency import validate_currency_code

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class EconomicBreakdown:
    """Complete result of applying a resale economic policy."""

    reference_market_value: Decimal
    expected_item_sale_prices: tuple[Decimal, ...]
    expected_sale_revenue: Decimal
    quick_sale_discount_total: Decimal
    selling_fees: Decimal
    fixed_selling_costs: Decimal
    safety_buffer: Decimal
    acquisition_price: Decimal
    acquisition_overhead: Decimal
    total_acquisition_cost: Decimal
    net_expected_proceeds: Decimal
    net_profit: Decimal
    break_even_sale_revenue: Decimal
    item_count: int
    currency: str

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name not in {
                "expected_item_sale_prices",
                "item_count",
                "currency",
            }:
                require_decimal(field.name, getattr(self, field.name))
        for price in self.expected_item_sale_prices:
            require_decimal("expected_item_sale_prices", price, non_negative=True)
        validate_currency_code(self.currency)

    @property
    def net_profit_margin_percentage(self) -> Decimal:
        if self.expected_sale_revenue > ZERO:
            return self.net_profit / self.expected_sale_revenue * HUNDRED
        return ZERO

    @property
    def net_roi_percentage(self) -> Decimal:
        if self.total_acquisition_cost > ZERO:
            return self.net_profit / self.total_acquisition_cost * HUNDRED
        return ZERO

    @property
    def acquisition_discount_to_reference_market_percentage(self) -> Decimal:
        if self.reference_market_value > ZERO:
            return (
                (self.reference_market_value - self.acquisition_price)
                / self.reference_market_value
                * HUNDRED
            )
        return ZERO


@dataclass(frozen=True)
class ResaleAbsoluteCosts:
    """Absolute resale costs for one currency."""

    quick_sale_discount_per_item: Decimal
    fixed_selling_cost_per_item: Decimal
    acquisition_overhead: Decimal

    def __post_init__(self) -> None:
        for field in fields(self):
            require_decimal(field.name, getattr(self, field.name), non_negative=True)


@dataclass(frozen=True)
class ResaleEconomicPolicy:
    """Currency-aware absolute costs and global dimensionless rates."""

    absolute_costs_by_currency: Mapping[str, ResaleAbsoluteCosts]
    selling_fee_rate: Decimal
    safety_buffer_rate: Decimal

    def __post_init__(self) -> None:
        validated_costs: dict[str, ResaleAbsoluteCosts] = {}
        for currency, costs in self.absolute_costs_by_currency.items():
            validate_currency_code(currency, "absolute_costs_by_currency key")
            if not isinstance(costs, ResaleAbsoluteCosts):
                raise TypeError(
                    "absolute_costs_by_currency values must be ResaleAbsoluteCosts"
                )
            validated_costs[currency] = costs
        object.__setattr__(
            self,
            "absolute_costs_by_currency",
            MappingProxyType(validated_costs),
        )

        for name, value in {
            "selling_fee_rate": self.selling_fee_rate,
            "safety_buffer_rate": self.safety_buffer_rate,
        }.items():
            require_decimal(name, value, non_negative=True)
        if self.selling_fee_rate >= ONE:
            raise ValueError("selling_fee_rate must be less than 1")
        if self.safety_buffer_rate >= ONE:
            raise ValueError("safety_buffer_rate must be less than 1")
        if self.selling_fee_rate + self.safety_buffer_rate >= ONE:
            raise ValueError("selling_fee_rate + safety_buffer_rate must be less than 1")

    @classmethod
    def neutral(cls, currency: str = "EUR") -> "ResaleEconomicPolicy":
        validate_currency_code(currency)
        return cls(
            {currency: ResaleAbsoluteCosts(ZERO, ZERO, ZERO)},
            ZERO,
            ZERO,
        )

    def _absolute_costs_for_currency(
        self, currency: str
    ) -> ResaleAbsoluteCosts:
        try:
            return self.absolute_costs_by_currency[currency]
        except KeyError:
            raise ValueError(
                f"No resale absolute costs configured for currency {currency}"
            ) from None

    def calculate(
        self,
        reference_item_prices: Sequence[Decimal],
        acquisition_price: Decimal,
        currency: str,
    ) -> EconomicBreakdown:
        """Calculate an auditable economic breakdown without rounding."""
        prices = tuple(reference_item_prices)
        for price in prices:
            require_decimal("reference item prices", price, non_negative=True)
        require_decimal("acquisition_price", acquisition_price, non_negative=True)
        validate_currency_code(currency)
        absolute_costs = self._absolute_costs_for_currency(currency)

        expected_prices = tuple(
            max(ZERO, price - absolute_costs.quick_sale_discount_per_item)
            for price in prices
        )
        reference_market_value = sum(prices, ZERO)
        expected_sale_revenue = sum(expected_prices, ZERO)
        quick_sale_discount_total = reference_market_value - expected_sale_revenue
        selling_fees = expected_sale_revenue * self.selling_fee_rate
        fixed_selling_costs = (
            Decimal(len(prices)) * absolute_costs.fixed_selling_cost_per_item
        )
        safety_buffer = expected_sale_revenue * self.safety_buffer_rate
        total_acquisition_cost = acquisition_price + absolute_costs.acquisition_overhead
        net_expected_proceeds = (
            expected_sale_revenue
            - selling_fees
            - fixed_selling_costs
            - safety_buffer
        )
        net_profit = net_expected_proceeds - total_acquisition_cost
        break_even_sale_revenue = (
            total_acquisition_cost + fixed_selling_costs
        ) / (ONE - self.selling_fee_rate - self.safety_buffer_rate)

        return EconomicBreakdown(
            reference_market_value,
            expected_prices,
            expected_sale_revenue,
            quick_sale_discount_total,
            selling_fees,
            fixed_selling_costs,
            safety_buffer,
            acquisition_price,
            absolute_costs.acquisition_overhead,
            total_acquisition_cost,
            net_expected_proceeds,
            net_profit,
            break_even_sale_revenue,
            len(prices),
            currency,
        )
