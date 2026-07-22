"""Lot opportunity entity.

Represents the economic opportunity of buying a lot (bundle) of games.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from domain._decimal import require_decimal
from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.resale_economics import EconomicBreakdown
from domain.interfaces.arbitrage_opportunity_detector import Recommendation


class LotReasonCode(StrEnum):
    """Reason code for lot opportunity decisions.

    Separate from the individual ReasonCode because lot semantics differ:
    a lot can be undervalued even if individual games have varying prices.
    """

    UNDERVALUED_LOT = "undervalued_lot"
    FAIR_VALUE_LOT = "fair_value_lot"
    OVERPRICED_LOT = "overpriced_lot"
    LOW_AGGREGATE_CONFIDENCE = "low_aggregate_confidence"
    INCOMPLETE_VALUATION = "incomplete_valuation"
    NO_GAMES_DETECTED = "no_games_detected"
    INVALID_LOT_PRICE = "invalid_lot_price"


@dataclass
class LotOpportunity:
    """Economic opportunity of buying a complete lot of games.

    Computes aggregate metrics from individual game valuations.
    The lot price is compared against the sum of all game market values.

    Attributes:
        listing: The candidate listing (lot) being evaluated
        game_valuations: Individual valuations for each game in the lot
        lot_price: Total price of the lot (= listing.price)
        economic_breakdown: Single source of financial values and metrics
        aggregate_confidence_score: Mean of individual confidence scores
        recommendation: BUY, MAYBE, or SKIP
        reason: Why this recommendation was made
        opportunity_score: Numeric score 0-100 for ranking
        created_at: Opportunity detection timestamp
    """

    listing: CandidateListing
    game_valuations: list[GameValuation]
    lot_price: Decimal
    aggregate_confidence_score: float
    recommendation: Recommendation
    reason: LotReasonCode
    opportunity_score: float
    created_at: datetime
    economic_breakdown: EconomicBreakdown

    def __post_init__(self) -> None:
        require_decimal("lot_price", self.lot_price, non_negative=True)

    @property
    def reference_market_value(self) -> Decimal:
        return self.economic_breakdown.reference_market_value

    @property
    def expected_sale_revenue(self) -> Decimal:
        return self.economic_breakdown.expected_sale_revenue

    @property
    def net_expected_proceeds(self) -> Decimal:
        return self.economic_breakdown.net_expected_proceeds

    @property
    def net_profit(self) -> Decimal:
        return self.economic_breakdown.net_profit

    @property
    def net_profit_margin_percentage(self) -> Decimal:
        return self.economic_breakdown.net_profit_margin_percentage

    @property
    def net_roi_percentage(self) -> Decimal:
        return self.economic_breakdown.net_roi_percentage

    @property
    def acquisition_discount_to_reference_market_percentage(self) -> Decimal:
        return self.economic_breakdown.acquisition_discount_to_reference_market_percentage

    @property
    def break_even_sale_revenue(self) -> Decimal:
        return self.economic_breakdown.break_even_sale_revenue

    @classmethod
    def from_valuations(
        cls,
        listing: CandidateListing,
        game_valuations: list[GameValuation],
        recommendation: Recommendation,
        reason: LotReasonCode,
        opportunity_score: float,
        economic_breakdown: EconomicBreakdown,
    ) -> "LotOpportunity":
        """Create a LotOpportunity from individual game valuations.

        Uses the supplied economic breakdown as the sole source of financial
        values. The recommendation and opportunity_score are set by the caller.

        Calculations:
            lot_price = listing.price
            aggregate_confidence_score = mean of individual confidence scores

        Note: aggregate_confidence_score currently uses arithmetic mean.
        This may be replaced by a weighted mean in the future.

        Args:
            listing: The candidate lot listing
            game_valuations: Individual game valuations
            recommendation: BUY, MAYBE, or SKIP
            reason: Reason for the recommendation
            opportunity_score: Numeric score 0-100

        Returns:
            LotOpportunity with computed aggregate metrics
        """
        lot_price = listing.price

        # Aggregate confidence: arithmetic mean of individual scores
        # Future: may be replaced by a weighted mean based on sample size
        if game_valuations:
            aggregate_confidence_score = round(
                sum(v.confidence_score for v in game_valuations)
                / len(game_valuations),
                4,
            )
        else:
            aggregate_confidence_score = 0.0

        return cls(
            listing=listing,
            game_valuations=game_valuations,
            lot_price=lot_price,
            aggregate_confidence_score=aggregate_confidence_score,
            recommendation=recommendation,
            reason=reason,
            opportunity_score=opportunity_score,
            created_at=datetime.now(),
            economic_breakdown=economic_breakdown,
        )
