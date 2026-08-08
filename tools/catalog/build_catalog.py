"""Build and validate the deterministic runtime game catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

SCHEMA_VERSION = 1
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from domain.entities.detected_game import Platform  # noqa: E402
from domain.entities.game_catalog_entry import GameCatalogEntry  # noqa: E402
from domain.entities.game_identity import GameIdentity  # noqa: E402

DEFAULT_CATALOG_ROOT = REPOSITORY_ROOT / "catalog"
DEFAULT_RUNTIME_CATALOG = (
    REPOSITORY_ROOT
    / "src"
    / "infrastructure"
    / "catalogs"
    / "resources"
    / "game_catalog.json"
)


class CatalogBuildError(ValueError):
    """A versioned catalog source is invalid and cannot be built."""


class CatalogOutOfDateError(CatalogBuildError):
    """The checked runtime artifact does not match the versioned sources."""


@dataclass(frozen=True)
class CatalogManifest:
    """Validated build manifest with explicitly ordered sources."""

    schema_version: int
    catalog_version: int
    sources: tuple[Path, ...]


@dataclass(frozen=True)
class ShortAlias:
    """One intentionally reviewable short alias and its owning identity."""

    identity: GameIdentity
    alias: str


@dataclass(frozen=True)
class _LocatedEntry:
    entry: GameCatalogEntry
    source_path: Path
    game_index: int


def _require_object(raw_value: object, *, location: str) -> dict[object, object]:
    if not isinstance(raw_value, dict):
        raise CatalogBuildError(f"{location}: root must be an object")
    return cast(dict[object, object], raw_value)


def _read_json(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as source_file:
            return json.load(source_file)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogBuildError(f"{path}: cannot read valid UTF-8 JSON") from error


def _required(raw_object: dict[object, object], key: str, *, location: str) -> object:
    if key not in raw_object:
        raise CatalogBuildError(f"{location}: field {key!r} is required")
    return raw_object[key]


def _validate_positive_int(raw_value: object, *, field: str, location: str) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 1:
        raise CatalogBuildError(f"{location}: field {field!r} must be a positive integer")
    return raw_value


def load_manifest(catalog_root: Path) -> CatalogManifest:
    """Load and validate the manifest under ``catalog_root``."""
    if not isinstance(catalog_root, Path):
        raise TypeError("catalog_root must be pathlib.Path")

    manifest_path = catalog_root / "manifest.json"
    raw_manifest = _require_object(_read_json(manifest_path), location=str(manifest_path))
    schema_version = _validate_positive_int(
        _required(raw_manifest, "schema_version", location=str(manifest_path)),
        field="schema_version",
        location=str(manifest_path),
    )
    if schema_version != SCHEMA_VERSION:
        raise CatalogBuildError(
            f"{manifest_path}: unsupported schema_version {schema_version}; "
            f"expected {SCHEMA_VERSION}"
        )
    catalog_version = _validate_positive_int(
        _required(raw_manifest, "catalog_version", location=str(manifest_path)),
        field="catalog_version",
        location=str(manifest_path),
    )

    raw_sources = _required(raw_manifest, "sources", location=str(manifest_path))
    if not isinstance(raw_sources, list):
        raise CatalogBuildError(f"{manifest_path}: field 'sources' must be a list")

    catalog_root_resolved = catalog_root.resolve()
    sources: list[Path] = []
    seen_sources: set[Path] = set()
    for source_index, raw_source in enumerate(raw_sources):
        location = f"{manifest_path}: sources[{source_index}]"
        if not isinstance(raw_source, str):
            raise CatalogBuildError(f"{location} must be a string")
        if not raw_source.strip():
            raise CatalogBuildError(f"{location} must not be empty")

        relative_source = Path(raw_source)
        if relative_source.is_absolute() or ".." in relative_source.parts:
            raise CatalogBuildError(f"{location} must stay within the catalog directory")
        if relative_source.suffix.casefold() != ".json":
            raise CatalogBuildError(f"{location} must reference a .json file")

        resolved_source = (catalog_root / relative_source).resolve()
        if not resolved_source.is_relative_to(catalog_root_resolved):
            raise CatalogBuildError(f"{location} resolves outside the catalog directory")
        if resolved_source in seen_sources:
            raise CatalogBuildError(f"{location} duplicates an earlier source")
        if not resolved_source.is_file():
            raise CatalogBuildError(f"{location} does not exist: {relative_source.as_posix()}")
        seen_sources.add(resolved_source)
        sources.append(relative_source)

    return CatalogManifest(
        schema_version=schema_version,
        catalog_version=catalog_version,
        sources=tuple(sources),
    )


def _parse_source(catalog_root: Path, relative_path: Path) -> tuple[_LocatedEntry, ...]:
    source_path = catalog_root / relative_path
    raw_source = _require_object(_read_json(source_path), location=str(source_path))

    raw_platform = _required(raw_source, "platform", location=str(source_path))
    if not isinstance(raw_platform, str):
        raise CatalogBuildError(f"{source_path}: field 'platform' must be a string")
    try:
        platform = Platform(raw_platform)
    except ValueError as error:
        raise CatalogBuildError(
            f"{source_path}: field 'platform' has unknown value {raw_platform!r}"
        ) from error
    if platform is Platform.UNKNOWN:
        raise CatalogBuildError(f"{source_path}: Platform.UNKNOWN is not a catalog platform")

    raw_games = _required(raw_source, "games", location=str(source_path))
    if not isinstance(raw_games, list):
        raise CatalogBuildError(f"{source_path}: field 'games' must be a list")

    located_entries: list[_LocatedEntry] = []
    for game_index, raw_game in enumerate(raw_games):
        location = f"{source_path}: games[{game_index}]"
        if not isinstance(raw_game, dict):
            raise CatalogBuildError(f"{location} must be an object")
        game = cast(dict[object, object], raw_game)

        canonical_name = _required(game, "canonical_name", location=location)
        if not isinstance(canonical_name, str):
            raise CatalogBuildError(f"{location}: field 'canonical_name' must be a string")
        if not canonical_name.strip():
            raise CatalogBuildError(f"{location}: field 'canonical_name' must not be empty")

        raw_aliases = _required(game, "aliases", location=location)
        if not isinstance(raw_aliases, list):
            raise CatalogBuildError(f"{location}: field 'aliases' must be a list")
        aliases: list[str] = []
        for alias_index, raw_alias in enumerate(raw_aliases):
            alias_location = f"{location}: aliases[{alias_index}]"
            if not isinstance(raw_alias, str):
                raise CatalogBuildError(f"{alias_location} must be a string")
            if not raw_alias.strip():
                raise CatalogBuildError(f"{alias_location} must not be empty")
            aliases.append(raw_alias)

        entry = GameCatalogEntry(
            canonical_name=canonical_name,
            platform=platform,
            detection_aliases=tuple(aliases),
        )
        located_entries.append(_LocatedEntry(entry, relative_path, game_index))
    return tuple(located_entries)


def load_sources(
    catalog_root: Path,
    manifest: CatalogManifest,
) -> tuple[_LocatedEntry, ...]:
    """Load source entries in manifest order and file order."""
    if not isinstance(catalog_root, Path):
        raise TypeError("catalog_root must be pathlib.Path")
    if not isinstance(manifest, CatalogManifest):
        raise TypeError("manifest must be CatalogManifest")
    return tuple(
        entry
        for relative_path in manifest.sources
        for entry in _parse_source(catalog_root, relative_path)
    )


def _normalize_term(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def validate_catalog(located_entries: Sequence[_LocatedEntry]) -> tuple[GameCatalogEntry, ...]:
    """Validate global identity and lexical uniqueness in linear time."""
    identities: dict[GameIdentity, _LocatedEntry] = {}
    lexical_owners: dict[tuple[Platform, str], _LocatedEntry] = {}

    for located in located_entries:
        entry = located.entry
        previous_identity = identities.get(entry.identity)
        if previous_identity is not None:
            raise CatalogBuildError(
                f"{located.source_path}: games[{located.game_index}] identity "
                f"{entry.canonical_name!r} / {entry.platform.value} duplicates "
                f"{previous_identity.source_path}: games[{previous_identity.game_index}]"
            )
        identities[entry.identity] = located

        canonical_key = (entry.platform, _normalize_term(entry.canonical_name))
        previous_owner = lexical_owners.get(canonical_key)
        if previous_owner is not None and previous_owner.entry.identity != entry.identity:
            raise CatalogBuildError(
                f"{located.source_path}: canonical name {entry.canonical_name!r} collides "
                f"with {previous_owner.entry.canonical_name!r} on {entry.platform.value}"
            )
        lexical_owners[canonical_key] = located

        aliases_in_entry: set[str] = set()
        for alias in entry.detection_aliases:
            normalized_alias = _normalize_term(alias)
            if normalized_alias in aliases_in_entry:
                raise CatalogBuildError(
                    f"{located.source_path}: games[{located.game_index}] alias {alias!r} "
                    f"is duplicated for {entry.canonical_name!r}"
                )
            aliases_in_entry.add(normalized_alias)

            alias_key = (entry.platform, normalized_alias)
            previous_owner = lexical_owners.get(alias_key)
            if previous_owner is not None and previous_owner.entry.identity != entry.identity:
                raise CatalogBuildError(
                    f"{located.source_path}: alias {alias!r} collides between "
                    f"{previous_owner.entry.canonical_name!r} and "
                    f"{entry.canonical_name!r} on {entry.platform.value}"
                )
            lexical_owners[alias_key] = located

    return tuple(located.entry for located in located_entries)


def build_runtime_entries(catalog_root: Path) -> tuple[GameCatalogEntry, ...]:
    """Build a fully validated immutable snapshot from versioned sources."""
    manifest = load_manifest(catalog_root)
    return validate_catalog(load_sources(catalog_root, manifest))


def find_short_aliases(
    entries: Sequence[GameCatalogEntry],
    *,
    maximum_length: int = 3,
) -> tuple[ShortAlias, ...]:
    """Enumerate aliases whose normalized form merits manual review."""
    if isinstance(maximum_length, bool) or not isinstance(maximum_length, int):
        raise TypeError("maximum_length must be int")
    if maximum_length < 1:
        raise ValueError("maximum_length must be positive")
    return tuple(
        ShortAlias(entry.identity, alias)
        for entry in entries
        for alias in entry.detection_aliases
        if len(_normalize_term(alias)) <= maximum_length
    )


def render_runtime_catalog(entries: Sequence[GameCatalogEntry]) -> bytes:
    """Render deterministic UTF-8 bytes in the runtime loader schema."""
    payload = [
        {
            "canonical_name": entry.canonical_name,
            "platform": entry.platform.value,
            "aliases": list(entry.detection_aliases),
        }
        for entry in entries
    ]
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def generate_runtime_catalog(catalog_root: Path = DEFAULT_CATALOG_ROOT) -> bytes:
    """Validate versioned sources and render the complete runtime artifact."""
    return render_runtime_catalog(build_runtime_entries(catalog_root))


def write_runtime_catalog(rendered_catalog: bytes, artifact_path: Path) -> None:
    """Atomically replace the runtime artifact with already validated bytes."""
    if not isinstance(rendered_catalog, bytes):
        raise TypeError("rendered_catalog must be bytes")
    if not isinstance(artifact_path, Path):
        raise TypeError("artifact_path must be pathlib.Path")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=artifact_path.parent,
            prefix=f".{artifact_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(rendered_catalog)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, artifact_path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise CatalogBuildError(f"Cannot write runtime catalog: {artifact_path}") from error


def build_catalog(
    catalog_root: Path = DEFAULT_CATALOG_ROOT,
    artifact_path: Path = DEFAULT_RUNTIME_CATALOG,
) -> None:
    """Validate all sources before atomically writing the runtime artifact."""
    rendered_catalog = generate_runtime_catalog(catalog_root)
    write_runtime_catalog(rendered_catalog, artifact_path)


def check_runtime_catalog(
    catalog_root: Path = DEFAULT_CATALOG_ROOT,
    artifact_path: Path = DEFAULT_RUNTIME_CATALOG,
) -> None:
    """Fail when the versioned runtime artifact is missing or out of date."""
    rendered_catalog = generate_runtime_catalog(catalog_root)
    try:
        current_catalog = artifact_path.read_bytes()
    except OSError as error:
        raise CatalogOutOfDateError(
            f"Generated catalog is out of date: artifact is missing: {artifact_path}"
        ) from error
    if current_catalog != rendered_catalog:
        raise CatalogOutOfDateError(
            f"Generated catalog is out of date: {artifact_path}"
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the deterministic runtime game catalog from versioned sources."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the runtime artifact exactly matches the sources",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the repository-local catalog build command."""
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.check:
            check_runtime_catalog()
        else:
            build_catalog()
    except CatalogBuildError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
