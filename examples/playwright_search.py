"""Playwright search proof of concept - Multiple searches in one browser session.

This script demonstrates how to perform multiple Wallapop searches
reusing the same browser session and capturing API responses.

This will be the foundation for the future WallapopPlaywrightClient.
"""

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from playwright.async_api import async_playwright


def find_in_dict(data: dict[str, Any], target_key: str) -> Any:
    """Recursively search for a key in a nested dictionary.

    Args:
        data: Dictionary to search in
        target_key: Key to find

    Returns:
        Value if found, None otherwise
    """
    if target_key in data:
        return data[target_key]

    for value in data.values():
        if isinstance(value, dict):
            result = find_in_dict(value, target_key)
            if result is not None:
                return result

    return None


def find_items_list(data: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Find the list of items/listings in the response.

    Searches for common keys: items, search_objects, results, listings.

    Args:
        data: API response data

    Returns:
        List of items if found, None otherwise
    """
    # Common keys for item lists
    possible_keys = ["items", "search_objects", "results", "listings", "data"]

    for key in possible_keys:
        result = find_in_dict(data, key)
        if result and isinstance(result, list) and len(result) > 0:
            return result

    return None


def find_prices(items: list[dict[str, Any]]) -> list[float]:
    """Extract prices from a list of items.

    Args:
        items: List of item dictionaries

    Returns:
        List of prices found
    """
    prices = []

    for item in items:
        # Try to find price in different possible structures
        price = None

        # Direct price key
        if "price" in item:
            price_data = item["price"]
            if isinstance(price_data, dict) and "amount" in price_data:
                price = price_data["amount"]
            elif isinstance(price_data, (int, float)):
                price = price_data

        if price is not None:
            prices.append(float(price))

    return prices


def sanitize_filename(query: str) -> str:
    """Convert search query to valid filename.

    Args:
        query: Search query string

    Returns:
        Sanitized filename
    """
    return query.replace(" ", "_").replace("/", "_").replace("\\", "_")


async def perform_search(page, query: str, output_dir: Path) -> None:
    """Perform a single search and capture the API response.

    Args:
        page: Playwright page object
        query: Search query
        output_dir: Directory to save responses
    """
    print("=" * 80)
    print(f"Searching: {query}")

    # Storage for captured response
    captured_response = None
    response_url = None
    response_status = None

    async def handle_response(response):
        """Capture API response."""
        nonlocal captured_response, response_url, response_status

        # Check if this is the search API endpoint
        if "api.wallapop.com/api/v3/search/section" in response.url:
            response_url = response.url
            response_status = response.status

            try:
                captured_response = await response.json()
            except Exception as e:
                print(f"Error parsing JSON: {e}")

    # Register response handler
    page.on("response", handle_response)

    # Navigate to search page
    encoded_query = quote(query)
    search_url = f"https://es.wallapop.com/app/search?keywords={encoded_query}"
    await page.goto(search_url, wait_until="networkidle")

    # Wait a bit for API responses
    await asyncio.sleep(3)

    # Remove response handler
    page.remove_listener("response", handle_response)

    # Process captured response
    if captured_response:
        print(f"Status: {response_status}")

        # Save to file
        filename = sanitize_filename(query) + ".json"
        output_file = output_dir / filename
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(captured_response, f, indent=2, ensure_ascii=False)
        print(f"Saved to: {output_file.name}")

        # Find search_id
        search_id = find_in_dict(captured_response, "search_id")
        if search_id:
            print(f"Search ID: {search_id}")
        else:
            print("Search ID: Not found")

        # Find items list
        items = find_items_list(captured_response)

        if items:
            print(f"Items encontrados: {len(items)}")

            # Find next_page
            next_page = find_in_dict(captured_response, "next_page")
            if next_page:
                print(f"Next page: {next_page}")
            else:
                print("Next page: None")

            # Extract and show prices
            prices = find_prices(items)
            if prices:
                print(f"\nPrimeros 5 precios:")
                for price in prices[:5]:
                    print(f"  {price:.0f}€")
            else:
                print("\nNo se pudieron extraer precios")
        else:
            print("WARNING: No se encontró lista de items")
            print("\nClaves principales del JSON:")
            for key in captured_response.keys():
                print(f"  - {key}")

            # Try to show nested structure
            if "data" in captured_response:
                print("\nClaves dentro de 'data':")
                if isinstance(captured_response["data"], dict):
                    for key in captured_response["data"].keys():
                        print(f"  - data.{key}")
    else:
        print("ERROR: No se capturó respuesta de la API")

    print("=" * 80)
    print()


async def main() -> None:
    """Main function - perform multiple searches in one browser session."""

    # Create output directory
    output_dir = Path("responses")
    output_dir.mkdir(exist_ok=True)
    print(f"Output directory: {output_dir.absolute()}\n")

    # List of searches to perform
    searches = [
        "rdr2 ps4",
        "gta 5 ps4",
        "cod bo6 ps4",
    ]

    print(f"Starting Playwright...")
    print(f"Will perform {len(searches)} searches in one browser session\n")

    async with async_playwright() as p:
        # Launch browser ONCE
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        # Perform all searches using the same page
        for query in searches:
            await perform_search(page, query, output_dir)

            # Small delay between searches
            await asyncio.sleep(2)

        # Close browser
        await browser.close()

    print("\n" + "=" * 80)
    print("ALL SEARCHES COMPLETE")
    print("=" * 80)
    print(f"\nResults saved to: {output_dir.absolute()}")
    print(f"Total searches: {len(searches)}")


if __name__ == "__main__":
    asyncio.run(main())
