"""Opt-in live integration test for Wallapop's browser search endpoint."""

from urllib.parse import urlsplit

import pytest

from infrastructure.marketplaces.wallapop.playwright_client import (
    WallapopPlaywrightClient,
)


@pytest.mark.live
@pytest.mark.integration
@pytest.mark.asyncio
async def test_wallapop_playwright_live_search() -> None:
    """Capture a small real search without login, writes, or persisted state."""
    client = WallapopPlaywrightClient(max_pages=1, request_delay=0, headless=False)

    async with client:
        listings = await client.search_listings(
            keywords="gta 5 ps4",
            latitude=40.4168,
            longitude=-3.7038,
            max_results=5,
        )

        assert any(
            urlsplit(url).path == WallapopPlaywrightClient.API_PATH
            for url in client.last_response_urls
        )
        assert isinstance(listings, list)
        assert any(
            listing.get("id")
            and listing.get("title")
            and isinstance(listing.get("price"), (int, float))
            for listing in listings
        )

    assert not client.is_open
