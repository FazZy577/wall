"""Default arbitrage opportunity detector implementation.

Detects profitable arbitrage opportunities by comparing listing prices
against estimated market prices using configurable business rules.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from domain._decimal import require_decimal
from domain.currency import CurrencyMismatchError, validate_currency_code
from domain.entities.candidate_listing import CandidateListing
from domain.entities.resale_economics import ResaleEconomicPolicy
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
    DEFAULT_MIN_NET_PROFIT_BY_CURRENCY: Mapping[str, Decimal] = MappingProxyType(
        {"EUR": Decimal("10.0")}
    )
    MIN_NET_PROFIT_MARGIN_PERCENT = Decimal("25.0")
    MIN_CONFIDENCE_SCORE = 0.50

    def __init__(
        self,
        economic_policy: ResaleEconomicPolicy,
        min_net_profit_by_currency: Mapping[str, Decimal] | None = None,
        min_net_profit_margin_percent: Decimal | None = None,
        min_confidence_score: float | None = None,
    ) -> None:
        """Initialize with optional custom thresholds.

        Args:
            min_net_profit_by_currency: Minimum profit by currency. Defaults to
                EUR 10.0 only when omitted or None.
            min_net_profit_margin_percent: Minimum profit margin % (default: 25.0)
            min_confidence_score: Minimum confidence score (default: 0.50)
        """
        configured_profit_thresholds = (
            self.DEFAULT_MIN_NET_PROFIT_BY_CURRENCY
            if min_net_profit_by_currency is None
            else min_net_profit_by_currency
        )
        validated_profit_thresholds: dict[str, Decimal] = {}
        for currency, threshold in configured_profit_thresholds.items():
            validate_currency_code(currency, "min_net_profit_by_currency key")
            require_decimal(
                f"min_net_profit_by_currency[{currency!r}]", threshold
            )
            validated_profit_thresholds[currency] = threshold
        if min_net_profit_margin_percent is not None:
            require_decimal(
                "min_net_profit_margin_percent", min_net_profit_margin_percent
            )
        self.economic_policy = economic_policy
        self.min_net_profit_by_currency: Mapping[str, Decimal] = MappingProxyType(
            validated_profit_thresholds
        )
        self.min_net_profit_margin_percent = (
            self.MIN_NET_PROFIT_MARGIN_PERCENT
            if min_net_profit_margin_percent is None
            else min_net_profit_margin_percent
        )
        self.min_confidence_score = (
            self.MIN_CONFIDENCE_SCORE
            if min_confidence_score is None
            else min_confidence_score
        )

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
        if listing.currency != market_estimate.currency:
            raise CurrencyMismatchError(
                listing.currency,
                market_estimate.currency,
                "ArbitrageOpportunityDetector",
            )

        # Extract prices
        listing_price = listing.price
        market_price = market_estimate.estimated_price

        economic_breakdown = self.economic_policy.calculate(
            reference_item_prices=[market_price],
            acquisition_price=listing_price,
            currency=listing.currency,
        )
        min_net_profit = self._min_net_profit_for_currency(
            economic_breakdown.currency
        )
        # Extract confidence
        confidence_score = market_estimate.confidence_score
        confidence_level = market_estimate.confidence_level

        # Determine recommendation and reason
        recommendation, reason = self._make_recommendation(
            listing_price=listing_price,
            net_profit=economic_breakdown.net_profit,
            net_profit_margin_percentage=economic_breakdown.net_profit_margin_percentage,
            confidence_score=confidence_score,
            min_net_profit=min_net_profit,
        )

        # Calculate opportunity score (0-100)
        opportunity_score = self._calculate_opportunity_score(
            net_profit_margin_percentage=economic_breakdown.net_profit_margin_percentage,
            net_profit=economic_breakdown.net_profit,
            confidence_score=confidence_score,
            net_roi_percentage=economic_breakdown.net_roi_percentage,
        )

        # Build result
        return ArbitrageOpportunity(
            listing=listing,
            game=market_estimate.game,
            market_price=market_price,
            listing_price=listing_price,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            opportunity_score=opportunity_score,
            recommendation=recommendation,
            reason=reason,
            created_at=datetime.now(UTC),
            economic_breakdown=economic_breakdown,
        )

    def _make_recommendation(
        self,
        listing_price: Decimal,
        net_profit: Decimal,
        net_profit_margin_percentage: Decimal,
        confidence_score: float,
        min_net_profit: Decimal,
    ) -> tuple[Recommendation, ReasonCode]:
        """Determine recommendation and reason based on business rules.

        Args:
            listing_price: Price in the listing
            net_profit: Expected profit
            net_profit_margin_percentage: Profit margin %
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
        if net_profit <= 0:
            return Recommendation.SKIP, ReasonCode.OVERPRICED

        # Check if meets all BUY criteria
        meets_profit_threshold = net_profit >= min_net_profit
        meets_margin_threshold = net_profit_margin_percentage >= self.min_net_profit_margin_percent
        meets_confidence_threshold = confidence_score >= self.min_confidence_score

        if meets_profit_threshold and meets_margin_threshold and meets_confidence_threshold:
            return Recommendation.BUY, ReasonCode.UNDERVALUED

        # Positive profit but doesn't meet all thresholds
        if net_profit > 0 and net_profit < min_net_profit:
            return Recommendation.MAYBE, ReasonCode.LOW_EXPECTED_PROFIT

        # Fair price (small profit margin)
        if net_profit > 0 and net_profit_margin_percentage < self.min_net_profit_margin_percent:
            return Recommendation.MAYBE, ReasonCode.FAIR_PRICE

        # Default: something profitable but uncertain
        return Recommendation.MAYBE, ReasonCode.FAIR_PRICE

    def _min_net_profit_for_currency(self, currency: str) -> Decimal:
        """Return the configured absolute threshold for ``currency``."""
        try:
            return self.min_net_profit_by_currency[currency]
        except KeyError:
            raise ValueError(
                "No minimum net profit threshold configured for currency "
                f"{currency}"
            ) from None

    def _calculate_opportunity_score(
        self,
        net_profit_margin_percentage: Decimal,
        net_profit: Decimal,
        confidence_score: float,
        net_roi_percentage: Decimal,
    ) -> float:
        """Calculate opportunity score (0-100) for ranking.

        Combines multiple factors:
        - Profit margin (40% weight): Higher margin = better deal
        - Absolute profit (30% weight): Higher profit = more worthwhile
        - Confidence (20% weight): Higher confidence = safer bet
        - ROI (10% weight): Higher ROI = better return

        Args:
            net_profit_margin_percentage: Profit margin %
            net_profit: Expected profit in EUR
            confidence_score: Confidence in market estimate (0-1)
            net_roi_percentage: Return on investment %

        Returns:
            Score from 0 to 100
        """
        # Normalize profit margin: 0% = 0, 50%+ = 100
        margin_score = min(
            float(net_profit_margin_percentage / Decimal("50") * Decimal("100")),
            100.0,
        )

        # Normalize absolute profit: 0€ = 0, 20€+ = 100
        profit_score = min(
            float(net_profit / Decimal("20") * Decimal("100")), 100.0
        )

        # Normalize confidence: 0.0 = 0, 1.0 = 100
        confidence_score_normalized = confidence_score * 100.0

        # Normalize ROI: 0% = 0, 100%+ = 100
        roi_score = min(
            float(net_roi_percentage / Decimal("100") * Decimal("100")), 100.0
        )

        # Weighted combination
        opportunity_score = (
            margin_score * 0.40
            + profit_score * 0.30
            + confidence_score_normalized * 0.20
            + roi_score * 0.10
        )

        # Clamp to [0, 100]
        return max(0.0, min(100.0, opportunity_score))
