"""Tests for deterministic lexical platform matching."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from domain.entities.detected_game import Platform
from infrastructure.matching.platform_lexical_matcher import (
    PlatformLexicalMatcher,
    PlatformMention,
)

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).parents[2]
MATCHER_PATH = PROJECT_ROOT / "src/infrastructure/matching/platform_lexical_matcher.py"

PLATFORM_CASES = (
    ("PS2", Platform.PS2),
    ("PlayStation 3", Platform.PS3),
    ("play station 4", Platform.PS4),
    ("play 5", Platform.PS5),
    ("Xbox original", Platform.XBOX),
    ("XBOX360", Platform.XBOX_360),
    ("xb1", Platform.XBOX_ONE),
    ("Xbox Series S", Platform.XBOX_SERIES),
    ("Nintendo GameCube", Platform.GAMECUBE),
    ("Nintendo Wii", Platform.WII),
    ("WiiU", Platform.WII_U),
    ("Nintendo Switch", Platform.SWITCH),
    ("NDS", Platform.NINTENDO_DS),
    ("Nintendo 3DS", Platform.NINTENDO_3DS),
    ("PlayStation Portable", Platform.PSP),
    ("PlayStation Vita", Platform.PS_VITA),
)


@pytest.fixture
def matcher() -> PlatformLexicalMatcher:
    return PlatformLexicalMatcher()


@pytest.mark.parametrize(("text", "platform"), PLATFORM_CASES)
def test_every_concrete_platform_family_is_recognized(
    matcher: PlatformLexicalMatcher,
    text: str,
    platform: Platform,
) -> None:
    mentions = matcher.find_mentions(f"Vendo {text}, completa")

    assert [mention.platform for mention in mentions] == [platform]
    assert all(mention.platform is not Platform.UNKNOWN for mention in mentions)


@pytest.mark.parametrize(
    ("text", "platform"),
    [
        ("xBoX SeRiEs X", Platform.XBOX_SERIES),
        ("(PSP)!", Platform.PSP),
        ("Wii-U", Platform.WII_U),
        ("Nintendo: Switch", Platform.SWITCH),
    ],
)
def test_matching_is_case_and_punctuation_insensitive(
    matcher: PlatformLexicalMatcher,
    text: str,
    platform: Platform,
) -> None:
    assert [mention.platform for mention in matcher.find_mentions(text)] == [platform]


@pytest.mark.parametrize("text", ["xps4x", "xx360x", "xpspx", "x3dsx"])
def test_aliases_respect_lexical_boundaries(
    matcher: PlatformLexicalMatcher,
    text: str,
) -> None:
    assert matcher.find_mentions(text) == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Xbox Series X", Platform.XBOX_SERIES),
        ("Xbox 360", Platform.XBOX_360),
        ("Nintendo Wii U", Platform.WII_U),
        ("Nintendo 3DS", Platform.NINTENDO_3DS),
    ],
)
def test_long_specific_alias_consumes_overlapping_generic_alias(
    matcher: PlatformLexicalMatcher,
    text: str,
    expected: Platform,
) -> None:
    mentions = matcher.find_mentions(text)

    assert len(mentions) == 1
    assert mentions[0].platform is expected


def test_repeated_same_platform_mentions_are_preserved(
    matcher: PlatformLexicalMatcher,
) -> None:
    mentions = matcher.find_mentions("PS4 y PlayStation 4")

    assert [mention.platform for mention in mentions] == [
        Platform.PS4,
        Platform.PS4,
    ]


def test_distinct_platforms_preserve_textual_order_and_positions(
    matcher: PlatformLexicalMatcher,
) -> None:
    mentions = matcher.find_mentions("PS5 + Xbox 360 + Wii U")

    assert [mention.platform for mention in mentions] == [
        Platform.PS5,
        Platform.XBOX_360,
        Platform.WII_U,
    ]
    assert [(mention.start, mention.end, mention.matched_text) for mention in mentions] == [
        (0, 3, "ps5"),
        (4, 12, "xbox 360"),
        (13, 18, "wii u"),
    ]


@pytest.mark.parametrize("unsafe_alias", ["ps", "one", "series", "ds", "ns", "s", "x"])
def test_unsafe_isolated_aliases_are_not_supported(
    matcher: PlatformLexicalMatcher,
    unsafe_alias: str,
) -> None:
    assert matcher.find_mentions(unsafe_alias) == ()


def test_empty_text_and_invalid_type_are_handled_explicitly(
    matcher: PlatformLexicalMatcher,
) -> None:
    assert matcher.find_mentions("") == ()
    with pytest.raises(TypeError, match="text must be str"):
        matcher.find_mentions(object())  # type: ignore[arg-type]


def test_mentions_are_immutable() -> None:
    mention = PlatformMention(Platform.PS4, 0, 3, "ps4")

    with pytest.raises(FrozenInstanceError):
        mention.start = 1  # type: ignore[misc]


def test_matcher_module_respects_infrastructure_boundary() -> None:
    source = MATCHER_PATH.read_text(encoding="utf-8")
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

    assert not any(
        module == root or module.startswith(f"{root}.")
        for module in imported_modules
        for root in ("application", "presentation")
    )
    assert "wallapop" not in source.casefold()
    assert "Platform.UNKNOWN" not in source
    assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))
