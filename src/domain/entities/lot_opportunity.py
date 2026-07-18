"""Lot opportunity entity.

Represents the economic opportunity of buying a lot (bundle) of games.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
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
        total_market_value: Sum of all game estimated market values
        lot_price: Total price of the lot (= listing.price)
        estimated_profit: total_market_value - lot_price
        profit_margin_percentage: Profit as percentage of market value
        roi_percentage: Return on investment (profit / lot_price * 100)
        aggregate_confidence_score: Mean of individual confidence scores
        recommendation: BUY, MAYBE, or SKIP
        reason: Why this recommendation was made
        opportunity_score: Numeric score 0-100 for ranking
        created_at: Opportunity detection timestamp
    """

    listing: CandidateListing
    game_valuations: list[GameValuation]
    total_market_value: float
    lot_price: float
    estimated_profit: float
    profit_margin_percentage: float
    roi_percentage: float
    aggregate_confidence_score: float
    recommendation: Recommendation
    reason: LotReasonCode
    opportunity_score: float
    created_at: datetime

    @classmethod
    def from_valuations(
        cls,
        listing: CandidateListing,
        game_valuations: list[GameValuation],
        recommendation: Recommendation,
        reason: LotReasonCode,
        opportunity_score: float,
    ) -> "LotOpportunity":
        """Create a LotOpportunity from individual game valuations.

        Computes all aggregate metrics explicitly. The recommendation
        and opportunity_score are set by the caller (future detector).

        Calculations:
            total_market_value = sum of each valuation's estimated_market_value
            lot_price = listing.price
            estimated_profit = total_market_value - lot_price
            profit_margin_percentage = estimated_profit / total_market_value * 100
            roi_percentage = estimated_profit / lot_price * 100
            aggregate_confidence_score = mean of individual confidence scores

        Edge cases:
            - If total_market_value <= 0: profit_margin_percentage = 0.0
            - If lot_price <= 0: roi_percentage = 0.0

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
        total_market_value = sum(
            v.estimated_market_value for v in game_valuations
        )
        lot_price = listing.price
        estimated_profit = total_market_value - lot_price

        # Profit margin: profit relative to market value
        if total_market_value > 0:
            profit_margin_percentage = round(
                estimated_profit / total_market_value * 100, 1
            )
        else:
            profit_margin_percentage = 0.0

        # ROI: profit relative to investment (lot price)
        roi_percentage = (
            round(estimated_profit / lot_price * 100, 1) if lot_price > 0 else 0.0
        )

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
            total_market_value=total_market_value,
            lot_price=lot_price,
            estimated_profit=estimated_profit,
            profit_margin_percentage=profit_margin_percentage,
            roi_percentage=roi_percentage,
            aggregate_confidence_score=aggregate_confidence_score,
            recommendation=recommendation,
            reason=reason,
            opportunity_score=opportunity_score,
            created_at=datetime.now(),
        )
