"""Arbitrage opportunity detector example.

Demonstrates how to use the arbitrage opportunity detector to evaluate
whether listings represent profitable resale opportunities.

Shows various scenarios:
- Clear BUY opportunities (high profit, good margin, high confidence)
- MAYBE cases (borderline profit or margin)
- SKIP cases (overpriced, low confidence, invalid data)
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.entities.candidate_listing import CandidateListing
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    Recommendation,
)
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    MarketPriceEstimate,
)
from domain.interfaces.market_price_estimator import (
    ReasonCode as EstimateReasonCode,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)


def create_listing(
    listing_id: str,
    title: str,
    price: float,
    _game: DetectedGame,
) -> CandidateListing:
    """Helper to create a listing."""
    return CandidateListing(
        listing_id=listing_id,
        title=title,
        description="",
        price=price,
        currency="EUR",
        url=f"https://wallapop.com/item/{listing_id}",
    )


def create_market_estimate(
    game: DetectedGame,
    estimated_price: float,
    confidence_score: float,
    confidence_level: ConfidenceLevel,
) -> MarketPriceEstimate:
    """Helper to create market estimate."""
    return MarketPriceEstimate(
        estimated_price=estimated_price,
        currency="EUR",
        confidence_score=confidence_score,
        confidence_level=confidence_level,
        strategy=EstimationStrategy.MEDIAN,
        reason_code=EstimateReasonCode.NORMAL,
        sample_size=20,
        observations_removed=2,
        outlier_percentage=10.0,
        minimum_price=estimated_price - 10.0,
        maximum_price=estimated_price + 10.0,
        standard_deviation=3.5,
        iqr=5.0,
        coefficient_of_variation=0.15,
        game=game,
        created_at=datetime.now(UTC),
    )


def print_opportunity_summary(opportunity: ArbitrageOpportunity) -> None:
    """Print a brief summary of the opportunity."""
    print(f"Listing: {opportunity.listing.title}")
    print(f"  Listing Price: EUR {opportunity.listing_price:.2f}")
    print(f"  Market Price: EUR {opportunity.market_price:.2f}")
    print(f"  Expected Profit: EUR {opportunity.estimated_profit:.2f}")
    print(f"  Profit Margin: {opportunity.profit_margin_percentage:.1f}%")
    print(f"  ROI: {opportunity.roi_percentage:.1f}%")
    print(
        f"  Confidence: {opportunity.confidence_score:.2f} ({opportunity.confidence_level.upper()})"
    )
    print(f"  Opportunity Score: {opportunity.opportunity_score:.1f}/100")
    print(f"  DECISION: {opportunity.recommendation.upper()} ({opportunity.reason})")
    print()


def main() -> None:
    """Run arbitrage detection examples."""

    print("=" * 80)
    print("ARBITRAGE OPPORTUNITY DETECTOR EXAMPLES")
    print("=" * 80)
    print()

    # Create detector
    # Example strategy: sell 3 EUR below market. Configure real channel costs.
    policy = ResaleEconomicPolicy(3.0, 0.0, 0.0, 0.0, 0.0)
    detector = DefaultArbitrageOpportunityDetector(policy)

    # Create game
    game = DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )

    print("SCENARIO 1: Excellent Deal (Clear BUY)")
    print("-" * 80)
    print()

    listing1 = create_listing("listing001", "GTA V PS4 - Great Condition", 8.0, game)
    estimate1 = create_market_estimate(game, 20.0, 0.90, ConfidenceLevel.VERY_HIGH)

    opp1 = detector.detect(listing1, estimate1)
    print_opportunity_summary(opp1)

    print("=" * 80)
    print()

    print("SCENARIO 2: Good Deal (BUY)")
    print("-" * 80)
    print()

    listing2 = create_listing("listing002", "GTA V PS4 - Used", 12.0, game)
    estimate2 = create_market_estimate(game, 22.0, 0.80, ConfidenceLevel.HIGH)

    opp2 = detector.detect(listing2, estimate2)
    print_opportunity_summary(opp2)

    print("=" * 80)
    print()

    print("SCENARIO 3: Borderline Profit (MAYBE)")
    print("-" * 80)
    print()

    listing3 = create_listing("listing003", "GTA V PS4 - Acceptable Condition", 12.0, game)
    estimate3 = create_market_estimate(game, 18.0, 0.80, ConfidenceLevel.HIGH)

    opp3 = detector.detect(listing3, estimate3)
    print_opportunity_summary(opp3)

    print("=" * 80)
    print()

    print("SCENARIO 4: Low Margin (MAYBE)")
    print("-" * 80)
    print()

    listing4 = create_listing("listing004", "GTA V PS4 - Like New", 18.0, game)
    estimate4 = create_market_estimate(game, 20.0, 0.80, ConfidenceLevel.HIGH)

    opp4 = detector.detect(listing4, estimate4)
    print_opportunity_summary(opp4)

    print("=" * 80)
    print()

    print("SCENARIO 5: Low Confidence (SKIP)")
    print("-" * 80)
    print()

    listing5 = create_listing("listing005", "GTA V PS4 - Good Deal", 10.0, game)
    estimate5 = create_market_estimate(game, 25.0, 0.40, ConfidenceLevel.LOW)

    opp5 = detector.detect(listing5, estimate5)
    print_opportunity_summary(opp5)

    print("=" * 80)
    print()

    print("SCENARIO 6: Overpriced (SKIP)")
    print("-" * 80)
    print()

    listing6 = create_listing("listing006", "GTA V PS4 - Collector's Edition", 25.0, game)
    estimate6 = create_market_estimate(game, 20.0, 0.80, ConfidenceLevel.HIGH)

    opp6 = detector.detect(listing6, estimate6)
    print_opportunity_summary(opp6)

    print("=" * 80)
    print()

    print("SCENARIO 7: Invalid Price (SKIP)")
    print("-" * 80)
    print()

    listing7 = create_listing("listing007", "GTA V PS4 - Free", 0.0, game)
    estimate7 = create_market_estimate(game, 20.0, 0.80, ConfidenceLevel.HIGH)

    opp7 = detector.detect(listing7, estimate7)
    print_opportunity_summary(opp7)

    print("=" * 80)
    print()

    # Show detailed explanation for one opportunity
    print("DETAILED EXPLANATION (Scenario 2)")
    print("-" * 80)
    print()
    print(opp2.explain())
    print()

    print("=" * 80)
    print()

    # Summary table
    print("SUMMARY TABLE")
    print("-" * 80)
    print()

    opportunities = [opp1, opp2, opp3, opp4, opp5, opp6, opp7]

    print(f"| Scenario | Listing | Market | Profit | Margin | Score | Decision |")
    print(f"|----------|---------|--------|--------|--------|-------|----------|")

    for i, opp in enumerate(opportunities, 1):
        rec_symbol = {
            Recommendation.BUY: "[BUY]",
            Recommendation.MAYBE: "[MAYBE]",
            Recommendation.SKIP: "[SKIP]",
        }[opp.recommendation]

        print(
            f"| {i:8} | EUR {opp.listing_price:4.2f} | EUR {opp.market_price:4.2f} | "
            f"EUR {opp.estimated_profit:4.2f} | {opp.profit_margin_percentage:5.1f}% | "
            f"{opp.opportunity_score:5.1f} | {rec_symbol:8} |"
        )

    print()
    print("=" * 80)
    print()

    # Business rules reminder
    print("BUSINESS RULES")
    print("-" * 80)
    print()
    print("For a BUY recommendation, ALL of the following must be true:")
    print(f"  - Expected profit >= EUR {detector.min_profit_eur:.2f}")
    print(f"  - Profit margin >= {detector.min_margin_percent:.1f}%")
    print(f"  - Confidence score >= {detector.min_confidence_score:.2f}")
    print(f"  - Listing price > 0")
    print()
    print("Otherwise:")
    print("  - MAYBE: Positive profit but doesn't meet all thresholds")
    print("  - SKIP: Overpriced, low confidence, or invalid data")

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
