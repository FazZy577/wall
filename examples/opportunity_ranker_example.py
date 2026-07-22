"""Opportunity ranker example.

Demonstrates how to use the opportunity ranker to sort and summarize
arbitrage opportunities. No Wallapop. No Playwright. No external calls.
"""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.entities.candidate_listing import CandidateListing
from domain.entities.resale_economics import ResaleEconomicPolicy
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
    estimated_profit: float,
    confidence_score: float,
    roi_percentage: float,
    market_discount_percentage: float,
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
        price=listing_price,
        currency="EUR",
        url=f"https://wallapop.com/item/{listing_id}",
    )
    return ArbitrageOpportunity(
        listing=listing,
        game=game,
        market_price=market_price,
        listing_price=listing_price,
        estimated_profit=estimated_profit,
        profit_margin_percentage=round(estimated_profit / market_price * 100, 1),
        roi_percentage=roi_percentage,
        market_discount_percentage=market_discount_percentage,
        break_even_price=listing_price,
        confidence_score=confidence_score,
        confidence_level="high",  # type: ignore[arg-type]
        opportunity_score=opportunity_score,
        recommendation=recommendation,
        reason=ReasonCode.UNDERVALUED,
        created_at=datetime.now(),
        economic_breakdown=ResaleEconomicPolicy.neutral().calculate(
            [market_price], listing_price
        ),
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
            estimated_profit=25.0,
            confidence_score=0.85,
            roi_percentage=200.0,
            market_discount_percentage=50.0,
            recommendation=Recommendation.BUY,
            listing_price=10.0,
            market_price=35.0,
        ),
        _make_opportunity(
            listing_id="lst_002",
            title="Red Dead Redemption 2 PS4",
            opportunity_score=89.1,
            estimated_profit=21.0,
            confidence_score=0.90,
            roi_percentage=150.0,
            market_discount_percentage=40.0,
            recommendation=Recommendation.BUY,
            listing_price=14.0,
            market_price=35.0,
        ),
        _make_opportunity(
            listing_id="lst_003",
            title="The Last of Us Part II",
            opportunity_score=73.0,
            estimated_profit=12.0,
            confidence_score=0.75,
            roi_percentage=80.0,
            market_discount_percentage=30.0,
            recommendation=Recommendation.MAYBE,
            listing_price=15.0,
            market_price=27.0,
        ),
        _make_opportunity(
            listing_id="lst_004",
            title="Call of Duty Black Ops 6",
            opportunity_score=65.0,
            estimated_profit=8.0,
            confidence_score=0.70,
            roi_percentage=50.0,
            market_discount_percentage=20.0,
            recommendation=Recommendation.MAYBE,
            listing_price=16.0,
            market_price=24.0,
        ),
        _make_opportunity(
            listing_id="lst_005",
            title="FIFA 25 PS4",
            opportunity_score=41.7,
            estimated_profit=3.0,
            confidence_score=0.60,
            roi_percentage=20.0,
            market_discount_percentage=10.0,
            recommendation=Recommendation.SKIP,
            listing_price=15.0,
            market_price=18.0,
        ),
        _make_opportunity(
            listing_id="lst_006",
            title="Overpriced Game PS4",
            opportunity_score=30.0,
            estimated_profit=-5.0,
            confidence_score=0.55,
            roi_percentage=-30.0,
            market_discount_percentage=5.0,
            recommendation=Recommendation.SKIP,
            listing_price=25.0,
            market_price=20.0,
        ),
        # Two opportunities with the SAME score to demonstrate tie-breaking
        _make_opportunity(
            listing_id="lst_007",
            title="NBA 2K25 PS4",
            opportunity_score=80.0,
            estimated_profit=10.0,
            confidence_score=0.80,
            roi_percentage=60.0,
            market_discount_percentage=25.0,
            recommendation=Recommendation.BUY,
            listing_price=12.0,
            market_price=22.0,
        ),
        _make_opportunity(
            listing_id="lst_008",
            title="NBA 2K25 PS4 (Steelbook)",
            opportunity_score=80.0,
            estimated_profit=18.0,  # Higher profit в†’ wins tie-break
            confidence_score=0.80,
            roi_percentage=80.0,
            market_discount_percentage=30.0,
            recommendation=Recommendation.BUY,
            listing_price=12.0,
            market_price=30.0,
        ),
    ]

    print(f"  Created {len(opportunities)} opportunities:")
    for opp in opportunities:
        print(
            f"    {opp.listing.listing_id}: {opp.listing.title[:30]:30s} "
            f"score={opp.opportunity_score:5.1f} "
            f"profit=в‚¬{opp.estimated_profit:6.2f} "
            f"{opp.recommendation.upper()}"
        )
    print()

    # =========================================================================
    # Step 2: Create ranker
    # =========================================================================
    print("Step 2: Creating ranker")
    print("-" * 80)

    ranker = DefaultOpportunityRanker(strategy=RankingStrategy.OPPORTUNITY_SCORE)
    print(f"  Strategy: {ranker.strategy}")
    print()

    # =========================================================================
    # Step 3: Full ranking
    # =========================================================================
    print("Step 3: Full ranking (no limit)")
    print("-" * 80)
    print()

    result = ranker.rank(opportunities)
    print(result.explain())
    print()

    # =========================================================================
    # Step 4: Top 3 (limit=3)
    # =========================================================================
    print("Step 4: Top 3 (limit=3)")
    print("-" * 80)
    print()

    top3 = ranker.rank(opportunities, limit=3)
    print(top3.explain())
    print()

    # =========================================================================
    # Step 5: Summary statistics
    # =========================================================================
    print("Step 5: Summary statistics")
    print("-" * 80)
    print()

    print(f"  total_received:  {result.total_received}")
    print(f"  total_ranked:    {result.total_ranked}")
    print(f"  total_returned:  {result.total_returned}")
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
    print("    lst_007 (NBA 2K25):          profit=в‚¬10.00")
    print("    lst_008 (NBA 2K25 Steelbook): profit=в‚¬18.00")
    print()
    print("  Result: lst_008 ranks HIGHER because tie-break #1 is estimated_profit.")
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

    empty = ranker.rank([])
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
    print("  - Empty input в†’ best_score=None, average_score=None.")
    print()


if __name__ == "__main__":
    main()
