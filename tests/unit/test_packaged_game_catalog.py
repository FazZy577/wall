"""Tests for the validated packaged game-catalog adapter."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from domain.entities.detected_game import Platform
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.interfaces.game_catalog import IGameCatalog
from infrastructure.catalogs.packaged_game_catalog import (
    GameCatalogSchemaError,
    PackagedGameCatalog,
)


def _raw_entry(
    canonical_name: object = "Grand Theft Auto V",
    platform: object = "PS4",
    aliases: object = None,
    **additional_fields: object,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "canonical_name": canonical_name,
        "platform": platform,
        "aliases": ["gta v", "gta 5"] if aliases is None else aliases,
    }
    entry.update(additional_fields)
    return entry


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def packaged_catalog() -> PackagedGameCatalog:
    return PackagedGameCatalog()


def test_packaged_resource_matches_current_inventory(
    packaged_catalog: PackagedGameCatalog,
) -> None:
    games = packaged_catalog.list_games()

    assert isinstance(packaged_catalog, IGameCatalog)
    assert isinstance(games, tuple)
    assert len(games) == 50
    assert sum(len(game.detection_aliases) for game in games) == 166
    assert all(game.platform is Platform.PS4 for game in games)
    assert all(game.canonical_name for game in games)
    assert all(game.detection_aliases for game in games)
    assert all(isinstance(game.detection_aliases, tuple) for game in games)
    assert {game.canonical_name for game in games} >= {
        "Grand Theft Auto V",
        "Red Dead Redemption 2",
    }


def test_packaged_resource_has_unique_normalized_identities(
    packaged_catalog: PackagedGameCatalog,
) -> None:
    games = packaged_catalog.list_games()
    identities = {
        (" ".join(game.canonical_name.strip().casefold().split()), game.platform)
        for game in games
    }

    assert len(identities) == len(games)


def test_list_games_returns_the_single_immutable_snapshot(
    packaged_catalog: PackagedGameCatalog,
) -> None:
    first = packaged_catalog.list_games()
    second = packaged_catalog.list_games()

    assert first is second
    with pytest.raises(FrozenInstanceError):
        first[0].canonical_name = "Changed"  # type: ignore[misc]


def test_packaged_resource_is_independent_of_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    games = PackagedGameCatalog().list_games()

    assert len(games) == 50
    assert games[0].canonical_name == "Grand Theft Auto V"


def test_explicit_valid_path_is_loaded(tmp_path: Path) -> None:
    path = _write_json(tmp_path / "catalog.json", [_raw_entry()])

    games = PackagedGameCatalog(path).list_games()

    assert games == (
        GameCatalogEntry(
            canonical_name="Grand Theft Auto V",
            platform=Platform.PS4,
            detection_aliases=("gta v", "gta 5"),
        ),
    )


def test_missing_explicit_path_propagates_file_not_found(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match="Game catalog not found"):
        PackagedGameCatalog(missing_path)


def test_corrupt_json_propagates_decode_error(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        PackagedGameCatalog(path)


@pytest.mark.parametrize("root", [None, {}, "invalid", 123, True])
def test_non_list_root_is_rejected(tmp_path: Path, root: object) -> None:
    path = _write_json(tmp_path / "catalog.json", root)

    with pytest.raises(GameCatalogSchemaError, match="root must be a list"):
        PackagedGameCatalog(path)


@pytest.mark.parametrize("item", [None, "invalid", 123, [], True])
def test_non_object_entry_is_rejected(tmp_path: Path, item: object) -> None:
    path = _write_json(tmp_path / "catalog.json", [item])

    with pytest.raises(GameCatalogSchemaError, match="entry at index 0 must be an object"):
        PackagedGameCatalog(path)


@pytest.mark.parametrize(
    ("entry", "field", "reason"),
    [
        ({"platform": "PS4", "aliases": []}, "canonical_name", "is required"),
        (_raw_entry(canonical_name=123), "canonical_name", "must be a string"),
        (_raw_entry(canonical_name="  "), "canonical_name", "must not be empty"),
        ({"canonical_name": "GTA V", "aliases": []}, "platform", "is required"),
        (_raw_entry(platform=123), "platform", "must be a string"),
        (_raw_entry(platform="PS6"), "platform", "has unknown value"),
        (_raw_entry(platform="Unknown"), "platform", "must not be Platform.UNKNOWN"),
        (
            {"canonical_name": "GTA V", "platform": "PS4"},
            "aliases",
            "is required",
        ),
        (_raw_entry(aliases="gta v"), "aliases", "must be a list"),
        (_raw_entry(aliases=["gta v", 123]), "aliases\\[1\\]", "must be a string"),
        (_raw_entry(aliases=["gta v", "  "]), "aliases\\[1\\]", "must not be empty"),
    ],
)
def test_invalid_entry_field_rejects_complete_catalog(
    tmp_path: Path,
    entry: dict[str, object],
    field: str,
    reason: str,
) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [_raw_entry("Valid Before"), entry, _raw_entry("Valid After")],
    )

    with pytest.raises(
        GameCatalogSchemaError,
        match=rf"index 1.*field '{field}'.*{reason}",
    ):
        PackagedGameCatalog(path)


@pytest.mark.parametrize(
    "duplicate_name",
    [
        "Grand Theft Auto V",
        "grand theft auto v",
        "  GRAND   THEFT AUTO V  ",
    ],
)
def test_duplicate_normalized_name_and_platform_rejects_catalog(
    tmp_path: Path,
    duplicate_name: str,
) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [_raw_entry(), _raw_entry(duplicate_name)],
    )

    with pytest.raises(
        GameCatalogSchemaError,
        match="index 1.*duplicate fields.*first seen at index 0",
    ):
        PackagedGameCatalog(path)


def test_same_normalized_name_on_different_platforms_is_allowed(
    tmp_path: Path,
) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [_raw_entry(), _raw_entry(" grand theft auto v ", platform="PS5")],
    )

    games = PackagedGameCatalog(path).list_games()

    assert [game.platform for game in games] == [Platform.PS4, Platform.PS5]


def test_same_game_on_ps3_ps4_and_ps5_has_three_distinct_identities(
    tmp_path: Path,
) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [
            _raw_entry(platform="PS3"),
            _raw_entry(platform="PS4"),
            _raw_entry(platform="PS5"),
        ],
    )

    games = PackagedGameCatalog(path).list_games()

    assert [game.identity for game in games] == [
        GameCatalogEntry(
            "Grand Theft Auto V", Platform.PS3, ("gta v", "gta 5")
        ).identity,
        GameCatalogEntry(
            "Grand Theft Auto V", Platform.PS4, ("gta v", "gta 5")
        ).identity,
        GameCatalogEntry(
            "Grand Theft Auto V", Platform.PS5, ("gta v", "gta 5")
        ).identity,
    ]
    assert len({game.identity for game in games}) == 3


@pytest.mark.parametrize(
    ("first_name", "second_name"),
    [
        ("Ragnarök", "Ragnarok"),
        ("Game: One", "Game One"),
        ("Game II", "Game 2"),
    ],
)
def test_identity_does_not_remove_accents_punctuation_or_transform_numbers(
    tmp_path: Path,
    first_name: str,
    second_name: str,
) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [_raw_entry(first_name), _raw_entry(second_name)],
    )

    games = PackagedGameCatalog(path).list_games()

    assert [game.canonical_name for game in games] == [first_name, second_name]


def test_canonical_name_may_also_be_detection_alias(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [_raw_entry(aliases=["Grand Theft Auto V", "gta v"])],
    )

    games = PackagedGameCatalog(path).list_games()

    assert games[0].detection_aliases == ("Grand Theft Auto V", "gta v")


def test_detection_alias_may_be_repeated_between_different_games(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [
            _raw_entry("First Game", aliases=["shared"]),
            _raw_entry("Second Game", aliases=["shared"]),
        ],
    )

    games = PackagedGameCatalog(path).list_games()

    assert [game.detection_aliases for game in games] == [("shared",), ("shared",)]


def test_additional_fields_are_ignored(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "catalog.json",
        [_raw_entry(search_aliases=["gta v ps4"], edition="standard")],
    )

    games = PackagedGameCatalog(path).list_games()

    assert games == (
        GameCatalogEntry(
            "Grand Theft Auto V",
            Platform.PS4,
            ("gta v", "gta 5"),
        ),
    )
    assert not hasattr(games[0], "search_aliases")
    assert not hasattr(games[0], "edition")


def test_catalog_file_is_not_read_again_by_list_games(tmp_path: Path) -> None:
    path = _write_json(tmp_path / "catalog.json", [_raw_entry()])
    catalog = PackagedGameCatalog(path)
    expected = catalog.list_games()
    path.write_text("{now invalid", encoding="utf-8")

    assert catalog.list_games() is expected


def test_instances_do_not_share_mutable_state(tmp_path: Path) -> None:
    path = _write_json(tmp_path / "catalog.json", [_raw_entry()])

    first = PackagedGameCatalog(path).list_games()
    second = PackagedGameCatalog(path).list_games()

    assert first == second
    assert first is not second
    assert first[0] is not second[0]


def test_adapter_never_exposes_raw_dictionaries(
    packaged_catalog: PackagedGameCatalog,
) -> None:
    games = packaged_catalog.list_games()

    assert all(type(game) is GameCatalogEntry for game in games)
    assert all(not isinstance(game, dict) for game in games)
