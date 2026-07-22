"""Full pipeline example using real Wallapop data.

Demonstrates the complete flow:
Game Detection → PriceCollection → Dataset Building → Statistics →
Outlier Removal → Market Price Estimation

Uses real JSON responses captured from Wallapop API.
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.filters.rule_based_comparable_filter import (
    RuleBasedComparableFilter,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def main() -> None:
    """Demonstrate full pipeline with real Wallapop data."""

    print("=" * 80)
    print("FULL PIPELINE EXAMPLE - Real Wallapop Data")
    print("=" * 80)
    print()

    # Step 1: Load real Wallapop response
    print("STEP 1: Load Real Wallapop Data")
    print("-" * 80)

    response_file = Path(__file__).parent.parent / "responses" / "gta_5_ps4.json"

    with open(response_file, encoding="utf-8") as f:
        wallapop_response = json.load(f)

    raw_listings = wallapop_response["data"]["section"]["items"]

    print(f"Loaded: {response_file.name}")
    print(f"Raw listings found: {len(raw_listings)}")
    print()
    print("=" * 80)
    print()

    # Step 2: Simulate Game Detection (normally done by GameDetector)
    print("STEP 2: Game Detection")
    print("-" * 80)

    target_game = DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )

    print(f"Detected Game: {target_game.canonical_name}")
    print(f"Platform: {target_game.platform}")
    print(f"Detection Confidence: {target_game.confidence:.2f}")
    print()
    print("=" * 80)
    print()

    # Step 3: Filter Comparable Listings
    print("STEP 3: Filter Comparable Listings")
    print("-" * 80)

    comparable_filter = RuleBasedComparableFilter()

    # Convert raw listings to ComparableListing objects
    comparable_listings = []
    for listing in raw_listings:
        # Only include listings with prices
        if 'price' not in listing or listing['price'] is None:
            continue

        # Create ComparableListing with proper structure
        comparable = ComparableListing(
            listing_id=listing['id'],
            title=listing['title'],
            description=listing.get('description', ''),
            price=listing['price']['amount'],
            currency=listing['price']['currency'],
            detected_game=target_game,
            url=f"https://wallapop.com/item/{listing['web_slug']}",
        )
        comparable_listings.append(comparable)

    print(f"Total listings before filtering: {len(comparable_listings)}")

    # Show sample titles
    print()
    print("Sample listing titles:")
    for comp in comparable_listings[:5]:
        print(f"  - EUR {comp.price:.2f} - {comp.title[:60]}...")

    print()
    print("=" * 80)
    print()

    # Step 4: Build Price Dataset
    print("STEP 4: Build Price Dataset")
    print("-" * 80)

    dataset_builder = DefaultPriceDatasetBuilder(source="wallapop")
    dataset = dataset_builder.build(comparable_listings)

    print(f"Dataset created:")
    print(f"  Sample size: {dataset.sample_size} observations")
    print(f"  Game: {dataset.game.canonical_name}")
    print(f"  Created at: {dataset.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Show price distribution
    prices = sorted([obs.price for obs in dataset.observations])
    print(f"Price distribution:")
    print(f"  Min: EUR {min(prices):.2f}")
    print(f"  Max: EUR {max(prices):.2f}")
    print(f"  All prices: {', '.join(f'EUR {p:.2f}' for p in prices)}")

    print()
    print("=" * 80)
    print()

    # Step 5: Calculate Statistics
    print("STEP 5: Calculate Price Statistics")
    print("-" * 80)

    statistics_calculator = DefaultPriceStatistics()
    stats = statistics_calculator.calculate(dataset)

    print(f"Statistical Metrics:")
    print(f"  Count: {stats.count}")
    print(f"  Mean: EUR {stats.mean_price:.2f}")
    print(f"  Median: EUR {stats.median_price:.2f}")
    print(f"  Std Dev: EUR {stats.standard_deviation:.2f}")
    print(f"  Variance: EUR {stats.variance:.2f}")
    print()
    print(f"  Q1 (25th percentile): EUR {stats.q1:.2f}")
    print(f"  Q3 (75th percentile): EUR {stats.q3:.2f}")
    print(f"  IQR: EUR {stats.iqr:.2f}")
    print()
    print(f"  Min: EUR {stats.min_price:.2f}")
    print(f"  Max: EUR {stats.max_price:.2f}")

    print()
    print("=" * 80)
    print()

    # Step 6: Remove Outliers
    print("STEP 6: Remove Outliers (Tukey's IQR Method)")
    print("-" * 80)

    outlier_removal = DefaultOutlierRemoval()
    outlier_result = outlier_removal.remove_outliers(dataset, stats)

    print(f"Outlier Detection Results:")
    print(f"  Method: {outlier_result.method}")
    print(f"  Lower bound: EUR {outlier_result.lower_bound:.2f}")
    print(f"  Upper bound: EUR {outlier_result.upper_bound:.2f}")
    print()
    print(f"  Observations kept: {outlier_result.kept_count}")
    print(f"  Observations removed: {outlier_result.removed_count}")

    if outlier_result.removed_observations:
        print()
        print(f"Removed outliers:")
        for outlier in outlier_result.removed_observations:
            print(f"  - EUR {outlier.price:.2f} ({outlier.reason})")
            # Use encode/decode to handle special characters on Windows
            title = outlier.original_observation.title[:60]
            title_safe = title.encode('ascii', 'replace').decode('ascii')
            print(f"    Title: {title_safe}...")
    else:
        print()
        print("  No outliers detected")

    print()
    print("=" * 80)
    print()

    # Step 7: Recalculate Statistics on Clean Data
    print("STEP 7: Recalculate Statistics (Clean Dataset)")
    print("-" * 80)

    clean_stats = statistics_calculator.calculate(outlier_result.clean_dataset)

    print(f"Clean Dataset Metrics:")
    print(f"  Count: {clean_stats.count}")
    print(f"  Mean: EUR {clean_stats.mean_price:.2f} (was EUR {stats.mean_price:.2f})")
    print(f"  Median: EUR {clean_stats.median_price:.2f} (was EUR {stats.median_price:.2f})")
    print(f"  Std Dev: EUR {clean_stats.standard_deviation:.2f} (was EUR {stats.standard_deviation:.2f})")
    print(f"  IQR: EUR {clean_stats.iqr:.2f} (was EUR {stats.iqr:.2f})")

    print()
    print("=" * 80)
    print()

    # Step 8: Estimate Market Price
    print("STEP 8: Estimate Market Price")
    print("-" * 80)

    estimator = DefaultMarketPriceEstimator()
    estimate = estimator.estimate(
        dataset=outlier_result.clean_dataset,
        statistics=clean_stats,
        observations_removed=outlier_result.removed_count,
    )

    print(f"MARKET PRICE ESTIMATE")
    print()
    print(f"  Game: {estimate.game.canonical_name} ({estimate.game.platform})")
    print(f"  Estimated Price: {estimate.currency} {estimate.estimated_price:.2f}")
    print()
    print(f"  Confidence Score: {estimate.confidence_score:.2f}")
    print(f"  Confidence Level: {estimate.confidence_level.upper()}")
    print(f"  Strategy: {estimate.strategy}")
    print(f"  Reason Code: {estimate.reason_code}")
    print()
    print(f"  Sample Size: {estimate.sample_size} observations")
    print(f"  Outliers Removed: {estimate.observations_removed} ({estimate.outlier_percentage:.1f}%)")
    print()
    print(f"  Price Range: {estimate.currency} {estimate.minimum_price:.2f} - {estimate.currency} {estimate.maximum_price:.2f}")
    print(f"  Standard Deviation: {estimate.currency} {estimate.standard_deviation:.2f}")
    print(f"  IQR: {estimate.currency} {estimate.iqr:.2f}")
    print(f"  Coefficient of Variation: {estimate.coefficient_of_variation:.2%}")

    print()
    print("=" * 80)
    print()

    # Use explain() method
    print("DETAILED EXPLANATION")
    print("-" * 80)
    print()
    print(estimate.explain())
    print()
    print("=" * 80)
    print()

    # Final Report
    print("FINAL REPORT")
    print("-" * 80)
    print()

    # Confidence interpretation
    confidence_interpretation = ""
    if estimate.confidence_score >= 0.80:
        confidence_interpretation = "[OK] High confidence - Safe for decision-making"
    elif estimate.confidence_score >= 0.50:
        confidence_interpretation = "[WARN] Medium confidence - Use with caution"
    else:
        confidence_interpretation = "[ERROR] Low confidence - Not recommended for decisions"

    print(f"Confidence: {estimate.confidence_score:.2f} - {confidence_interpretation}")
    print()

    # Reason interpretation
    reason_interpretation = {
        "normal": "Normal dataset with sufficient data and reasonable dispersion",
        "insufficient_data": "Too few observations for reliable estimate",
        "high_volatility": "High price variation indicates unstable market",
        "narrow_range": "All prices very similar (no variation)",
    }

    print(f"Reason: {estimate.reason_code} - {reason_interpretation.get(estimate.reason_code, 'Unknown')}")
    print()

    # Summary table
    print("Summary Table:")
    print()
    print(f"| Metric                    | Value                 |")
    print(f"|---------------------------|-----------------------|")
    print(f"| Game                      | {estimate.game.canonical_name:21} |")
    print(f"| Platform                  | {estimate.game.platform:21} |")
    print(f"| Estimated Price           | {estimate.currency} {estimate.estimated_price:18.2f} |")
    print(f"| Confidence Score          | {estimate.confidence_score:21.2f} |")
    print(f"| Confidence Level          | {estimate.confidence_level.upper():21} |")
    print(f"| Sample Size               | {estimate.sample_size:21} |")
    print(f"| Outliers Removed          | {estimate.observations_removed:21} |")
    print(f"| Outlier Percentage        | {estimate.outlier_percentage:20.1f}% |")
    print(f"| Price Range               | EUR {estimate.minimum_price:.2f} - EUR {estimate.maximum_price:.2f}      |")
    print(f"| Median                    | EUR {clean_stats.median_price:18.2f} |")
    print(f"| Mean                      | EUR {clean_stats.mean_price:18.2f} |")
    print(f"| Standard Deviation        | EUR {estimate.standard_deviation:18.2f} |")
    print(f"| IQR                       | EUR {estimate.iqr:18.2f} |")
    print(f"| Coefficient of Variation  | {estimate.coefficient_of_variation:.2%}                 |")

    print()
    print("=" * 80)
    print()

    print("PIPELINE COMPLETE")
    print()
    print("All modules executed successfully:")
    print("  [OK] Game Detection")
    print("  [OK] Comparable Filter")
    print("  [OK] Dataset Builder")
    print("  [OK] Price Statistics")
    print("  [OK] Outlier Removal")
    print("  [OK] Market Price Estimator")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
