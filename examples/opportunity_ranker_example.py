"""Opportunity ranker example.

Demonstrates how to use the opportunity ranker to sort and summarize
arbitrage opportunities. No Wallapop. No Playwright. No external calls.
"""

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from application.interfaces.opportunity_scanner import RankingResult
from domain.entities.candidate_listing import CandidateListing
from domain.entities.resale_economics import EconomicBreakdown
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    ReasonCode,
    Recommendation,
)
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.opportunity_ranker import RankingStrategy
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker


def _make_game(name: str) -> DetectedGame:
    """Create a sample game."""
    return DetectedGame(
        canonical_name=name,
        matched_text=name.lower(),
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def _make_opportunity(
    listing_id: str,
    title: str,
    opportunity_score: float,
    net_profit: float,
    confidence_score: float,
    net_roi_percentage: float,
    acquisition_discount_to_reference_market_percentage: float,
    recommendation: Recommendation,
    listing_price: float,
    market_price: float,
) -> ArbitrageOpportunity:
    """Create an ArbitrageOpportunity for example purposes."""
    game = _make_game(title)
    listing = CandidateListing(
        listing_id=listing_id,
        title=title,
        description="Good condition",
        price=Decimal(str(listing_price)),
        currency="EUR",
        url=f"https://wallapop.com/item/{listing_id}",
    )
    total_acquisition_cost = (
        net_profit / (net_roi_percentage / 100.0)
        if net_roi_percentage != 0
        else listing_price
    )
    acquisition_price = market_price * (
        1 - acquisition_discount_to_reference_market_percentage / 100.0
    )
    breakdown = EconomicBreakdown(
        reference_market_value=Decimal(str(market_price)),
        expected_item_sale_prices=(market_price,),
        expected_sale_revenue=Decimal(str(market_price)),
        quick_sale_discount_total=Decimal("0.0"),
        selling_fees=Decimal("0.0"),
        fixed_selling_costs=Decimal("0.0"),
        safety_buffer=Decimal("0.0"),
        acquisition_price=Decimal(str(acquisition_price)),
        acquisition_overhead=total_acquisition_cost - acquisition_price,
        total_acquisition_cost=Decimal(str(total_acquisition_cost)),
        net_expected_proceeds=net_profit + total_acquisition_cost,
        net_profit=Decimal(str(net_profit)),
        break_even_sale_revenue=Decimal(str(total_acquisition_cost)),
        item_count=1,
        currency="EUR",
    )
    return ArbitrageOpportunity(
        listing=listing,
        game=game,
        market_price=Decimal(str(market_price)),
        listing_price=Decimal(str(listing_price)),
        confidence_score=confidence_score,
        confidence_level="high",  # type: ignore[arg-type]
        opportunity_score=opportunity_score,
        recommendation=recommendation,
        reason=ReasonCode.UNDERVALUED,
        created_at=datetime.now(),
        economic_breakdown=breakdown,
    )


def main() -> None:
    """Demonstrate opportunity ranker."""

    print("=" * 80)
    print("OPPORTUNITY RANKER EXAMPLE")
    print("=" * 80)
    print()
    print("This module ONLY ranks opportunities.")
    print("It does NOT detect, estimate, or calculate anything.")
    print()

    # =========================================================================
    # Step 1: Create sample opportunities
    # =========================================================================
    print("Step 1: Creating sample opportunities")
    print("-" * 80)

    opportunities = [
        _make_opportunity(
            listing_id="lst_001",
            title="Grand Theft Auto V PS4",
            opportunity_score=92.4,
            net_profit=Decimal("25.0"),
            confidence_score=0.85,
            net_roi_percentage=200.0,
            acquisition_discount_to_reference_market_percentage=50.0,
            recommendation=Recommendation.BUY,
            listing_price=Decimal("10.0"),
            market_price=Decimal("35.0"),
        ),
        _make_opportunity(
            listing_id="lst_002",
            title="Red Dead Redemption 2 PS4",
            opportunity_score=89.1,
            net_profit=Decimal("21.0"),
            confidence_score=0.90,
            net_roi_percentage=150.0,
            acquisition_discount_to_reference_market_percentage=40.0,
            recommendation=Recommendation.BUY,
            listing_price=Decimal("14.0"),
            market_price=Decimal("35.0"),
        ),
        _make_opportunity(
            listing_id="lst_003",
            title="The Last of Us Part II",
            opportunity_score=73.0,
            net_profit=Decimal("12.0"),
            confidence_score=0.75,
            net_roi_percentage=80.0,
            acquisition_discount_to_reference_market_percentage=30.0,
            recommendation=Recommendation.MAYBE,
            listing_price=Decimal("15.0"),
            market_price=Decimal("27.0"),
        ),
        _make_opportunity(
            listing_id="lst_004",
            title="Call of Duty Black Ops 6",
            opportunity_score=65.0,
            net_profit=Decimal("8.0"),
            confidence_score=0.70,
            net_roi_percentage=50.0,
            acquisition_discount_to_reference_market_percentage=20.0,
            recommendation=Recommendation.MAYBE,
            listing_price=Decimal("16.0"),
            market_price=Decimal("24.0"),
        ),
        _make_opportunity(
            listing_id="lst_005",
            title="FIFA 25 PS4",
            opportunity_score=41.7,
            net_profit=Decimal("3.0"),
            confidence_score=0.60,
            net_roi_percentage=20.0,
            acquisition_discount_to_reference_market_percentage=10.0,
            recommendation=Recommendation.SKIP,
            listing_price=Decimal("15.0"),
            market_price=Decimal("18.0"),
        ),
        _make_opportunity(
            listing_id="lst_006",
            title="Overpriced Game PS4",
            opportunity_score=30.0,
            net_profit=Decimal("-5.0"),
            confidence_score=0.55,
            net_roi_percentage=-30.0,
            acquisition_discount_to_reference_market_percentage=5.0,
            recommendation=Recommendation.SKIP,
            listing_price=Decimal("25.0"),
            market_price=Decimal("20.0"),
        ),
        # Two opportunities with the SAME score to demonstrate tie-breaking
        _make_opportunity(
            listing_id="lst_007",
            title="NBA 2K25 PS4",
            opportunity_score=80.0,
            net_profit=Decimal("10.0"),
            confidence_score=0.80,
            net_roi_percentage=60.0,
            acquisition_discount_to_reference_market_percentage=25.0,
            recommendation=Recommendation.BUY,
            listing_price=Decimal("12.0"),
            market_price=Decimal("22.0"),
        ),
        _make_opportunity(
            listing_id="lst_008",
            title="NBA 2K25 PS4 (Steelbook)",
            opportunity_score=80.0,
            net_profit=Decimal("18.0"),  # Higher profit РІвЂ вЂ™ wins tie-break
            confidence_score=0.80,
            net_roi_percentage=80.0,
            acquisition_discount_to_reference_market_percentage=30.0,
            recommendation=Recommendation.BUY,
            listing_price=Decimal("12.0"),
            market_price=Decimal("30.0"),
        ),
    ]

    print(f"  Created {len(opportunities)} opportunities:")
    for opp in opportunities:
        print(
            f"    {opp.listing.listing_id}: {opp.listing.title[:30]:30s} "
            f"score={opp.opportunity_score:5.1f} "
            f"profit=РІвЂљВ¬{opp.net_profit:6.2f} "
            f"{opp.recommendation.upper()}"
        )
    print()

    # =========================================================================
    # Step 2: Create ranker
    # =========================================================================
    print("Step 2: Creating ranker")
    print("-" * 80)

    ranker = DefaultOpportunityRanker()
    print(f"  Strategy: {RankingStrategy.OPPORTUNITY_SCORE}")
    print()

    # =========================================================================
    # Step 3: Full ranking
    # =========================================================================
    print("Step 3: Full ranking (no limit)")
    print("-" * 80)
    print()

    ranked = ranker.rank(opportunities)
    result = RankingResult.from_ranked_opportunities(ranked)
    for position, opportunity in enumerate(result.ordered_opportunities, 1):
        print(position, opportunity.listing.listing_id, opportunity.recommendation)
    print()

    # =========================================================================
    # Step 4: Show the first three already-ranked items
    # =========================================================================
    print("Step 4: First three ranked items")
    print("-" * 80)
    print()

    top3 = result.ordered_opportunities[:3]
    print([opportunity.listing.listing_id for opportunity in top3])
    print()

    # =========================================================================
    # Step 5: Summary statistics
    # =========================================================================
    print("Step 5: Summary statistics")
    print("-" * 80)
    print()

    print(f"  total_opportunities: {result.total_opportunities}")
    print()
    print(f"  BUY:    {result.buy_count}")
    print(f"  MAYBE:  {result.maybe_count}")
    print(f"  SKIP:   {result.skip_count}")
    print()
    print(f"  best_score:    {result.best_score}")
    print(f"  average_score: {result.average_score}")
    print()

    # =========================================================================
    # Step 6: Tie-breaking demonstration
    # =========================================================================
    print("Step 6: Tie-breaking demonstration")
    print("-" * 80)
    print()

    print("  Two opportunities with score=80.0:")
    print("    lst_007 (NBA 2K25):          profit=РІвЂљВ¬10.00")
    print("    lst_008 (NBA 2K25 Steelbook): profit=РІвЂљВ¬18.00")
    print()
    print("  Result: lst_008 ranks HIGHER because tie-break #1 is net_profit.")
    print()

    # Verify
    top_80s = [o for o in result.ordered_opportunities if o.opportunity_score == 80.0]
    if len(top_80s) == 2:
        print(
            f"  Confirmed: {top_80s[0].listing.listing_id} is before {top_80s[1].listing.listing_id}"
        )
        print()

    # =========================================================================
    # Step 7: Empty ranking
    # =========================================================================
    print("Step 7: Empty ranking")
    print("-" * 80)
    print()

    empty = RankingResult.from_ranked_opportunities(ranker.rank([]))
    print(f"  best_score:    {empty.best_score}")
    print(f"  average_score: {empty.average_score}")
    print()

    print("=" * 80)
    print("RANKER EXAMPLE COMPLETE")
    print("=" * 80)
    print()
    print("Key takeaways:")
    print("  - Ranker ONLY sorts, it does NOT calculate anything.")
    print("  - Tie-breaking is fully deterministic.")
    print("  - Counts are over ALL received, not just returned.")
    print("  - limit applies AFTER sorting.")
    print("  - Empty input РІвЂ вЂ™ best_score=None, average_score=None.")
    print()


if __name__ == "__main__":
    main()
