"""Regression coverage for overlapping titles through detection and classification."""

from decimal import Decimal

import pytest

from domain.entities.candidate_classification import CandidateDisposition
from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.interfaces.game_catalog import IGameCatalog
from domain.interfaces.game_detector import ListingText, Platform
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector


@pytest.fixture(scope="module")
def detector() -> FuzzyGameDetector:
    return FuzzyGameDetector(PackagedGameCatalog())


def _classify(detector: FuzzyGameDetector, title: str, description: str = ""):
    games = detector.detect_games(ListingText(title, description))
    listing = CandidateListing("b01", title, description, Decimal("55"), "EUR", "")
    return games, RuleBasedCandidateEligibilityPolicy().classify(listing, games)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Dark Souls II PS3", "Dark Souls II"),
        ("LittleBigPlanet 2 PS3", "LittleBigPlanet 2"),
        ("Dead Space 2 PS3", "Dead Space 2"),
        ("BioShock Infinite PS3", "BioShock Infinite"),
        ("God of War Ragnarok PS4", "God of War Ragnarök"),
        ("The Last of Us Part II PS4", "The Last of Us Part II"),
        ("Spider-Man: Miles Morales PS4", "Spider-Man: Miles Morales"),
        ("Spider-Man Miles Morales PS4", "Spider-Man: Miles Morales"),
        ("Call of Duty: Black Ops 6 PS5", "Call of Duty: Black Ops 6"),
        ("Call of Duty Black Ops 6 PS5", "Call of Duty: Black Ops 6"),
        ("Red Dead Redemption 2 Xbox Series", "Red Dead Redemption 2"),
    ],
)
def test_specific_title_is_one_game(detector, title, expected):
    games, result = _classify(detector, title)
    assert [game.canonical_name for game in games] == [expected]
    assert result.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL
    assert [game.canonical_name for game in result.included_games] == [expected]


@pytest.mark.integration
@pytest.mark.parametrize("separator", [" + ", " y ", ", ", "\n"])
def test_original_and_sequel_are_a_real_lot(detector, separator):
    games, result = _classify(detector, f"Lote Dark Souls{separator}Dark Souls II PS3")
    assert {game.canonical_name for game in games} == {"Dark Souls", "Dark Souls II"}
    assert result.disposition is CandidateDisposition.ELIGIBLE_LOT
    assert len(result.included_games) == 2


@pytest.mark.integration
def test_contextual_original_does_not_borrow_sequel_title(detector):
    _, result = _classify(detector, "Dark Souls II PS3", "Busco Dark Souls PS3")
    assert result.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL
    assert [game.canonical_name for game in result.included_games] == ["Dark Souls II"]


@pytest.mark.integration
def test_punctuated_title_keeps_exclusion_context(detector):
    _, result = _classify(detector, "Busco Call of Duty: Black Ops 6 PS5")
    assert not result.included_games
    assert result.disposition is CandidateDisposition.IGNORED


@pytest.mark.integration
def test_contextual_punctuated_title_does_not_add_a_product_platform(detector):
    _, result = _classify(
        detector, "Elden Ring PS5", "Busco Call of Duty: Black Ops 6 PS4"
    )
    assert result.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL
    assert [game.canonical_name for game in result.included_games] == ["Elden Ring"]


class _SyntheticCatalog(IGameCatalog):
    def list_games(self) -> tuple[GameCatalogEntry, ...]:
        return (
            GameCatalogEntry("Áurea: Voyage", Platform.PS5, ()),
            GameCatalogEntry("Áurea: Voyage, Chapter II", Platform.PS5, ()),
        )


@pytest.mark.integration
@pytest.mark.parametrize("description_only", [False, True])
@pytest.mark.parametrize("context", ["", "Busco ", "No incluye "])
def test_punctuation_and_overlaps_work_for_arbitrary_catalog_entries(
    description_only, context
):
    detector = FuzzyGameDetector(_SyntheticCatalog())
    text = f"{context}ÁUREA:  Voyage, Chapter II PS5"
    title, description = ("Anuncio PS5", text) if description_only else (text, "")
    games, result = _classify(detector, title, description)
    assert [game.canonical_name for game in games] == ["Áurea: Voyage, Chapter II"]
    if context:
        assert not result.included_games
        assert result.disposition is CandidateDisposition.IGNORED
    else:
        assert result.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL
        assert len(result.included_games) == 1
