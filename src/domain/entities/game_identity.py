"""Canonical immutable identity for one game on one concrete platform."""

from dataclasses import dataclass

from domain.entities.detected_game import DetectedGame, Platform
from domain.entities.game_record import IdentityStatus, ReleaseIdentity


@dataclass(frozen=True, eq=False)
class GameIdentity:
    """Use a stable release when present; legacy name keys remain isolated.

    A legacy key never equals a registered key solely because their names match.
    """

    canonical_name: str
    platform: Platform
    release_identity: ReleaseIdentity | None = None

    @classmethod
    def from_game(cls, game: DetectedGame) -> "GameIdentity":
        return cls(game.canonical_name, game.platform, game.release_identity)

    def _key(self) -> object:
        return self.release_identity if self.release_identity is not None else (self.canonical_name, self.platform)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GameIdentity):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

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
        if self.release_identity is not None:
            if not isinstance(self.release_identity, ReleaseIdentity):
                raise TypeError("release_identity must be ReleaseIdentity")
            if self.release_identity.status is not IdentityStatus.CONFIRMED:
                raise ValueError("provisional identity cannot be used for valuation")
            if self.release_identity.platform is not self.platform:
                raise ValueError("release platform does not match identity")


__all__ = ("GameIdentity",)
