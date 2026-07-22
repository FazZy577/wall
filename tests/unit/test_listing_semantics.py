"""Nominal and typed boundaries between candidates and comparables."""

from typing import get_type_hints
from unittest.mock import Mock

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    IArbitrageOpportunityDetector,
)
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from domain.interfaces.opportunity_scanner import IOpportunityScanner
from domain.interfaces.price_collector import ComparableListing, IPriceCollector
from domain.interfaces.price_dataset_builder import InvalidComparableListingError
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.scanners.default_opportunity_scanner import DefaultOpportunityScanner


def _game(platform: Platform = Platform.PS4) -> DetectedGame:
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="GTA V",
        platform=platform,
        confidence=1.0,
        detection_method=DetectionMethod.ALIAS_MATCH,
    )


def _candidate(identifier: str = "candidate") -> CandidateListing:
    return CandidateListing(
        listing_id=identifier,
        title="Lote PS3 PS4 PS5",
        description="GTA V y otros juegos",
        price=30.0,
        currency="EUR",
        url=f"https://example.test/{identifier}",
        raw_listing={"candidate": identifier},
    )


def test_candidate_and_comparable_are_nominally_unrelated() -> None:
    candidate = _candidate()
    comparable = ComparableListing(
        listing_id="comparable",
        title="GTA V PS4",
        description="",
        price=15.0,
        currency="EUR",
        detected_game=_game(),
        url="https://example.test/comparable",
    )

    assert type(candidate) is CandidateListing
    assert type(comparable) is ComparableListing
    assert not isinstance(candidate, ComparableListing)
    assert not isinstance(comparable, CandidateListing)
    assert not issubclass(CandidateListing, ComparableListing)
    assert not issubclass(ComparableListing, CandidateListing)


def test_candidate_has_no_single_platform_requirement() -> None:
    candidate = _candidate()
    detected_games = [_game(Platform.PS4), _game(Platform.PS5)]

    assert not hasattr(candidate, "platform")
    assert [game.platform for game in detected_games] == [Platform.PS4, Platform.PS5]


def test_dataset_builder_rejects_candidate_as_market_observation() -> None:
    with pytest.raises(
        InvalidComparableListingError,
        match="CandidateListing cannot be used as a market comparable",
    ):
        DefaultPriceDatasetBuilder().build([_candidate()])


def test_candidate_is_rejected_even_when_mixed_with_valid_comparables() -> None:
    comparable = ComparableListing(
        listing_id="comparable",
        title="GTA V PS4",
        description="",
        price=15.0,
        currency="EUR",
        detected_game=_game(),
        url="https://example.test/comparable",
    )

    with pytest.raises(InvalidComparableListingError):
        DefaultPriceDatasetBuilder().build([comparable, _candidate()])


def test_public_type_hints_enforce_listing_boundaries() -> None:
    scanner_single = get_type_hints(IOpportunityScanner.scan_listing)
    scanner_multiple = get_type_hints(IOpportunityScanner.scan_multiple)
    detector = get_type_hints(IArbitrageOpportunityDetector.detect)
    opportunity = get_type_hints(ArbitrageOpportunity)
    collector = get_type_hints(IPriceCollector.collect_comparables)

    assert scanner_single["listing"] is CandidateListing
    assert scanner_multiple["listings"] == list[CandidateListing]
    assert detector["listing"] is CandidateListing
    assert opportunity["listing"] is CandidateListing
    assert collector["return"] == list[ComparableListing]


def test_scanner_detects_games_from_candidate_text_without_candidate_platform() -> None:
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=Mock(),
        dataset_builder=Mock(),
        statistics=Mock(),
        outlier_removal=Mock(),
        market_estimator=Mock(),
        arbitrage_detector=Mock(),
    )
    scanner._run_async = Mock(return_value=[])
    scanner.dataset_builder.build.return_value = Mock(sample_size=0)
    candidate = _candidate()

    scanner.scan_listing(candidate)

    text = game_detector.detect_games.call_args.args[0]
    assert text.title == candidate.title
    assert text.description == candidate.description
    assert not hasattr(candidate, "platform")
