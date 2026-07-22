"""Explicit Decimal-based economic policy and auditable resale calculation."""

from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal

from domain._decimal import require_decimal

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

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name not in {"expected_item_sale_prices", "item_count"}:
                require_decimal(field.name, getattr(self, field.name))
        for price in self.expected_item_sale_prices:
            require_decimal("expected_item_sale_prices", price, non_negative=True)

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
class ResaleEconomicPolicy:
    """Configuration for converting market references into net economics."""

    quick_sale_discount_per_item: Decimal
    selling_fee_rate: Decimal
    fixed_selling_cost_per_item: Decimal
    acquisition_overhead: Decimal
    safety_buffer_rate: Decimal

    def __post_init__(self) -> None:
        values = {
            "quick_sale_discount_per_item": self.quick_sale_discount_per_item,
            "selling_fee_rate": self.selling_fee_rate,
            "fixed_selling_cost_per_item": self.fixed_selling_cost_per_item,
            "acquisition_overhead": self.acquisition_overhead,
            "safety_buffer_rate": self.safety_buffer_rate,
        }
        for name, value in values.items():
            require_decimal(name, value, non_negative=True)
        if self.selling_fee_rate >= ONE:
            raise ValueError("selling_fee_rate must be less than 1")
        if self.safety_buffer_rate >= ONE:
            raise ValueError("safety_buffer_rate must be less than 1")
        if self.selling_fee_rate + self.safety_buffer_rate >= ONE:
            raise ValueError("selling_fee_rate + safety_buffer_rate must be less than 1")

    @classmethod
    def neutral(cls) -> "ResaleEconomicPolicy":
        return cls(ZERO, ZERO, ZERO, ZERO, ZERO)

    def calculate(
        self,
        reference_item_prices: Sequence[Decimal],
        acquisition_price: Decimal,
    ) -> EconomicBreakdown:
        """Calculate an auditable economic breakdown without rounding."""
        require_decimal("acquisition_price", acquisition_price, non_negative=True)
        prices = tuple(reference_item_prices)
        for price in prices:
            require_decimal("reference item prices", price, non_negative=True)

        expected_prices = tuple(
            max(ZERO, price - self.quick_sale_discount_per_item) for price in prices
        )
        reference_market_value = sum(prices, ZERO)
        expected_sale_revenue = sum(expected_prices, ZERO)
        quick_sale_discount_total = reference_market_value - expected_sale_revenue
        selling_fees = expected_sale_revenue * self.selling_fee_rate
        fixed_selling_costs = Decimal(len(prices)) * self.fixed_selling_cost_per_item
        safety_buffer = expected_sale_revenue * self.safety_buffer_rate
        total_acquisition_cost = acquisition_price + self.acquisition_overhead
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
            self.acquisition_overhead,
            total_acquisition_cost,
            net_expected_proceeds,
            net_profit,
            break_even_sale_revenue,
            len(prices),
        )
