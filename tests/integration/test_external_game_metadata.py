"""B09: external confirmation, atomic evidence, restart and provider isolation."""

import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.game_metadata import (
    GameMetadata,
    IGameMetadataProvider,
    MetadataUnavailable,
)
from application.interfaces.search_orchestrator import SearchPlan
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import Platform
from domain.entities.game_identity import GameIdentity
from domain.entities.game_record import GameRecord, IdentityStatus, ReleaseIdentity
from domain.interfaces.game_detector import ListingText
from infrastructure.catalogs.sqlite_game_registry import SqliteGameRegistry
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.metadata.igdb import IgdbMetadataProvider
from infrastructure.metadata.resolver import VerifiedMetadataResolver
from presentation.cli.composition import build_operational_runtime
from presentation.cli.config import AppConfig, MetadataConfig, PersistenceConfig
from tests.integration.test_observation_persistence import config_at, marketplace_mock, rows

pytestmark = pytest.mark.integration


def metadata(**changes):
    return replace(GameMetadata("igdb", "424242", "Zyxqv Odyssey IX: Beyond Stars",
                                (Platform.PS5,), ("Odisea Zyxqv IX: Mas Alla",),
                                "main game", source_url="https://www.igdb.com/games/zyxqv"), **changes)


def listing(title="Zyxqv Odyssey IX: Beyond Stars PS5", description="Juego fisico completo"):
    return CandidateListing("new-game", title, description, Decimal("20"), "EUR", "")


def resolver_at(tmp_path, candidates=None):
    store = SqliteGameRegistry(tmp_path / "registry.sqlite3")
    detector = FuzzyGameDetector(store)
    provider = AsyncMock(spec=IGameMetadataProvider)
    provider.search.return_value = (metadata(),) if candidates is None else candidates
    resolver = VerifiedMetadataResolver(provider, store, detector, RuleBasedCandidateEligibilityPolicy())
    return resolver, store, detector, provider


@pytest.mark.asyncio
async def test_empty_registry_external_identity_survives_restart_and_has_provenance(tmp_path):
    resolver, store, detector, provider = resolver_at(tmp_path)
    item = listing()
    text = ListingText(item.title, item.description)
    assert detector.detect_games(text) == []
    assert await resolver.resolve(item)
    first = detector.detect_games(text)[0]
    second = FuzzyGameDetector(SqliteGameRegistry(store.database_path)).detect_games(text)[0]
    assert GameIdentity.from_game(first) == GameIdentity.from_game(second)
    assert second.release_identity.game_id == store.get_game(second.release_identity.game_id).game_id
    assert rows(store.database_path, "SELECT provider, external_id FROM external_game_references") == [("igdb", "424242")]
    evidence = rows(store.database_path, "SELECT query,status,candidates_json,release_id FROM metadata_resolutions")[0]
    assert evidence[:2] == ("zyxqv odyssey ix beyond stars", "confirmed")
    assert json.loads(evidence[2])[0]["source_url"] == metadata().source_url
    assert evidence[3] == first.release_identity.release_id
    provider.search.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", [
    metadata(name="Zyxqv Odyssey X: Beyond Stars", aliases=()),
    metadata(name="Zyxqv Odyssey IX", aliases=()),
    metadata(platforms=(Platform.PS4,)),
    metadata(content_type="dlc_addon"), metadata(content_type="expansion"),
    metadata(content_type="bundle"), metadata(content_type="unknown"),
    metadata(edition=True),
])
async def test_incompatible_metadata_cannot_confirm(tmp_path, candidate):
    resolver, store, detector, _ = resolver_at(tmp_path, (candidate,))
    assert not await resolver.resolve(listing())
    assert store.list_games() == ()
    assert detector.detect_games(ListingText(listing().title, "")) == []
    assert rows(store.database_path, "SELECT status FROM metadata_resolutions")[0][0] != "confirmed"


@pytest.mark.asyncio
@pytest.mark.parametrize("title,description", [
    ("Zyxqv Odyssey IX PS5", ""),
    ("Zyxqv Odyssey IX Beyond Stars deluxe PS5", ""),
    ("Zyxqv Odyssey IX Beyond Stars PS5 + Otro Juego", ""),
    ("Zyxqv Odyssey IX Beyond Stars PS5", "codigo digital"),
    ("Zyxqv Odyssey IX Beyond Stars PS5", "solo caja sin juego"),
    ("Zyxqv Odyssey IX Beyond Stars PS5", "busco este juego"),
    ("Zyxqv Odyssey IX Beyond Stars PS5", "20 euros cada uno"),
    ("Zyxqv Odyssey IX Beyond Stars", ""),
    ("Zyxqv Odyssey IX Beyond Stars PS5 PS4", ""),
])
async def test_seller_text_cannot_change_the_confirmed_identity(tmp_path, title, description):
    resolver, store, _, _ = resolver_at(tmp_path)
    assert not await resolver.resolve(listing(title, description))
    assert store.list_games() == ()


@pytest.mark.asyncio
async def test_ambiguous_provider_hits_remain_pending(tmp_path):
    resolver, store, _, _ = resolver_at(tmp_path, (metadata(), metadata(external_id="other")))
    assert not await resolver.resolve(listing())
    assert rows(store.database_path, "SELECT status FROM metadata_resolutions") == [("ambiguous",)]


@pytest.mark.asyncio
async def test_verified_alias_is_saved_but_selling_prefix_is_not(tmp_path):
    resolver, store, detector, _ = resolver_at(tmp_path)
    assert await resolver.resolve(listing("Vendo Odisea Zyxqv IX: Mas Alla PS5"))
    game = store.get_game(store.list_games()[0].release_identity.game_id)
    assert game.aliases == metadata().aliases
    assert detector.detect_games(ListingText("Odisea Zyxqv IX Mas Alla PS5", ""))[0].canonical_name == metadata().name


@pytest.mark.asyncio
async def test_identity_and_evidence_rollback_together(tmp_path):
    resolver, store, detector, _ = resolver_at(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("""CREATE TRIGGER reject_metadata BEFORE INSERT ON metadata_resolutions
            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        await resolver.resolve(listing())
    assert store.list_games() == ()
    assert rows(store.database_path, "SELECT * FROM external_game_references") == []
    assert detector.detect_games(ListingText(listing().title, "")) == []


def raw_game(**changes):
    return {"id": 424242, "name": metadata().name, "platforms": [{"name": "PlayStation 5"}],
            "game_type": {"type": "Main Game"}, "url": metadata().source_url, **changes}


@pytest.mark.asyncio
async def test_real_adapter_oauth_query_escape_token_reuse_and_platform_mapping():
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.host == "id.twitch.tv":
            assert b"client_secret=private-secret" in request.content
            assert "private-secret" not in str(request.url)
            return httpx.Response(200, json={"access_token": "private-token", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer private-token"
        return httpx.Response(200, json=[raw_game(platforms=[{"name": "Nintendo Switch 2"}])])

    provider = IgdbMetadataProvider("client-id", "private-secret", httpx.MockTransport(respond))
    result = await provider.search('Name "; fields *;')
    await provider.search("Another")
    assert len(requests) == 3
    assert result[0].platforms == (Platform.SWITCH_2,)
    assert requests[1].content.decode().startswith('search "Name \\"; fields *;";')


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {}, [raw_game(id="wrong")], [raw_game(game_type=None)],
    [raw_game(platforms=[{}])], [raw_game(name="")], [raw_game()] * 50,
])
async def test_malformed_or_truncated_provider_data_is_not_a_partial_success(payload):
    def respond(request):
        if request.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "secret", "expires_in": 3600})
        return httpx.Response(200, json=payload)
    with pytest.raises(MetadataUnavailable):
        await IgdbMetadataProvider("id", "secret", httpx.MockTransport(respond)).search("Name")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500])
async def test_provider_errors_are_sanitized(status):
    def respond(request):
        return httpx.Response(status, text="secret-leaked-by-provider")
    with pytest.raises(MetadataUnavailable) as error:
        await IgdbMetadataProvider("id", "secret", httpx.MockTransport(respond)).search("Name")
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_composed_pipeline_recognizes_new_games_or_keeps_pending_without_affecting_known(tmp_path, monkeypatch, fails):
    config = config_at(tmp_path).model_copy(update={"metadata": MetadataConfig(enabled=True)})
    provider = AsyncMock(spec=IGameMetadataProvider)
    if fails:
        provider.search.side_effect = MetadataUnavailable("unavailable")
    else:
        provider.search.return_value = (metadata(),)
    monkeypatch.setattr("presentation.cli.composition.IgdbMetadataProvider", lambda *args: provider)
    market = marketplace_mock()
    market.search_listings.side_effect = [[
        {"id": "new", "title": listing().title, "description": "", "price": "20", "currency": "EUR"},
        {"id": "known", "title": "Elden Ring PS5", "description": "", "price": "20", "currency": "EUR"},
    ], [], []]
    plan = SearchPlan((SearchQuery("juegos PS5", 40.4, -3.7, 10),))
    result = await build_operational_runtime(config, market).search_orchestrator.execute(plan)
    provider.search.assert_awaited_once()
    states = rows(config.persistence.database_path, """SELECT o.listing_id,i.status FROM listing_observations o
        JOIN listing_identifications i ON o.observation_id=i.observation_id ORDER BY o.listing_id""")
    assert states == [("known", "resolved"), ("new", "unknown" if fails else "resolved")]
    if fails:
        assert [f.kind.value for f in result.routing_failures] == ["metadata_resolution_error"]
    else:
        assert not result.routing_failures
        provider.search.reset_mock()
        market.search_listings.side_effect = [[
            {"id": "new", "title": listing().title, "description": "", "price": "20", "currency": "EUR"},
        ], []]
        await build_operational_runtime(config, market).search_orchestrator.execute(plan)
        provider.search.assert_not_awaited()


def test_metadata_is_opt_in_and_requires_persistence(tmp_path):
    config = config_at(tmp_path)
    assert not config.metadata.enabled
    values = {name: getattr(config, name) for name in type(config).model_fields}
    values.update(metadata=MetadataConfig(enabled=True), persistence=PersistenceConfig())
    with pytest.raises(ValidationError, match="metadata requires persistence"):
        AppConfig(**values)


@pytest.mark.asyncio
async def test_same_provider_identity_is_reused_across_platforms_and_repeated_attempts(tmp_path):
    candidate = metadata(platforms=(Platform.PS5, Platform.PS4))
    resolver, store, detector, _ = resolver_at(tmp_path, (candidate,))
    assert await resolver.resolve(listing())
    original = store.list_games()[0].release_identity
    assert await resolver.resolve(listing())
    assert store.list_games()[0].release_identity == original
    assert await resolver.resolve(listing(listing().title.replace("PS5", "PS4")))
    entries = store.list_games()
    assert len(entries) == 2
    assert {e.release_identity.game_id for e in entries} == {original.game_id}
    assert len({e.release_identity.release_id for e in entries}) == 2
    assert detector.detect_games(ListingText(listing().title, ""))[0].release_identity == original


@pytest.mark.asyncio
@pytest.mark.parametrize("alias_collision", [False, True])
async def test_local_name_or_alias_collision_never_merges_by_name(tmp_path, alias_collision):
    resolver, store, _, _ = resolver_at(tmp_path)
    store.save_game(GameRecord("local-id", "Other Name" if alias_collision else metadata().name,
                              status=IdentityStatus.CONFIRMED))
    store.save_release(ReleaseIdentity("local-id", "local-release", Platform.PS4),
                       (metadata().name,) if alias_collision else ())
    assert not await resolver.resolve(listing())
    assert rows(store.database_path, "SELECT game_id FROM games") == [("local-id",)]
    assert rows(store.database_path, "SELECT status FROM metadata_resolutions") == [("ambiguous",)]
    assert rows(store.database_path, "SELECT * FROM external_game_references") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [Platform.SWITCH, Platform.SWITCH_2])
async def test_switch_2_cannot_be_confirmed_as_switch(tmp_path, supported):
    resolver, store, _, _ = resolver_at(tmp_path, (metadata(platforms=(supported,)),))
    resolved = await resolver.resolve(listing(listing().title.replace("PS5", "Switch 2")))
    assert resolved is (supported is Platform.SWITCH_2)
    if resolved:
        assert store.list_games()[0].platform is Platform.SWITCH_2


@pytest.mark.asyncio
async def test_timeout_is_safe_and_cancellation_propagates():
    def timeout(request):
        raise httpx.ReadTimeout("private-secret", request=request)
    with pytest.raises(MetadataUnavailable) as error:
        await IgdbMetadataProvider("id", "secret", httpx.MockTransport(timeout)).search("Name")
    assert "secret" not in str(error.value)

    async def cancelled(request):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await IgdbMetadataProvider("id", "secret", httpx.MockTransport(cancelled)).search("Name")


@pytest.mark.asyncio
async def test_missing_credentials_do_not_start_http_requests():
    def unexpected(request):
        pytest.fail("Missing credentials must not reach network")
    with pytest.raises(MetadataUnavailable, match="not configured"):
        await IgdbMetadataProvider("", "", httpx.MockTransport(unexpected)).search("Name")


@pytest.mark.asyncio
async def test_expired_token_is_refreshed_on_next_attempt_after_unauthorized_response():
    auth_count = 0
    game_count = 0

    def respond(request):
        nonlocal auth_count, game_count
        if request.url.host == "id.twitch.tv":
            auth_count += 1
            return httpx.Response(200, json={"access_token": f"token-{auth_count}", "expires_in": 3600})
        game_count += 1
        if game_count == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer token-2"
        return httpx.Response(200, json=[raw_game()])

    provider = IgdbMetadataProvider("id", "secret", httpx.MockTransport(respond))
    with pytest.raises(MetadataUnavailable):
        await provider.search("Name")
    assert (await provider.search("Name"))[0].name == metadata().name
    assert auth_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_new_subtitle_is_not_priced_as_the_known_shorter_game(tmp_path, monkeypatch, fails):
    config = config_at(tmp_path).model_copy(update={"metadata": MetadataConfig(enabled=True)})
    new_name = "Elden Ring: Zyxqv Chronicles"
    provider = AsyncMock(spec=IGameMetadataProvider)
    if fails:
        provider.search.side_effect = MetadataUnavailable("down")
    else:
        provider.search.return_value = (metadata(name=new_name, aliases=()),)
    monkeypatch.setattr("presentation.cli.composition.IgdbMetadataProvider", lambda *args: provider)
    market = marketplace_mock()
    market.search_listings.side_effect = [[{
        "id": "new", "title": f"{new_name} PS5", "description": "", "price": "20", "currency": "EUR",
    }], []]
    result = await build_operational_runtime(config, market).search_orchestrator.execute(
        SearchPlan((SearchQuery("juegos PS5", 40.4, -3.7, 10),))
    )
    provider.search.assert_awaited_once_with("elden ring zyxqv chronicles")
    if fails:
        assert len(result.ambiguous_candidates) == 1
        assert market.search_listings.await_count == 1  # No valuation of the shorter game.
    else:
        assert not result.routing_failures
        stored = SqliteGameRegistry(config.persistence.database_path)
        new_game = next(entry for entry in stored.list_games() if entry.canonical_name == new_name)
        original = next(entry for entry in stored.list_games() if entry.canonical_name == "Elden Ring" and entry.platform is Platform.PS5)
        assert new_game.release_identity.game_id != original.release_identity.game_id
        assert market.search_listings.await_count == 2
