"""Canonical listing ID validation and exact identity preservation."""

from collections.abc import Callable
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.interfaces.price_dataset_builder import PriceObservation
from domain.listing_id import validate_listing_id
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.marketplaces.wallapop.listing_id import (
    normalize_wallapop_listing_id,
)


def _game() -> DetectedGame:
    return DetectedGame(
        "Grand Theft Auto V",
        "GTA V",
        Platform.PS4,
        1.0,
        DetectionMethod.ALIAS_MATCH,
    )


def _candidate(identifier: Any) -> CandidateListing:
    return CandidateListing(identifier, "GTA V", "", Decimal("10"), "EUR", "url")


def _comparable(identifier: Any) -> ComparableListing:
    return ComparableListing(
        identifier,
        "GTA V",
        "",
        Decimal("10"),
        "EUR",
        _game(),
        "url",
    )


def _observation(identifier: Any) -> PriceObservation:
    return PriceObservation(
        Decimal("10"),
        "EUR",
        identifier,
        "GTA V",
        Platform.PS4,
        "wallapop",
        {},
    )


VALID_IDS = ("1", "00123", "abc", "ABC", "abc-123", "abc_123", "item:123")
INVALID_STRING_IDS = ("", " ", "   ", " 123", "123 ", "\t123", "123\n")
INVALID_TYPED_IDS = (None, 123, 12.3, True, False)


@pytest.mark.parametrize("factory", [_candidate, _comparable, _observation])
@pytest.mark.parametrize("identifier", VALID_IDS)
def test_canonical_models_preserve_valid_opaque_ids(
    factory: Callable[[Any], object], identifier: str
) -> None:
    model = factory(identifier)

    assert asdict(model)["listing_id"] == identifier


@pytest.mark.parametrize("factory", [_candidate, _comparable, _observation])
@pytest.mark.parametrize("identifier", INVALID_STRING_IDS)
def test_canonical_models_reject_empty_or_untrimmed_ids(
    factory: Callable[[Any], object], identifier: str
) -> None:
    with pytest.raises(ValueError, match="listing_id"):
        factory(identifier)


@pytest.mark.parametrize("factory", [_candidate, _comparable, _observation])
@pytest.mark.parametrize("identifier", INVALID_TYPED_IDS)
def test_canonical_models_reject_non_string_ids(
    factory: Callable[[Any], object], identifier: object
) -> None:
    with pytest.raises(TypeError, match="listing_id must be a string"):
        factory(identifier)


def test_validator_returns_the_exact_string_without_normalization() -> None:
    assert validate_listing_id("00123") == "00123"
    assert validate_listing_id("AbC-123") == "AbC-123"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("123", "123"),
        (" 123 ", "123"),
        (123, "123"),
        ("00123", "00123"),
        ("ABC", "ABC"),
        ("", None),
        ("   ", None),
        (None, None),
        (True, None),
        (False, None),
        (123.0, None),
    ],
)
def test_wallapop_boundary_normalizes_only_confirmed_formats(
    raw: object, expected: str | None
) -> None:
    assert normalize_wallapop_listing_id(raw) == expected


def test_deduplication_keeps_leading_zero_case_and_punctuation_distinct() -> None:
    comparables = [
        _comparable("00123"),
        _comparable("00123"),
        _comparable("123"),
        _comparable("ABC"),
        _comparable("abc"),
        _comparable("item-1"),
        _comparable("item_1"),
    ]

    dataset = DefaultPriceDatasetBuilder().build(comparables, "EUR")

    assert [item.listing_id for item in dataset.observations] == [
        "00123",
        "123",
        "ABC",
        "abc",
        "item-1",
        "item_1",
    ]
