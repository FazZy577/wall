"""Local game registry and non-destructive migration of the packaged seed."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from application.interfaces.game_metadata import GameMetadata, IMetadataResolutionStore
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import Platform
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.entities.game_record import (
    ExternalGameReference,
    GameRecord,
    IdentityStatus,
    MediaFormat,
    ReleaseIdentity,
)
from domain.interfaces.game_registry import IGameRegistry
from infrastructure.matching.platform_lexical_matcher import PlatformLexicalMatcher


def create_registry_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("""CREATE TABLE IF NOT EXISTS games (
        game_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL,
        aliases_json TEXT NOT NULL, status TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS game_releases (
        release_id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(game_id),
        platform TEXT NOT NULL, edition TEXT NOT NULL, media_format TEXT NOT NULL,
        status TEXT NOT NULL, aliases_json TEXT NOT NULL,
        UNIQUE(game_id, platform, edition, media_format))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS external_game_references (
        provider TEXT NOT NULL, external_id TEXT NOT NULL,
        game_id TEXT NOT NULL REFERENCES games(game_id), PRIMARY KEY(provider, external_id))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS metadata_resolutions (
        attempt_id INTEGER PRIMARY KEY, listing_id TEXT NOT NULL,
        title TEXT NOT NULL, description TEXT NOT NULL, query TEXT NOT NULL,
        platform TEXT NOT NULL, status TEXT NOT NULL, candidates_json TEXT NOT NULL,
        game_id TEXT REFERENCES games(game_id), release_id TEXT REFERENCES game_releases(release_id),
        attempted_at TEXT NOT NULL)""")


class SqliteGameRegistry(IGameRegistry, IMetadataResolutionStore):
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database_path)) as connection, connection:
            create_registry_schema(connection)

    def import_seed(self, entries: tuple[GameCatalogEntry, ...]) -> None:
        """Import missing IDs atomically; never overwrite local names or statuses."""
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            create_registry_schema(connection)
            for entry in entries:
                identity = entry.release_identity
                if identity is None:
                    raise ValueError("Seed migration requires explicit stable IDs")
                connection.execute("INSERT OR IGNORE INTO games VALUES (?, ?, ?, ?)", (
                    identity.game_id, entry.canonical_name, "[]", IdentityStatus.CONFIRMED.value,
                ))
                existing = connection.execute(
                    "SELECT game_id, platform, edition, media_format FROM game_releases WHERE release_id = ?",
                    (identity.release_id,),
                ).fetchone()
                expected = (identity.game_id, identity.platform.value, identity.edition, identity.media_format.value)
                if existing is not None and existing != expected:
                    raise ValueError("Seed release ID conflicts with registered identity")
                if existing is None:
                    connection.execute("INSERT INTO game_releases VALUES (?, ?, ?, ?, ?, ?, ?)", (
                        identity.release_id, *expected, identity.status.value, json.dumps(entry.detection_aliases),
                    ))

    def get_game(self, game_id: str) -> GameRecord | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute("SELECT canonical_name, aliases_json, status FROM games WHERE game_id=?", (game_id,)).fetchone()
            if row is None:
                return None
            refs = connection.execute("SELECT provider, external_id FROM external_game_references WHERE game_id=? ORDER BY provider, external_id", (game_id,)).fetchall()
            return GameRecord(game_id, row[0], tuple(json.loads(row[1])), IdentityStatus(row[2]),
                              tuple(ExternalGameReference(*ref) for ref in refs))

    def save_game(self, game: GameRecord) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            create_registry_schema(connection)
            existing = connection.execute("SELECT canonical_name, aliases_json FROM games WHERE game_id=?", (game.game_id,)).fetchone()
            aliases = list(game.aliases)
            if existing and existing[0] != game.canonical_name:
                aliases = list(dict.fromkeys([*json.loads(existing[1]), existing[0], *aliases]))
            connection.execute("""INSERT INTO games VALUES (?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET canonical_name=excluded.canonical_name,
                aliases_json=excluded.aliases_json, status=excluded.status""",
                (game.game_id, game.canonical_name, json.dumps(aliases), game.status.value))
            connection.execute("DELETE FROM external_game_references WHERE game_id=?", (game.game_id,))
            connection.executemany("INSERT INTO external_game_references VALUES (?, ?, ?)", (
                (ref.provider, ref.external_id, game.game_id) for ref in game.external_references
            ))

    def save_release(self, release: ReleaseIdentity, aliases: tuple[str, ...] = ()) -> None:
        # Reusing an ID for a different platform/product is an error, not an update.
        GameRecord(release.game_id, "validation", aliases)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            create_registry_schema(connection)
            row = connection.execute("SELECT game_id, platform, edition, media_format FROM game_releases WHERE release_id=?", (release.release_id,)).fetchone()
            expected = (release.game_id, release.platform.value, release.edition, release.media_format.value)
            if row is not None and row != expected:
                raise ValueError("Cannot change the product associated with a release ID")
            connection.execute("""INSERT INTO game_releases VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(release_id) DO UPDATE SET status=excluded.status, aliases_json=excluded.aliases_json""",
                (release.release_id, *expected, release.status.value, json.dumps(aliases)))

    def list_games(self) -> tuple[GameCatalogEntry, ...]:
        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute("""SELECT g.canonical_name, r.platform, r.aliases_json,
                g.aliases_json, g.game_id, r.release_id, r.edition, r.media_format
                FROM game_releases r JOIN games g ON g.game_id=r.game_id
                WHERE g.status='confirmed' AND r.status='confirmed'
                ORDER BY g.game_id, r.release_id""").fetchall()
        return tuple(GameCatalogEntry(
            canonical_name=row[0], platform=Platform(row[1]),
            detection_aliases=tuple(dict.fromkeys([*json.loads(row[2]), *json.loads(row[3])])),
            release_identity=ReleaseIdentity(row[4], row[5], Platform(row[1]), row[6], MediaFormat(row[7])),
        ) for row in rows)

    def record_resolution(
        self, listing: CandidateListing, query: str, platform: Platform,
        status: str, candidates: tuple[GameMetadata, ...],
        selected: GameMetadata | None = None,
    ) -> GameCatalogEntry | None:
        """Store provider evidence and identity together, never overwrite a local identity."""
        if (selected is not None) != (status == "confirmed"):
            raise ValueError("Confirmed resolutions require selected metadata")
        if selected is not None and (selected not in candidates or platform not in selected.platforms):
            raise ValueError("Selected metadata must support this platform")
        entry = None
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            if selected is not None:
                ref = connection.execute(
                    "SELECT game_id FROM external_game_references WHERE provider=? AND external_id=?",
                    (selected.provider, selected.external_id),
                ).fetchone()
                if ref is None:
                    # Name equality alone cannot merge two provider identities or a local seed.
                    collisions = connection.execute(
                        """SELECT g.canonical_name, g.aliases_json, r.aliases_json
                           FROM games g LEFT JOIN game_releases r ON r.game_id=g.game_id
                           WHERE g.status='confirmed'"""
                    ).fetchall()
                    normalize = PlatformLexicalMatcher.normalize_text
                    proposed_names = {normalize(name) for name in (selected.name, *selected.aliases)}
                    existing_names = {
                        normalize(name) for row in collisions
                        for name in (row[0], *json.loads(row[1]), *json.loads(row[2] or "[]"))
                    }
                    if proposed_names & existing_names:
                        status = "ambiguous"
                    else:
                        game_id = str(uuid4())
                        connection.execute("INSERT INTO games VALUES (?, ?, ?, 'confirmed')",
                                           (game_id, selected.name, json.dumps(selected.aliases)))
                        connection.execute("INSERT INTO external_game_references VALUES (?, ?, ?)",
                                           (selected.provider, selected.external_id, game_id))
                        ref = (game_id,)
                else:
                    # Refresh only the same external identity; never learn seller text.
                    other_names = connection.execute("""SELECT g.canonical_name,g.aliases_json,r.aliases_json
                        FROM games g LEFT JOIN game_releases r ON r.game_id=g.game_id
                        WHERE g.status='confirmed' AND g.game_id<>?""", (ref[0],)).fetchall()
                    normalize = PlatformLexicalMatcher.normalize_text
                    incoming_names = {normalize(name) for name in (selected.name, *selected.aliases)}
                    occupied_names = {
                        normalize(name) for row in other_names
                        for name in (row[0], *json.loads(row[1]), *json.loads(row[2] or "[]"))
                    }
                    if incoming_names & occupied_names:
                        status = "ambiguous"
                        ref = None
                    else:
                        previous = connection.execute("SELECT canonical_name,aliases_json FROM games WHERE game_id=?",
                                                      (ref[0],)).fetchone()
                        aliases = tuple(dict.fromkeys((*json.loads(previous[1]), selected.name, *selected.aliases)))
                        aliases = tuple(alias for alias in aliases if alias != previous[0])
                        connection.execute("UPDATE games SET aliases_json=? WHERE game_id=?",
                                           (json.dumps(aliases), ref[0]))
                if ref is not None:
                    game_id = ref[0]
                    game = connection.execute(
                        "SELECT canonical_name, aliases_json, status FROM games WHERE game_id=?", (game_id,)
                    ).fetchone()
                    if game[2] != "confirmed":
                        raise ValueError("External reference belongs to an unconfirmed local identity")
                    release = connection.execute(
                        """SELECT release_id, status FROM game_releases WHERE game_id=? AND platform=?
                           AND edition='standard' AND media_format='physical'""", (game_id, platform.value)
                    ).fetchone()
                    if release is None:
                        release = (str(uuid4()), "confirmed")
                        connection.execute("INSERT INTO game_releases VALUES (?, ?, ?, 'standard', 'physical', 'confirmed', '[]')",
                                           (release[0], game_id, platform.value))
                    if release[1] != "confirmed":
                        raise ValueError("Cannot silently confirm an existing provisional release")
                    entry = GameCatalogEntry(game[0], platform, tuple(json.loads(game[1])),
                                             ReleaseIdentity(game_id, release[0], platform))
            connection.execute("""INSERT INTO metadata_resolutions
                (listing_id,title,description,query,platform,status,candidates_json,game_id,release_id,attempted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    listing.listing_id, listing.title, listing.description, query, platform.value, status,
                    json.dumps([asdict(candidate) for candidate in candidates], ensure_ascii=False),
                    entry.release_identity.game_id if entry and entry.release_identity else None,
                    entry.release_identity.release_id if entry and entry.release_identity else None,
                    datetime.now(UTC).isoformat(),
                ))
        return entry
