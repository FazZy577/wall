"""Validation script for FuzzyGameDetector using real Wallapop data.

This script analyzes captured listings from Wallapop and validates
the game detector's performance on real-world data.

Usage:
    python validate_detector.py
    python validate_detector.py --query rdr2_ps4
    python validate_detector.py --limit 10
    python validate_detector.py --export
    python validate_detector.py --query gta_5_ps4 --limit 20 --export
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.interfaces.game_detector import ListingText
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector


def find_items_recursively(data: dict[str, Any] | list[Any], depth: int = 0) -> list[dict[str, Any]]:
    """Recursively search for lists of items in JSON structure.

    Looks for common keys: items, search_objects, results, listings, data.

    Args:
        data: JSON data to search
        depth: Current recursion depth (to prevent infinite loops)

    Returns:
        List of item dictionaries found
    """
    if depth > 10:  # Prevent infinite recursion
        return []

    items = []

    if isinstance(data, dict):
        # Check common keys first
        for key in ["items", "search_objects", "results", "listings"]:
            if key in data and isinstance(data[key], list):
                # Verify it's a list of dicts with item-like structure
                if data[key] and isinstance(data[key][0], dict):
                    if "title" in data[key][0] or "id" in data[key][0]:
                        return data[key]

        # Recursively search all dict values
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = find_items_recursively(value, depth + 1)
                if found:
                    items.extend(found)

    elif isinstance(data, list):
        # Check if this list contains item-like dicts
        if data and isinstance(data[0], dict):
            if "title" in data[0] or "id" in data[0]:
                return data

        # Recursively search list items
        for item in data:
            if isinstance(item, (dict, list)):
                found = find_items_recursively(item, depth + 1)
                if found:
                    items.extend(found)

    return items


def extract_listing_info(item: dict[str, Any]) -> dict[str, str]:
    """Extract title and description from an item.

    Args:
        item: Item dictionary

    Returns:
        Dict with title and description
    """
    title = item.get("title", "")
    description = item.get("description", "")

    # Fallback: sometimes description is nested
    if not description and "content" in item:
        if isinstance(item["content"], dict):
            description = item["content"].get("description", "")
        elif isinstance(item["content"], str):
            description = item["content"]

    return {"title": title, "description": description}


def is_potential_false_negative(title: str, description: str) -> bool:
    """Check if listing might contain games but none were detected.

    Args:
        title: Listing title
        description: Listing description

    Returns:
        True if looks like gaming-related content
    """
    text = f"{title} {description}".lower()

    # Gaming platform keywords
    platform_keywords = [
        r"\bps3\b",
        r"\bps4\b",
        r"\bps5\b",
        r"\bplaystation\b",
        r"\bxbox\b",
        r"\bswitch\b",
        r"\bnintendo\b",
    ]

    # Common gaming terms
    gaming_keywords = [
        r"\bjuego[s]?\b",
        r"\bgame[s]?\b",
        r"\bvideojuego[s]?\b",
        r"\blote\b",
        r"\bpack\b",
        r"\bcoleccion\b",
        r"\bcod\b",
        r"\bfifa\b",
        r"\bgta\b",
    ]

    # Check for platform keywords
    for pattern in platform_keywords:
        if re.search(pattern, text):
            # If platform found, check for gaming terms
            for gaming_pattern in gaming_keywords:
                if re.search(gaming_pattern, text):
                    return True

    return False


def main() -> None:
    """Main validation script."""

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Validate FuzzyGameDetector with real Wallapop data"
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Process only specific query file (e.g., rdr2_ps4)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Process only first N listings",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export results to validation_report.json",
    )

    args = parser.parse_args()

    # Start timing
    start_time = time.time()

    print("=" * 80)
    print("GAME DETECTOR VALIDATION - REAL WALLAPOP DATA")
    print("=" * 80)
    print()

    # Initialize detector
    detector = FuzzyGameDetector()
    print("[OK] FuzzyGameDetector loaded")
    print()

    # Find all JSON files in responses/
    responses_dir = Path("responses")
    if not responses_dir.exists():
        print("[X] Error: responses/ directory not found")
        print("   Run playwright_search.py first to capture data")
        return

    # Filter files by query if specified
    if args.query:
        query_file = responses_dir / f"{args.query}.json"
        if not query_file.exists():
            print(f"[X] Error: {query_file.name} not found in responses/")
            return
        json_files = [query_file]
        print(f"[*] Processing single query: {args.query}")
    else:
        json_files = list(responses_dir.glob("*.json"))

    if not json_files:
        print("[X] Error: No JSON files found in responses/")
        return

    print(f"Found {len(json_files)} JSON file(s) to process:")
    for file in json_files:
        print(f"  - {file.name}")

    if args.limit:
        print(f"\n[*] Limiting to first {args.limit} listings per file")

    print()

    # Statistics
    total_listings = 0
    listings_with_games = 0
    listings_without_games = 0
    total_games_detected = 0
    confidence_scores = []
    game_counter = Counter()
    potential_false_negatives = []
    processing_times = []

    # Detailed results for export
    detailed_results = []

    # Process each file
    for json_file in json_files:
        print("-" * 80)
        print(f"Processing: {json_file.name}")
        print("-" * 80)

        # Load JSON
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)

        # Find items
        items = find_items_recursively(data)

        if not items:
            print("[!] Warning: No items found in this file")
            print()
            continue

        # Apply limit if specified
        if args.limit:
            items = items[:args.limit]

        print(f"Found {len(items)} listings")
        print()

        # Process each item
        for i, item in enumerate(items, 1):
            item_start_time = time.time()
            total_listings += 1

            # Extract info
            info = extract_listing_info(item)
            title = info["title"]
            description = info["description"]

            if not title:
                continue  # Skip items without title

            # Detect games
            listing = ListingText(title=title, description=description)
            detected_games = detector.detect_games(listing)

            item_processing_time = time.time() - item_start_time
            processing_times.append(item_processing_time)

            # Print results (ASCII-safe)
            title_display = title[:70].encode('ascii', 'replace').decode('ascii')
            print(f"[{i}] {title_display}")

            listing_result = {
                "title": title,
                "description": description[:200],
                "games_detected": [],
            }

            if detected_games:
                listings_with_games += 1
                total_games_detected += len(detected_games)

                for game in detected_games:
                    print(f"    [+] {game.canonical_name}")
                    print(f"        Platform: {game.platform}")
                    print(f"        Confidence: {game.confidence:.0%}")
                    print(f"        Method: {game.detection_method}")

                    # Collect statistics
                    confidence_scores.append(game.confidence)
                    game_counter[game.canonical_name] += 1

                    # Store for export
                    listing_result["games_detected"].append({
                        "canonical_name": game.canonical_name,
                        "platform": str(game.platform),
                        "confidence": game.confidence,
                        "detection_method": str(game.detection_method),
                    })
            else:
                listings_without_games += 1
                print("    [-] No games detected")

                # Check for potential false negative
                if is_potential_false_negative(title, description):
                    print("    [!] POTENTIAL FALSE NEGATIVE (gaming keywords found)")
                    potential_false_negatives.append(
                        {"title": title, "description": description[:100]}
                    )
                    listing_result["potential_false_negative"] = True

            detailed_results.append(listing_result)
            print()

    # Calculate timing
    end_time = time.time()
    total_time = end_time - start_time
    avg_time_per_listing = sum(processing_times) / len(processing_times) if processing_times else 0

    # Print summary
    print()
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print()

    print(f"Total listings processed: {total_listings}")
    print(f"Listings with games detected: {listings_with_games} ({listings_with_games/total_listings*100:.1f}%)")
    print(f"Listings without games: {listings_without_games} ({listings_without_games/total_listings*100:.1f}%)")
    print(f"Total games detected: {total_games_detected}")

    if confidence_scores:
        avg_confidence = sum(confidence_scores) / len(confidence_scores)
        print(f"Average confidence: {avg_confidence:.1%}")
        print(f"Min confidence: {min(confidence_scores):.1%}")
        print(f"Max confidence: {max(confidence_scores):.1%}")

    print()
    print(f"Total execution time: {total_time:.2f}s")
    print(f"Average time per listing: {avg_time_per_listing*1000:.1f}ms")
    print()

    # Top detected games
    if game_counter:
        print("Top 10 detected games:")
        for game_name, count in game_counter.most_common(10):
            print(f"  {count:3d}x {game_name}")
        print()

    # Potential false negatives
    if potential_false_negatives:
        print(f"Potential false negatives: {len(potential_false_negatives)}")
        print("(Listings with gaming keywords but no games detected)")
        print()
        for item in potential_false_negatives[:5]:  # Show first 5
            title_safe = item['title'][:60].encode('ascii', 'replace').decode('ascii')
            print(f"  - {title_safe}")
            if item["description"]:
                desc_safe = item['description'][:60].encode('ascii', 'replace').decode('ascii')
                print(f"    {desc_safe}...")
            print()

        if len(potential_false_negatives) > 5:
            print(f"  ... and {len(potential_false_negatives) - 5} more")
            print()

    # Export results if requested
    if args.export:
        export_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "query_filter": args.query,
            "limit": args.limit,
            "summary": {
                "total_listings": total_listings,
                "listings_with_games": listings_with_games,
                "listings_without_games": listings_without_games,
                "total_games_detected": total_games_detected,
                "detection_rate": listings_with_games / total_listings if total_listings > 0 else 0,
                "avg_confidence": sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0,
                "min_confidence": min(confidence_scores) if confidence_scores else 0,
                "max_confidence": max(confidence_scores) if confidence_scores else 0,
                "total_execution_time_seconds": total_time,
                "avg_time_per_listing_ms": avg_time_per_listing * 1000,
            },
            "top_games": [
                {"game": game_name, "count": count}
                for game_name, count in game_counter.most_common(10)
            ],
            "potential_false_negatives": potential_false_negatives[:10],
            "detailed_results": detailed_results,
        }

        export_file = Path("validation_report.json")
        with open(export_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        print(f"[OK] Results exported to: {export_file.absolute()}")
        print()

    print("=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
