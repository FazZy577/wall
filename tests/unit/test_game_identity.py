"""Contracts for canonical game-and-platform identity."""

import ast
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from domain.entities.detected_game import Platform
from domain.entities.game_identity import GameIdentity


@pytest.mark.parametrize(
    "platform",
    [
        Platform.PS3,
        Platform.PS4,
        Platform.PS5,
        Platform.XBOX_360,
        Platform.GAMECUBE,
        Platform.WII_U,
        Platform.NINTENDO_3DS,
        Platform.PSP,
        Platform.PS_VITA,
    ],
)
def test_concrete_platform_identity_is_valid(platform: Platform) -> None:
    identity = GameIdentity("Grand Theft Auto V", platform)

    assert identity.canonical_name == "grand theft auto v"
    assert identity.platform is platform


@pytest.mark.parametrize(
    "canonical_name",
    [
        "Grand Theft Auto V",
        " grand theft auto v ",
        "GRAND   THEFT AUTO V",
        "\tGrand\nTheft  Auto V\r",
    ],
)
def test_name_normalization_produces_the_same_identity(
    canonical_name: str,
) -> None:
    assert GameIdentity(canonical_name, Platform.PS4) == GameIdentity(
        "grand theft auto v",
        Platform.PS4,
    )


def test_normalization_does_not_remove_accents_or_punctuation() -> None:
    identity = GameIdentity("  Ragnarök:   II  ", Platform.PS5)

    assert identity.canonical_name == "ragnarök: ii"


def test_equal_identities_have_equal_hashes() -> None:
    first = GameIdentity(" Grand  Theft Auto V ", Platform.PS4)
    second = GameIdentity("GRAND THEFT AUTO V", Platform.PS4)

    assert first == second
    assert hash(first) == hash(second)


def test_same_name_on_different_platforms_is_a_different_identity() -> None:
    assert GameIdentity("GTA V", Platform.PS4) != GameIdentity(
        "GTA V",
        Platform.PS5,
    )


def test_different_names_on_same_platform_are_different_identities() -> None:
    assert GameIdentity("GTA V", Platform.PS4) != GameIdentity(
        "Red Dead Redemption 2",
        Platform.PS4,
    )


def test_identity_is_a_stable_dictionary_key_and_set_member() -> None:
    original = GameIdentity(" GTA   V ", Platform.XBOX_360)
    equivalent = GameIdentity("gta v", Platform.XBOX_360)
    values = {original: "market"}
    identities = {original, equivalent}

    assert values[equivalent] == "market"
    assert identities == {original}


@pytest.mark.parametrize("canonical_name", [None, 123, True, object()])
def test_non_string_name_is_rejected(canonical_name: object) -> None:
    with pytest.raises(TypeError, match="canonical_name must be str"):
        GameIdentity(canonical_name, Platform.PS4)  # type: ignore[arg-type]


@pytest.mark.parametrize("canonical_name", ["", " ", "\t\r\n"])
def test_empty_normalized_name_is_rejected(canonical_name: str) -> None:
    with pytest.raises(ValueError, match="canonical_name must not be empty"):
        GameIdentity(canonical_name, Platform.PS4)


@pytest.mark.parametrize("platform", ["PS4", None, 4, True, object()])
def test_non_platform_value_is_rejected(platform: object) -> None:
    with pytest.raises(TypeError, match="platform must be Platform"):
        GameIdentity("GTA V", platform)  # type: ignore[arg-type]


def test_unknown_platform_is_rejected() -> None:
    with pytest.raises(ValueError, match="platform must not be Platform.UNKNOWN"):
        GameIdentity("GTA V", Platform.UNKNOWN)


def test_identity_is_frozen_and_contains_only_identity_fields() -> None:
    identity = GameIdentity("GTA V", Platform.PS4)

    assert [field.name for field in fields(identity)] == [
        "canonical_name",
        "platform",
    ]
    for unrelated_field in (
        "aliases",
        "detection_aliases",
        "confidence",
        "matched_text",
        "price",
        "edition",
        "condition",
        "region",
    ):
        assert not hasattr(identity, unrelated_field)
    with pytest.raises(FrozenInstanceError):
        identity.canonical_name = "other"  # type: ignore[misc]


def test_identity_module_respects_domain_architecture() -> None:
    module_path = (
        Path(__file__).parents[2]
        / "src"
        / "domain"
        / "entities"
        / "game_identity.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert GameIdentity.__module__ == "domain.entities.game_identity"
    assert {
        module.split(".", maxsplit=1)[0]
        for module in imported_modules
    } <= {"dataclasses", "domain"}
    assert not any(
        module == root or module.startswith(f"{root}.")
        for module in imported_modules
        for root in ("application", "infrastructure", "presentation")
    )
    assert "wallapop" not in source.casefold()
    assert "import re" not in source
    assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "open"
        for node in ast.walk(tree)
    )
