"""B04: comparable identity and physical product composition."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.interfaces.comparable_filter import ComparableFilterInput
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.filters.rule_based_comparable_filter import RuleBasedComparableFilter
from tests.game_fixtures import seed_identity

pytestmark = pytest.mark.integration


def game(name, platform=Platform.PS5, alias=None):
    return DetectedGame(name, alias or name, platform, 1.0, DetectionMethod.EXACT_MATCH, seed_identity(name, platform))


@pytest.fixture(scope="module")
def comparable_filter():
    return RuleBasedComparableFilter()


@pytest.mark.parametrize(
    "name,platform,title,description,expected",
    [
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "", True),
        ("Grand Theft Auto IV", Platform.PS3, "GTA V PS3", "", False),
        ("Grand Theft Auto V", Platform.PS4, "GTA IV PS3", "", False),
        ("FIFA 23", Platform.PS4, "FIFA 23 PS4, 20 euros", "", True),
        ("FIFA 23", Platform.PS4, "FIFA 20 PS4", "", False),
        ("Elden Ring", Platform.PS5, "Elden Ring PS4", "", False),
        ("Elden Ring", Platform.PS5, "Elden Ring", "", False),
        ("Elden Ring", Platform.PS5, "Busco Elden Ring PS5", "", False),
        ("Elden Ring", Platform.PS5, "God of War Ragnarok PS5", "Cambio por Elden Ring PS5", False),
        ("Elden Ring", Platform.PS5, "Elden Ring + God of War Ragnarok PS5", "", False),
        ("Elden Ring", Platform.PS5, "Dos copias de Elden Ring PS5", "", False),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "Sin consola ni mando", True),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "También vendo mando por separado", True),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "Incluye mando", False),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5 digital", "", False),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "Físico, no digital", True),
        ("Elden Ring", Platform.PS5, "Elden Ring Deluxe Edition PS5", "", False),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "Solo caja", False),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "Solo disco", False),
        (
            "Elden Ring",
            Platform.PS5,
            "Elden Ring PS5",
            "Busco otro juego: God of War Ragnarok PS5",
            True,
        ),
        ("Elden Ring", Platform.PS5, "Elden Ring PS5", "Sin funda pero código digital", False),
    ],
)
def test_comparable_is_same_single_physical_product(
    comparable_filter, name, platform, title, description, expected
):
    listing = ComparableFilterInput(title, description, Decimal("20"))
    assert comparable_filter.is_valid_comparable(game(name, platform), listing) is expected


def test_supplied_detection_does_not_require_packaged_catalog(comparable_filter):
    target = game("Future Adventure: Code Collection")
    listing = ComparableFilterInput(
        "Future Adventure: Code Collection PS5", price=Decimal("20"), detected_games=(target,)
    )
    assert comparable_filter.is_valid_comparable(target, listing)


@pytest.mark.parametrize("title", ["Future Adventure PS4", "Future Adventure"])
def test_supplied_detection_cannot_override_missing_or_wrong_platform(comparable_filter, title):
    target = game("Future Adventure")
    listing = ComparableFilterInput(title, price=Decimal("20"), detected_games=(target,))
    assert not comparable_filter.is_valid_comparable(target, listing)


def test_empty_detection_is_authoritative(comparable_filter):
    assert not comparable_filter.is_valid_comparable(
        game("Elden Ring"), ComparableFilterInput("Elden Ring PS5", detected_games=())
    )


@pytest.mark.parametrize("title,description", [
    ("Busco: Elden Ring PS5", ""),
    ("Anuncio PS5", "Busco: Elden Ring"),
    ("Anuncio PS5", "No incluye: Elden Ring"),
    ("Elden Ring PS5", "Sin caja"),
    ("Elden Ring PS5", "Sin la caja"),
])
def test_incomplete_or_contextual_product_cannot_be_comparable(comparable_filter, title, description):
    assert not comparable_filter.is_valid_comparable(
        game("Elden Ring"), ComparableFilterInput(title, description, Decimal("20"))
    )


@pytest.mark.parametrize("title,expected", [
    ("Elden Ring PS5", True),
    ("Elden Ring + God of War Ragnarok PS5", False),
    ("Dos copias de Elden Ring PS5", False),
    ("Busco Elden Ring PS5", False),
])
def test_collector_passes_complete_detection_to_filter_once(title, expected):
    detector = Mock(wraps=FuzzyGameDetector(PackagedGameCatalog()))
    unused_detector = Mock()
    unused_detector.detect_games.side_effect = AssertionError("Must reuse collector evidence")
    collector = WallapopPriceCollector(Mock(), detector, RuleBasedComparableFilter(unused_detector))
    raw = {"id": "b04", "title": title, "description": "", "price": "20", "currency": "EUR"}
    result = collector._process_listing(raw, game("Elden Ring"))
    assert (result is not None) is expected
    detector.detect_games.assert_called_once()
    unused_detector.detect_games.assert_not_called()
