"""Example usage of FuzzyGameDetector.

Demonstrates how to use the game detector to identify games in listings.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.interfaces.game_detector import ListingText
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector


def main() -> None:
    """Demonstrate game detection on sample listings."""

    # Initialize detector
    detector = FuzzyGameDetector(PackagedGameCatalog())

    # Example listings
    examples = [
        {
            "title": "Lote PS4 GTA V RDR2 FIFA 24",
            "description": "Todos completos en perfecto estado",
        },
        {
            "title": "Pack juegos PS4",
            "description": "Incluye GTA 5, Red Dead Redemption 2 y FC 24",
        },
        {
            "title": "Cod BO6 PS5",
            "description": "Nuevo precintado",
        },
        {
            "title": "Lote Nintendo Switch",
            "description": "Varios juegos de Switch en buen estado",
        },
        {
            "title": "Mando PS4",
            "description": "Mando inalambrico azul",
        },
    ]

    print("=" * 80)
    print("FUZZY GAME DETECTOR - EXAMPLE USAGE")
    print("=" * 80)
    print()

    for i, example in enumerate(examples, 1):
        print(f"Example {i}:")
        print(f"  Title: {example['title']}")
        print(f"  Description: {example['description']}")
        print()

        # Create listing text
        listing = ListingText(
            title=example["title"],
            description=example["description"],
        )

        # Detect games
        detected_games = detector.detect_games(listing)

        if detected_games:
            print(f"  Detected {len(detected_games)} game(s):")
            for game in detected_games:
                print(f"    - {game.canonical_name}")
                print(f"      Platform: {game.platform}")
                print(f"      Confidence: {game.confidence:.2%}")
                print(f"      Method: {game.detection_method}")
                print(f"      Matched text: '{game.matched_text}'")
                print()
        else:
            print("  No games detected")
            print()

        print("-" * 80)
        print()


if __name__ == "__main__":
    main()
