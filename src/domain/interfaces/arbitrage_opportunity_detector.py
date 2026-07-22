"""Arbitrage opportunity detector interface (port).

Defines the contract for detecting profitable arbitrage opportunities.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame
from domain.entities.resale_economics import EconomicBreakdown
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    MarketPriceEstimate,
)


class Recommendation(StrEnum):
    """Recommendation for whether to pursue this opportunity."""

    BUY = "buy"
    MAYBE = "maybe"
    SKIP = "skip"


class ReasonCode(StrEnum):
    """Reason code explaining the recommendation."""

    UNDERVALUED = "undervalued"
    FAIR_PRICE = "fair_price"
    OVERPRICED = "overpriced"
    LOW_CONFIDENCE = "low_confidence"
    INSUFFICIENT_DATA = "insufficient_data"
    LOW_EXPECTED_PROFIT = "low_expected_profit"
    INVALID_LISTING_PRICE = "invalid_listing_price"


@dataclass
class ArbitrageOpportunity:
    """Result of arbitrage opportunity detection.

    Attributes:
        listing: Original listing from marketplace
        game: Detected game in this listing
        market_price: Estimated market price
        listing_price: Price in the listing
        economic_breakdown: Single source of financial values and metrics
        confidence_score: Confidence in market price estimate
        confidence_level: Human-readable confidence level
        opportunity_score: Numeric score 0-100 for ranking opportunities
        recommendation: BUY, MAYBE, or SKIP
        reason: Why this recommendation was made
        created_at: Detection timestamp
    """

    listing: CandidateListing
    game: DetectedGame
    market_price: float
    listing_price: float
    confidence_score: float
    confidence_level: ConfidenceLevel
    opportunity_score: float
    recommendation: Recommendation
    reason: ReasonCode
    created_at: datetime
    economic_breakdown: EconomicBreakdown

    @property
    def reference_market_value(self) -> float:
        return self.economic_breakdown.reference_market_value

    @property
    def expected_sale_revenue(self) -> float:
        return self.economic_breakdown.expected_sale_revenue

    @property
    def net_expected_proceeds(self) -> float:
        return self.economic_breakdown.net_expected_proceeds

    @property
    def net_profit(self) -> float:
        return self.economic_breakdown.net_profit

    @property
    def net_profit_margin_percentage(self) -> float:
        return self.economic_breakdown.net_profit_margin_percentage

    @property
    def net_roi_percentage(self) -> float:
        return self.economic_breakdown.net_roi_percentage

    @property
    def acquisition_discount_to_reference_market_percentage(self) -> float:
        return self.economic_breakdown.acquisition_discount_to_reference_market_percentage

    @property
    def break_even_sale_revenue(self) -> float:
        return self.economic_breakdown.break_even_sale_revenue

    def explain(self) -> str:
        """Generate human-readable explanation of the opportunity.

        Returns:
            Multi-line string explaining the arbitrage decision
        """
        lines = []
        lines.append("=" * 60)
        lines.append("ARBITRAGE OPPORTUNITY ANALYSIS")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Game: {self.game.canonical_name} ({self.game.platform})")
        lines.append(f"Listing ID: {self.listing.listing_id}")
        lines.append("")
        lines.append("PRICING")
        lines.append("-" * 60)
        lines.append(f"Listing Price: EUR {self.listing_price:.2f}")
        lines.append(f"Estimated Market Price: EUR {self.market_price:.2f}")
        lines.append(
            f"Expected Sale Revenue: EUR {self.economic_breakdown.expected_sale_revenue:.2f}"
        )
        lines.append(
            f"Selling Costs and Buffer: EUR "
            f"{self.economic_breakdown.selling_fees + self.economic_breakdown.fixed_selling_costs + self.economic_breakdown.safety_buffer:.2f}"
        )
        lines.append(f"Net Profit: EUR {self.net_profit:.2f}")
        lines.append("")
        lines.append("PROFITABILITY METRICS")
        lines.append("-" * 60)
        lines.append(f"Net Profit Margin: {self.net_profit_margin_percentage:.1f}%")
        lines.append(f"Net ROI: {self.net_roi_percentage:.1f}%")
        lines.append(
            "Acquisition Discount to Reference Market: "
            f"{self.acquisition_discount_to_reference_market_percentage:.1f}%"
        )
        lines.append(f"Break-even Sale Revenue: EUR {self.break_even_sale_revenue:.2f}")
        lines.append("")
        lines.append("CONFIDENCE")
        lines.append("-" * 60)
        lines.append(f"Confidence Score: {self.confidence_score:.2f}")
        lines.append(f"Confidence Level: {self.confidence_level.upper()}")
        lines.append("")
        lines.append("DECISION")
        lines.append("-" * 60)
        lines.append(f"Recommendation: {self.recommendation.upper()}")
        lines.append(f"Opportunity Score: {self.opportunity_score:.1f}/100")
        lines.append(f"Reason: {self.reason}")
        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


class IArbitrageOpportunityDetector(ABC):
    """Interface for arbitrage opportunity detection implementations.

    Evaluates whether a listing represents a profitable arbitrage opportunity
    by comparing listing price against estimated market price.
    """

    @abstractmethod
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
        pass
