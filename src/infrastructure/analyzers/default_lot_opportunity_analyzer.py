"""Default lot opportunity analyzer implementation.

Analyzes candidate lots by computing aggregate metrics, determining
BUY/MAYBE/SKIP recommendations, and calculating opportunity scores.

Contains business rules for lot decisions — but NO market data access.
"""

import logging
from decimal import Decimal

from domain.currency import CurrencyMismatchError
from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity, LotReasonCode
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.arbitrage_opportunity_detector import Recommendation
from domain.interfaces.lot_opportunity_analyzer import ILotOpportunityAnalyzer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decision thresholds (private constants)
# ---------------------------------------------------------------------------

_MIN_LOT_PROFIT_EUR = Decimal("10.0")
_MIN_LOT_MARGIN_PERCENTAGE = Decimal("25.0")
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

    def __init__(self, economic_policy: ResaleEconomicPolicy) -> None:
        self.economic_policy = economic_policy

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

        for valuation in game_valuations:
            if valuation.currency != listing.currency:
                raise CurrencyMismatchError(
                    listing.currency,
                    valuation.currency,
                    "LotOpportunityAnalyzer",
                )

        # Compute aggregate metrics
        economic_breakdown = self.economic_policy.calculate(
            reference_item_prices=[
                valuation.estimated_market_value for valuation in game_valuations
            ],
            acquisition_price=listing.price,
            currency=listing.currency,
        )
        net_profit = economic_breakdown.net_profit
        net_profit_margin = economic_breakdown.net_profit_margin_percentage
        aggregate_confidence = self._compute_aggregate_confidence(game_valuations)

        # Determine recommendation and reason
        valued_count = len(game_valuations)
        recommendation, reason = self._determine_recommendation_and_reason(
            listing=listing,
            total_detected_games=total_detected_games,
            valued_count=valued_count,
            net_profit=net_profit,
            net_profit_margin=net_profit_margin,
            aggregate_confidence=aggregate_confidence,
        )

        # Calculate opportunity score
        opportunity_score = self._calculate_opportunity_score(
            net_profit_margin=net_profit_margin,
            net_profit=net_profit,
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
            economic_breakdown=economic_breakdown,
        )

    # ------------------------------------------------------------------
    # Metric computation
    # ------------------------------------------------------------------

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
        net_profit: Decimal,
        net_profit_margin: Decimal,
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
            if net_profit > 0:
                return Recommendation.MAYBE, LotReasonCode.INCOMPLETE_VALUATION
            return Recommendation.SKIP, LotReasonCode.INCOMPLETE_VALUATION

        # Rule 5: Low aggregate confidence
        if aggregate_confidence < _MIN_AGGREGATE_CONFIDENCE:
            return Recommendation.SKIP, LotReasonCode.LOW_AGGREGATE_CONFIDENCE

        # Rule 6: Overpriced lot
        if net_profit < 0:
            return Recommendation.SKIP, LotReasonCode.OVERPRICED_LOT

        # Rule 7: Fair value (exactly at market price)
        if net_profit == 0:
            return Recommendation.SKIP, LotReasonCode.FAIR_VALUE_LOT

        # Rule 8: Clear BUY opportunity
        if (
            net_profit >= _MIN_LOT_PROFIT_EUR
            and net_profit_margin >= _MIN_LOT_MARGIN_PERCENTAGE
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
        net_profit_margin: Decimal,
        net_profit: Decimal,
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

        margin_component = self._normalize_margin(net_profit_margin)
        profit_component = self._normalize_profit(net_profit)
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
    def _normalize_margin(net_profit_margin: Decimal) -> float:
        """Normalize profit margin: 0%→0, 50%+→100."""
        return max(
            0.0,
            min(100.0, float(net_profit_margin / Decimal("50") * Decimal("100"))),
        )

    @staticmethod
    def _normalize_profit(net_profit: Decimal) -> float:
        """Normalize absolute profit: 0€→0, 50€+→100."""
        return max(
            0.0,
            min(100.0, float(net_profit / Decimal("50") * Decimal("100"))),
        )

    @staticmethod
    def _normalize_confidence(aggregate_confidence: float) -> float:
        """Normalize confidence: 0.0→0, 1.0→100."""
        return max(0.0, min(100.0, aggregate_confidence * 100.0))

    @staticmethod
    def _normalize_completion(completion_ratio: float) -> float:
        """Normalize completion: 0.0→0, 1.0→100."""
        return max(0.0, min(100.0, completion_ratio * 100.0))
