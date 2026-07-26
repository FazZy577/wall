"""Tests for the shared already-detected candidate contract."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from application.interfaces.detected_candidate import DetectedCandidate
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform


def _listing() -> CandidateListing:
    return CandidateListing(
        "candidate-1",
        "GTA V and RDR2",
        "",
        Decimal("20"),
        "EUR",
        "https://example.test/candidate-1",
    )


def _game(name: str) -> DetectedGame:
    return DetectedGame(
        name,
        name,
        Platform.PS4,
        1.0,
        DetectionMethod.EXACT_MATCH,
    )


def test_detected_candidate_preserves_listing_and_snapshots_games() -> None:
    listing = _listing()
    games = [_game("GTA V"), _game("RDR2")]

    candidate = DetectedCandidate(listing, games)  # type: ignore[arg-type]
    games.clear()

    assert candidate.listing is listing
    assert isinstance(candidate.detected_games, tuple)
    assert [game.canonical_name for game in candidate.detected_games] == [
        "GTA V",
        "RDR2",
    ]


def test_detected_candidate_allows_empty_detection() -> None:
    candidate = DetectedCandidate(_listing(), ())

    assert candidate.detected_games == ()


def test_detected_candidate_preserves_duplicates_and_order() -> None:
    first = _game("GTA V")
    second = _game("RDR2")

    candidate = DetectedCandidate(_listing(), (first, second, first))

    assert candidate.detected_games == (first, second, first)


def test_detected_candidate_is_frozen() -> None:
    candidate = DetectedCandidate(_listing(), ())

    with pytest.raises(FrozenInstanceError):
        candidate.detected_games = ()  # type: ignore[misc]


def test_detected_candidate_requires_canonical_listing() -> None:
    with pytest.raises(TypeError, match="listing must be CandidateListing"):
        DetectedCandidate(object(), ())  # type: ignore[arg-type]
