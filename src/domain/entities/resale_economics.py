"""Explicit economic policy and auditable resale calculation."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class EconomicBreakdown:
    """Complete result of applying a resale economic policy."""

    reference_market_value: float
    expected_item_sale_prices: tuple[float, ...]
    expected_sale_revenue: float
    quick_sale_discount_total: float
    selling_fees: float
    fixed_selling_costs: float
    safety_buffer: float
    acquisition_price: float
    acquisition_overhead: float
    total_acquisition_cost: float
    net_expected_proceeds: float
    net_profit: float
    break_even_sale_revenue: float
    item_count: int

    @property
    def net_profit_margin_percentage(self) -> float:
        """Return net profit as a percentage of expected sale revenue."""
        if self.expected_sale_revenue > 0:
            return self.net_profit / self.expected_sale_revenue * 100.0
        return 0.0

    @property
    def net_roi_percentage(self) -> float:
        """Return net profit as a percentage of total acquisition cost."""
        if self.total_acquisition_cost > 0:
            return self.net_profit / self.total_acquisition_cost * 100.0
        return 0.0

    @property
    def acquisition_discount_to_reference_market_percentage(self) -> float:
        """Return acquisition-price discount against reference market value."""
        if self.reference_market_value > 0:
            return (
                (self.reference_market_value - self.acquisition_price)
                / self.reference_market_value
                * 100.0
            )
        return 0.0


@dataclass(frozen=True)
class ResaleEconomicPolicy:
    """Configuration for converting market references into net economics."""

    quick_sale_discount_per_item: float
    selling_fee_rate: float
    fixed_selling_cost_per_item: float
    acquisition_overhead: float
    safety_buffer_rate: float

    def __post_init__(self) -> None:
        values = {
            "quick_sale_discount_per_item": self.quick_sale_discount_per_item,
            "selling_fee_rate": self.selling_fee_rate,
            "fixed_selling_cost_per_item": self.fixed_selling_cost_per_item,
            "acquisition_overhead": self.acquisition_overhead,
            "safety_buffer_rate": self.safety_buffer_rate,
        }
        for name, value in values.items():
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.selling_fee_rate >= 1:
            raise ValueError("selling_fee_rate must be less than 1")
        if self.safety_buffer_rate >= 1:
            raise ValueError("safety_buffer_rate must be less than 1")
        if self.selling_fee_rate + self.safety_buffer_rate >= 1:
            raise ValueError("selling_fee_rate + safety_buffer_rate must be less than 1")

    @classmethod
    def neutral(cls) -> "ResaleEconomicPolicy":
        """Build an explicit zero-cost policy for regression comparisons."""
        return cls(0.0, 0.0, 0.0, 0.0, 0.0)

    def calculate(
        self,
        reference_item_prices: Sequence[float],
        acquisition_price: float,
    ) -> EconomicBreakdown:
        """Calculate an auditable economic breakdown without rounding."""
        if not isfinite(acquisition_price):
            raise ValueError("acquisition_price must be finite")
        if acquisition_price < 0:
            raise ValueError("acquisition_price must be non-negative")

        prices = tuple(reference_item_prices)
        for price in prices:
            if not isfinite(price):
                raise ValueError("reference item prices must be finite")
            if price < 0:
                raise ValueError("reference item prices must be non-negative")

        expected_prices = tuple(
            max(0.0, price - self.quick_sale_discount_per_item)
            for price in prices
        )
        reference_market_value = sum(prices)
        expected_sale_revenue = sum(expected_prices)
        quick_sale_discount_total = reference_market_value - expected_sale_revenue
        selling_fees = expected_sale_revenue * self.selling_fee_rate
        fixed_selling_costs = len(prices) * self.fixed_selling_cost_per_item
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
        ) / (1 - self.selling_fee_rate - self.safety_buffer_rate)

        return EconomicBreakdown(
            reference_market_value=reference_market_value,
            expected_item_sale_prices=expected_prices,
            expected_sale_revenue=expected_sale_revenue,
            quick_sale_discount_total=quick_sale_discount_total,
            selling_fees=selling_fees,
            fixed_selling_costs=fixed_selling_costs,
            safety_buffer=safety_buffer,
            acquisition_price=acquisition_price,
            acquisition_overhead=self.acquisition_overhead,
            total_acquisition_cost=total_acquisition_cost,
            net_expected_proceeds=net_expected_proceeds,
            net_profit=net_profit,
            break_even_sale_revenue=break_even_sale_revenue,
            item_count=len(prices),
        )
