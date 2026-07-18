"""Production Wallapop search client backed by Playwright."""

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from domain.interfaces.marketplace_search import IMarketplaceSearch

logger = logging.getLogger(__name__)


class PlaywrightStarter(Protocol):
    """Structural type returned by ``async_playwright``."""

    async def start(self) -> Playwright:
        """Start Playwright without entering a context manager."""
        ...


PlaywrightFactory = Callable[[], PlaywrightStarter]


class WallapopPlaywrightError(Exception):
    """Base exception for Playwright-backed Wallapop searches."""


class WallapopSearchTimeoutError(WallapopPlaywrightError):
    """Raised when Wallapop does not produce a search response in time."""


class WallapopSearchHTTPError(WallapopPlaywrightError):
    """Raised when the captured search endpoint returns a non-200 status."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Wallapop search returned HTTP {status_code}")


class WallapopSearchResponseError(WallapopPlaywrightError):
    """Raised when a captured Wallapop response cannot be decoded."""


class WallapopPlaywrightClient(IMarketplaceSearch):
    """Search Wallapop by capturing its browser API responses.

    One browser, context, and page are opened lazily and reused for every
    search until :meth:`close` is called. Pagination is triggered through the
    Wallapop page itself, so the opaque ``meta.next_page`` token is never
    decoded or reconstructed by this client.
    """

    API_HOST = "api.wallapop.com"
    API_PATH = "/api/v3/search/section"
    SEARCH_URL = "https://es.wallapop.com/app/search"
    DEFAULT_TIMEOUT_MS = 30_000.0
    DEFAULT_MAX_PAGES = 3
    DEFAULT_REQUEST_DELAY = 1.0
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        timeout_ms: float = DEFAULT_TIMEOUT_MS,
        max_pages: int = DEFAULT_MAX_PAGES,
        request_delay: float = DEFAULT_REQUEST_DELAY,
        headless: bool = False,
        debug_response_dir: Path | str | None = None,
        playwright_factory: PlaywrightFactory = async_playwright,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be greater than zero")
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero")
        if request_delay < 0:
            raise ValueError("request_delay cannot be negative")

        self.timeout_ms = timeout_ms
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.headless = headless
        self.debug_response_dir = (
            Path(debug_response_dir) if debug_response_dir is not None else None
        )
        self._playwright_factory = playwright_factory
        self._playwright_manager: PlaywrightStarter | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._search_lock = asyncio.Lock()
        self._debug_search_number = 0
        self._last_response_urls: list[str] = []

    @property
    def is_open(self) -> bool:
        """Whether the reusable browser session is currently open."""
        return self._browser is not None and self._context is not None and self._page is not None

    @property
    def last_response_urls(self) -> tuple[str, ...]:
        """Endpoint responses captured during the most recent search."""
        return tuple(self._last_response_urls)

    async def __aenter__(self) -> "WallapopPlaywrightClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def start(self) -> None:
        """Open Chromium once; repeated calls reuse the existing session."""
        if self.is_open:
            return

        logger.info("Starting reusable Chromium session for Wallapop")
        try:
            manager = self._playwright_factory()
            self._playwright_manager = manager
            self._playwright = await manager.start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="es-ES",
                user_agent=self.DEFAULT_USER_AGENT,
            )
            await self._context.grant_permissions(
                ["geolocation"],
                origin="https://es.wallapop.com",
            )
            self._page = await self._context.new_page()
        except Exception as error:
            await self.close()
            raise WallapopPlaywrightError("Unable to start Chromium") from error

    async def close(self) -> None:
        """Close context, browser, and Playwright even after partial failures."""
        context, browser, playwright = self._context, self._browser, self._playwright
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._playwright_manager = None

        for resource_name, close_operation in (
            ("browser context", context.close if context is not None else None),
            ("browser", browser.close if browser is not None else None),
            ("Playwright", playwright.stop if playwright is not None else None),
        ):
            if close_operation is None:
                continue
            try:
                await close_operation()
            except Exception:
                logger.exception("Failed to close %s", resource_name)

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Search and normalize listings captured from the real API endpoint."""
        if not keywords.strip():
            raise ValueError("keywords cannot be empty")
        if max_results <= 0:
            raise ValueError("max_results must be greater than zero")
        if not -90 <= latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")

        async with self._search_lock:
            await self.start()
            if self._page is None or self._context is None:
                raise WallapopPlaywrightError("Chromium session was not initialized")

            self._last_response_urls = []
            self._debug_search_number += 1
            await self._context.set_geolocation({"latitude": latitude, "longitude": longitude})
            return await self._capture_search(
                page=self._page,
                keywords=keywords,
                latitude=latitude,
                longitude=longitude,
                max_results=max_results,
            )

    async def _capture_search(
        self,
        *,
        page: Page,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        response_queue: asyncio.Queue[Response] = asyncio.Queue()

        def handle_response(response: Response) -> None:
            if self._is_search_response(response.url):
                response_queue.put_nowait(response)

        page.on("response", handle_response)
        query = urlencode(
            {
                "keywords": keywords,
                "latitude": latitude,
                "longitude": longitude,
            }
        )
        search_url = f"{self.SEARCH_URL}?{query}"

        try:
            try:
                await page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
            except PlaywrightTimeoutError as error:
                raise WallapopSearchTimeoutError(
                    "Wallapop search page navigation timed out"
                ) from error

            listings: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            for page_number in range(1, self.max_pages + 1):
                response = await self._next_response(response_queue)
                self._last_response_urls.append(response.url)
                payload = await self._read_payload(response)
                await self._save_debug_payload(payload, page_number)
                page_items, next_page = self._extract_page(payload)

                for item in page_items:
                    normalized = self._normalize_item(item)
                    listing_id = str(normalized.get("id", ""))
                    if listing_id and listing_id in seen_ids:
                        continue
                    if listing_id:
                        seen_ids.add(listing_id)
                    listings.append(normalized)
                    if len(listings) >= max_results:
                        return listings[:max_results]

                if not next_page or page_number >= self.max_pages:
                    break

                if self.request_delay:
                    await asyncio.sleep(self.request_delay)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            return listings[:max_results]
        finally:
            page.remove_listener("response", handle_response)

    async def _next_response(
        self,
        response_queue: asyncio.Queue[Response],
    ) -> Response:
        try:
            return await asyncio.wait_for(
                response_queue.get(),
                timeout=self.timeout_ms / 1000,
            )
        except TimeoutError as error:
            raise WallapopSearchTimeoutError(
                f"No response captured from {self.API_PATH}"
            ) from error

    async def _read_payload(self, response: Response) -> dict[str, Any]:
        if response.status != 200:
            raise WallapopSearchHTTPError(response.status)
        try:
            payload: Any = await response.json()
        except Exception as error:
            raise WallapopSearchResponseError("Wallapop returned malformed JSON") from error
        if not isinstance(payload, dict):
            raise WallapopSearchResponseError("Wallapop response root is not an object")
        return payload

    @classmethod
    def _is_search_response(cls, url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.hostname == cls.API_HOST and parsed.path == cls.API_PATH

    @staticmethod
    def _extract_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        data = payload.get("data")
        if not isinstance(data, dict):
            return [], None
        section = data.get("section")
        if not isinstance(section, dict):
            return [], None

        raw_items = section.get("items")
        items: list[dict[str, Any]] = []
        if isinstance(raw_items, list):
            items = [item for item in raw_items if isinstance(item, dict)]

        next_page: Any = None
        meta = payload.get("meta")
        if isinstance(meta, dict):
            next_page = meta.get("next_page")
        if not next_page:
            next_page = section.get("next_page")

        return items, next_page if isinstance(next_page, str) and next_page else None

    @staticmethod
    def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = dict(item)
        price = item.get("price")
        if isinstance(price, dict):
            normalized["price"] = price.get("amount")
            normalized["currency"] = price.get("currency", "EUR")
        else:
            normalized["currency"] = item.get("currency", "EUR")
        return normalized

    async def _save_debug_payload(
        self,
        payload: dict[str, Any],
        page_number: int,
    ) -> None:
        if self.debug_response_dir is None:
            return
        self.debug_response_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.debug_response_dir / (
            f"search_{self._debug_search_number:03d}_page_{page_number:02d}.json"
        )
        with output_path.open("w", encoding="utf-8") as output_file:
            json.dump(payload, output_file, ensure_ascii=False, indent=2)
        logger.debug("Saved debug response to %s", output_path)
