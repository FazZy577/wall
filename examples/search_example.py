"""Example script to test WallapopClient.

This script demonstrates how to use WallapopClient to search for listings.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infrastructure.marketplaces.wallapop.client import WallapopClient, WallapopClientError


async def main() -> None:
    """Search for videogame lots on Wallapop and print first 10 results."""
    # Madrid coordinates
    MADRID_LAT = 40.4168
    MADRID_LON = -3.7038

    print("Searching Wallapop for 'lote videojuegos'...\n")

    try:
        async with WallapopClient() as client:
            # Search for videogame lots
            response = await client.search(
                keywords="lote videojuegos",
                latitude=MADRID_LAT,
                longitude=MADRID_LON,
            )

            listings = response.get("search_objects", [])

            if not listings:
                print("No results found.")
                return

            print(f"Found {len(listings)} listings in first page\n")
            print("=" * 80)
            print("FIRST 10 LISTINGS:")
            print("=" * 80)

            # Print first 10 listings
            for i, listing in enumerate(listings[:10], 1):
                print(f"\n[{i}] {listing.get('title', 'N/A')}")
                print(f"    Price: {listing.get('price', 'N/A')} EUR")
                print(f"    ID: {listing.get('id', 'N/A')}")
                print(f"    URL: https://es.wallapop.com/item/{listing.get('web_slug', 'N/A')}")

                # Optional: Show location if available
                location = listing.get("location", {})
                city = location.get("city", "N/A")
                print(f"    Location: {city}")

            print("\n" + "=" * 80)

            # Show next page info if available
            next_page = response.get("next_page")
            if next_page:
                print(f"\nNext page available: {next_page}")
            else:
                print("\nNo more pages available")

            # Optional: Print full JSON of first listing for inspection
            print("\n" + "=" * 80)
            print("FULL JSON OF FIRST LISTING (for inspection):")
            print("=" * 80)
            if listings:
                print(json.dumps(listings[0], indent=2, ensure_ascii=False))

    except WallapopClientError as e:
        print(f"Wallapop client error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
