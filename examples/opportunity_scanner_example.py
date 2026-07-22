"""Opportunity scanner example.

Demonstrates how to use the opportunity scanner to orchestrate
the complete arbitrage detection pipeline.

This example uses a mock price collector to avoid real API calls.
The scanner itself contains NO business logic вЂ” it only coordinates.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from application.interfaces.opportunity_scanner import RankingResult
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    IGameDetector,
    ListingText,
    Platform,
)
from domain.interfaces.opportunity_ranker import RankingStrategy
from domain.interfaces.price_collector import IPriceCollector
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class MockGameDetector(IGameDetector):
    """Mock game detector for demonstration purposes.

    In production, use FuzzyGameDetector instead.
    """

    def detect_games(self, _listing_text: ListingText) -> list[DetectedGame]:
        """Always returns GTA V for demo purposes."""
        return [
            DetectedGame(
                canonical_name="Grand Theft Auto V",
                matched_text="gta v",
                platform=Platform.PS4,
                confidence=1.0,
                detection_method=DetectionMethod.EXACT_MATCH,
            )
        ]


class MockPriceCollector(IPriceCollector):
    """Mock price collector for demonstration purposes.

    Returns sample comparable listings without calling Wallapop API.
    In production, use WallapopPriceCollector instead.
    """

    async def collect_comparables(
        self,
        game: DetectedGame,
        _latitude: float,
        _longitude: float,
        _max_results: int | None = None,
    ) -> list[ComparableListing]:
        """Return mock comparable listings for the given game."""
        # Simulate network delay
        await asyncio.sleep(0.01)

        return [
            ComparableListing(
                listing_id=f"mock_{game.canonical_name.replace(' ', '_')}_{i}",
                title=f"{game.canonical_name} {game.platform}",
                description="Good condition",
                price=15.0 + i * 3.0,  # Prices from 15в‚¬ to 39в‚¬
                currency="EUR",
                detected_game=game,
                url=f"https://wallapop.com/item/mock_{i}",
            )
            for i in range(8)
        ]


async def main() -> None:
    """Demonstrate opportunity scanner with complete pipeline."""

    print("=" * 80)
    print("OPPORTUNITY SCANNER вЂ” FULL PIPELINE EXAMPLE")
    print("=" * 80)
    print()
    print("This module contains NO business logic.")
    print("It ONLY orchestrates the pipeline in the correct order.")
    print()

    # =========================================================================
    # Step 1: Create all dependencies (Dependency Injection)
    # =========================================================================
    print("Step 1: Initializing all pipeline components")
    print("-" * 80)

    game_detector = MockGameDetector()
    price_collector = MockPriceCollector()
    dataset_builder = DefaultPriceDatasetBuilder(source="wallapop")
    statistics = DefaultPriceStatistics()
    outlier_removal = DefaultOutlierRemoval()
    market_estimator = DefaultMarketPriceEstimator()
    # Example strategy: 3 EUR below market; this is not a production default.
    economic_policy = ResaleEconomicPolicy(3.0, 0.0, 0.0, 0.0, 0.0)
    arbitrage_detector = DefaultArbitrageOpportunityDetector(economic_policy)

    print("  вњ“ GameDetector (mock)")
    print("  вњ“ PriceCollector (mock)")
    print("  вњ“ PriceDatasetBuilder")
    print("  вњ“ PriceStatistics")
    print("  вњ“ OutlierRemoval")
    print("  вњ“ MarketPriceEstimator")
    print("  вњ“ ArbitrageOpportunityDetector")
    print()

    # =========================================================================
    # Step 2: Create scanner with all dependencies injected
    # =========================================================================
    print("Step 2: Creating Opportunity Scanner (DI)")
    print("-" * 80)

    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=price_collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        arbitrage_detector=arbitrage_detector,
        opportunity_ranker=DefaultOpportunityRanker(),
    )

    print("  вњ“ All 7 dependencies injected into scanner")
    print("  вњ“ Scanner does NOT instantiate any component internally")
    print()

    # =========================================================================
    # Step 3: Create sample listings
    # =========================================================================
    print("Step 3: Creating sample listings")
    print("-" * 80)

    # A listing priced well below market в†’ should be BUY
    cheap_listing = CandidateListing(
        listing_id="listing_001",
        title="GTA V PS4 - Cheap!",
        description="Good condition, quick sale",
        price=5.0,
        currency="EUR",
        url="https://wallapop.com/item/listing_001",
    )

    # A listing priced near market в†’ should be MAYBE or SKIP
    expensive_listing = CandidateListing(
        listing_id="listing_002",
        title="COD BO6 PS4 - Premium",
        description="Like new, collector's edition",
        price=45.0,
        currency="EUR",
        url="https://wallapop.com/item/listing_002",
    )

    # A listing without a detected game в†’ will be skipped
    unknown_listing = CandidateListing(
        listing_id="listing_003",
        title="Random stuff",
        description="Various items",
        price=10.0,
        currency="EUR",
        url="https://wallapop.com/item/listing_003",
    )

    listings = [cheap_listing, expensive_listing, unknown_listing]

    print(f"  Created {len(listings)} listings:")
    for item in listings:
        print(f"    - {item.listing_id}: {item.title} (в‚¬{item.price:.2f})")
    print()

    # =========================================================================
    # Step 4: Scan a single listing
    # =========================================================================
    print("Step 4: scan_listing() вЂ” Single listing pipeline")
    print("-" * 80)
    print()

    opportunity = await scanner.scan_listing(cheap_listing)

    if opportunity:
        print()
        print(f"  Result: {opportunity.recommendation.upper()}")
        print(f"  Listing price:  в‚¬{opportunity.listing_price:.2f}")
        print(f"  Market price:   в‚¬{opportunity.market_price:.2f}")
        print(f"  Expected profit: в‚¬{opportunity.net_profit:.2f}")
        print(f"  Profit margin:  {opportunity.net_profit_margin_percentage:.1f}%")
        print(f"  Score:          {opportunity.opportunity_score:.1f}/100")
        print()
    else:
        print("  No opportunity found (listing skipped)")
        print()

    # =========================================================================
    # Step 5: Scan multiple listings
    # =========================================================================
    print("Step 5: scan_multiple() вЂ” Batch pipeline")
    print("-" * 80)
    print()

    result = await scanner.scan_multiple(listings)

    print()
    print("=" * 80)
    print("SCAN RESULTS")
    print("=" * 80)
    print()
    print(f"  Total Processed:  {result.total_processed}")
    print(f"  Successful:       {result.successful}")
    print(f"  Failed:           {result.failed}")
    print(f"  Processing Time:  {result.processing_time:.2f}s")
    print(f"  Created At:       {result.created_at.isoformat()}")
    print()

    if result.opportunities:
        # Create RankingResult for summary statistics
        ranking = RankingResult.from_ranked_opportunities(
            result.opportunities,
            strategy=RankingStrategy.OPPORTUNITY_SCORE,
        )

        print("OPPORTUNITIES FOUND")
        print("-" * 80)
        print()
        print(f"  Ranking strategy: {RankingStrategy.OPPORTUNITY_SCORE}")
        print(f"  BUY:    {ranking.buy_count}")
        print(f"  MAYBE:  {ranking.maybe_count}")
        print(f"  SKIP:   {ranking.skip_count}")
        print(f"  Best score:   {ranking.best_score:.1f}/100")
        print(f"  Average score: {ranking.average_score:.1f}/100")
        print("  Priority: BUY > MAYBE > SKIP; score orders within each group")
        print()

        for i, opp in enumerate(ranking.ordered_opportunities, 1):
            print(f"  {i}. {opp.listing.title}")
            print(f"     Listing ID:     {opp.listing.listing_id}")
            print(f"     Listing Price:  в‚¬{opp.listing_price:.2f}")
            print(f"     Market Price:   в‚¬{opp.market_price:.2f}")
            print(f"     Expected Profit: в‚¬{opp.net_profit:.2f}")
            print(f"     Profit Margin:  {opp.net_profit_margin_percentage:.1f}%")
            print(f"     ROI:            {opp.net_roi_percentage:.1f}%")
            print(f"     Score:          {opp.opportunity_score:.1f}/100")
            print(f"     Recommendation: {opp.recommendation.upper()}")
            print(f"     Reason:         {opp.reason}")
            print()

    if result.failures:
        print("FAILURES")
        print("-" * 80)
        print()
        for f in result.failures:
            print(f"  вњ— {f.listing_id}")
            print(f"    Stage:  {f.stage}")
            print(f"    Reason: {f.reason}")
            if f.error_message:
                print(f"    Error:  {f.error_message}")
            print()

    # =========================================================================
    # Summary
    # =========================================================================
    print("=" * 80)
    print("PIPELINE COMPLETE")
    print("=" * 80)
    print()
    print("The scanner coordinated these steps for each listing:")
    print()
    print("  1. GameDetector         вЂ” Verify game is detected")
    print("  2. PriceCollector       вЂ” Collect comparable listings")
    print("  3. PriceDatasetBuilder  вЂ” Build price dataset")
    print("  4. PriceStatistics      вЂ” Calculate statistics")
    print("  5. OutlierRemoval       вЂ” Remove outliers")
    print("  6. PriceStatistics      вЂ” Recalculate on clean data")
    print("  7. MarketPriceEstimator вЂ” Estimate market price")
    print("  8. ArbitrageDetector    вЂ” Detect opportunity")
    print()
    print("The scanner itself made ZERO decisions.")
    print("All business logic lives in the individual components.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
