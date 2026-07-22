"""Example usage of DefaultPriceDatasetBuilder.

Demonstrates how to transform comparable listings into a clean price dataset.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)


def main() -> None:
    """Demonstrate price dataset builder usage."""

    print("=" * 80)
    print("PRICE DATASET BUILDER - EXAMPLE USAGE")
    print("=" * 80)
    print()

    # Target game
    target_game = DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )

    # Sample comparable listings (would come from PriceCollector)
    comparable_listings = [
        ComparableListing(
            listing_id="1",
            title="GTA V PS4",
            description="Juego en buen estado",
            price=15.0,
            currency="EUR",
            detected_game=target_game,
            url="https://es.wallapop.com/item/gta-v-ps4-1",
        ),
        ComparableListing(
            listing_id="2",
            title="GTA V Premium Edition",
            description="Edicion premium completa",
            price=18.0,
            currency="EUR",
            detected_game=target_game,
            url="https://es.wallapop.com/item/gta-v-premium-2",
        ),
        ComparableListing(
            listing_id="3",
            title="GTA V PS4 Usado",
            description="Buen estado",
            price=12.0,
            currency="EUR",
            detected_game=target_game,
            url="https://es.wallapop.com/item/gta-v-usado-3",
        ),
        ComparableListing(
            listing_id="4",
            title="GTA V Steelbook",
            description="Edicion steelbook",
            price=20.0,
            currency="EUR",
            detected_game=target_game,
            url="https://es.wallapop.com/item/gta-v-steelbook-4",
        ),
        ComparableListing(
            listing_id="5",
            title="GTA V PS4",
            description="Como nuevo",
            price=16.5,
            currency="EUR",
            detected_game=target_game,
            url="https://es.wallapop.com/item/gta-v-nuevo-5",
        ),
        # Invalid listing (will be discarded)
        ComparableListing(
            listing_id="6",
            title="GTA V Invalid",
            description="Precio invalido",
            price=0.0,  # Invalid: price = 0
            currency="EUR",
            detected_game=target_game,
            url="https://es.wallapop.com/item/gta-v-invalid-6",
        ),
    ]

    print(f"Target Game: {target_game.canonical_name} ({target_game.platform})")
    print()
    print(f"Input: {len(comparable_listings)} comparable listings")
    print()
    print("-" * 80)
    print()

    # Create dataset builder
    builder = DefaultPriceDatasetBuilder(source="wallapop")

    # Build dataset
    dataset = builder.build(comparable_listings)

    print()
    print("-" * 80)
    print()
    print("PRICE DATASET")
    print()
    print(f"Game: {dataset.game.canonical_name}")
    print(f"Platform: {dataset.game.platform}")
    print(f"Sample size: {dataset.sample_size}")
    print(f"Created at: {dataset.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()
    print("Observations:")
    print()

    for i, obs in enumerate(dataset.observations, 1):
        print(f"[{i}] {obs.title}")
        print(f"    Price: {obs.currency} {obs.price}")
        print(f"    Listing ID: {obs.listing_id}")
        print(f"    Platform: {obs.platform}")
        print(f"    Source: {obs.source}")
        print()

    print("-" * 80)
    print()
    print("IMPORTANT:")
    print("This dataset contains ONLY the raw observations.")
    print("It does NOT calculate:")
    print("  - Mean, median, mode")
    print("  - Percentiles")
    print("  - Standard deviation")
    print("  - Outlier detection")
    print("  - Price estimates")
    print()
    print("Statistical calculations will be done by the next module:")
    print("Price Statistics Engine")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
