"""B02: game lots and contextual hardware must not be treated as consoles."""

from decimal import Decimal

import pytest

from domain.entities.candidate_classification import CandidateDisposition
from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.game_detector import ListingText
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector


@pytest.fixture(scope="module")
def detector():
    return FuzzyGameDetector(PackagedGameCatalog())


def classify(detector, title, description=""):
    listing = CandidateListing("b02", title, description, Decimal("20"), "EUR", "")
    games = detector.detect_games(ListingText(title, description))
    return RuleBasedCandidateEligibilityPolicy().classify(listing, games)


@pytest.mark.parametrize("title", [
    "Lote de juegos PS4", "Juegos para PS4", "Pack de juegos PS4",
    "2 juegos PS4", "Juegos PS4 Pro", "Juegos para PS4 Slim",
])
def test_game_lots_are_not_hardware(detector, title):
    result = classify(detector, title, "Incluye GTA V y RDR2")
    assert result.disposition is CandidateDisposition.ELIGIBLE_LOT
    assert len(result.included_games) == 2


@pytest.mark.parametrize("description", [
    "Sin consola", "No incluye consola", "Consola no incluida",
    "Juego para consola PS4", "Probado en consola PS4",
    "Compatible con consola PS4", "Busco una consola PS4",
    "Cambio por consola PS4", "También vendo consola PS4 por separado",
    "Compatible con mando PS4", "Mando PS4 no incluido",
    "Busco un mando", "También vendo mando por separado",
    "Sin consola ni mando", "No incluye consola ni mando",
    "GTA V compatible con PS4 Slim", "Sin mando. Sin consola",
])
def test_contextual_products_do_not_discard_game(detector, description):
    result = classify(detector, "GTA V PS4", description)
    assert result.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL


@pytest.mark.parametrize("title,description", [
    ("PS4 + juegos", "Incluye GTA V"),
    ("PS4 negra + GTA V", ""),
    ("PS4 500GB + GTA V", ""),
    ("Consola PS4 y GTA V", ""),
    ("GTA V PS4", "Incluye consola PS4"),
    ("GTA V PS4", "Incluye mando"),
    ("GTA V PS4", "Sin mando. Incluye consola"),
    ("GTA V PS4", "Sin consola. Incluye mando"),
    ("GTA V PS4", "Mando no incluido. Incluye otro mando"),
    ("GTA V PS4", "Sin mando pero incluye consola"),
    ("GTA V + PS4 500GB", ""),
    ("GTA V con PS4 negra", ""),
    ("GTA V PS4", "Incluye PS4 Slim"),
])
def test_included_hardware_stays_excluded(detector, title, description):
    result = classify(detector, title, description)
    assert result.disposition is CandidateDisposition.IGNORED
    assert not result.included_games
