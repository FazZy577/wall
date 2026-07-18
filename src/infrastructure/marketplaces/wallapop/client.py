"""Wallapop HTTP client for API communication.

This module handles all HTTP communication with Wallapop's search API.
"""

import asyncio
from typing import Any

import httpx


class WallapopClientError(Exception):
    """Base exception for Wallapop client errors."""

    pass


class WallapopAPIError(WallapopClientError):
    """Raised when Wallapop API returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Wallapop API error {status_code}: {message}")


class WallapopClient:
    """HTTP client for Wallapop API.

    Handles search requests with pagination, retries, and error handling.
    """

    BASE_URL = "https://api.wallapop.com/api/v3/general/search"
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY = 1.0
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Origin": "https://es.wallapop.com",
        "Referer": "https://es.wallapop.com/",
    }

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        """Initialize the Wallapop client.

        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "WallapopClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.DEFAULT_HEADERS,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    async def search(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        start: int = 0,
    ) -> dict[str, Any]:
        """Search for listings on Wallapop.

        Args:
            keywords: Search keywords
            latitude: Latitude for geolocation
            longitude: Longitude for geolocation
            start: Pagination offset (default: 0)

        Returns:
            Raw JSON response from Wallapop API containing:
                - search_objects: List of listings
                - next_page: URL for next page (if available)

        Raises:
            WallapopClientError: If client is not initialized
            WallapopAPIError: If API returns an error
            httpx.HTTPError: For network-related errors
        """
        if not self._client:
            raise WallapopClientError("Client not initialized. Use async context manager.")

        params: dict[str, str | float | int] = {
            "keywords": keywords,
            "latitude": latitude,
            "longitude": longitude,
            "start": start,
        }

        for attempt in range(self.max_retries):
            try:
                response = await self._client.get(self.BASE_URL, params=params)

                if response.status_code == 200:
                    data: dict[str, Any] = response.json()
                    return data

                # Handle API errors
                if response.status_code >= 400:
                    error_message = self._extract_error_message(response)
                    raise WallapopAPIError(response.status_code, error_message)

            except httpx.TimeoutException as e:
                if attempt == self.max_retries - 1:
                    raise WallapopClientError(f"Request timeout after {self.max_retries} attempts") from e
                await asyncio.sleep(self.retry_delay)

            except httpx.NetworkError as e:
                if attempt == self.max_retries - 1:
                    raise WallapopClientError(f"Network error after {self.max_retries} attempts") from e
                await asyncio.sleep(self.retry_delay)

            except WallapopAPIError:
                # Don't retry on API errors (client errors like 400, 404)
                raise

        raise WallapopClientError(f"Request failed after {self.max_retries} attempts")

    async def search_all_pages(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search and automatically paginate through all results.

        Args:
            keywords: Search keywords
            latitude: Latitude for geolocation
            longitude: Longitude for geolocation
            max_results: Maximum number of results to retrieve (None for all)

        Returns:
            List of all listing objects from all pages

        Raises:
            WallapopClientError: If client is not initialized
            WallapopAPIError: If API returns an error
        """
        all_listings: list[dict[str, Any]] = []
        start = 0

        while True:
            response = await self.search(keywords, latitude, longitude, start)
            listings = response.get("search_objects", [])

            if not listings:
                break

            all_listings.extend(listings)

            if max_results and len(all_listings) >= max_results:
                all_listings = all_listings[:max_results]
                break

            # Check if there's a next page
            next_page = response.get("next_page")
            if not next_page:
                break

            # Extract start parameter from next_page URL
            next_start = self._extract_start_from_next_page(next_page)
            if next_start is None:
                break

            start = next_start

        return all_listings

    def _extract_error_message(self, response: httpx.Response) -> str:
        """Extract error message from response.

        Args:
            response: HTTP response

        Returns:
            Error message string
        """
        try:
            error_data: dict[str, Any] = response.json()
            return str(error_data.get("error", response.text))
        except Exception:
            return response.text or f"HTTP {response.status_code}"

    def _extract_start_from_next_page(self, next_page_url: str) -> int | None:
        """Extract start parameter from next_page URL.

        Args:
            next_page_url: Next page URL from API response

        Returns:
            Start parameter value, or None if not found
        """
        try:
            # Parse the URL to extract start parameter
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(next_page_url)
            params = parse_qs(parsed.query)
            start_values = params.get("start", [])

            if start_values:
                return int(start_values[0])
        except Exception:
            pass

        return None
