"""Example usage of DefaultMarketPriceEstimator.

Demonstrates how to estimate fair market prices from clean datasets
using the MEDIAN strategy with confidence scoring.
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
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def main() -> None:
    """Demonstrate market price estimation."""

    print("=" * 80)
    print("MARKET PRICE ESTIMATOR - EXAMPLE USAGE")
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

    # Example 1: Stable market (high confidence)
    print("EXAMPLE 1: Stable Market (High Confidence)")
    print("-" * 80)
    print()

    prices_stable = [14.0, 14.5, 15.0, 15.0, 15.5, 15.5, 16.0, 16.0, 16.5, 17.0]
    prices_stable += [14.5, 15.0, 15.5, 16.0, 16.5, 17.0, 14.0, 15.0, 16.0, 15.5]

    dataset_stable = create_dataset(prices_stable, target_game)

    print(f"Sample size: {dataset_stable.sample_size} observations")
    print(f"Prices: {format_price_summary(prices_stable)}")
    print()

    # Calculate statistics
    stats_calculator = DefaultPriceStatistics()
    stats_stable = stats_calculator.calculate(dataset_stable)

    print(f"Statistics:")
    print(f"  Mean: EUR {stats_stable.mean_price:.2f}")
    print(f"  Median: EUR {stats_stable.median_price:.2f}")
    print(f"  Std Dev: EUR {stats_stable.standard_deviation:.2f}")
    print(f"  IQR: EUR {stats_stable.iqr:.2f}")
    print()

    # Estimate market price
    estimator = DefaultMarketPriceEstimator()
    estimate_stable = estimator.estimate(
        dataset=dataset_stable,
        statistics=stats_stable,
        observations_removed=2,  # Assume 2 outliers were removed earlier
    )

    print(f"Market Price Estimate:")
    print(f"  Estimated Price: EUR {estimate_stable.estimated_price:.2f}")
    print(f"  Confidence Score: {estimate_stable.confidence_score:.2f}")
    print(f"  Strategy: {estimate_stable.strategy}")
    print(f"  Reason: {estimate_stable.reason_code}")
    print(f"  Price Range: EUR {estimate_stable.minimum_price:.2f} - EUR {estimate_stable.maximum_price:.2f}")
    print()
    print(f"Interpretation:")
    print(f"  [OK] High confidence ({estimate_stable.confidence_score:.2f})")
    print(f"  [OK] {estimate_stable.sample_size} observations")
    print(f"  [OK] Stable market (low dispersion)")
    print()
    print("=" * 80)
    print()

    # Example 2: Volatile market (low confidence)
    print("EXAMPLE 2: Volatile Market (Low Confidence)")
    print("-" * 80)
    print()

    prices_volatile = [5.0, 8.0, 10.0, 12.0, 15.0, 18.0, 20.0, 25.0, 30.0, 35.0]

    dataset_volatile = create_dataset(prices_volatile, target_game)

    print(f"Sample size: {dataset_volatile.sample_size} observations")
    print(f"Prices: {format_price_summary(prices_volatile)}")
    print()

    stats_volatile = stats_calculator.calculate(dataset_volatile)

    print(f"Statistics:")
    print(f"  Mean: EUR {stats_volatile.mean_price:.2f}")
    print(f"  Median: EUR {stats_volatile.median_price:.2f}")
    print(f"  Std Dev: EUR {stats_volatile.standard_deviation:.2f}")
    print(f"  IQR: EUR {stats_volatile.iqr:.2f}")
    print()

    estimate_volatile = estimator.estimate(
        dataset=dataset_volatile,
        statistics=stats_volatile,
        observations_removed=0,
    )

    print(f"Market Price Estimate:")
    print(f"  Estimated Price: EUR {estimate_volatile.estimated_price:.2f}")
    print(f"  Confidence Score: {estimate_volatile.confidence_score:.2f}")
    print(f"  Strategy: {estimate_volatile.strategy}")
    print(f"  Reason: {estimate_volatile.reason_code}")
    print(f"  Price Range: EUR {estimate_volatile.minimum_price:.2f} - EUR {estimate_volatile.maximum_price:.2f}")
    print()
    print(f"Interpretation:")
    print(f"  [WARN] Low confidence ({estimate_volatile.confidence_score:.2f})")
    print(f"  [WARN] High price volatility")
    print(f"  [WARN] Wide price range (EUR {estimate_volatile.minimum_price:.2f} - EUR {estimate_volatile.maximum_price:.2f})")
    print()
    print("=" * 80)
    print()

    # Example 3: Insufficient data
    print("EXAMPLE 3: Insufficient Data (Very Low Confidence)")
    print("-" * 80)
    print()

    prices_small = [15.0, 16.0, 17.0]

    dataset_small = create_dataset(prices_small, target_game)

    print(f"Sample size: {dataset_small.sample_size} observations")
    print(f"Prices: {format_price_summary(prices_small)}")
    print()

    stats_small = stats_calculator.calculate(dataset_small)

    print(f"Statistics:")
    print(f"  Mean: EUR {stats_small.mean_price:.2f}")
    print(f"  Median: EUR {stats_small.median_price:.2f}")
    print(f"  Std Dev: EUR {stats_small.standard_deviation:.2f}")
    print()

    estimate_small = estimator.estimate(
        dataset=dataset_small,
        statistics=stats_small,
        observations_removed=0,
    )

    print(f"Market Price Estimate:")
    print(f"  Estimated Price: EUR {estimate_small.estimated_price:.2f}")
    print(f"  Confidence Score: {estimate_small.confidence_score:.2f}")
    print(f"  Strategy: {estimate_small.strategy}")
    print(f"  Reason: {estimate_small.reason_code}")
    print()
    print(f"Interpretation:")
    print(f"  [ERROR] Very low confidence ({estimate_small.confidence_score:.2f})")
    print(f"  [ERROR] Insufficient data (only {estimate_small.sample_size} observations)")
    print(f"  [ERROR] Not recommended for decision-making")
    print()
    print("=" * 80)
    print()

    # Comparison table
    print("CONFIDENCE SCORE COMPARISON")
    print("-" * 80)
    print()
    print(f"| Scenario          | Sample | Mean    | Std Dev | CV    | Confidence | Reason            |")
    print(f"|-------------------|--------|---------|---------|-------|------------|-------------------|")
    print(f"| Stable Market     | {estimate_stable.sample_size:6} | {stats_stable.mean_price:7.2f} | {stats_stable.standard_deviation:7.2f} | {stats_stable.standard_deviation/stats_stable.mean_price:5.2f} | {estimate_stable.confidence_score:10.2f} | {estimate_stable.reason_code:17} |")
    print(f"| Volatile Market   | {estimate_volatile.sample_size:6} | {stats_volatile.mean_price:7.2f} | {stats_volatile.standard_deviation:7.2f} | {stats_volatile.standard_deviation/stats_volatile.mean_price:5.2f} | {estimate_volatile.confidence_score:10.2f} | {estimate_volatile.reason_code:17} |")
    print(f"| Insufficient Data | {estimate_small.sample_size:6} | {stats_small.mean_price:7.2f} | {stats_small.standard_deviation:7.2f} | {stats_small.standard_deviation/stats_small.mean_price:5.2f} | {estimate_small.confidence_score:10.2f} | {estimate_small.reason_code:17} |")
    print()
    print("=" * 80)
    print()

    print("IMPORTANT:")
    print()
    print("This module ONLY estimates the fair market price.")
    print()
    print("It does NOT:")
    print("  - Decide whether to buy or sell")
    print("  - Calculate profit margins")
    print("  - Calculate ROI")
    print("  - Assess market demand")
    print("  - Make business decisions")
    print()
    print("These decisions belong to future modules:")
    print("  - Arbitrage Opportunity Detector")
    print("  - Purchase Decision Engine")
    print()
    print("=" * 80)


def create_dataset(prices: list[float], game: DetectedGame) -> PriceDataset:
    """Helper to create PriceDataset from list of prices."""
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

    return PriceDataset(
        observations=observations,
        game=game,
        created_at=datetime.now(timezone.utc),
        sample_size=len(observations),
    )


def format_price_summary(prices: list[float]) -> str:
    """Format price list as summary string."""
    if len(prices) <= 5:
        return ", ".join(f"EUR {p:.2f}" for p in prices)

    first_three = ", ".join(f"EUR {p:.2f}" for p in prices[:3])
    last_two = ", ".join(f"EUR {p:.2f}" for p in prices[-2:])
    return f"{first_three}, ..., {last_two}"


if __name__ == "__main__":
    main()
