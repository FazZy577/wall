"""Validated adapter for the packaged game-catalog resource."""

import json
from importlib.resources import files
from pathlib import Path
from typing import cast

from domain.entities.detected_game import Platform
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.interfaces.game_catalog import IGameCatalog


class GameCatalogSchemaError(ValueError):
    """The catalog JSON has an invalid schema or invalid domain values."""


class PackagedGameCatalog(IGameCatalog):
    """Load and validate one immutable catalog snapshot during construction."""

    def __init__(self, catalog_path: Path | str | None = None) -> None:
        self._catalog_path = Path(catalog_path) if catalog_path is not None else None
        self._games = self._load_games()

    def list_games(self) -> tuple[GameCatalogEntry, ...]:
        """Return the snapshot loaded during construction."""
        return self._games

    def _load_games(self) -> tuple[GameCatalogEntry, ...]:
        raw_catalog = self._load_raw_catalog()
        if not isinstance(raw_catalog, list):
            raise GameCatalogSchemaError("Game catalog root must be a list")

        games: list[GameCatalogEntry] = []
        seen_identities: dict[tuple[str, Platform], int] = {}
        for index, raw_entry in enumerate(raw_catalog):
            if not isinstance(raw_entry, dict):
                raise GameCatalogSchemaError(
                    f"Game catalog entry at index {index} must be an object"
                )

            entry = self._parse_entry(cast(dict[object, object], raw_entry), index)
            identity = self._identity(entry)
            if identity in seen_identities:
                first_index = seen_identities[identity]
                raise GameCatalogSchemaError(
                    f"Game catalog entry at index {index} has duplicate fields "
                    f"'canonical_name' and 'platform'; first seen at index {first_index}"
                )
            seen_identities[identity] = index
            games.append(entry)

        return tuple(games)

    def _load_raw_catalog(self) -> object:
        if self._catalog_path is not None:
            if not self._catalog_path.exists():
                raise FileNotFoundError(f"Game catalog not found: {self._catalog_path}")
            with self._catalog_path.open(encoding="utf-8") as catalog_file:
                raw_catalog: object = json.load(catalog_file)
                return raw_catalog

        catalog_resource = files("infrastructure.catalogs.resources").joinpath(
            "game_catalog.json"
        )
        with catalog_resource.open(encoding="utf-8") as catalog_file:
            packaged_catalog: object = json.load(catalog_file)
            return packaged_catalog

    @classmethod
    def _parse_entry(
        cls,
        raw_entry: dict[object, object],
        index: int,
    ) -> GameCatalogEntry:
        canonical_name = cls._required_field(raw_entry, "canonical_name", index)
        if not isinstance(canonical_name, str):
            raise cls._field_error(index, "canonical_name", "must be a string")
        if not canonical_name.strip():
            raise cls._field_error(index, "canonical_name", "must not be empty")

        raw_platform = cls._required_field(raw_entry, "platform", index)
        if not isinstance(raw_platform, str):
            raise cls._field_error(index, "platform", "must be a string")
        try:
            platform = Platform(raw_platform)
        except ValueError as error:
            raise cls._field_error(
                index,
                "platform",
                f"has unknown value {raw_platform!r}",
            ) from error
        if platform is Platform.UNKNOWN:
            raise cls._field_error(index, "platform", "must not be Platform.UNKNOWN")

        raw_aliases = cls._required_field(raw_entry, "aliases", index)
        if not isinstance(raw_aliases, list):
            raise cls._field_error(index, "aliases", "must be a list")

        aliases: list[str] = []
        for alias_index, raw_alias in enumerate(raw_aliases):
            alias_field = f"aliases[{alias_index}]"
            if not isinstance(raw_alias, str):
                raise cls._field_error(index, alias_field, "must be a string")
            if not raw_alias.strip():
                raise cls._field_error(index, alias_field, "must not be empty")
            aliases.append(raw_alias)

        return GameCatalogEntry(
            canonical_name=canonical_name,
            platform=platform,
            detection_aliases=tuple(aliases),
        )

    @staticmethod
    def _required_field(
        raw_entry: dict[object, object],
        field: str,
        index: int,
    ) -> object:
        if field not in raw_entry:
            raise PackagedGameCatalog._field_error(index, field, "is required")
        return raw_entry[field]

    @staticmethod
    def _field_error(
        index: int,
        field: str,
        reason: str,
    ) -> GameCatalogSchemaError:
        return GameCatalogSchemaError(
            f"Game catalog entry at index {index}: field {field!r} {reason}"
        )

    @staticmethod
    def _identity(entry: GameCatalogEntry) -> tuple[str, Platform]:
        normalized_name = " ".join(entry.canonical_name.strip().casefold().split())
        return normalized_name, entry.platform
