"""Canonical immutable identity for one game on one concrete platform."""

from dataclasses import dataclass

from domain.entities.detected_game import Platform


@dataclass(frozen=True)
class GameIdentity:
    """Identify a game by normalized canonical name and concrete platform."""

    canonical_name: str
    platform: Platform

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_name, str):
            raise TypeError("canonical_name must be str")
        normalized_name = " ".join(
            self.canonical_name.strip().casefold().split()
        )
        if not normalized_name:
            raise ValueError("canonical_name must not be empty")

        if not isinstance(self.platform, Platform):
            raise TypeError("platform must be Platform")
        if self.platform is Platform.UNKNOWN:
            raise ValueError("platform must not be Platform.UNKNOWN")

        object.__setattr__(self, "canonical_name", normalized_name)


__all__ = ("GameIdentity",)
