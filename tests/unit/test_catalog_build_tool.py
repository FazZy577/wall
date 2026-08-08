"""Tests for the versioned, deterministic game-catalog build pipeline."""

import json
from pathlib import Path

import pytest

from domain.entities.detected_game import Platform
from domain.entities.game_identity import GameIdentity
from tools.catalog import build_catalog as catalog_tool
from tools.catalog.build_catalog import (
    CatalogBuildError,
    CatalogOutOfDateError,
    build_catalog,
    build_runtime_entries,
    check_runtime_catalog,
    find_short_aliases,
    generate_runtime_catalog,
    load_manifest,
    write_runtime_catalog,
)

_DEFAULT = object()


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _game(
    canonical_name: object = "Grand Theft Auto V",
    aliases: object = _DEFAULT,
) -> dict[str, object]:
    return {
        "canonical_name": canonical_name,
        "aliases": ["gta v", "gta 5"] if aliases is _DEFAULT else aliases,
    }


def _source(platform: object = "PS4", games: object = _DEFAULT) -> dict[str, object]:
    return {
        "platform": platform,
        "games": [_game()] if games is _DEFAULT else games,
    }


def _write_catalog(
    root: Path,
    *,
    sources: tuple[tuple[str, object], ...] = (("platforms/ps4.json", _DEFAULT),),
    schema_version: object = 1,
    catalog_version: object = 1,
) -> Path:
    manifest_sources: list[str] = []
    for source_name, payload in sources:
        manifest_sources.append(source_name)
        _write_json(root / source_name, _source() if payload is _DEFAULT else payload)
    _write_json(
        root / "manifest.json",
        {
            "schema_version": schema_version,
            "catalog_version": catalog_version,
            "sources": manifest_sources,
        },
    )
    return root


def test_valid_manifest_preserves_explicit_source_order(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(
            ("platforms/second.json", _source(games=[_game("Second", ["second"])])),
            ("platforms/first.json", _source(games=[_game("First", ["first"])])),
        ),
        catalog_version=7,
    )

    manifest = load_manifest(root)
    entries = build_runtime_entries(root)

    assert manifest.schema_version == 1
    assert manifest.catalog_version == 7
    assert manifest.sources == (
        Path("platforms/second.json"),
        Path("platforms/first.json"),
    )
    assert [entry.canonical_name for entry in entries] == ["Second", "First"]


@pytest.mark.parametrize("root_payload", [None, [], "invalid", 1, True])
def test_manifest_root_must_be_object(tmp_path: Path, root_payload: object) -> None:
    root = tmp_path / "catalog"
    _write_json(root / "manifest.json", root_payload)

    with pytest.raises(CatalogBuildError, match="root must be an object"):
        load_manifest(root)


@pytest.mark.parametrize("missing_field", ["schema_version", "catalog_version", "sources"])
def test_manifest_requires_all_fields(tmp_path: Path, missing_field: str) -> None:
    root = tmp_path / "catalog"
    payload = {"schema_version": 1, "catalog_version": 1, "sources": []}
    del payload[missing_field]
    _write_json(root / "manifest.json", payload)

    with pytest.raises(CatalogBuildError, match=rf"field '{missing_field}' is required"):
        load_manifest(root)


@pytest.mark.parametrize("schema_version", [0, 2, -1, True, "1"])
def test_manifest_rejects_invalid_or_unknown_schema_version(
    tmp_path: Path,
    schema_version: object,
) -> None:
    root = _write_catalog(tmp_path / "catalog", schema_version=schema_version)

    with pytest.raises(CatalogBuildError, match="schema_version"):
        load_manifest(root)


@pytest.mark.parametrize("catalog_version", [0, -1, True, 1.5, "1"])
def test_manifest_rejects_invalid_catalog_version(
    tmp_path: Path,
    catalog_version: object,
) -> None:
    root = _write_catalog(tmp_path / "catalog", catalog_version=catalog_version)

    with pytest.raises(CatalogBuildError, match="catalog_version"):
        load_manifest(root)


def test_manifest_sources_must_be_list(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    _write_json(
        root / "manifest.json",
        {"schema_version": 1, "catalog_version": 1, "sources": "ps4.json"},
    )

    with pytest.raises(CatalogBuildError, match="'sources' must be a list"):
        load_manifest(root)


@pytest.mark.parametrize("source", [None, 1, True, [], {}])
def test_manifest_source_must_be_string(tmp_path: Path, source: object) -> None:
    root = tmp_path / "catalog"
    _write_json(
        root / "manifest.json",
        {"schema_version": 1, "catalog_version": 1, "sources": [source]},
    )

    with pytest.raises(CatalogBuildError, match=r"sources\[0\] must be a string"):
        load_manifest(root)


@pytest.mark.parametrize("source", ["", "   "])
def test_manifest_source_must_not_be_empty(tmp_path: Path, source: str) -> None:
    root = tmp_path / "catalog"
    _write_json(
        root / "manifest.json",
        {"schema_version": 1, "catalog_version": 1, "sources": [source]},
    )

    with pytest.raises(CatalogBuildError, match="must not be empty"):
        load_manifest(root)


def test_manifest_rejects_duplicate_source_after_path_resolution(tmp_path: Path) -> None:
    root = _write_catalog(tmp_path / "catalog")
    _write_json(
        root / "manifest.json",
        {
            "schema_version": 1,
            "catalog_version": 1,
            "sources": ["platforms/ps4.json", "platforms/./ps4.json"],
        },
    )

    with pytest.raises(CatalogBuildError, match="duplicates an earlier source"):
        load_manifest(root)


@pytest.mark.parametrize("source", ["../outside.json", "platforms/../../outside.json"])
def test_manifest_rejects_path_traversal(tmp_path: Path, source: str) -> None:
    root = tmp_path / "catalog"
    _write_json(
        root / "manifest.json",
        {"schema_version": 1, "catalog_version": 1, "sources": [source]},
    )

    with pytest.raises(CatalogBuildError, match="within the catalog directory"):
        load_manifest(root)


def test_manifest_rejects_absolute_source_path(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    _write_json(
        root / "manifest.json",
        {
            "schema_version": 1,
            "catalog_version": 1,
            "sources": [str((tmp_path / "source.json").resolve())],
        },
    )

    with pytest.raises(CatalogBuildError, match="within the catalog directory"):
        load_manifest(root)


def test_manifest_rejects_unexpected_extension(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    _write_json(
        root / "manifest.json",
        {"schema_version": 1, "catalog_version": 1, "sources": ["source.toml"]},
    )

    with pytest.raises(CatalogBuildError, match=r"\.json"):
        load_manifest(root)


def test_manifest_rejects_missing_source(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    _write_json(
        root / "manifest.json",
        {"schema_version": 1, "catalog_version": 1, "sources": ["missing.json"]},
    )

    with pytest.raises(CatalogBuildError, match="does not exist"):
        load_manifest(root)


@pytest.mark.parametrize("source_root", [None, [], "invalid", 1, True])
def test_source_root_must_be_object(tmp_path: Path, source_root: object) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(("platforms/source.json", source_root),),
    )

    with pytest.raises(CatalogBuildError, match="root must be an object"):
        build_runtime_entries(root)


@pytest.mark.parametrize("platform", [None, 1, True, "PS6", "Unknown"])
def test_source_rejects_invalid_or_unknown_platform(
    tmp_path: Path,
    platform: object,
) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(("platforms/source.json", _source(platform=platform)),),
    )

    with pytest.raises(CatalogBuildError, match="platform|UNKNOWN"):
        build_runtime_entries(root)


@pytest.mark.parametrize("games", [None, "invalid", 1, True, {}])
def test_source_games_must_be_list(tmp_path: Path, games: object) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(("platforms/source.json", {"platform": "PS4", "games": games}),),
    )

    with pytest.raises(CatalogBuildError, match="'games' must be a list"):
        build_runtime_entries(root)


@pytest.mark.parametrize("game", [None, "invalid", 1, True, []])
def test_source_game_must_be_object(tmp_path: Path, game: object) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(("platforms/source.json", _source(games=[game])),),
    )

    with pytest.raises(CatalogBuildError, match=r"games\[0\] must be an object"):
        build_runtime_entries(root)


@pytest.mark.parametrize("canonical_name", [None, 1, True, "", "  "])
def test_source_rejects_invalid_canonical_name(
    tmp_path: Path,
    canonical_name: object,
) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(("platforms/source.json", _source(games=[_game(canonical_name)])),),
    )

    with pytest.raises(CatalogBuildError, match="canonical_name"):
        build_runtime_entries(root)


@pytest.mark.parametrize("aliases", [None, "alias", 1, True, {}])
def test_source_aliases_must_be_list(tmp_path: Path, aliases: object) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(("platforms/source.json", _source(games=[_game(aliases=aliases)])),),
    )

    with pytest.raises(CatalogBuildError, match="'aliases' must be a list"):
        build_runtime_entries(root)


@pytest.mark.parametrize("alias", [None, 1, True, "", "  "])
def test_source_rejects_invalid_alias(tmp_path: Path, alias: object) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(("platforms/source.json", _source(games=[_game(aliases=[alias])])),),
    )

    with pytest.raises(CatalogBuildError, match=r"aliases\[0\]"):
        build_runtime_entries(root)


@pytest.mark.parametrize("duplicate_name", ["Game A", " game a ", "GAME   A"])
def test_duplicate_identity_in_one_source_is_rejected(
    tmp_path: Path,
    duplicate_name: str,
) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=((
            "platforms/ps4.json",
            _source(games=[_game("Game A", ["a"]), _game(duplicate_name, ["b"])]),
        ),),
    )

    with pytest.raises(CatalogBuildError, match="identity.*duplicates"):
        build_runtime_entries(root)


def test_duplicate_identity_across_sources_is_rejected(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(
            ("platforms/one.json", _source(games=[_game("Game A", ["a"])])),
            ("platforms/two.json", _source(games=[_game(" game a ", ["b"])])),
        ),
    )

    with pytest.raises(CatalogBuildError, match="identity.*duplicates"):
        build_runtime_entries(root)


def test_same_name_on_different_platforms_is_allowed(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(
            ("platforms/ps4.json", _source("PS4", [_game("Game A", ["shared"])])),
            ("platforms/ps5.json", _source("PS5", [_game(" game a ", ["shared"])])),
        ),
    )

    entries = build_runtime_entries(root)

    assert [entry.identity for entry in entries] == [
        GameIdentity("Game A", Platform.PS4),
        GameIdentity("Game A", Platform.PS5),
    ]


def test_duplicate_alias_within_identity_is_rejected(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=((
            "platforms/ps4.json",
            _source(games=[_game("Game A", ["Alias", " alias  "])]),
        ),),
    )

    with pytest.raises(CatalogBuildError, match="alias.*duplicated"):
        build_runtime_entries(root)


def test_alias_collision_within_platform_is_rejected(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=((
            "platforms/ps4.json",
            _source(games=[_game("Game A", ["Shared"]), _game("Game B", [" shared "])]),
        ),),
    )

    with pytest.raises(CatalogBuildError, match="alias.*collides.*PS4"):
        build_runtime_entries(root)


def test_alias_reuse_across_platforms_is_allowed(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=(
            ("platforms/ps4.json", _source("PS4", [_game("Game A", ["shared"])])),
            ("platforms/ps5.json", _source("PS5", [_game("Game B", ["shared"])])),
        ),
    )

    assert len(build_runtime_entries(root)) == 2


def test_canonical_name_vs_alias_collision_is_rejected(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=((
            "platforms/ps4.json",
            _source(games=[_game("Alpha", ["first"]), _game("Beta", [" alpha "])]),
        ),),
    )

    with pytest.raises(CatalogBuildError, match="alias.*collides.*PS4"):
        build_runtime_entries(root)


def test_short_aliases_are_enumerated_without_rejection(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=((
            "platforms/ps4.json",
            _source(games=[_game("God of War", ["gow", "god of war"])]),
        ),),
    )

    short_aliases = find_short_aliases(build_runtime_entries(root))

    assert short_aliases[0].identity == GameIdentity("God of War", Platform.PS4)
    assert [alias.alias for alias in short_aliases] == ["gow"]


def test_render_is_deterministic_utf8_and_preserves_unicode(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=((
            "platforms/ps4.json",
            _source(games=[_game("God of War Ragnarök", ["ragnarök"])]),
        ),),
    )

    first = generate_runtime_catalog(root)
    second = generate_runtime_catalog(root)

    assert first == second
    assert first.endswith(b"\n")
    assert b"Ragnar\xc3\xb6k" in first
    assert b"\r\n" not in first
    assert json.loads(first) == [
        {
            "canonical_name": "God of War Ragnarök",
            "platform": "PS4",
            "aliases": ["ragnarök"],
        }
    ]


def test_check_succeeds_for_exact_artifact(tmp_path: Path) -> None:
    root = _write_catalog(tmp_path / "catalog")
    artifact = tmp_path / "game_catalog.json"
    artifact.write_bytes(generate_runtime_catalog(root))

    assert check_runtime_catalog(root, artifact) is None


@pytest.mark.parametrize("existing", [b"[]\n", b"out of date"])
def test_check_rejects_outdated_artifact_without_writing(
    tmp_path: Path,
    existing: bytes,
) -> None:
    root = _write_catalog(tmp_path / "catalog")
    artifact = tmp_path / "game_catalog.json"
    artifact.write_bytes(existing)

    with pytest.raises(CatalogOutOfDateError, match="out of date"):
        check_runtime_catalog(root, artifact)

    assert artifact.read_bytes() == existing
    assert list(tmp_path.glob("*.tmp")) == []


def test_check_rejects_missing_artifact_without_creating_it(tmp_path: Path) -> None:
    root = _write_catalog(tmp_path / "catalog")
    artifact = tmp_path / "missing.json"

    with pytest.raises(CatalogOutOfDateError, match="artifact is missing"):
        check_runtime_catalog(root, artifact)

    assert not artifact.exists()


def test_build_writes_exact_generated_bytes_atomically(tmp_path: Path) -> None:
    root = _write_catalog(tmp_path / "catalog")
    artifact = tmp_path / "game_catalog.json"

    build_catalog(root, artifact)

    assert artifact.read_bytes() == generate_runtime_catalog(root)
    assert list(tmp_path.glob(f".{artifact.name}.*.tmp")) == []


def test_validation_failure_does_not_overwrite_artifact(tmp_path: Path) -> None:
    root = _write_catalog(
        tmp_path / "catalog",
        sources=((
            "platforms/ps4.json",
            _source(games=[_game("Duplicate", ["same"]), _game("duplicate", ["other"])]),
        ),),
    )
    artifact = tmp_path / "game_catalog.json"
    artifact.write_bytes(b"existing")

    with pytest.raises(CatalogBuildError):
        build_catalog(root, artifact)

    assert artifact.read_bytes() == b"existing"
    assert list(tmp_path.glob(f".{artifact.name}.*.tmp")) == []


def test_write_failure_cleans_temporary_and_preserves_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "game_catalog.json"
    artifact.write_bytes(b"existing")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(catalog_tool.os, "replace", fail_replace)

    with pytest.raises(CatalogBuildError, match="Cannot write runtime catalog") as caught:
        write_runtime_catalog(b"replacement", artifact)

    assert isinstance(caught.value.__cause__, OSError)
    assert artifact.read_bytes() == b"existing"
    assert list(tmp_path.glob(f".{artifact.name}.*.tmp")) == []


def test_repository_sources_exactly_match_runtime_artifact() -> None:
    assert check_runtime_catalog() is None


def test_repository_inventory_remains_exactly_50_ps4_entries() -> None:
    entries = build_runtime_entries(catalog_tool.DEFAULT_CATALOG_ROOT)

    assert len(entries) == 50
    assert sum(len(entry.detection_aliases) for entry in entries) == 166
    assert {entry.platform for entry in entries} == {Platform.PS4}
    assert [entry.canonical_name for entry in entries[:2]] == [
        "Grand Theft Auto V",
        "Red Dead Redemption 2",
    ]


def test_repository_short_alias_inventory_is_explicitly_reviewable() -> None:
    entries = build_runtime_entries(catalog_tool.DEFAULT_CATALOG_ROOT)

    assert [short.alias for short in find_short_aliases(entries)] == [
        "bo6",
        "mw3",
        "mw2",
        "gow",
        "hzd",
        "hfw",
        "got",
        "re2",
        "re3",
        "re8",
        "ds3",
        "gts",
        "gt7",
        "bf5",
        "bfv",
        "sf5",
        "sfv",
        "ow2",
    ]


def test_runtime_resource_has_catalog_ownership_and_single_productive_reference() -> None:
    repository_root = catalog_tool.REPOSITORY_ROOT
    old_resource = (
        repository_root
        / "src"
        / "infrastructure"
        / "detectors"
        / "resources"
        / "game_catalog.json"
    )
    new_resource = catalog_tool.DEFAULT_RUNTIME_CATALOG
    references = [
        path
        for path in (repository_root / "src").rglob("*.py")
        if "game_catalog.json" in path.read_text(encoding="utf-8")
    ]

    assert not old_resource.exists()
    assert new_resource.is_file()
    assert references == [
        repository_root / "src" / "infrastructure" / "catalogs" / "packaged_game_catalog.py"
    ]
