"""Deterministic lexical matching of concrete gaming platforms."""

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from domain.entities.detected_game import Platform


@dataclass(frozen=True)
class PlatformMention:
    """One non-overlapping platform mention in normalized text."""

    platform: Platform
    start: int
    end: int
    matched_text: str


@dataclass(frozen=True)
class _PlatformAliasPattern:
    platform: Platform
    alias: str
    pattern: re.Pattern[str]


_PLATFORM_ALIASES: Final[tuple[tuple[Platform, tuple[str, ...]], ...]] = (
    (Platform.PS2, ("ps2", "playstation 2", "play station 2")),
    (Platform.PS3, ("ps3", "playstation 3", "play station 3")),
    (Platform.PS4, ("ps4", "playstation 4", "play station 4", "play 4")),
    (Platform.PS5, ("ps5", "playstation 5", "play station 5", "play 5")),
    (Platform.XBOX, ("xbox original", "original xbox", "xbox")),
    (Platform.XBOX_360, ("xbox 360", "xbox360", "x360")),
    (Platform.XBOX_ONE, ("xbox one", "xboxone", "xb1")),
    (
        Platform.XBOX_SERIES,
        ("xbox series x", "xbox series s", "xbox series", "xsx", "xss"),
    ),
    (Platform.GAMECUBE, ("nintendo gamecube", "gamecube")),
    (Platform.WII, ("nintendo wii", "wii")),
    (Platform.WII_U, ("nintendo wii u", "wii u", "wiiu")),
    (Platform.SWITCH, ("nintendo switch", "switch")),
    (Platform.NINTENDO_DS, ("nintendo ds", "nds")),
    (Platform.NINTENDO_3DS, ("nintendo 3ds", "3ds")),
    (Platform.PSP, ("psp", "playstation portable")),
    (Platform.PS_VITA, ("ps vita", "playstation vita")),
)


class PlatformLexicalMatcher:
    """Find controlled platform aliases with lexical boundaries."""

    def __init__(self) -> None:
        patterns = [
            _PlatformAliasPattern(
                platform=platform,
                alias=alias,
                pattern=re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)"),
            )
            for platform, aliases in _PLATFORM_ALIASES
            for alias in aliases
        ]
        self._patterns = tuple(
            sorted(
                patterns,
                key=lambda item: (-len(item.alias), item.alias, item.platform.value),
            )
        )

    def find_mentions(self, text: str) -> tuple[PlatformMention, ...]:
        """Return non-overlapping mentions in normalized textual order."""
        if not isinstance(text, str):
            raise TypeError("text must be str")
        normalized_text = self.normalize_text(text)
        candidates = [
            PlatformMention(
                platform=item.platform,
                start=match.start(),
                end=match.end(),
                matched_text=match.group(),
            )
            for item in self._patterns
            for match in item.pattern.finditer(normalized_text)
        ]

        selected: list[PlatformMention] = []
        for candidate in sorted(
            candidates,
            key=lambda mention: (
                -(mention.end - mention.start),
                mention.start,
                mention.platform.value,
            ),
        ):
            if any(self._overlaps(candidate, existing) for existing in selected):
                continue
            selected.append(candidate)

        return tuple(sorted(selected, key=lambda mention: (mention.start, mention.end)))

    @staticmethod
    def normalize_text(text: str) -> str:
        """Apply the detector-compatible normalization used for lexical spans."""
        normalized = text.lower()
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _overlaps(first: PlatformMention, second: PlatformMention) -> bool:
        return first.start < second.end and second.start < first.end


__all__ = ("PlatformLexicalMatcher", "PlatformMention")
