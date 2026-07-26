"""Canonical candidate-search boundary for normalized Wallapop items."""

import asyncio
import logging
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.candidate_search import (
    CandidateItemFailure,
    CandidateItemFailureKind,
    CandidateSearchResult,
    ICandidateSearch,
    SearchQuery,
)
from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.marketplaces.wallapop.adapter import (
    WallapopCandidateSearchAdapter,
)


def _query(**changes: object) -> SearchQuery:
    values: dict[str, object] = {
        "keywords": "lote videojuegos",
        "latitude": 40.4168,
        "longitude": -3.7038,
        "max_results": 20,
    }
    values.update(changes)
    return SearchQuery(**values)  # type: ignore[arg-type]


def _raw(
    identifier: object = "listing-1",
    *,
    title: object = "Lote GTA V y RDR2",
    description: object = "Juegos de PS4",
    price: object = 25.5,
    currency: object = "EUR",
    web_slug: object = "lote-gta-v-rdr2-1",
) -> dict[str, Any]:
    return {
        "id": identifier,
        "title": title,
        "description": description,
        "price": price,
        "currency": currency,
        "web_slug": web_slug,
        "images": [{"url": "https://cdn.example.test/image.jpg"}],
    }


def _adapter(return_value: object) -> tuple[WallapopCandidateSearchAdapter, Mock]:
    marketplace_search = Mock(spec=IMarketplaceSearch)
    marketplace_search.search_listings = AsyncMock(return_value=return_value)
    return WallapopCandidateSearchAdapter(marketplace_search), marketplace_search


@pytest.mark.asyncio
async def test_realistic_normalized_item_becomes_canonical_candidate() -> None:
    raw_item = _raw()
    adapter, _ = _adapter([raw_item])

    result = await adapter.search_candidates(_query())

    assert isinstance(adapter, ICandidateSearch)
    assert result.total_items_received == 1
    assert result.failures == ()
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert type(candidate) is CandidateListing
    assert candidate.listing_id == "listing-1"
    assert candidate.title == "Lote GTA V y RDR2"
    assert candidate.description == "Juegos de PS4"
    assert candidate.price == Decimal("25.5")
    assert candidate.currency == "EUR"
    assert candidate.url == "https://es.wallapop.com/item/lote-gta-v-rdr2-1"
    assert candidate.raw_listing == raw_item
    assert candidate.raw_listing is not raw_item


@pytest.mark.asyncio
async def test_empty_search_is_a_successful_empty_result() -> None:
    adapter, _ = _adapter([])
    query = _query()

    result = await adapter.search_candidates(query)

    assert result == CandidateSearchResult(query, (), (), 0)


@pytest.mark.asyncio
async def test_valid_candidates_preserve_source_order() -> None:
    adapter, _ = _adapter(
        [
            _raw("third", price=30),
            _raw("first", price=10),
            _raw("second", price=20),
        ]
    )

    result = await adapter.search_candidates(_query())

    assert [candidate.listing_id for candidate in result.candidates] == [
        "third",
        "first",
        "second",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_item", "expected_type"),
    [
        (None, "NoneType"),
        ("invalid", "str"),
        (123, "int"),
        ([], "list"),
    ],
)
async def test_non_dict_item_is_structured_and_warned_safely(
    invalid_item: object,
    expected_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, _ = _adapter([invalid_item])

    with caplog.at_level(logging.WARNING):
        result = await adapter.search_candidates(_query())

    assert result.candidates == ()
    assert result.failures == (
        CandidateItemFailure(
            item_index=0,
            kind=CandidateItemFailureKind.INVALID_RAW_ITEM,
            reason="Marketplace search item is not an object",
            listing_id=None,
            error_message=None,
        ),
    )
    assert (
        f"Ignoring malformed candidate item at index 0: type={expected_type}"
        in caplog.text
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_id",
    [None, "", "   ", True, False, 1.5],
)
async def test_missing_empty_or_invalid_id_rejects_candidate(
    invalid_id: object,
) -> None:
    adapter, _ = _adapter([_raw(invalid_id)])

    result = await adapter.search_candidates(_query())

    assert result.candidates == ()
    assert result.failures[0].kind is CandidateItemFailureKind.INVALID_CANDIDATE
    assert result.failures[0].listing_id is None


@pytest.mark.asyncio
async def test_valid_external_id_is_normalized_before_candidate_construction() -> None:
    adapter, _ = _adapter([_raw(" 00123 ")])

    result = await adapter.search_candidates(_query())

    assert result.candidates[0].listing_id == "00123"


@pytest.mark.asyncio
async def test_missing_title_follows_candidate_listing_validation() -> None:
    raw_item = _raw()
    del raw_item["title"]
    adapter, _ = _adapter([raw_item])

    result = await adapter.search_candidates(_query())

    assert result.candidates == ()
    assert result.failures[0].listing_id == "listing-1"
    assert result.failures[0].kind is CandidateItemFailureKind.INVALID_CANDIDATE
    assert result.failures[0].error_message == "title must not be empty"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_price",
    [None, "invalid", Decimal("NaN"), Decimal("Infinity"), float("nan"), float("inf")],
)
async def test_missing_invalid_or_non_finite_price_rejects_candidate(
    invalid_price: object,
) -> None:
    adapter, _ = _adapter([_raw(price=invalid_price)])

    result = await adapter.search_candidates(_query())

    assert result.candidates == ()
    assert result.failures[0].kind is CandidateItemFailureKind.INVALID_CANDIDATE


@pytest.mark.asyncio
async def test_zero_price_is_valid_under_candidate_listing_semantics() -> None:
    adapter, _ = _adapter([_raw(price=0)])

    result = await adapter.search_candidates(_query())

    assert result.candidates[0].price == Decimal("0")
    assert result.failures == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_currency", [None, "", "EU", "EURO", 123])
async def test_missing_or_invalid_currency_rejects_candidate(
    invalid_currency: object,
) -> None:
    adapter, _ = _adapter([_raw(currency=invalid_currency)])

    result = await adapter.search_candidates(_query())

    assert result.candidates == ()
    assert result.failures[0].kind is CandidateItemFailureKind.INVALID_CANDIDATE


@pytest.mark.asyncio
async def test_currency_is_normalized_without_assuming_eur() -> None:
    adapter, _ = _adapter(
        [
            _raw("eur", currency=" eur "),
            _raw("usd", currency=" usd "),
        ]
    )

    result = await adapter.search_candidates(_query())

    assert [candidate.currency for candidate in result.candidates] == ["EUR", "USD"]


@pytest.mark.asyncio
async def test_missing_url_is_valid_and_remains_empty() -> None:
    raw_item = _raw()
    del raw_item["web_slug"]
    adapter, _ = _adapter([raw_item])

    result = await adapter.search_candidates(_query())

    assert result.candidates[0].url == ""


@pytest.mark.asyncio
async def test_missing_description_is_valid_and_defaults_to_empty() -> None:
    raw_item = _raw()
    del raw_item["description"]
    adapter, _ = _adapter([raw_item])

    result = await adapter.search_candidates(_query())

    assert result.candidates[0].description == ""


@pytest.mark.asyncio
async def test_valid_invalid_valid_preserves_both_valid_candidates() -> None:
    adapter, _ = _adapter([_raw("A"), None, _raw("B")])

    result = await adapter.search_candidates(_query())

    assert [candidate.listing_id for candidate in result.candidates] == ["A", "B"]
    assert [failure.item_index for failure in result.failures] == [1]
    assert result.total_items_received == 3


@pytest.mark.asyncio
async def test_duplicate_candidates_are_not_removed() -> None:
    adapter, _ = _adapter([_raw("same", price=10), _raw("same", price=20)])

    result = await adapter.search_candidates(_query())

    assert [candidate.listing_id for candidate in result.candidates] == [
        "same",
        "same",
    ]
    assert [candidate.price for candidate in result.candidates] == [
        Decimal("10"),
        Decimal("20"),
    ]


@pytest.mark.asyncio
async def test_raw_dictionary_is_not_modified_and_candidate_keeps_own_copy() -> None:
    raw_item = _raw()
    original = dict(raw_item)
    adapter, _ = _adapter([raw_item])

    result = await adapter.search_candidates(_query())

    assert raw_item == original
    assert result.candidates[0].raw_listing == original
    assert result.candidates[0].raw_listing is not raw_item
    raw_item["title"] = "Changed later"
    assert result.candidates[0].raw_listing["title"] == "Lote GTA V y RDR2"


@pytest.mark.asyncio
async def test_result_does_not_alias_search_port_list() -> None:
    raw_items = [_raw("A")]
    adapter, _ = _adapter(raw_items)

    result = await adapter.search_candidates(_query())
    raw_items.append(_raw("B"))

    assert [candidate.listing_id for candidate in result.candidates] == ["A"]
    assert result.total_items_received == 1


def test_result_collections_are_tuple_snapshots_of_mutable_inputs() -> None:
    candidates = [
        CandidateListing(
            "A",
            "GTA V",
            "",
            Decimal("10"),
            "EUR",
            "",
        )
    ]
    failures = [
        CandidateItemFailure(
            1,
            CandidateItemFailureKind.INVALID_RAW_ITEM,
            "invalid",
            None,
            None,
        )
    ]

    result = CandidateSearchResult(
        _query(),
        candidates,  # type: ignore[arg-type]
        failures,  # type: ignore[arg-type]
        2,
    )
    candidates.clear()
    failures.clear()

    assert isinstance(result.candidates, tuple)
    assert isinstance(result.failures, tuple)
    assert len(result.candidates) == 1
    assert len(result.failures) == 1


@pytest.mark.asyncio
async def test_search_port_is_awaited_exactly_once_with_query_values() -> None:
    adapter, marketplace_search = _adapter([])
    query = _query()

    await adapter.search_candidates(query)

    marketplace_search.search_listings.assert_awaited_once_with(
        keywords="lote videojuegos",
        latitude=40.4168,
        longitude=-3.7038,
        max_results=20,
    )


@pytest.mark.asyncio
async def test_technical_search_error_propagates_unchanged() -> None:
    error = RuntimeError("marketplace unavailable")
    adapter, marketplace_search = _adapter([])
    marketplace_search.search_listings.side_effect = error

    with pytest.raises(RuntimeError) as exc_info:
        await adapter.search_candidates(_query())

    assert exc_info.value is error


@pytest.mark.asyncio
async def test_cancellation_propagates_unchanged() -> None:
    cancellation = asyncio.CancelledError()
    adapter, marketplace_search = _adapter([])
    marketplace_search.search_listings.side_effect = cancellation

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await adapter.search_candidates(_query())

    assert exc_info.value is cancellation


@pytest.mark.asyncio
async def test_logging_survives_unprintable_conversion_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class UnprintableError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("cannot format")

    class BrokenGetDict(dict[str, object]):
        def get(self, key: str, default: object = None) -> object:
            raise UnprintableError()

    adapter, _ = _adapter([BrokenGetDict()])

    with caplog.at_level(logging.WARNING):
        result = await adapter.search_candidates(_query())

    assert result.candidates == ()
    assert result.failures[0].listing_id is None
    assert result.failures[0].error_message == "<unprintable UnprintableError>"
    assert "<unprintable UnprintableError>" in caplog.text


@pytest.mark.asyncio
async def test_second_call_has_no_candidates_or_failures_from_first_call() -> None:
    adapter, marketplace_search = _adapter([])
    marketplace_search.search_listings.side_effect = [
        [_raw("first"), None],
        [],
    ]

    first = await adapter.search_candidates(_query())
    second = await adapter.search_candidates(_query(keywords="second"))

    assert len(first.candidates) == len(first.failures) == 1
    assert second.candidates == ()
    assert second.failures == ()
    assert second.total_items_received == 0


def test_search_query_trims_only_outer_keyword_whitespace() -> None:
    query = _query(keywords="  GTA   V Ps4  ")

    assert query.keywords == "GTA   V Ps4"


@pytest.mark.parametrize("keywords", ["", " ", "\t\n"])
def test_search_query_rejects_empty_keywords(keywords: str) -> None:
    with pytest.raises(ValueError, match="keywords"):
        _query(keywords=keywords)


def test_search_query_rejects_non_string_keywords() -> None:
    with pytest.raises(TypeError, match="keywords"):
        _query(keywords=123)


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("latitude", float("nan"), ValueError),
        ("latitude", float("inf"), ValueError),
        ("latitude", -90.01, ValueError),
        ("latitude", 90.01, ValueError),
        ("latitude", True, TypeError),
        ("latitude", "40", TypeError),
        ("longitude", float("nan"), ValueError),
        ("longitude", float("-inf"), ValueError),
        ("longitude", -180.01, ValueError),
        ("longitude", 180.01, ValueError),
        ("longitude", False, TypeError),
        ("longitude", "-3", TypeError),
    ],
)
def test_search_query_rejects_invalid_coordinates(
    field: str,
    value: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type, match=field):
        _query(**{field: value})


@pytest.mark.parametrize("latitude", [-90.0, 90.0])
@pytest.mark.parametrize("longitude", [-180.0, 180.0])
def test_search_query_accepts_coordinate_boundaries(
    latitude: float,
    longitude: float,
) -> None:
    query = _query(latitude=latitude, longitude=longitude)

    assert query.latitude == latitude
    assert query.longitude == longitude


@pytest.mark.parametrize("max_results", [0, -1, 1.5, "1"])
def test_search_query_rejects_non_positive_or_non_integer_max_results(
    max_results: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="max_results"):
        _query(max_results=max_results)


@pytest.mark.parametrize("max_results", [True, False])
def test_search_query_explicitly_rejects_bool_max_results(
    max_results: bool,
) -> None:
    with pytest.raises(TypeError, match="max_results"):
        _query(max_results=max_results)


def test_search_query_and_result_contracts_are_immutable() -> None:
    query = _query()
    result = CandidateSearchResult(query, (), (), 0)

    with pytest.raises(FrozenInstanceError):
        query.keywords = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.total_items_received = 1  # type: ignore[misc]


@pytest.mark.parametrize("total", [-1, True, 1.5])
def test_candidate_search_result_rejects_invalid_total(total: object) -> None:
    with pytest.raises((TypeError, ValueError), match="total_items_received"):
        CandidateSearchResult(_query(), (), (), total)  # type: ignore[arg-type]
