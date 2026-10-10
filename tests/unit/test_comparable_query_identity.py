"""B05: search terms and provenance derive from identity, never seller spelling."""

from unittest.mock import AsyncMock, Mock

import pytest

from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.game_identity import GameIdentity
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from tests.game_fixtures import seed_identity


def game(name, alias="seller text"):
    return DetectedGame(name, alias, Platform.PS3, 1.0, DetectionMethod.EXACT_MATCH, seed_identity(name, Platform.PS3))


@pytest.mark.parametrize(
    "name",
    [
        "Grand Theft Auto IV",
        "Grand Theft Auto: San Andreas",
        "Call of Duty: Modern Warfare III",
        "Dark Souls II",
        "Uncharted 2: Among Thieves",
        "Future Adventure: Chapter IX",
    ],
)
@pytest.mark.parametrize("alias", ["gta v", "gta4", "", "untrusted short alias"])
def test_canonical_identity_survives_query_generation(name, alias):
    collector = WallapopPriceCollector(Mock(), Mock(), Mock())
    assert collector._generate_search_query(game(name, alias)) == f"{name} PS3"


@pytest.mark.asyncio
async def test_verified_fallback_records_exact_query_without_mutating_raw_listing():
    target = game("Grand Theft Auto IV")
    raw = {"id": "b05", "title": "GTA IV PS3", "description": "", "price": "20", "currency": "EUR"}
    market = AsyncMock()
    market.search_listings.side_effect = [[], [raw]]
    detector = FuzzyGameDetector(PackagedGameCatalog())
    product_filter = Mock()
    product_filter.is_valid_comparable.return_value = True
    aliases = {GameIdentity.from_game(target): ("GTA IV",)}
    collector = WallapopPriceCollector(
        market, detector, product_filter, verified_search_aliases=aliases
    )
    aliases.clear()
    results = await collector.collect_comparables(target, 40.4, -3.7)
    assert [call.kwargs["keywords"] for call in market.search_listings.call_args_list] == [
        "Grand Theft Auto IV PS3",
        "GTA IV PS3",
    ]
    assert results[0].source_query == "GTA IV PS3"
    assert "source_query" not in raw


@pytest.mark.asyncio
async def test_canonical_success_avoids_extra_queries_and_records_provenance():
    target = game("Grand Theft Auto IV")
    raw = {"id": "b05", "title": "GTA IV PS3", "price": "20", "currency": "EUR"}
    market, detector, product_filter = AsyncMock(), Mock(), Mock()
    market.search_listings.return_value = [raw]
    detector.detect_games.return_value = [target]
    product_filter.is_valid_comparable.return_value = True
    collector = WallapopPriceCollector(
        market,
        detector,
        product_filter,
        verified_search_aliases={GameIdentity.from_game(target): ("GTA IV",)},
    )
    results = await collector.collect_comparables(target, 40.4, -3.7)
    market.search_listings.assert_awaited_once()
    assert results[0].source_query == "Grand Theft Auto IV PS3"


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["GTA V", "GTA IV PS5", "GTA", "not a game"])
async def test_unverified_or_wrong_identity_alias_is_never_searched(alias):
    target = game("Grand Theft Auto IV")
    market = AsyncMock()
    market.search_listings.return_value = []
    collector = WallapopPriceCollector(
        market,
        FuzzyGameDetector(PackagedGameCatalog()),
        Mock(),
        verified_search_aliases={GameIdentity.from_game(target): (alias,)},
    )
    assert await collector.collect_comparables(target, 40.4, -3.7) == []
    market.search_listings.assert_awaited_once()
    assert market.search_listings.call_args.kwargs["keywords"] == "Grand Theft Auto IV PS3"


@pytest.mark.asyncio
async def test_duplicate_verified_aliases_do_not_repeat_searches():
    target = game("Grand Theft Auto IV")
    market = AsyncMock()
    market.search_listings.return_value = []
    collector = WallapopPriceCollector(
        market,
        FuzzyGameDetector(PackagedGameCatalog()),
        Mock(),
        verified_search_aliases={
            GameIdentity.from_game(target): (
                "Grand Theft Auto IV",
                "GTA IV",
                "gta iv",
                " GTA   IV PS3 ",
            ),
        },
    )
    assert await collector.collect_comparables(target, 40.4, -3.7) == []
    assert [call.kwargs["keywords"] for call in market.search_listings.call_args_list] == [
        "Grand Theft Auto IV PS3",
        "GTA IV PS3",
    ]
