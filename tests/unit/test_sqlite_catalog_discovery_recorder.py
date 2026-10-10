"""Unit tests for catalog-discovery recorder implementations."""

import inspect
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from application.interfaces.catalog_discovery_recorder import (
    ICatalogDiscoveryRecorder,
    NullCatalogDiscoveryRecorder,
)
from infrastructure.discovery.sqlite_catalog_discovery_recorder import (
    SqliteCatalogDiscoveryRecorder,
)


def _rows(database_path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(database_path)) as connection:
        return connection.execute(
            """
            SELECT
                normalized_title,
                mentioned_platform,
                occurrence_count,
                first_seen,
                last_seen,
                example_title,
                latest_listing_id
            FROM catalog_discovery_observations
            ORDER BY normalized_title, mentioned_platform
            """
        ).fetchall()


@pytest.mark.asyncio
async def test_first_observation_creates_one_normalized_platform_row(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "discovery.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(database_path)
    observed_at = datetime(2026, 8, 18, 10, 30, tzinfo=UTC)

    await recorder.record_unrecognized_candidate(
        listing_id="wallapop-1",
        original_title="  Pokémon   Legends   PS5  ",
        observed_at=observed_at,
    )

    assert _rows(database_path) == [
        (
            "pokemon legends ps5",
            "PS5",
            1,
            "2026-08-18T10:30:00Z",
            "2026-08-18T10:30:00Z",
            "  Pokémon   Legends   PS5  ",
            "wallapop-1",
        )
    ]


@pytest.mark.asyncio
async def test_repeated_normalized_title_and_platform_increments_occurrences(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "discovery.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(database_path)
    first_seen = datetime(2026, 8, 18, 10, tzinfo=UTC)
    last_seen = first_seen + timedelta(hours=2)

    await recorder.record_unrecognized_candidate(
        listing_id="first-id",
        original_title="Pokémon Legends PS5",
        observed_at=first_seen,
    )
    await recorder.record_unrecognized_candidate(
        listing_id="latest-id",
        original_title="  POKÉMON   LEGENDS   PS5 ",
        observed_at=last_seen,
    )

    row = _rows(database_path)[0]
    assert row == (
        "pokemon legends ps5",
        "PS5",
        2,
        "2026-08-18T10:00:00Z",
        "2026-08-18T12:00:00Z",
        "Pokémon Legends PS5",
        "latest-id",
    )


@pytest.mark.asyncio
async def test_distinct_titles_and_each_mentioned_platform_create_distinct_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "discovery.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(database_path)
    observed_at = datetime(2026, 8, 18, tzinfo=UTC)

    await recorder.record_unrecognized_candidate(
        listing_id="multi",
        original_title="Unknown Game PS5 Xbox Series",
        observed_at=observed_at,
    )
    await recorder.record_unrecognized_candidate(
        listing_id="without-platform",
        original_title="Another Unknown Game",
        observed_at=observed_at,
    )

    assert [row[:3] for row in _rows(database_path)] == [
        ("another unknown game", "", 1),
        ("unknown game ps5 xbox series", "PS5", 1),
        ("unknown game ps5 xbox series", "Xbox Series", 1),
    ]


@pytest.mark.asyncio
async def test_write_failure_is_logged_and_does_not_propagate(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocking file", encoding="utf-8")
    recorder = SqliteCatalogDiscoveryRecorder(blocked_parent / "discovery.sqlite3")

    await recorder.record_unrecognized_candidate(
        listing_id="listing-id",
        original_title="Unknown Game PS5",
        observed_at=datetime.now(UTC),
    )

    assert "could not be persisted" in caplog.text
    assert not (blocked_parent / "discovery.sqlite3").exists()


@pytest.mark.asyncio
async def test_schema_and_port_cannot_persist_nonessential_listing_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "discovery.sqlite3"
    recorder = SqliteCatalogDiscoveryRecorder(database_path)
    await recorder.record_unrecognized_candidate(
        listing_id="safe-id",
        original_title="Unknown Game PS5",
        observed_at=datetime.now(UTC),
    )

    with closing(sqlite3.connect(database_path)) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(catalog_discovery_observations)"
            )
        }

    assert columns == {
        "normalized_title",
        "mentioned_platform",
        "occurrence_count",
        "first_seen",
        "last_seen",
        "example_title",
        "latest_listing_id",
    }
    parameters = inspect.signature(
        ICatalogDiscoveryRecorder.record_unrecognized_candidate
    ).parameters
    assert list(parameters) == [
        "self",
        "listing_id",
        "original_title",
        "observed_at",
    ]


@pytest.mark.asyncio
async def test_null_recorder_never_persists_or_fails(tmp_path: Path) -> None:
    recorder = NullCatalogDiscoveryRecorder()

    await recorder.record_unrecognized_candidate(
        listing_id="ignored",
        original_title="Anything",
        observed_at=datetime.now(UTC),
    )

    assert list(tmp_path.iterdir()) == []
    assert isinstance(recorder, ICatalogDiscoveryRecorder)
