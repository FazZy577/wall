"""SQLite listing versions and evidence, alongside legacy title aggregates."""

import hashlib
import json
import logging
import sqlite3
import unicodedata
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from application.interfaces.candidate_search import QueryScan
from application.interfaces.catalog_discovery_recorder import (
    ICatalogDiscoveryRecorder,
)
from application.interfaces.listing_observation_recorder import (
    IListingObservationRecorder,
    ListingObservation,
    ObservationStorageError,
)
from domain.entities.detected_game import Platform
from infrastructure.catalogs.sqlite_game_registry import create_registry_schema
from infrastructure.matching.platform_lexical_matcher import PlatformLexicalMatcher

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE_PATH = Path("data/catalog_discovery.sqlite3")
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS catalog_discovery_observations (
    normalized_title TEXT NOT NULL,
    mentioned_platform TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL CHECK (occurrence_count > 0),
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    example_title TEXT NOT NULL,
    latest_listing_id TEXT NOT NULL,
    PRIMARY KEY (normalized_title, mentioned_platform)
)
"""
_UPSERT_SQL = """
INSERT INTO catalog_discovery_observations (
    normalized_title,
    mentioned_platform,
    occurrence_count,
    first_seen,
    last_seen,
    example_title,
    latest_listing_id
) VALUES (?, ?, 1, ?, ?, ?, ?)
ON CONFLICT(normalized_title, mentioned_platform) DO UPDATE SET
    occurrence_count = occurrence_count + 1,
    last_seen = excluded.last_seen,
    latest_listing_id = excluded.latest_listing_id
"""


class SqliteCatalogDiscoveryRecorder(ICatalogDiscoveryRecorder, IListingObservationRecorder):
    """Persist listing observations while retaining the legacy aggregation API."""

    def __init__(self, database_path: Path | None = None) -> None:
        if database_path is not None and not isinstance(database_path, Path):
            raise TypeError("database_path must be pathlib.Path or None")
        self.database_path = (
            _DEFAULT_DATABASE_PATH if database_path is None else database_path
        )
        self._platform_matcher = PlatformLexicalMatcher()

    def initialize(self) -> None:
        """Create the versioned store without altering legacy title aggregates."""
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.database_path)) as connection, connection:
                self._create_observation_schema(connection)
                pending = connection.execute("""SELECT observation_id, marketplace, listing_id, title
                    FROM listing_observations o WHERE provisional_game_id IS NULL
                    AND (SELECT status FROM listing_identifications i
                         WHERE i.observation_id=o.observation_id
                         ORDER BY last_attempt DESC LIMIT 1)='unknown'""").fetchall()
                for observation_id, marketplace, listing_id, title in pending:
                    self._link_provisional(connection, observation_id, marketplace, listing_id, title)
        except (OSError, sqlite3.Error) as error:
            raise ObservationStorageError(
                f"Unable to initialize observation database: {type(error).__name__}"
            ) from error

    @staticmethod
    def _create_observation_schema(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        create_registry_schema(connection)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS query_scans (
                run_id TEXT NOT NULL,
                query_index INTEGER NOT NULL,
                category TEXT,
                keywords TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                max_results INTEGER NOT NULL,
                max_pages INTEGER,
                pages_received INTEGER,
                items_received INTEGER,
                stop_reason TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                error_type TEXT,
                PRIMARY KEY (run_id, query_index)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS listing_observations (
                observation_id INTEGER PRIMARY KEY,
                marketplace TEXT NOT NULL,
                listing_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                price TEXT NOT NULL,
                currency TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE (marketplace, listing_id, content_hash)
            )
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(listing_observations)")}
        if "provisional_game_id" not in columns:
            connection.execute("ALTER TABLE listing_observations ADD COLUMN provisional_game_id TEXT REFERENCES games(game_id)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS listing_identifications (
                observation_id INTEGER NOT NULL REFERENCES listing_observations(observation_id),
                evidence_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                first_attempt TEXT NOT NULL,
                last_attempt TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (observation_id, evidence_hash)
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS listing_observation_queries (
                observation_id INTEGER NOT NULL REFERENCES listing_observations(observation_id),
                role TEXT NOT NULL,
                query TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (observation_id, role, query)
            )
        """)

    async def record_query_scan(self, scan: QueryScan) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            self._create_observation_schema(connection)
            connection.execute("""
                INSERT INTO query_scans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                scan.run_id, scan.query_index,
                scan.query.category.value if scan.query.category else None,
                scan.query.keywords, scan.query.latitude, scan.query.longitude,
                scan.query.max_results, scan.coverage.max_pages, scan.coverage.pages_received,
                scan.coverage.items_received, scan.coverage.stop_reason.value,
                self._timestamp(scan.started_at), self._timestamp(scan.completed_at), scan.error_type,
            ))

    @staticmethod
    def _link_provisional(connection: sqlite3.Connection, observation_id: int,
                          marketplace: str, listing_id: str, title: str) -> None:
        provisional_id = str(uuid5(NAMESPACE_URL,
            f"wallapop-arbitrage:provisional:{marketplace}:{listing_id}"))
        connection.execute("INSERT OR IGNORE INTO games VALUES (?, ?, '[]', 'provisional')",
                           (provisional_id, title))
        connection.execute("UPDATE listing_observations SET provisional_game_id=? WHERE observation_id=?",
                           (provisional_id, observation_id))

    async def record_observation(self, observation: ListingObservation) -> None:
        """Upsert a version and its evidence in one transaction; never swallow errors."""
        self._timestamp(observation.observed_at)  # Validate timezone awareness.
        timestamp = observation.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
        price = format(observation.price, "f")
        if "." in price:
            price = price.rstrip("0").rstrip(".")
        content = json.dumps(
            [observation.title, observation.description, price, observation.currency],
            ensure_ascii=False,
        )
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        classification = observation.classification
        evidence = json.dumps({
            "role": observation.role,
            "status": observation.status,
            "error_type": observation.error_type,
            "disposition": classification.disposition.value if classification else None,
            "reason": classification.reason.value if classification else None,
            "included_games": [
                {"name": game.canonical_name, "platform": game.platform.value, "quantity": quantity}
                for game, quantity in zip(
                    classification.included_games, classification.quantities, strict=True
                )
            ] if classification else [],
            "detected_games": [
                {"name": game.canonical_name, "platform": game.platform.value,
                 "game_id": game.release_identity.game_id if game.release_identity else None,
                 "release_id": game.release_identity.release_id if game.release_identity else None,
                 "edition": game.release_identity.edition if game.release_identity else None,
                 "media_format": game.release_identity.media_format.value if game.release_identity else None,
                 "identity_status": game.release_identity.status.value if game.release_identity else "legacy",
                 "matched_text": game.matched_text, "confidence": game.confidence,
                 "method": game.detection_method.value}
                for game in observation.detected_games
            ],
        }, ensure_ascii=False, sort_keys=True)
        evidence_hash = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            self._create_observation_schema(connection)
            connection.execute("""
                INSERT INTO listing_observations
                    (marketplace, listing_id, content_hash, title, description, price,
                     currency, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(marketplace, listing_id, content_hash) DO UPDATE SET
                    first_seen = min(first_seen, excluded.first_seen),
                    last_seen = max(last_seen, excluded.last_seen), seen_count = seen_count + 1
            """, (observation.marketplace, observation.listing_id, content_hash,
                  observation.title, observation.description, price, observation.currency,
                  timestamp, timestamp))
            row = connection.execute("""
                SELECT observation_id FROM listing_observations
                WHERE marketplace = ? AND listing_id = ? AND content_hash = ?
            """, (observation.marketplace, observation.listing_id, content_hash)).fetchone()
            assert row is not None
            observation_id = row[0]
            if observation.status == "unknown":
                self._link_provisional(connection, observation_id, observation.marketplace,
                                       observation.listing_id, observation.title)
            connection.execute("""
                INSERT INTO listing_identifications
                    (observation_id, evidence_hash, role, status, evidence_json,
                     first_attempt, last_attempt)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(observation_id, evidence_hash) DO UPDATE SET
                    first_attempt = min(first_attempt, excluded.first_attempt),
                    last_attempt = max(last_attempt, excluded.last_attempt),
                    attempt_count = attempt_count + 1
            """, (observation_id, evidence_hash, observation.role, observation.status,
                  evidence, timestamp, timestamp))
            if observation.source_query is not None:
                connection.execute("""
                    INSERT INTO listing_observation_queries
                        (observation_id, role, query, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(observation_id, role, query) DO UPDATE SET
                        first_seen = min(first_seen, excluded.first_seen),
                        last_seen = max(last_seen, excluded.last_seen)
                """, (observation_id, observation.role, observation.source_query,
                      timestamp, timestamp))

    async def record_unrecognized_candidate(
        self,
        *,
        listing_id: str,
        original_title: str,
        observed_at: datetime,
    ) -> None:
        """Persist one observation; isolate all expected filesystem/SQLite errors."""
        try:
            self._record(
                listing_id=listing_id,
                original_title=original_title,
                observed_at=observed_at,
            )
        except (OSError, sqlite3.Error) as error:
            logger.warning(
                "Catalog discovery observation could not be persisted: type=%s",
                type(error).__name__,
            )

    def _record(
        self,
        *,
        listing_id: str,
        original_title: str,
        observed_at: datetime,
    ) -> None:
        normalized_title = self._normalize_title(original_title)
        timestamp = self._timestamp(observed_at)
        platforms = self._mentioned_platforms(original_title)
        platform_values = tuple(platform.value for platform in platforms) or ("",)

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(_CREATE_TABLE_SQL)
            connection.executemany(
                _UPSERT_SQL,
                (
                    (
                        normalized_title,
                        platform,
                        timestamp,
                        timestamp,
                        original_title,
                        listing_id,
                    )
                    for platform in platform_values
                ),
            )

    def _mentioned_platforms(self, title: str) -> tuple[Platform, ...]:
        platforms: list[Platform] = []
        for mention in self._platform_matcher.find_mentions(title):
            if mention.platform not in platforms:
                platforms.append(mention.platform)
        return tuple(platforms)

    @staticmethod
    def _normalize_title(title: str) -> str:
        normalized = unicodedata.normalize("NFKD", title.casefold())
        without_accents = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return " ".join(without_accents.split())

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if not isinstance(value, datetime):
            raise TypeError("observed_at must be datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ("SqliteCatalogDiscoveryRecorder",)
