"""Default arbitrage opportunity detector implementation.

Detects profitable arbitrage opportunities by comparing listing prices
against estimated market prices using configurable business rules.
"""

from datetime import UTC, datetime

from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    IArbitrageOpportunityDetector,
    ReasonCode,
    Recommendation,
)
from domain.interfaces.market_price_estimator import MarketPriceEstimate


class DefaultArbitrageOpportunityDetector(IArbitrageOpportunityDetector):
    """Default implementation using configurable business rules.

    Uses profit thresholds and confidence requirements to determine
    whether a listing represents a good arbitrage opportunity.
    """

    # Business rule constants
    MIN_PROFIT_EUR = 10.0
    MIN_MARGIN_PERCENT = 25.0
    MIN_CONFIDENCE_SCORE = 0.50

    def __init__(
        self,
        min_profit_eur: float | None = None,
        min_margin_percent: float | None = None,
        min_confidence_score: float | None = None,
    ) -> None:
        """Initialize with optional custom thresholds.

        Args:
            min_profit_eur: Minimum profit in EUR (default: 10.0)
            min_margin_percent: Minimum profit margin % (default: 25.0)
            min_confidence_score: Minimum confidence score (default: 0.50)
        """
        self.min_profit_eur = min_profit_eur or self.MIN_PROFIT_EUR
        self.min_margin_percent = min_margin_percent or self.MIN_MARGIN_PERCENT
        self.min_confidence_score = min_confidence_score or self.MIN_CONFIDENCE_SCORE

    def detect(
        self,
        listing: CandidateListing,
        market_estimate: MarketPriceEstimate,
    ) -> ArbitrageOpportunity:
        """Detect if a listing is a profitable arbitrage opportunity.

        Args:
            listing: Original listing from marketplace
            market_estimate: Estimated market price for the game

        Returns:
            Arbitrage opportunity with recommendation and profitability metrics
        """
        # Extract prices
        listing_price = listing.price
        market_price = market_estimate.estimated_price

        # Calculate profitability metrics
        estimated_profit = market_price - listing_price

        profit_margin_percentage = (
            (estimated_profit / market_price * 100.0) if market_price > 0 else 0.0
        )

        roi_percentage = (
            (estimated_profit / listing_price * 100.0) if listing_price > 0 else 0.0
        )

        market_discount_percentage = (
            ((market_price - listing_price) / market_price * 100.0)
            if market_price > 0
            else 0.0
        )

        break_even_price = listing_price

        # Extract confidence
        confidence_score = market_estimate.confidence_score
        confidence_level = market_estimate.confidence_level

        # Determine recommendation and reason
        recommendation, reason = self._make_recommendation(
            listing_price=listing_price,
            estimated_profit=estimated_profit,
            profit_margin_percentage=profit_margin_percentage,
            confidence_score=confidence_score,
        )

        # Calculate opportunity score (0-100)
        opportunity_score = self._calculate_opportunity_score(
            profit_margin_percentage=profit_margin_percentage,
            estimated_profit=estimated_profit,
            confidence_score=confidence_score,
            roi_percentage=roi_percentage,
        )

        # Build result
        return ArbitrageOpportunity(
            listing=listing,
            game=market_estimate.game,
            market_price=market_price,
            listing_price=listing_price,
            estimated_profit=estimated_profit,
            profit_margin_percentage=profit_margin_percentage,
            roi_percentage=roi_percentage,
            market_discount_percentage=market_discount_percentage,
            break_even_price=break_even_price,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            opportunity_score=opportunity_score,
            recommendation=recommendation,
            reason=reason,
            created_at=datetime.now(UTC),
        )

    def _make_recommendation(
        self,
        listing_price: float,
        estimated_profit: float,
        profit_margin_percentage: float,
        confidence_score: float,
    ) -> tuple[Recommendation, ReasonCode]:
        """Determine recommendation and reason based on business rules.

        Args:
            listing_price: Price in the listing
            estimated_profit: Expected profit
            profit_margin_percentage: Profit margin %
            confidence_score: Confidence in market estimate

        Returns:
            Tuple of (recommendation, reason)
        """
        # Invalid listing price
        if listing_price <= 0:
            return Recommendation.SKIP, ReasonCode.INVALID_LISTING_PRICE

        # Low confidence in market estimate
        if confidence_score < self.min_confidence_score:
            return Recommendation.SKIP, ReasonCode.LOW_CONFIDENCE

        # Overpriced (negative or zero profit)
        if estimated_profit <= 0:
            return Recommendation.SKIP, ReasonCode.OVERPRICED

        # Check if meets all BUY criteria
        meets_profit_threshold = estimated_profit >= self.min_profit_eur
        meets_margin_threshold = profit_margin_percentage >= self.min_margin_percent
        meets_confidence_threshold = confidence_score >= self.min_confidence_score

        if meets_profit_threshold and meets_margin_threshold and meets_confidence_threshold:
            return Recommendation.BUY, ReasonCode.UNDERVALUED

        # Positive profit but doesn't meet all thresholds
        if estimated_profit > 0 and estimated_profit < self.min_profit_eur:
            return Recommendation.MAYBE, ReasonCode.LOW_EXPECTED_PROFIT

        # Fair price (small profit margin)
        if estimated_profit > 0 and profit_margin_percentage < self.min_margin_percent:
            return Recommendation.MAYBE, ReasonCode.FAIR_PRICE

        # Default: something profitable but uncertain
        return Recommendation.MAYBE, ReasonCode.FAIR_PRICE

    def _calculate_opportunity_score(
        self,
        profit_margin_percentage: float,
        estimated_profit: float,
        confidence_score: float,
        roi_percentage: float,
    ) -> float:
        """Calculate opportunity score (0-100) for ranking.

        Combines multiple factors:
        - Profit margin (40% weight): Higher margin = better deal
        - Absolute profit (30% weight): Higher profit = more worthwhile
        - Confidence (20% weight): Higher confidence = safer bet
        - ROI (10% weight): Higher ROI = better return

        Args:
            profit_margin_percentage: Profit margin %
            estimated_profit: Expected profit in EUR
            confidence_score: Confidence in market estimate (0-1)
            roi_percentage: Return on investment %

        Returns:
            Score from 0 to 100
        """
        # Normalize profit margin: 0% = 0, 50%+ = 100
        margin_score = min(profit_margin_percentage / 50.0 * 100.0, 100.0)

        # Normalize absolute profit: 0€ = 0, 20€+ = 100
        profit_score = min(estimated_profit / 20.0 * 100.0, 100.0)

        # Normalize confidence: 0.0 = 0, 1.0 = 100
        confidence_score_normalized = confidence_score * 100.0

        # Normalize ROI: 0% = 0, 100%+ = 100
        roi_score = min(roi_percentage / 100.0 * 100.0, 100.0)

        # Weighted combination
        opportunity_score = (
            margin_score * 0.40
            + profit_score * 0.30
            + confidence_score_normalized * 0.20
            + roi_score * 0.10
        )

        # Clamp to [0, 100]
        return max(0.0, min(100.0, opportunity_score))
