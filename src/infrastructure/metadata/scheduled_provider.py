"""Persistent metadata cache, retry cadence, request leases and per-scan budgets."""

import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from application.interfaces.game_metadata import (
    GameMetadata,
    IGameMetadataProvider,
    IMetadataSchedule,
    MetadataDeferred,
    MetadataUnavailable,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import Platform
from infrastructure.metadata.query import extract_metadata_query, unsupported_metadata_listing


class ScheduledMetadataProvider(IGameMetadataProvider, IMetadataSchedule):
    """Cache provider responses, never decisions about individual seller listings."""

    def __init__(self, provider: IGameMetadataProvider, database_path: Path,
                 provider_name: str = "igdb", *, max_queries: int = 20,
                 metadata_ttl_seconds: int = 604800, pending_retry_seconds: int = 86400,
                 error_retry_seconds: int = 300, clock: Callable[[], float] = time.time) -> None:
        if any(type(value) is not int or value <= 0 for value in (
            max_queries, metadata_ttl_seconds, pending_retry_seconds, error_retry_seconds,
        )):
            raise ValueError("Metadata budgets and intervals must be positive integers")
        if not provider_name.strip():
            raise ValueError("A provider namespace is required")
        self.provider = provider
        self.database_path = database_path
        self.provider_name = provider_name
        self.max_queries = max_queries
        self.metadata_ttl_seconds = metadata_ttl_seconds
        self.pending_retry_seconds = pending_retry_seconds
        self.error_retry_seconds = error_retry_seconds
        self.clock = clock
        self.queries_used = 0
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS metadata_query_cache (
                provider TEXT NOT NULL, query TEXT NOT NULL, status TEXT NOT NULL,
                candidates_json TEXT NOT NULL, attempted_at REAL NOT NULL,
                next_attempt_at REAL NOT NULL, lease_owner TEXT, lease_until REAL NOT NULL,
                PRIMARY KEY(provider, query))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS metadata_watchlist (
                provider TEXT NOT NULL, query TEXT NOT NULL, platform TEXT NOT NULL,
                listing_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
                price TEXT NOT NULL, currency TEXT NOT NULL, last_seen REAL NOT NULL,
                PRIMARY KEY(provider, query, platform))""")
            self._migrate_observations(connection)

    def _migrate_observations(self, connection: sqlite3.Connection) -> None:
        """Import B06-B09 pending observations once, without changing their evidence."""
        connection.execute("CREATE TABLE IF NOT EXISTS metadata_schedule_migrations (provider TEXT PRIMARY KEY)")
        if connection.execute("SELECT 1 FROM metadata_schedule_migrations WHERE provider=?", (self.provider_name,)).fetchone():
            return
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"listing_observations", "listing_identifications", "metadata_resolutions"} <= tables:
            return
        if self.provider_name == "igdb":  # B09 shipped only IGDB; do not transfer cache across providers.
            for query, status, payload, attempted_at in connection.execute("""SELECT query,status,candidates_json,attempted_at
                    FROM metadata_resolutions WHERE status<>'unsupported_listing' ORDER BY attempt_id DESC"""):
                if status == "deferred":
                    continue
                decoded = self._decode(payload)
                if any(candidate.provider != self.provider_name for candidate in decoded):
                    continue
                when = datetime.fromisoformat(attempted_at).timestamp()
                cache_status = "provider_error" if status == "provider_error" else ("found" if decoded else "not_found")
                interval = (self.error_retry_seconds if cache_status == "provider_error" else
                            self.metadata_ttl_seconds if status == "confirmed" else self.pending_retry_seconds)
                connection.execute("INSERT OR IGNORE INTO metadata_query_cache VALUES (?,?,?,?,?,?,NULL,0)",
                                   (self.provider_name, query, cache_status, payload, when, when + interval))
        # Include previously queried identities for expiry, plus never-queried unknowns.
        for row in connection.execute("""SELECT o.listing_id,o.title,o.description,o.price,o.currency,o.last_seen
                FROM listing_observations o WHERE NOT EXISTS (
                    SELECT 1 FROM listing_observations newer WHERE newer.marketplace=o.marketplace
                    AND newer.listing_id=o.listing_id AND newer.last_seen>o.last_seen)
                AND (EXISTS (SELECT 1 FROM metadata_resolutions m WHERE m.listing_id=o.listing_id
                    AND m.title=o.title AND m.description=o.description)
                OR EXISTS (SELECT 1 FROM listing_identifications i WHERE i.observation_id=o.observation_id
                    AND i.status IN ('unknown','ambiguous') AND i.last_attempt=(
                        SELECT MAX(last_attempt) FROM listing_identifications WHERE observation_id=o.observation_id)))
                ORDER BY o.last_seen DESC"""):
            listing = CandidateListing(row[0], row[1], row[2], Decimal(row[3]), row[4], "")
            extracted = extract_metadata_query(listing)
            if extracted is None or unsupported_metadata_listing(listing):
                continue
            query, platform = extracted
            connection.execute("INSERT OR IGNORE INTO metadata_watchlist VALUES (?,?,?,?,?,?,?,?,?)",
                               (self.provider_name, query, platform.value, *row[:5], datetime.fromisoformat(row[5]).timestamp()))
        connection.execute("INSERT INTO metadata_schedule_migrations VALUES (?)", (self.provider_name,))

    def begin_run(self) -> None:
        self.queries_used = 0

    def remember(self, listing: CandidateListing, query: str, platform: Platform) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("""INSERT INTO metadata_watchlist VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider,query,platform) DO UPDATE SET listing_id=excluded.listing_id,
                title=excluded.title, description=excluded.description, price=excluded.price,
                currency=excluded.currency, last_seen=excluded.last_seen""", (
                    self.provider_name, query, platform.value, listing.listing_id,
                    listing.title, listing.description, str(listing.price), listing.currency, self.clock(),
                ))

    def due_listings(self, limit: int) -> tuple[CandidateListing, ...]:
        if limit <= 0:
            return ()
        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute("""SELECT w.listing_id,w.title,w.description,w.price,w.currency
                FROM metadata_watchlist w LEFT JOIN metadata_query_cache c
                ON c.provider=w.provider AND c.query=w.query
                WHERE w.provider=? AND (c.query IS NULL OR (c.next_attempt_at<=? AND c.lease_until<=?))
                ORDER BY COALESCE(c.next_attempt_at,0),w.last_seen,w.query,w.platform LIMIT ?""",
                (self.provider_name, self.clock(), self.clock(), limit)).fetchall()
        return tuple(CandidateListing(row[0], row[1], row[2], Decimal(row[3]), row[4], "") for row in rows)

    def resolution_status(self, query: str, status: str) -> None:
        if status not in {"not_found", "ambiguous", "unsupported_content"}:
            return
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("""UPDATE metadata_query_cache SET next_attempt_at=
                MIN(next_attempt_at,attempted_at+?) WHERE provider=? AND query=? AND status='found'""",
                (self.pending_retry_seconds, self.provider_name, query))

    async def search(self, name: str) -> tuple[GameMetadata, ...]:
        now = self.clock()
        owner = uuid4().hex
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""SELECT status,candidates_json,next_attempt_at,lease_until
                FROM metadata_query_cache WHERE provider=? AND query=?""", (self.provider_name, name)).fetchone()
            if row is not None and row[2] > now:
                if row[0] == "provider_error":
                    raise MetadataUnavailable("Metadata provider is in its retry interval")
                return self._decode(row[1])
            if row is not None and row[3] > now:
                raise MetadataDeferred("Metadata request is already in progress")
            if self.queries_used >= self.max_queries:
                raise MetadataDeferred("Metadata request budget exhausted for this scan")
            # Lease expires after a crashed worker; no external I/O inside the SQLite transaction.
            connection.execute("""INSERT INTO metadata_query_cache VALUES (?,?,'pending','[]',0,0,?,?)
                ON CONFLICT(provider,query) DO UPDATE SET lease_owner=excluded.lease_owner,
                lease_until=excluded.lease_until""", (self.provider_name, name, owner, now + 300))
        self.queries_used += 1
        try:
            try:
                candidates = await self.provider.search(name)
                if not isinstance(candidates, tuple) or any(
                    not isinstance(candidate, GameMetadata) or candidate.provider != self.provider_name
                    for candidate in candidates
                ):
                    raise MetadataUnavailable("Invalid metadata provider response")
            except Exception:
                self._finish(name, owner, "provider_error", (), self.error_retry_seconds)
                raise MetadataUnavailable("Metadata provider request failed") from None
            self._finish(name, owner, "found" if candidates else "not_found", candidates,
                         self.metadata_ttl_seconds if candidates else self.pending_retry_seconds)
            return candidates
        finally:
            # Cancellation propagates, but releases the claim for a later run.
            with closing(sqlite3.connect(self.database_path)) as connection, connection:
                connection.execute("""UPDATE metadata_query_cache SET lease_owner=NULL,lease_until=0
                    WHERE provider=? AND query=? AND lease_owner=?""", (self.provider_name, name, owner))

    def _finish(self, query: str, owner: str, status: str,
                candidates: tuple[GameMetadata, ...], interval: int) -> None:
        now = self.clock()
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            updated = connection.execute("""UPDATE metadata_query_cache SET status=?,candidates_json=?,
                attempted_at=?,next_attempt_at=?,lease_owner=NULL,lease_until=0
                WHERE provider=? AND query=? AND lease_owner=?""", (
                    status, json.dumps([asdict(candidate) for candidate in candidates]),
                    now, now + interval, self.provider_name, query, owner,
                ))
            if updated.rowcount != 1:
                raise MetadataDeferred("Metadata request lease was superseded")

    @staticmethod
    def _decode(payload: str) -> tuple[GameMetadata, ...]:
        rows = json.loads(payload)
        return tuple(GameMetadata(
            row["provider"], row["external_id"], row["name"],
            tuple(Platform(platform) for platform in row["platforms"]), tuple(row["aliases"]),
            row["content_type"], row["edition"], row["source_url"],
        ) for row in rows)
