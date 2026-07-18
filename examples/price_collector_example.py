"""Example usage of WallapopPriceCollector.

Demonstrates how to collect comparable listings for a game by orchestrating:
WallapopClient -> GameDetector -> ComparableFilter
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.filters.rule_based_comparable_filter import RuleBasedComparableFilter
from infrastructure.marketplaces.wallapop.client import WallapopClient


async def main() -> None:
    """Demonstrate price collector usage."""

    print("=" * 80)
    print("PRICE COLLECTOR - EXAMPLE USAGE")
    print("=" * 80)
    print()

    # Target game we want to find comparables for
    target_game = DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )

    print(f"Target Game: {target_game.canonical_name} ({target_game.platform})")
    print()

    # Initialize components
    wallapop_client = WallapopClient()
    game_detector = FuzzyGameDetector()
    comparable_filter = RuleBasedComparableFilter()

    # Create price collector
    price_collector = WallapopPriceCollector(
        wallapop_client=wallapop_client,
        game_detector=game_detector,
        comparable_filter=comparable_filter,
    )

    # Madrid coordinates
    latitude = 40.4168
    longitude = -3.7038

    print(f"Searching near Madrid ({latitude}, {longitude})")
    print("Max results: 10")
    print()
    print("-" * 80)
    print()

    # Collect comparables
    async with wallapop_client:
        comparables = await price_collector.collect_comparables(
            game=target_game,
            latitude=latitude,
            longitude=longitude,
            max_results=10,
        )

    print(f"Found {len(comparables)} valid comparable listings:")
    print()

    if comparables:
        for i, comparable in enumerate(comparables, 1):
            print(f"[{i}] {comparable.title}")
            print(f"    Price: {comparable.currency} {comparable.price}")
            print(f"    Detected: {comparable.detected_game.canonical_name}")
            print(f"    Confidence: {comparable.detected_game.confidence:.2f}")
            print(f"    URL: {comparable.url}")
            print()

        # Calculate basic statistics
        prices = [c.price for c in comparables]
        avg_price = sum(prices) / len(prices)
        min_price = min(prices)
        max_price = max(prices)

        print("-" * 80)
        print()
        print("Price Statistics:")
        print(f"  Average: EUR {avg_price:.2f}")
        print(f"  Min: EUR {min_price:.2f}")
        print(f"  Max: EUR {max_price:.2f}")
        print()
    else:
        print("No comparable listings found.")
        print()

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
