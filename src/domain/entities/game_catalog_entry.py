"""Canonical immutable game-catalog entry."""

from collections.abc import Sequence
from dataclasses import dataclass

from domain.entities.detected_game import Platform
from domain.entities.game_identity import GameIdentity


@dataclass(frozen=True)
class GameCatalogEntry:
    """One known game and its aliases used for listing-text detection."""

    canonical_name: str
    platform: Platform
    detection_aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_name, str):
            raise TypeError("canonical_name must be str")
        canonical_name = self.canonical_name.strip()
        if not canonical_name:
            raise ValueError("canonical_name must not be empty")

        if not isinstance(self.platform, Platform):
            raise TypeError("platform must be Platform")
        if self.platform is Platform.UNKNOWN:
            raise ValueError("platform must not be Platform.UNKNOWN")

        aliases = self.detection_aliases
        if isinstance(aliases, (str, bytes)) or not isinstance(aliases, Sequence):
            raise TypeError("detection_aliases must be a sequence of strings")

        alias_snapshot: list[str] = []
        for alias in aliases:
            if not isinstance(alias, str):
                raise TypeError("detection_aliases must contain only strings")
            normalized_alias = alias.strip()
            if not normalized_alias:
                raise ValueError("detection_aliases must not contain empty aliases")
            alias_snapshot.append(normalized_alias)

        object.__setattr__(self, "canonical_name", canonical_name)
        object.__setattr__(self, "detection_aliases", tuple(alias_snapshot))

    @property
    def identity(self) -> GameIdentity:
        """Return the canonical game-and-platform identity."""
        return GameIdentity(self.canonical_name, self.platform)
