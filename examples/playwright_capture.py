"""Playwright proof of concept to capture Wallapop API responses.

This script opens a browser, navigates to a Wallapop search page,
and captures the JSON response from the API call.
"""

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def capture_wallapop_api_response() -> None:
    """Capture API response from Wallapop search page."""

    print("Starting Playwright...")

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        # Storage for captured response
        captured_response = None

        async def handle_response(response):
            """Handle network responses and capture the API call."""
            nonlocal captured_response

            # Check if this is the search API endpoint
            if "api.wallapop.com/api/v3/search/section" in response.url:
                print(f"\nCaptured API call: {response.url}")
                print(f"Status: {response.status}")

                try:
                    # Get the JSON response
                    json_data = await response.json()
                    captured_response = json_data
                    print("Response captured successfully!")
                except Exception as e:
                    print(f"Error parsing JSON: {e}")

        # Register response handler
        page.on("response", handle_response)

        # Navigate to search page
        search_url = "https://es.wallapop.com/app/search?keywords=lote%20ps4"
        print(f"\nNavigating to: {search_url}")
        await page.goto(search_url, wait_until="networkidle")

        # Wait a bit for API calls to complete
        print("Waiting for API responses...")
        await asyncio.sleep(5)

        # Close browser
        await browser.close()

        # Process captured response
        if captured_response:
            print("\n" + "="*80)
            print("API RESPONSE CAPTURED")
            print("="*80)

            # Save to file
            output_file = Path("response.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(captured_response, f, indent=2, ensure_ascii=False)
            print(f"\nSaved to: {output_file.absolute()}")

            # Extract and print key information
            search_objects = captured_response.get("search_objects", [])
            search_id = captured_response.get("search_id", "N/A")
            next_page = captured_response.get("next_page")

            print(f"\nNumber of listings found: {len(search_objects)}")
            print(f"Search ID: {search_id}")

            if next_page:
                print(f"Next page: {next_page}")
            else:
                print("Next page: None")

            # Print first 3 listings as preview
            if search_objects:
                print("\n" + "="*80)
                print("FIRST 3 LISTINGS PREVIEW")
                print("="*80)
                for i, listing in enumerate(search_objects[:3], 1):
                    title = listing.get("title", "N/A")
                    price = listing.get("price", "N/A")
                    listing_id = listing.get("id", "N/A")
                    print(f"\n[{i}] {title}")
                    print(f"    Price: {price} EUR")
                    print(f"    ID: {listing_id}")
        else:
            print("\n❌ No API response captured")
            print("This might happen if:")
            print("  - The page structure changed")
            print("  - The API endpoint URL changed")
            print("  - Network requests were blocked")


if __name__ == "__main__":
    asyncio.run(capture_wallapop_api_response())
