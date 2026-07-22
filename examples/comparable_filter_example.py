"""Example usage of RuleBasedComparableFilter.

Demonstrates how to filter valid comparable listings for price estimation.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.interfaces.comparable_filter import ComparableFilterInput
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from infrastructure.filters.rule_based_comparable_filter import RuleBasedComparableFilter


def main() -> None:
    """Demonstrate comparable filtering on sample listings."""

    # Initialize filter
    filter_instance = RuleBasedComparableFilter()

    # Target game we want to price
    target_game = DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )

    # Sample listings
    listings = [
        ComparableFilterInput(title="GTA V PS4", description="Juego en buen estado", price=15.0),
        ComparableFilterInput(title="Lote GTA V + RDR2 + FIFA", description="3 juegos", price=40.0),
        ComparableFilterInput(title="Mando DualShock 4 PS4", description="Controller", price=25.0),
        ComparableFilterInput(title="Caja GTA V sin disco", description="Solo caja", price=5.0),
        ComparableFilterInput(title="GTA Trilogy", description="3 juegos clásicos", price=30.0),
        ComparableFilterInput(title="GTA V Premium Edition PS4", description="Completo", price=18.0),
        ComparableFilterInput(title="PS4 (PlayStation 4) Negra", description="Consola", price=150.0),
        ComparableFilterInput(title="GTA V PS4 Usado", description="Buen estado", price=12.0),
    ]

    print("=" * 80)
    print("COMPARABLE FILTER - EXAMPLE USAGE")
    print("=" * 80)
    print()
    print(f"Target Game: {target_game.canonical_name} ({target_game.platform})")
    print()
    print("Evaluating listings:")
    print("-" * 80)
    print()

    valid_comparables = []

    for i, listing in enumerate(listings, 1):
        is_valid = filter_instance.is_valid_comparable(target_game, listing)
        status = "[OK] VALID" if is_valid else "[X] REJECTED"

        print(f"[{i}] {listing.title}")
        print(f"    Price: EUR {listing.price}")
        print(f"    Status: {status}")

        if is_valid:
            valid_comparables.append(listing)

        print()

    print("-" * 80)
    print()
    print(f"Valid comparables: {len(valid_comparables)}/{len(listings)}")

    if valid_comparables:
        print()
        print("These listings can be used for price estimation:")
        for listing in valid_comparables:
            print(f"  - {listing.title}: EUR {listing.price}")

    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
