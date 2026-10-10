"""B10 retry cadence, bounded maintenance and catalog-free discovery."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from application.interfaces.game_metadata import (
    IGameMetadataProvider,
    MetadataDeferred,
    MetadataUnavailable,
)
from application.interfaces.listing_observation_recorder import ListingObservation
from application.interfaces.search_plan_generator import (
    SearchPlanGenerationRequest,
    SearchPlanGenerationStrategy,
)
from domain.entities.detected_game import Platform
from domain.entities.game_record import GameRecord, IdentityStatus, ReleaseIdentity
from domain.entities.search_coverage import MarketplaceSearchBatch, SearchCoverage
from domain.interfaces.game_detector import ListingText
from infrastructure.catalogs.sqlite_game_registry import SqliteGameRegistry
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.discovery.sqlite_catalog_discovery_recorder import (
    SqliteCatalogDiscoveryRecorder,
)
from infrastructure.metadata.resolver import VerifiedMetadataResolver
from infrastructure.metadata.scheduled_provider import ScheduledMetadataProvider
from presentation.cli.composition import build_operational_runtime
from presentation.cli.config import MetadataConfig
from tests.integration.test_external_game_metadata import listing, metadata
from tests.integration.test_observation_persistence import config_at, marketplace_mock, rows

pytestmark = pytest.mark.integration


class Clock:
    now = 1700000000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def setup(tmp_path, **options):
    clock = Clock()
    store = SqliteGameRegistry(tmp_path / "registry.sqlite3")
    provider = AsyncMock(spec=IGameMetadataProvider)
    provider.search.return_value = (metadata(),)
    cache = ScheduledMetadataProvider(provider, store.database_path, clock=clock, **options)
    detector = FuzzyGameDetector(store)
    resolver = VerifiedMetadataResolver(cache, store, detector, RuleBasedCandidateEligibilityPolicy(), cache)
    return clock, store, provider, cache, detector, resolver


@pytest.mark.asyncio
@pytest.mark.parametrize("result,interval", [((), 86400), ((metadata(),), 604800)])
async def test_persistent_cache_expires_at_boundary_without_sliding_on_hits(tmp_path, result, interval):
    clock, store, provider, cache, _, _ = setup(tmp_path)
    provider.search.return_value = result
    assert await cache.search("query") == result
    for delta in (1, interval - 2):
        clock.advance(delta)
        restarted = ScheduledMetadataProvider(provider, store.database_path, clock=clock)
        assert await restarted.search("query") == result
    provider.search.assert_awaited_once()
    clock.advance(1)
    assert await restarted.search("query") == result
    assert provider.search.await_count == 2


@pytest.mark.asyncio
async def test_provider_failure_uses_short_retry_interval_and_survives_restart(tmp_path):
    clock, store, provider, cache, _, _ = setup(tmp_path)
    provider.search.side_effect = MetadataUnavailable("private diagnostics")
    for step in (0, 299):
        clock.advance(step)
        with pytest.raises(MetadataUnavailable) as error:
            await ScheduledMetadataProvider(provider, store.database_path, clock=clock).search("query")
        assert "private" not in str(error.value)
    provider.search.assert_awaited_once()
    clock.advance(1)
    provider.search.side_effect = None
    assert await cache.search("query") == (metadata(),)
    assert provider.search.await_count == 2


@pytest.mark.asyncio
async def test_ambiguous_results_use_pending_cadence_and_do_not_extend_it(tmp_path):
    clock, store, provider, cache, _, resolver = setup(tmp_path)
    provider.search.return_value = (metadata(), metadata(external_id="other"))
    assert not await resolver.resolve(listing())
    first_due = rows(store.database_path, "SELECT next_attempt_at FROM metadata_query_cache")[0][0]
    assert first_due == clock.now + 86400
    clock.advance(86399)
    assert not await resolver.resolve(listing())
    assert rows(store.database_path, "SELECT next_attempt_at FROM metadata_query_cache") == [(first_due,)]
    provider.search.assert_awaited_once()
    clock.advance(1)
    provider.search.return_value = (metadata(),)
    assert await resolver.resolve(listing())
    assert len(store.list_games()) == 1
    assert provider.search.await_count == 2


@pytest.mark.asyncio
async def test_budget_counts_real_requests_including_errors_but_not_cache_hits(tmp_path):
    _, _, provider, cache, _, _ = setup(tmp_path, max_queries=2)
    await cache.search("first")
    await cache.search("first")
    provider.search.side_effect = MetadataUnavailable("down")
    with pytest.raises(MetadataUnavailable):
        await cache.search("second")
    with pytest.raises(MetadataDeferred, match="budget"):
        await cache.search("third")
    assert provider.search.await_count == 2
    cache.begin_run()
    provider.search.side_effect = None
    await cache.search("third")
    assert provider.search.await_count == 3


@pytest.mark.asyncio
async def test_two_workers_cannot_issue_same_query_while_in_flight(tmp_path):
    clock, store, provider, first, _, _ = setup(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(name):
        started.set()
        await release.wait()
        return (metadata(),)

    provider.search.side_effect = slow
    second = ScheduledMetadataProvider(provider, store.database_path, clock=clock)
    task = asyncio.create_task(first.search("query"))
    await started.wait()
    try:
        with pytest.raises(MetadataDeferred, match="progress"):
            await second.search("query")
    finally:
        release.set()
        await task
    assert await second.search("query") == (metadata(),)
    provider.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_request_releases_claim_and_does_not_cache_failure(tmp_path):
    _, store, provider, cache, _, _ = setup(tmp_path)
    provider.search.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await cache.search("query")
    assert rows(store.database_path, "SELECT status,lease_owner,lease_until FROM metadata_query_cache") == [("pending", None, 0.0)]
    provider.search.side_effect = None
    assert await cache.search("query") == (metadata(),)


@pytest.mark.asyncio
async def test_crashed_worker_lease_expires(tmp_path):
    clock, store, provider, cache, _, _ = setup(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("INSERT INTO metadata_query_cache VALUES ('igdb','query','pending','[]',0,0,'crashed',?)",
                           (clock.now + 300,))
    with pytest.raises(MetadataDeferred):
        await cache.search("query")
    clock.advance(300)
    await cache.search("query")
    provider.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_retries_without_rediscovery_and_only_after_due_time(tmp_path):
    clock, store, provider, cache, detector, resolver = setup(tmp_path)
    provider.search.return_value = ()
    assert not await resolver.resolve(listing())
    provider.search.return_value = (metadata(),)
    assert await resolver.begin_run() == ()
    assert store.list_games() == ()
    provider.search.assert_awaited_once()
    clock.advance(86400)
    assert await resolver.begin_run() == ()
    assert len(store.list_games()) == 1
    assert detector.detect_games(ListingText(listing().title, ""))
    assert provider.search.await_count == 2


@pytest.mark.asyncio
async def test_expired_metadata_adds_verified_alias_but_preserves_ids_and_local_name(tmp_path):
    clock, store, provider, cache, detector, resolver = setup(tmp_path)
    assert await resolver.resolve(listing())
    original = store.list_games()[0].release_identity
    new_alias = "Zyxqv Beyond Horizons"
    provider.search.return_value = (metadata(aliases=(*metadata().aliases, new_alias)),)
    clock.advance(604800)
    assert await resolver.begin_run() == ()
    after = detector.detect_games(ListingText(f"{new_alias} PS5", ""))[0]
    assert after.release_identity == original
    assert after.canonical_name == metadata().name
    assert "vendo" not in " ".join(store.get_game(original.game_id).aliases).casefold()


@pytest.mark.asyncio
async def test_refresh_rejects_alias_of_another_identity_and_preserves_existing_data(tmp_path):
    clock, store, provider, _, detector, resolver = setup(tmp_path)
    assert await resolver.resolve(listing())
    original = store.list_games()[0]
    store.save_game(GameRecord("other", "Other Identity", status=IdentityStatus.CONFIRMED))
    store.save_release(ReleaseIdentity("other", "other-release", Platform.PS5))
    provider.search.return_value = (metadata(aliases=("Other Identity",)),)
    clock.advance(604800)
    assert await resolver.begin_run() == ()
    assert store.get_game(original.release_identity.game_id).aliases == metadata().aliases
    assert rows(store.database_path, "SELECT status FROM metadata_resolutions ORDER BY attempt_id DESC LIMIT 1") == [("ambiguous",)]
    assert detector.detect_games(ListingText(listing().title, ""))[0].release_identity == original.release_identity


@pytest.mark.asyncio
async def test_cache_never_reuses_listing_eligibility_for_other_seller(tmp_path):
    _, store, provider, _, _, resolver = setup(tmp_path)
    assert not await resolver.resolve(listing(description="20 euros cada uno"))
    assert store.list_games() == ()
    assert await resolver.resolve(listing(description="Juego fisico completo"))
    provider.search.assert_awaited_once()
    assert store.list_games()[0].canonical_name == metadata().name


@pytest.mark.asyncio
async def test_maintenance_is_bounded_and_does_not_starve_fresh_queries(tmp_path):
    clock, _, provider, cache, _, resolver = setup(tmp_path, max_queries=4)
    resolver.maintenance_limit = 2
    provider.search.return_value = ()
    for index in range(4):
        await resolver.resolve(listing(f"Unknown Adventure {index} PS5"))
    clock.advance(86400)
    assert await resolver.begin_run() == ()
    assert cache.queries_used == 2
    await resolver.resolve(listing("Fresh Adventure PS5"))
    assert cache.queries_used == 3


@pytest.mark.asyncio
async def test_empty_database_pipeline_never_reads_seed_and_pending_resolves_next_run(tmp_path, monkeypatch):
    clock = Clock()
    config = config_at(tmp_path)
    config = config.model_copy(update={
        "persistence": config.persistence.model_copy(update={"seed_catalog": False}),
        "metadata": MetadataConfig(enabled=True),
    })
    provider = AsyncMock(spec=IGameMetadataProvider)
    provider.search.return_value = ()
    monkeypatch.setattr("presentation.cli.composition.IgdbMetadataProvider", lambda *args: provider)
    monkeypatch.setattr("presentation.cli.composition.ScheduledMetadataProvider",
                        lambda *args, **kwargs: ScheduledMetadataProvider(*args, **kwargs, clock=clock))

    def forbidden_seed():
        pytest.fail("Discovery must work with the seed unavailable")

    monkeypatch.setattr("presentation.cli.composition.PackagedGameCatalog", forbidden_seed)
    market = marketplace_mock()
    async def scoped_search(*, category=None, **kwargs):
        return MarketplaceSearchBatch(tuple(await market.search_listings(**kwargs)), SearchCoverage())
    market.search_with_scope = AsyncMock(side_effect=scoped_search)
    raw = {"id": "new", "title": listing().title, "description": "", "price": "20", "currency": "EUR"}
    market.search_listings.return_value = [raw]
    runtime = build_operational_runtime(config, market)
    request = SearchPlanGenerationRequest((), 40.4, -3.7, 10, 1, SearchPlanGenerationStrategy.DISCOVERY)
    plan = runtime.plan_generator.generate(request).plan
    first = await runtime.search_orchestrator.execute(plan)
    assert not first.query_failures
    assert first.individual_candidates == 0
    assert SqliteGameRegistry(config.persistence.database_path).list_games() == ()
    provider.search.return_value = (metadata(),)
    market.search_listings.return_value = []
    clock.advance(86400)
    second = await build_operational_runtime(config, market).search_orchestrator.execute(plan)
    # Metadata maintenance cannot turn an old observation into a purchase candidate.
    assert second.unique_candidates == second.individual_candidates == 0
    assert len(SqliteGameRegistry(config.persistence.database_path).list_games()) == 1
    provider.search.reset_mock()
    market.search_listings.side_effect = [[raw], []]
    third = await build_operational_runtime(config, market).search_orchestrator.execute(plan)
    assert third.individual_candidates == 1
    assert not third.routing_failures
    provider.search.assert_not_awaited()


@pytest.mark.parametrize("changes", [
    {"max_queries_per_scan": 0}, {"max_queries_per_scan": True}, {"max_queries_per_scan": 201},
    {"metadata_ttl_seconds": 0}, {"pending_retry_seconds": -1}, {"error_retry_seconds": 1},
    {"maintenance_limit": -1}, {"metadata_ttl_seconds": "60"},
])
def test_invalid_schedule_configuration_is_rejected(changes):
    with pytest.raises(ValidationError):
        MetadataConfig(**changes)


@pytest.mark.asyncio
async def test_migrates_legacy_unknowns_once_and_preserves_original_evidence(tmp_path):
    clock = Clock()
    path = tmp_path / "old.sqlite3"
    item = listing()
    observation = ListingObservation(item.listing_id, item.title, item.description, item.price,
                                     item.currency, datetime.fromtimestamp(clock.now, UTC), "unknown")
    recorder = SqliteCatalogDiscoveryRecorder(path)
    await recorder.record_observation(observation)
    before = rows(path, "SELECT * FROM listing_identifications")
    store = SqliteGameRegistry(path)
    provider = AsyncMock(spec=IGameMetadataProvider)
    provider.search.return_value = (metadata(),)
    cache = ScheduledMetadataProvider(provider, path, clock=clock)
    assert cache.due_listings(5) == (replace(item, url=""),)
    resolver = VerifiedMetadataResolver(cache, store, FuzzyGameDetector(store),
                                        RuleBasedCandidateEligibilityPolicy(), cache)
    assert await resolver.begin_run() == ()
    assert len(store.list_games()) == 1
    assert rows(path, "SELECT * FROM listing_identifications") == before
    assert ScheduledMetadataProvider(provider, path, clock=clock).due_listings(5) == ()
    assert rows(path, "SELECT count(*) FROM metadata_watchlist") == [(1,)]


@pytest.mark.asyncio
async def test_b09_migration_preserves_retry_deadline_and_distinct_outcomes(tmp_path):
    clock = Clock()
    clock.now = datetime.now(UTC).timestamp()
    path = tmp_path / "b09.sqlite3"
    store = SqliteGameRegistry(path)
    item = listing()
    recorder = SqliteCatalogDiscoveryRecorder(path)
    await recorder.record_observation(ListingObservation(item.listing_id, item.title, item.description,
                                                        item.price, item.currency, datetime.now(UTC), "unknown"))
    store.record_resolution(item, "zyxqv odyssey ix beyond stars", Platform.PS5, "provider_error", ())
    provider = AsyncMock(spec=IGameMetadataProvider)
    provider.search.return_value = (metadata(),)
    cache = ScheduledMetadataProvider(provider, path, clock=clock)
    assert cache.due_listings(5) == ()
    with pytest.raises(MetadataUnavailable):
        await cache.search("zyxqv odyssey ix beyond stars")
    provider.search.assert_not_awaited()
    clock.advance(301)
    assert len(cache.due_listings(5)) == 1
    await cache.search("zyxqv odyssey ix beyond stars")
    provider.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_maintenance_errors_do_not_stop_known_fresh_candidates(tmp_path, monkeypatch):
    config = config_at(tmp_path).model_copy(update={"metadata": MetadataConfig(enabled=True)})
    provider = AsyncMock(spec=IGameMetadataProvider)
    monkeypatch.setattr("presentation.cli.composition.IgdbMetadataProvider", lambda *args: provider)
    market = marketplace_mock()
    market.search_listings.side_effect = [[{
        "id": "known", "title": "Elden Ring PS5", "description": "", "price": "20", "currency": "EUR",
    }], []]
    runtime = build_operational_runtime(config, market)
    runtime.search_orchestrator.unknown_game_resolver.begin_run = AsyncMock(side_effect=sqlite3.OperationalError("private path"))
    from application.interfaces.candidate_search import SearchQuery
    from application.interfaces.search_orchestrator import SearchPlan
    result = await runtime.search_orchestrator.execute(SearchPlan((SearchQuery("PS5", 40.4, -3.7, 10),)))
    assert result.individual_candidates == 1
    assert [failure.kind.value for failure in result.routing_failures] == ["metadata_maintenance_error"]
    assert "private" not in result.routing_failures[0].error_message
    provider.search.assert_not_awaited()
