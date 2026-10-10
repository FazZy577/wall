"""B06: real SQLite across independent runtimes, without network access."""

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MethodType
from unittest.mock import AsyncMock

import pytest

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.listing_observation_recorder import (
    ListingObservation,
    ObservationStorageError,
)
from application.interfaces.search_orchestrator import SearchPlan
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.discovery.sqlite_catalog_discovery_recorder import (
    SqliteCatalogDiscoveryRecorder,
)
from presentation.cli.composition import build_operational_runtime
from presentation.cli.config import PersistenceConfig
from presentation.cli.config_loader import AppConfigLoadError, load_app_config

pytestmark = pytest.mark.integration


def marketplace_mock():
    market = AsyncMock(spec=IMarketplaceSearch)
    market.search_with_scope = MethodType(IMarketplaceSearch.search_with_scope, market)
    return market


def rows(path, sql):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(sql).fetchall()


def config_at(tmp_path):
    source = Path(__file__).resolve().parents[2] / "config.example.toml"
    path = tmp_path / "config.toml"
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return load_app_config(path)


def observation(**changes):
    return replace(ListingObservation(
        listing_id="unknown-1", title="Future Adventure IX PS5",
        description="Complete physical game", price=Decimal("20.00"), currency="EUR",
        observed_at=datetime(2026, 10, 1, tzinfo=UTC), status="unknown",
        source_query="juegos PS5",
    ), **changes)


@pytest.mark.asyncio
async def test_versions_and_evidence_survive_restart_without_duplicate_snapshots(tmp_path):
    path = tmp_path / "observations.sqlite3"
    first = observation()
    await SqliteCatalogDiscoveryRecorder(path).record_observation(first)
    await SqliteCatalogDiscoveryRecorder(path).record_observation(replace(
        first, observed_at=first.observed_at + timedelta(hours=1), price=Decimal("20")
    ))
    assert rows(path, "SELECT title, description, price, seen_count FROM listing_observations") == [
        (first.title, first.description, "20", 2),
    ]
    assert rows(path, "SELECT status, attempt_count FROM listing_identifications") == [("unknown", 2)]
    assert rows(path, "SELECT first_seen, last_seen FROM listing_observations") == [
        ("2026-10-01T00:00:00.000000+00:00", "2026-10-01T01:00:00.000000+00:00"),
    ]
    await SqliteCatalogDiscoveryRecorder(path).record_observation(replace(first, status="ambiguous"))
    assert rows(path, "SELECT count(*) FROM listing_observations") == [(1,)]
    assert rows(path, "SELECT count(*) FROM listing_identifications") == [(2,)]
    await SqliteCatalogDiscoveryRecorder(path).record_observation(replace(first, description="Changed contents"))
    await SqliteCatalogDiscoveryRecorder(path).record_observation(replace(first, price=Decimal("25")))
    await SqliteCatalogDiscoveryRecorder(path).record_observation(replace(first, listing_id="unknown-2"))
    assert rows(path, "SELECT count(*) FROM listing_observations") == [(4,)]


@pytest.mark.asyncio
async def test_multiple_queries_and_roles_do_not_duplicate_content(tmp_path):
    path = tmp_path / "store.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(path)
    await recorder.record_observation(observation())
    await recorder.record_observation(observation(source_query="Future Adventure IX PS5", role="comparable"))
    assert rows(path, "SELECT count(*) FROM listing_observations") == [(1,)]
    assert rows(path, "SELECT count(*) FROM listing_observation_queries") == [(2,)]


@pytest.mark.asyncio
async def test_transaction_rolls_back_content_when_evidence_write_fails(tmp_path):
    path = tmp_path / "store.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(path)
    recorder.initialize()
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""CREATE TRIGGER reject_evidence BEFORE INSERT ON listing_identifications
            BEGIN SELECT RAISE(ABORT, 'test storage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        await recorder.record_observation(observation())
    assert rows(path, "SELECT count(*) FROM listing_observations") == [(0,)]


@pytest.mark.asyncio
async def test_legacy_aggregates_are_preserved(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(path)
    await recorder.record_unrecognized_candidate(
        listing_id="old", original_title="Unknown PS5", observed_at=datetime.now(UTC)
    )
    before = rows(path, "SELECT * FROM catalog_discovery_observations")
    recorder.initialize()
    await recorder.record_observation(observation())
    assert rows(path, "SELECT * FROM catalog_discovery_observations") == before


@pytest.mark.asyncio
async def test_cli_composition_records_unknowns_across_fresh_runtimes(tmp_path):
    config = config_at(tmp_path)
    path = config.persistence.database_path
    assert path == tmp_path / "data/catalog_discovery.sqlite3"
    assert not path.exists()  # Loading configuration must not write files.
    market = marketplace_mock()
    market.search_listings.return_value = [{
        "id": "new-game", "title": "Zyxqv Adventure PS5", "description": "Unlisted physical game",
        "price": "20", "currency": "EUR", "seller": "not persisted",
    }]
    plan = SearchPlan((SearchQuery("juegos PS5", 40.4, -3.7, 10),))
    for _ in range(2):
        runtime = build_operational_runtime(config, market)
        result = await runtime.search_orchestrator.execute(plan)
        assert not result.routing_failures
    assert rows(path, "SELECT listing_id, seen_count FROM listing_observations") == [("new-game", 2)]
    evidence = rows(path, "SELECT status, evidence_json, attempt_count FROM listing_identifications")
    assert evidence[0][0] == "unknown"
    assert evidence[0][2] == 2
    assert json.loads(evidence[0][1])["reason"] == "no_included_game"
    assert "seller" not in evidence[0][1]


@pytest.mark.asyncio
async def test_storage_failure_is_structured_and_processing_continues(tmp_path):
    config = config_at(tmp_path)
    market = marketplace_mock()
    market.search_listings.return_value = [
        {"id": name, "title": "Zyxqv PS5", "description": "", "price": "20", "currency": "EUR"}
        for name in ("one", "two")
    ]
    runtime = build_operational_runtime(config, market)
    with closing(sqlite3.connect(config.persistence.database_path)) as connection, connection:
        connection.execute("""CREATE TRIGGER reject_listing BEFORE INSERT ON listing_observations
            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    result = await runtime.search_orchestrator.execute(SearchPlan((SearchQuery("juegos PS5", 40.4, -3.7, 10),)))
    assert len(result.ignored_candidates) == 2
    assert [failure.kind.value for failure in result.routing_failures] == ["observation_storage_error"] * 2


def test_disabled_storage_creates_nothing_and_invalid_destination_fails(tmp_path):
    config = config_at(tmp_path)
    disabled = config.model_copy(update={"persistence": PersistenceConfig()})
    build_operational_runtime(disabled, AsyncMock(spec=IMarketplaceSearch))
    assert not (tmp_path / "data").exists()
    (tmp_path / "data").write_text("blocking parent", encoding="utf-8")
    with pytest.raises(ObservationStorageError):
        build_operational_runtime(config, AsyncMock(spec=IMarketplaceSearch))


@pytest.mark.parametrize("section", [
    '[persistence]\nenabled = true\n',
    '[persistence]\nenabled = true\ndatabase_path = ""\n',
    '[persistence]\nenabled = "true"\ndatabase_path = "x.db"\n',
    '[persistence]\nenabled = true\ndatabase_path = "reports/scan.json"\n',
])
def test_invalid_persistence_config_is_rejected(tmp_path, section):
    config_at(tmp_path)
    path = tmp_path / "config.toml"
    original = path.read_text(encoding="utf-8").split("[persistence]")[0]
    path.write_text(original + section, encoding="utf-8")
    with pytest.raises(AppConfigLoadError):
        load_app_config(path)


@pytest.mark.asyncio
async def test_comparables_persist_query_and_identification_evidence(tmp_path):
    config = config_at(tmp_path)
    market = marketplace_mock()
    market.search_listings.side_effect = [
        [{"id": "candidate", "title": "GTA V PS4", "description": "", "price": "5", "currency": "EUR"}],
        [{"id": "reference", "title": "GTA V PS4", "description": "", "price": "20", "currency": "EUR"}],
    ]
    runtime = build_operational_runtime(config, market)
    await runtime.search_orchestrator.execute(SearchPlan((SearchQuery("juegos PS4", 40.4, -3.7, 10),)))
    path = config.persistence.database_path
    assert rows(path, "SELECT listing_id FROM listing_observations ORDER BY listing_id") == [
        ("candidate",), ("reference",),
    ]
    assert rows(path, "SELECT role, query FROM listing_observation_queries ORDER BY role") == [
        ("candidate", "juegos PS4"), ("comparable", "Grand Theft Auto V PS4"),
    ]
    evidence = json.loads(rows(path, "SELECT evidence_json FROM listing_identifications WHERE role='comparable'")[0][0])
    assert evidence["detected_games"][0]["name"] == "Grand Theft Auto V"
    assert evidence["detected_games"][0]["platform"] == "PS4"


@pytest.mark.asyncio
async def test_detection_errors_are_persisted_as_errors_not_unknown_games(tmp_path):
    from unittest.mock import Mock

    config = config_at(tmp_path)
    market = marketplace_mock()
    market.search_listings.return_value = [{
        "id": "broken", "title": "GTA V PS4", "description": "", "price": "20", "currency": "EUR",
    }]
    runtime = build_operational_runtime(config, market)
    runtime.search_orchestrator.game_detector = Mock()
    runtime.search_orchestrator.game_detector.detect_games.side_effect = RuntimeError("failure")
    await runtime.search_orchestrator.execute(SearchPlan((SearchQuery("juegos PS4", 40.4, -3.7, 10),)))
    assert rows(config.persistence.database_path, "SELECT status FROM listing_identifications") == [("error",)]
