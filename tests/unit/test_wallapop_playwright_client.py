"""Unit tests for the production Playwright Wallapop client."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from infrastructure.marketplaces.wallapop.playwright_client import (
    WallapopPlaywrightClient,
    WallapopSearchHTTPError,
    WallapopSearchResponseError,
    WallapopSearchTimeoutError,
)

SECTION_URL = "https://api.wallapop.com/api/v3/search/section?keywords=gta%205%20ps4"


def make_listing(index: int) -> dict[str, Any]:
    """Create one raw listing in the captured endpoint schema."""
    return {
        "id": f"listing-{index}",
        "title": f"GTA V PS4 {index}",
        "description": "Juego completo",
        "price": {"amount": 10.0 + index, "currency": "EUR"},
        "web_slug": f"gta-v-ps4-{index}",
    }


def make_payload(
    items: list[dict[str, Any]] | None = None,
    *,
    next_page: str | None = None,
) -> dict[str, Any]:
    """Create one endpoint payload with the observed response structure."""
    return {
        "data": {"section": {"items": items or []}},
        "meta": {"next_page": next_page},
    }


def make_response(
    *,
    payload: dict[str, Any] | None = None,
    url: str = SECTION_URL,
    status: int = 200,
    json_error: Exception | None = None,
) -> Mock:
    """Create a mocked Playwright response."""
    response = Mock()
    response.url = url
    response.status = status
    response.json = AsyncMock(
        side_effect=json_error,
        return_value=payload if payload is not None else make_payload(),
    )
    return response


class PlaywrightHarness:
    """Mocked Playwright object graph with deterministic response emissions."""

    def __init__(self, emissions: list[list[Mock]] | None = None) -> None:
        self.emissions = list(emissions or [])
        self.response_handler: Callable[[Any], None] | None = None

        self.page = Mock()
        self.page.on = Mock(side_effect=self._on)
        self.page.remove_listener = Mock(side_effect=self._remove_listener)
        self.page.goto = AsyncMock(side_effect=self._emit_next)
        self.page.evaluate = AsyncMock(side_effect=self._emit_next)

        self.context = Mock()
        self.context.grant_permissions = AsyncMock()
        self.context.set_geolocation = AsyncMock()
        self.context.new_page = AsyncMock(return_value=self.page)
        self.context.close = AsyncMock()

        self.browser = Mock()
        self.browser.new_context = AsyncMock(return_value=self.context)
        self.browser.close = AsyncMock()

        self.chromium = Mock()
        self.chromium.launch = AsyncMock(return_value=self.browser)

        self.playwright = Mock()
        self.playwright.chromium = self.chromium
        self.playwright.stop = AsyncMock()

        self.manager = Mock()
        self.manager.start = AsyncMock(return_value=self.playwright)
        self.factory = Mock(return_value=self.manager)

    def _on(self, event: str, handler: Callable[[Any], None]) -> None:
        assert event == "response"
        self.response_handler = handler

    def _remove_listener(self, event: str, handler: Callable[[Any], None]) -> None:
        assert event == "response"
        assert handler is self.response_handler
        self.response_handler = None

    async def _emit_next(self, *_args: Any, **_kwargs: Any) -> None:
        if not self.emissions:
            return
        responses = self.emissions.pop(0)
        assert self.response_handler is not None
        for response in responses:
            self.response_handler(response)

    def build_client(
        self,
        *,
        timeout_ms: float = 100,
        max_pages: int = 3,
    ) -> WallapopPlaywrightClient:
        """Build a client wired to the mocked object graph."""
        return WallapopPlaywrightClient(
            timeout_ms=timeout_ms,
            max_pages=max_pages,
            request_delay=0,
            playwright_factory=self.factory,
        )


@pytest.mark.unit
class TestWallapopPlaywrightClient:
    """Exercise lifecycle, capture, normalization, errors, and pagination."""

    @pytest.mark.asyncio
    async def test_creates_and_closes_all_browser_resources(self) -> None:
        harness = PlaywrightHarness()
        client = harness.build_client()

        async with client:
            assert client.is_open

        assert not client.is_open
        harness.manager.start.assert_awaited_once()
        harness.chromium.launch.assert_awaited_once_with(headless=False)
        harness.browser.new_context.assert_awaited_once_with(
            viewport={"width": 1440, "height": 900},
            locale="es-ES",
            user_agent=WallapopPlaywrightClient.DEFAULT_USER_AGENT,
        )
        harness.context.close.assert_awaited_once()
        harness.browser.close.assert_awaited_once()
        harness.playwright.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reuses_one_session_for_multiple_searches(self) -> None:
        harness = PlaywrightHarness(
            [
                [make_response(payload=make_payload([make_listing(1)]))],
                [make_response(payload=make_payload([make_listing(2)]))],
            ]
        )
        client = harness.build_client()

        async with client:
            first = await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)
            second = await client.search_listings("rdr2 ps4", 40.4, -3.7, 5)

        assert first[0]["id"] == "listing-1"
        assert second[0]["id"] == "listing-2"
        harness.chromium.launch.assert_awaited_once()
        harness.context.new_page.assert_awaited_once()
        assert harness.page.goto.await_count == 2

    @pytest.mark.asyncio
    async def test_captures_only_exact_search_endpoint(self) -> None:
        unrelated = make_response(
            url="https://api.wallapop.com/api/v3/general/search",
            payload=make_payload([make_listing(99)]),
        )
        related = make_response(payload=make_payload([make_listing(1)]))
        harness = PlaywrightHarness([[unrelated, related]])
        client = harness.build_client()

        async with client:
            result = await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

        assert [item["id"] for item in result] == ["listing-1"]
        assert client.last_response_urls == (SECTION_URL,)
        unrelated.json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unrelated_responses_are_ignored(self) -> None:
        unrelated = make_response(url="https://es.wallapop.com/api/other")
        harness = PlaywrightHarness([[unrelated]])
        client = harness.build_client(timeout_ms=10)

        async with client:
            with pytest.raises(WallapopSearchTimeoutError):
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

        unrelated.json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_malformed_json_raises_explicit_error(self) -> None:
        response = make_response(json_error=ValueError("invalid JSON"))
        harness = PlaywrightHarness([[response]])
        client = harness.build_client()

        async with client:
            with pytest.raises(WallapopSearchResponseError):
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

    @pytest.mark.asyncio
    async def test_timeout_waiting_for_endpoint(self) -> None:
        harness = PlaywrightHarness([[]])
        client = harness.build_client(timeout_ms=10)

        async with client:
            with pytest.raises(WallapopSearchTimeoutError):
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

    @pytest.mark.asyncio
    async def test_non_200_response_raises_explicit_error(self) -> None:
        harness = PlaywrightHarness([[make_response(status=503)]])
        client = harness.build_client()

        async with client:
            with pytest.raises(WallapopSearchHTTPError) as error:
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

        assert error.value.status_code == 503

    @pytest.mark.asyncio
    async def test_absent_items_raises_response_error(self) -> None:
        response = make_response(payload={"data": {"section": {}}, "meta": {}})
        harness = PlaywrightHarness([[response]])
        client = harness.build_client()

        async with client:
            with pytest.raises(
                WallapopSearchResponseError,
                match="Wallapop response field 'data.section.items' is missing",
            ):
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ({}, "Wallapop response field 'data' is missing"),
            ({"data": None}, "Wallapop response field 'data' is not an object"),
            ({"data": []}, "Wallapop response field 'data' is not an object"),
            ({"data": ""}, "Wallapop response field 'data' is not an object"),
            ({"data": 0}, "Wallapop response field 'data' is not an object"),
            ({"data": True}, "Wallapop response field 'data' is not an object"),
            (
                {"data": {}},
                "Wallapop response field 'data.section' is missing",
            ),
        ],
    )
    def test_extract_page_rejects_missing_or_invalid_data(
        self,
        payload: dict[str, Any],
        message: str,
    ) -> None:
        with pytest.raises(WallapopSearchResponseError, match=message):
            WallapopPlaywrightClient._extract_page(payload)

    @pytest.mark.parametrize(
        ("section", "message"),
        [
            (None, "Wallapop response field 'data.section' is not an object"),
            ([], "Wallapop response field 'data.section' is not an object"),
            ("", "Wallapop response field 'data.section' is not an object"),
            (0, "Wallapop response field 'data.section' is not an object"),
            (True, "Wallapop response field 'data.section' is not an object"),
            ({}, "Wallapop response field 'data.section.items' is missing"),
        ],
    )
    def test_extract_page_rejects_missing_or_invalid_section_contents(
        self,
        section: Any,
        message: str,
    ) -> None:
        with pytest.raises(WallapopSearchResponseError, match=message):
            WallapopPlaywrightClient._extract_page({"data": {"section": section}})

    @pytest.mark.parametrize("raw_items", [None, {}, "", 0, True, (make_listing(1),)])
    def test_extract_page_rejects_non_list_items(self, raw_items: Any) -> None:
        payload = {"data": {"section": {"items": raw_items}}}

        with pytest.raises(
            WallapopSearchResponseError,
            match="Wallapop response field 'data.section.items' is not an array",
        ):
            WallapopPlaywrightClient._extract_page(payload)

    def test_extract_page_accepts_empty_items(self) -> None:
        assert WallapopPlaywrightClient._extract_page(make_payload([])) == ([], None)

    def test_extract_page_preserves_mapping_order_and_skips_other_elements(
        self,
    ) -> None:
        first = make_listing(1)
        second = make_listing(2)
        payload = {
            "data": {
                "section": {
                    "items": [first, None, "text", 1, True, second],
                }
            }
        }

        assert WallapopPlaywrightClient._extract_page(payload) == (
            [first, second],
            None,
        )

    @pytest.mark.parametrize("meta", [None, [], "", 0, True])
    def test_extract_page_rejects_non_mapping_meta(self, meta: Any) -> None:
        payload = {"data": {"section": {"items": []}}, "meta": meta}

        with pytest.raises(
            WallapopSearchResponseError,
            match="Wallapop response field 'meta' is not an object",
        ):
            WallapopPlaywrightClient._extract_page(payload)

    @pytest.mark.parametrize("invalid_token", [True, 1, 1.5, [], {}])
    @pytest.mark.parametrize(
        ("location", "field_path"),
        [
            ("meta", "meta.next_page"),
            ("section", "data.section.next_page"),
        ],
    )
    def test_extract_page_rejects_invalid_next_page_types(
        self,
        invalid_token: Any,
        location: str,
        field_path: str,
    ) -> None:
        section: dict[str, Any] = {"items": []}
        payload: dict[str, Any] = {"data": {"section": section}}
        if location == "meta":
            payload["meta"] = {"next_page": invalid_token}
        else:
            section["next_page"] = invalid_token

        with pytest.raises(
            WallapopSearchResponseError,
            match=f"Wallapop response field '{field_path}' has invalid type",
        ):
            WallapopPlaywrightClient._extract_page(payload)

    @pytest.mark.parametrize("meta_token", [None, ""])
    def test_extract_page_falls_back_to_section_token(
        self,
        meta_token: str | None,
    ) -> None:
        payload = {
            "data": {
                "section": {"items": [], "next_page": "section-token"},
            },
            "meta": {"next_page": meta_token},
        }

        assert WallapopPlaywrightClient._extract_page(payload) == (
            [],
            "section-token",
        )

    def test_extract_page_prefers_meta_token_but_validates_section_token(self) -> None:
        valid = {
            "data": {
                "section": {"items": [], "next_page": "section-token"},
            },
            "meta": {"next_page": "meta-token"},
        }
        invalid = {
            "data": {"section": {"items": [], "next_page": True}},
            "meta": {"next_page": "meta-token"},
        }

        assert WallapopPlaywrightClient._extract_page(valid) == ([], "meta-token")
        with pytest.raises(
            WallapopSearchResponseError,
            match=(
                "Wallapop response field 'data.section.next_page' has invalid type"
            ),
        ):
            WallapopPlaywrightClient._extract_page(invalid)

    def test_extract_page_accepts_optional_empty_or_absent_pagination(self) -> None:
        no_meta = {"data": {"section": {"items": []}}}
        empty_meta = {"data": {"section": {"items": []}}, "meta": {}}
        section_token = {
            "data": {
                "section": {"items": [], "next_page": "section-token"},
            }
        }

        assert WallapopPlaywrightClient._extract_page(no_meta) == ([], None)
        assert WallapopPlaywrightClient._extract_page(empty_meta) == ([], None)
        assert WallapopPlaywrightClient._extract_page(section_token) == (
            [],
            "section-token",
        )

    @pytest.mark.asyncio
    async def test_valid_empty_first_page_returns_empty_list(self) -> None:
        harness = PlaywrightHarness([[make_response(payload=make_payload([]))]])
        client = harness.build_client()

        async with client:
            result = await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

        assert result == []
        harness.page.evaluate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_max_results_truncates_normalized_items(self) -> None:
        response = make_response(payload=make_payload([make_listing(i) for i in range(5)]))
        harness = PlaywrightHarness([[response]])
        client = harness.build_client()

        async with client:
            result = await client.search_listings("gta 5 ps4", 40.4, -3.7, 2)

        assert len(result) == 2
        assert result[0]["price"] == 10.0
        assert result[0]["currency"] == "EUR"

    @pytest.mark.asyncio
    async def test_normalizes_real_string_and_integer_ids_and_discards_invalid_ids(
        self,
    ) -> None:
        items = [
            {**make_listing(1), "id": " 00123 "},
            {**make_listing(2), "id": 42},
            {**make_listing(3), "id": ""},
            {**make_listing(4), "id": None},
            {**make_listing(5), "id": True},
            {**make_listing(6), "id": 12.5},
        ]
        harness = PlaywrightHarness([[make_response(payload=make_payload(items))]])
        client = harness.build_client()

        async with client:
            result = await client.search_listings("gta 5 ps4", 40.4, -3.7, 10)

        assert [item["id"] for item in result] == ["00123", "42"]

    @pytest.mark.asyncio
    async def test_multiple_pages_are_loaded_through_the_page(self) -> None:
        first = make_response(
            payload=make_payload([make_listing(1), make_listing(2)], next_page="opaque-token")
        )
        second = make_response(payload=make_payload([make_listing(3), make_listing(4)]))
        harness = PlaywrightHarness([[first], [second]])
        client = harness.build_client(max_pages=2)

        async with client:
            result = await client.search_listings("gta 5 ps4", 40.4, -3.7, 10)

        assert [item["id"] for item in result] == [
            "listing-1",
            "listing-2",
            "listing-3",
            "listing-4",
        ]
        harness.page.evaluate.assert_awaited_once_with(
            "window.scrollTo(0, document.body.scrollHeight)"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"data": {}},
            {"data": {"section": {}}},
            {"data": {"section": {"items": None}}},
            {
                "data": {"section": {"items": []}},
                "meta": {"next_page": True},
            },
        ],
    )
    async def test_malformed_first_page_fails_without_requesting_another_page(
        self,
        payload: dict[str, Any],
    ) -> None:
        harness = PlaywrightHarness([[make_response(payload=payload)]])
        client = harness.build_client(max_pages=2)

        with pytest.raises(WallapopSearchResponseError):
            async with client:
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

        harness.page.evaluate.assert_not_awaited()
        assert not client.is_open

    @pytest.mark.asyncio
    async def test_valid_empty_second_page_returns_previous_items(self) -> None:
        first = make_response(
            payload=make_payload(
                [make_listing(1), make_listing(2)],
                next_page="opaque-token",
            )
        )
        second = make_response(payload=make_payload([]))
        harness = PlaywrightHarness([[first], [second]])
        client = harness.build_client(max_pages=2)

        async with client:
            result = await client.search_listings("gta 5 ps4", 40.4, -3.7, 10)

        assert [item["id"] for item in result] == ["listing-1", "listing-2"]
        harness.page.evaluate.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "malformed_payload",
        [
            {},
            {"data": {}},
            {"data": {"section": {}}},
            {"data": {"section": {"items": {}}}},
        ],
    )
    async def test_malformed_second_page_discards_partial_results(
        self,
        malformed_payload: dict[str, Any],
    ) -> None:
        first = make_response(
            payload=make_payload(
                [make_listing(1), make_listing(2)],
                next_page="opaque-token",
            )
        )
        second = make_response(payload=malformed_payload)
        harness = PlaywrightHarness([[first], [second]])
        client = harness.build_client(max_pages=2)

        with pytest.raises(WallapopSearchResponseError):
            async with client:
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 10)

        harness.page.evaluate.assert_awaited_once()
        assert not client.is_open

    @pytest.mark.asyncio
    async def test_max_results_avoids_unneeded_malformed_second_page(self) -> None:
        first = make_response(
            payload=make_payload(
                [make_listing(1), make_listing(2)],
                next_page="opaque-token",
            )
        )
        unrequested = make_response(payload={})
        harness = PlaywrightHarness([[first], [unrequested]])
        client = harness.build_client(max_pages=2)

        async with client:
            result = await client.search_listings("gta 5 ps4", 40.4, -3.7, 2)

        assert [item["id"] for item in result] == ["listing-1", "listing-2"]
        harness.page.evaluate.assert_not_awaited()
        unrequested.json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_context_manager_closes_after_search_exception(self) -> None:
        harness = PlaywrightHarness([[make_response(status=500)]])
        client = harness.build_client()

        with pytest.raises(WallapopSearchHTTPError):
            async with client:
                await client.search_listings("gta 5 ps4", 40.4, -3.7, 5)

        assert not client.is_open
        harness.context.close.assert_awaited_once()
        harness.browser.close.assert_awaited_once()
