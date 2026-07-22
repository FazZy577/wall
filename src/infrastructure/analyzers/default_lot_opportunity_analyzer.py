"""Default lot opportunity analyzer implementation.

Analyzes candidate lots by computing aggregate metrics, determining
BUY/MAYBE/SKIP recommendations, and calculating opportunity scores.

Contains business rules for lot decisions — but NO market data access.
"""

import logging

from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity, LotReasonCode
from domain.interfaces.arbitrage_opportunity_detector import Recommendation
from domain.interfaces.lot_opportunity_analyzer import ILotOpportunityAnalyzer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision thresholds (private constants)
# ---------------------------------------------------------------------------

_MIN_LOT_PROFIT_EUR = 10.0
_MIN_LOT_MARGIN_PERCENTAGE = 25.0
_MIN_AGGREGATE_CONFIDENCE = 0.50

# ---------------------------------------------------------------------------
# Opportunity score weights
# ---------------------------------------------------------------------------

_WEIGHT_MARGIN = 0.35
_WEIGHT_PROFIT = 0.30
_WEIGHT_CONFIDENCE = 0.20
_WEIGHT_COMPLETION = 0.15


class DefaultLotOpportunityAnalyzer(ILotOpportunityAnalyzer):
    """Default implementation that analyzes lot opportunities.

    Computes aggregate metrics, determines BUY/MAYBE/SKIP using
    explicit decision rules, and calculates opportunity scores.

    The analyzer contains NO knowledge of:
    - Wallapop or any marketplace
    - Price collection or comparable listings
    - Statistical calculations
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        listing: CandidateListing,
        game_valuations: list[GameValuation],
        total_detected_games: int,
    ) -> LotOpportunity:
        """Analyze a candidate listing with its game valuations.

        Args:
            listing: The candidate listing (lot) being evaluated
            game_valuations: Successfully obtained game valuations
            total_detected_games: Total games detected in the listing

        Returns:
            LotOpportunity with recommendation, reason, and score
        """
        # Compute aggregate metrics
        total_market_value = sum(
            v.estimated_market_value for v in game_valuations
        )
        lot_price = listing.price
        estimated_profit = total_market_value - lot_price

        profit_margin = self._compute_margin(total_market_value, estimated_profit)
        aggregate_confidence = self._compute_aggregate_confidence(game_valuations)

        # Determine recommendation and reason
        valued_count = len(game_valuations)
        recommendation, reason = self._determine_recommendation_and_reason(
            listing=listing,
            total_detected_games=total_detected_games,
            valued_count=valued_count,
            estimated_profit=estimated_profit,
            profit_margin=profit_margin,
            aggregate_confidence=aggregate_confidence,
        )

        # Calculate opportunity score
        opportunity_score = self._calculate_opportunity_score(
            profit_margin=profit_margin,
            estimated_profit=estimated_profit,
            aggregate_confidence=aggregate_confidence,
            total_detected_games=total_detected_games,
            valued_count=valued_count,
        )

        return LotOpportunity.from_valuations(
            listing=listing,
            game_valuations=game_valuations,
            recommendation=recommendation,
            reason=reason,
            opportunity_score=opportunity_score,
        )

    # ------------------------------------------------------------------
    # Metric computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_margin(total_market_value: float, estimated_profit: float) -> float:
        """Compute profit margin percentage."""
        if total_market_value > 0:
            return round(estimated_profit / total_market_value * 100, 1)
        return 0.0

    @staticmethod
    def _compute_roi(lot_price: float, estimated_profit: float) -> float:
        """Compute ROI percentage."""
        if lot_price > 0:
            return round(estimated_profit / lot_price * 100, 1)
        return 0.0

    @staticmethod
    def _compute_aggregate_confidence(
        game_valuations: list[GameValuation],
    ) -> float:
        """Compute arithmetic mean of individual confidence scores."""
        if not game_valuations:
            return 0.0
        return round(
            sum(v.confidence_score for v in game_valuations)
            / len(game_valuations),
            4,
        )

    # ------------------------------------------------------------------
    # Decision rules
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_recommendation_and_reason(
        listing: CandidateListing,
        total_detected_games: int,
        valued_count: int,
        estimated_profit: float,
        profit_margin: float,
        aggregate_confidence: float,
    ) -> tuple[Recommendation, LotReasonCode]:
        """Determine BUY/MAYBE/SKIP using explicit priority rules.

        Rules are evaluated in priority order. The first matching
        rule determines the outcome.
        """
        is_complete = total_detected_games > 0 and valued_count == total_detected_games

        # Rule 1: No games detected
        if total_detected_games == 0:
            return Recommendation.SKIP, LotReasonCode.NO_GAMES_DETECTED

        # Rule 2: Invalid lot price
        if listing.price <= 0:
            return Recommendation.SKIP, LotReasonCode.INVALID_LOT_PRICE

        # Rule 3: No games could be valued
        if valued_count == 0:
            return Recommendation.SKIP, LotReasonCode.INCOMPLETE_VALUATION

        # Rule 4: Incomplete valuation
        if not is_complete:
            if estimated_profit > 0:
                return Recommendation.MAYBE, LotReasonCode.INCOMPLETE_VALUATION
            return Recommendation.SKIP, LotReasonCode.INCOMPLETE_VALUATION

        # Rule 5: Low aggregate confidence
        if aggregate_confidence < _MIN_AGGREGATE_CONFIDENCE:
            return Recommendation.SKIP, LotReasonCode.LOW_AGGREGATE_CONFIDENCE

        # Rule 6: Overpriced lot
        if estimated_profit < 0:
            return Recommendation.SKIP, LotReasonCode.OVERPRICED_LOT

        # Rule 7: Fair value (exactly at market price)
        if estimated_profit == 0:
            return Recommendation.SKIP, LotReasonCode.FAIR_VALUE_LOT

        # Rule 8: Clear BUY opportunity
        if (
            estimated_profit >= _MIN_LOT_PROFIT_EUR
            and profit_margin >= _MIN_LOT_MARGIN_PERCENTAGE
            and aggregate_confidence >= _MIN_AGGREGATE_CONFIDENCE
        ):
            return Recommendation.BUY, LotReasonCode.UNDERVALUED_LOT

        # Rule 9: Positive profit but below thresholds
        return Recommendation.MAYBE, LotReasonCode.FAIR_VALUE_LOT

    # ------------------------------------------------------------------
    # Opportunity score
    # ------------------------------------------------------------------

    def _calculate_opportunity_score(
        self,
        profit_margin: float,
        estimated_profit: float,
        aggregate_confidence: float,
        total_detected_games: int,
        valued_count: int,
    ) -> float:
        """Calculate opportunity score (0-100) using weighted components.

        The score is informative — it does NOT override safety rules.
        An incomplete or low-confidence lot may have a high score but
        will never receive a BUY recommendation.
        """
        completion_ratio = (
            valued_count / total_detected_games if total_detected_games > 0 else 0.0
        )

        margin_component = self._normalize_margin(profit_margin)
        profit_component = self._normalize_profit(estimated_profit)
        confidence_component = self._normalize_confidence(aggregate_confidence)
        completion_component = self._normalize_completion(completion_ratio)

        score = (
            margin_component * _WEIGHT_MARGIN
            + profit_component * _WEIGHT_PROFIT
            + confidence_component * _WEIGHT_CONFIDENCE
            + completion_component * _WEIGHT_COMPLETION
        )

        return round(max(0.0, min(100.0, score)), 1)

    @staticmethod
    def _normalize_margin(profit_margin: float) -> float:
        """Normalize profit margin: 0%→0, 50%+→100."""
        return max(0.0, min(100.0, profit_margin / 50.0 * 100.0))

    @staticmethod
    def _normalize_profit(estimated_profit: float) -> float:
        """Normalize absolute profit: 0€→0, 50€+→100."""
        return max(0.0, min(100.0, estimated_profit / 50.0 * 100.0))

    @staticmethod
    def _normalize_confidence(aggregate_confidence: float) -> float:
        """Normalize confidence: 0.0→0, 1.0→100."""
        return max(0.0, min(100.0, aggregate_confidence * 100.0))

    @staticmethod
    def _normalize_completion(completion_ratio: float) -> float:
        """Normalize completion: 0.0→0, 1.0→100."""
        return max(0.0, min(100.0, completion_ratio * 100.0))
