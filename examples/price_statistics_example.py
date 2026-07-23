"""Example usage of DefaultPriceStatistics.

Demonstrates how to calculate statistical metrics from a price dataset.
"""

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from domain.interfaces.price_dataset_builder import (
    PriceDataset,
    PriceObservation,
)
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def main() -> None:
    """Demonstrate price statistics calculation."""

    print("=" * 80)
    print("PRICE STATISTICS ENGINE - EXAMPLE USAGE")
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

    # Create sample dataset with realistic prices
    prices = [10.0, 12.0, 12.5, 13.0, 15.0, 15.0, 16.0, 17.0, 18.0, 20.0, 25.0]

    observations = [
        PriceObservation(
            price=Decimal(str(price)),
            currency="EUR",
            listing_id=str(i),
            title=f"GTA V PS4 Listing {i}",
            platform=Platform.PS4,
            source="wallapop",
            raw_listing={},
        )
        for i, price in enumerate(prices, 1)
    ]

    dataset = PriceDataset(
        observations=observations,
        game=target_game,
        created_at=datetime.now(timezone.utc),
        sample_size=len(observations),
        currency="EUR",
    )

    print(f"Target Game: {target_game.canonical_name} ({target_game.platform})")
    print()
    print("Price Dataset:")
    print(f"  Sample size: {dataset.sample_size} observations")
    print(f"  Prices: {', '.join(f'EUR {p}' for p in prices)}")
    print()
    print("-" * 80)
    print()

    # Calculate statistics
    calculator = DefaultPriceStatistics()
    stats = calculator.calculate(dataset)

    print("STATISTICAL METRICS")
    print()
    print("Basic Metrics:")
    print(f"  Count: {stats.count}")
    print(f"  Min price: EUR {stats.min_price:.2f}")
    print(f"  Max price: EUR {stats.max_price:.2f}")
    print(f"  Mean price: EUR {stats.mean_price:.2f}")
    print(f"  Median price: EUR {stats.median_price:.2f}")
    print()
    print("Spread Metrics:")
    print(f"  Standard deviation: EUR {stats.standard_deviation:.2f}")
    print(f"  Variance: {stats.variance:.2f}")
    print()
    print("Quartiles:")
    print(f"  Q1 (25th percentile): EUR {stats.q1:.2f}")
    print(f"  Q2 (Median): EUR {stats.median_price:.2f}")
    print(f"  Q3 (75th percentile): EUR {stats.q3:.2f}")
    print(f"  IQR (Q3 - Q1): EUR {stats.iqr:.2f}")
    print()
    print("Percentiles:")
    print(f"  10th percentile: EUR {stats.percentile_10:.2f}")
    print(f"  25th percentile: EUR {stats.percentile_25:.2f}")
    print(f"  75th percentile: EUR {stats.percentile_75:.2f}")
    print(f"  90th percentile: EUR {stats.percentile_90:.2f}")
    print()
    print("-" * 80)
    print()
    print("IMPORTANT:")
    print()
    print("This module ONLY calculates descriptive statistics.")
    print()
    print("It does NOT:")
    print("  - Remove outliers")
    print("  - Estimate market price")
    print("  - Calculate confidence scores")
    print("  - Make pricing recommendations")
    print("  - Filter observations")
    print()
    print("These will be handled by separate modules:")
    print("  - Outlier Removal Engine")
    print("  - Market Price Estimator")
    print("  - Confidence Score Engine")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
