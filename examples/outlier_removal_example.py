"""Example usage of DefaultOutlierRemoval.

Demonstrates how to detect and remove outliers from a price dataset
using Tukey's IQR method.
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
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def main() -> None:
    """Demonstrate outlier removal."""

    print("=" * 80)
    print("OUTLIER REMOVAL ENGINE - EXAMPLE USAGE")
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

    # Create dataset with obvious outliers
    prices = [
        2.0,   # Outlier: too low (suspicious)
        10.0, 12.0, 12.5, 13.0, 15.0, 15.0, 16.0, 17.0, 18.0, 20.0,  # Normal range
        150.0,  # Outlier: too high (collector's edition? error?)
    ]

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
    )

    print(f"Target Game: {target_game.canonical_name} ({target_game.platform})")
    print()
    print("Original Dataset:")
    print(f"  Sample size: {dataset.sample_size} observations")
    print(f"  Prices: {', '.join(f'EUR {p:.2f}' for p in prices)}")
    print()
    print("-" * 80)
    print()

    # Step 1: Calculate statistics
    print("Step 1: Calculate statistics using Price Statistics Engine")
    print()

    statistics_calculator = DefaultPriceStatistics()
    stats = statistics_calculator.calculate(dataset)

    print(f"  Count: {stats.count}")
    print(f"  Min: EUR {stats.min_price:.2f}")
    print(f"  Max: EUR {stats.max_price:.2f}")
    print(f"  Mean: EUR {stats.mean_price:.2f}")
    print(f"  Median: EUR {stats.median_price:.2f}")
    print(f"  Q1 (25th percentile): EUR {stats.q1:.2f}")
    print(f"  Q3 (75th percentile): EUR {stats.q3:.2f}")
    print(f"  IQR: EUR {stats.iqr:.2f}")
    print()
    print("-" * 80)
    print()

    # Step 2: Remove outliers using Tukey's IQR method
    print("Step 2: Remove outliers using Tukey's IQR method")
    print()

    outlier_removal = DefaultOutlierRemoval()
    result = outlier_removal.remove_outliers(dataset, stats)

    print(f"  Method: {result.method}")
    print(f"  Lower bound: EUR {result.lower_bound:.2f}")
    print(f"  Upper bound: EUR {result.upper_bound:.2f}")
    print()
    print(f"  Formula:")
    print(f"    lower_bound = Q1 - 1.5 * IQR = {stats.q1:.2f} - 1.5 * {stats.iqr:.2f} = {result.lower_bound:.2f}")
    print(f"    upper_bound = Q3 + 1.5 * IQR = {stats.q3:.2f} + 1.5 * {stats.iqr:.2f} = {result.upper_bound:.2f}")
    print()
    print("-" * 80)
    print()

    # Step 3: Show results
    print("OUTLIER REMOVAL RESULTS")
    print()
    print(f"Removed: {result.removed_count} observations")
    print(f"Kept: {result.kept_count} observations")
    print()

    if result.removed_observations:
        print("Removed Observations:")
        for outlier in result.removed_observations:
            print(f"  - EUR {outlier.price:.2f} ({outlier.reason})")
            print(f"    Listing: {outlier.original_observation.title}")
        print()

    print("Clean Dataset:")
    clean_prices = [obs.price for obs in result.clean_dataset.observations]
    print(f"  Sample size: {result.clean_dataset.sample_size}")
    print(f"  Prices: {', '.join(f'EUR {p:.2f}' for p in clean_prices)}")
    print()
    print("-" * 80)
    print()

    # Optional: Recalculate statistics on clean dataset
    print("Optional: Recalculate statistics on clean dataset")
    print()

    clean_stats = statistics_calculator.calculate(result.clean_dataset)

    print("Before outlier removal:")
    print(f"  Mean: EUR {stats.mean_price:.2f}")
    print(f"  Median: EUR {stats.median_price:.2f}")
    print(f"  Std Dev: EUR {stats.standard_deviation:.2f}")
    print()
    print("After outlier removal:")
    print(f"  Mean: EUR {clean_stats.mean_price:.2f}")
    print(f"  Median: EUR {clean_stats.median_price:.2f}")
    print(f"  Std Dev: EUR {clean_stats.standard_deviation:.2f}")
    print()
    print("-" * 80)
    print()

    print("IMPORTANT:")
    print()
    print("This module ONLY removes statistical outliers.")
    print()
    print("It does NOT:")
    print("  - Estimate market price")
    print("  - Calculate confidence scores")
    print("  - Make pricing recommendations")
    print("  - Decide which price is 'correct'")
    print()
    print("These decisions belong to the next module:")
    print("  - Market Price Estimator")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
