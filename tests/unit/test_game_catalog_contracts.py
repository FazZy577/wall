"""Contracts for canonical game-catalog entries and the read-only port."""

from dataclasses import FrozenInstanceError
from typing import get_type_hints

import pytest

from domain.entities.detected_game import Platform
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.entities.game_identity import GameIdentity
from domain.interfaces.game_catalog import IGameCatalog

CONCRETE_PLATFORMS = (
    Platform.PS2,
    Platform.PS3,
    Platform.PS4,
    Platform.PS5,
    Platform.XBOX,
    Platform.XBOX_360,
    Platform.XBOX_ONE,
    Platform.XBOX_SERIES,
    Platform.GAMECUBE,
    Platform.WII,
    Platform.WII_U,
    Platform.SWITCH,
    Platform.NINTENDO_DS,
    Platform.NINTENDO_3DS,
    Platform.PSP,
    Platform.PS_VITA,
)


def _entry(
    *,
    canonical_name: object = "Grand Theft Auto V",
    platform: object = Platform.PS4,
    aliases: object = ("gta v", "gta 5"),
) -> GameCatalogEntry:
    return GameCatalogEntry(
        canonical_name=canonical_name,  # type: ignore[arg-type]
        platform=platform,  # type: ignore[arg-type]
        detection_aliases=aliases,  # type: ignore[arg-type]
    )


def test_valid_entry_preserves_domain_values() -> None:
    entry = _entry()

    assert entry == GameCatalogEntry(
        canonical_name="Grand Theft Auto V",
        platform=Platform.PS4,
        detection_aliases=("gta v", "gta 5"),
    )


def test_canonical_name_is_stripped_without_other_normalization() -> None:
    entry = _entry(canonical_name="  God of War: Ragnarök II  ")

    assert entry.canonical_name == "God of War: Ragnarök II"


@pytest.mark.parametrize("canonical_name", ["", " ", "\t\n"])
def test_empty_canonical_name_is_rejected(canonical_name: str) -> None:
    with pytest.raises(ValueError, match="canonical_name must not be empty"):
        _entry(canonical_name=canonical_name)


@pytest.mark.parametrize("canonical_name", [None, 123, object()])
def test_non_string_canonical_name_is_rejected(canonical_name: object) -> None:
    with pytest.raises(TypeError, match="canonical_name must be str"):
        _entry(canonical_name=canonical_name)


@pytest.mark.parametrize(
    "platform",
    CONCRETE_PLATFORMS,
)
def test_concrete_platforms_are_valid(platform: Platform) -> None:
    assert _entry(platform=platform).platform is platform


def test_platform_has_exact_supported_members_and_stable_values() -> None:
    assert list(Platform) == [*CONCRETE_PLATFORMS, Platform.UNKNOWN]
    assert [platform.value for platform in Platform] == [
        "PS2",
        "PS3",
        "PS4",
        "PS5",
        "Xbox",
        "Xbox 360",
        "Xbox One",
        "Xbox Series",
        "Nintendo GameCube",
        "Nintendo Wii",
        "Nintendo Wii U",
        "Nintendo Switch",
        "Nintendo DS",
        "Nintendo 3DS",
        "PSP",
        "PS Vita",
        "Unknown",
    ]
    assert len({platform.value for platform in Platform}) == len(Platform)
    for variant in (
        "PS4_PRO",
        "PS5_PRO",
        "PS2_SLIM",
        "PS3_SLIM",
        "XBOX_ONE_S",
        "XBOX_ONE_X",
        "XBOX_SERIES_S",
        "XBOX_SERIES_X",
        "SWITCH_LITE",
        "SWITCH_OLED",
    ):
        assert not hasattr(Platform, variant)


@pytest.mark.parametrize("platform", ["PS4", None, 4, object()])
def test_non_platform_value_is_rejected(platform: object) -> None:
    with pytest.raises(TypeError, match="platform must be Platform"):
        _entry(platform=platform)


def test_unknown_platform_is_rejected() -> None:
    with pytest.raises(ValueError, match="platform must not be Platform.UNKNOWN"):
        _entry(platform=Platform.UNKNOWN)


def test_catalog_entry_exposes_total_canonical_identity() -> None:
    entry = _entry(canonical_name="  GRAND   THEFT AUTO V  ", platform=Platform.PS3)

    assert entry.identity == GameIdentity("grand theft auto v", Platform.PS3)


def test_external_alias_list_is_snapshotted_as_tuple() -> None:
    aliases = ["gta v", "gta 5"]

    entry = _entry(aliases=aliases)
    aliases.append("gtav")

    assert entry.detection_aliases == ("gta v", "gta 5")
    assert isinstance(entry.detection_aliases, tuple)


def test_alias_order_and_duplicates_are_preserved() -> None:
    entry = _entry(aliases=["gta 5", "gta v", "gta 5"])

    assert entry.detection_aliases == ("gta 5", "gta v", "gta 5")


def test_aliases_are_stripped_without_other_normalization() -> None:
    entry = _entry(aliases=["  GTA V  ", " Ragnarök II "])

    assert entry.detection_aliases == ("GTA V", "Ragnarök II")


@pytest.mark.parametrize("alias", ["", " ", "\t\n"])
def test_empty_alias_is_rejected(alias: str) -> None:
    with pytest.raises(ValueError, match="empty aliases"):
        _entry(aliases=["gta v", alias])


@pytest.mark.parametrize("alias", [None, 123, object()])
def test_non_string_alias_is_rejected(alias: object) -> None:
    with pytest.raises(TypeError, match="contain only strings"):
        _entry(aliases=["gta v", alias])


@pytest.mark.parametrize("aliases", ["gta v", b"gta v", None, 123, object()])
def test_non_sequence_collection_is_rejected(aliases: object) -> None:
    with pytest.raises(TypeError, match="sequence of strings"):
        _entry(aliases=aliases)


def test_empty_alias_collection_is_allowed() -> None:
    assert _entry(aliases=[]).detection_aliases == ()


def test_entry_is_frozen() -> None:
    entry = _entry()

    with pytest.raises(FrozenInstanceError):
        entry.canonical_name = "Other"  # type: ignore[misc]


def test_game_catalog_port_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        IGameCatalog()


def test_synchronous_fake_catalog_can_return_tuple_snapshot() -> None:
    entries = (_entry(),)

    class FakeGameCatalog(IGameCatalog):
        def list_games(self) -> tuple[GameCatalogEntry, ...]:
            return entries

    catalog = FakeGameCatalog()

    assert catalog.list_games() is entries
    assert get_type_hints(IGameCatalog.list_games)["return"] == tuple[
        GameCatalogEntry, ...
    ]
