"""Stable game and release contracts, independent of metadata providers."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.entities.detected_game import Platform


class IdentityStatus(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"


class MediaFormat(StrEnum):
    PHYSICAL = "physical"
    DIGITAL = "digital"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExternalGameReference:
    provider: str
    external_id: str

    def __post_init__(self) -> None:
        for value in (self.provider, self.external_id):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("external reference requires provider and external_id")
        object.__setattr__(self, "provider", self.provider.strip().casefold())
        object.__setattr__(self, "external_id", self.external_id.strip())


@dataclass(frozen=True)
class GameRecord:
    game_id: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    status: IdentityStatus = IdentityStatus.PROVISIONAL
    external_references: tuple[ExternalGameReference, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.game_id, self.canonical_name):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("game_id and canonical_name must be non-empty strings")
        if not isinstance(self.status, IdentityStatus):
            raise TypeError("status must be IdentityStatus")
        if isinstance(self.aliases, str) or any(not isinstance(a, str) or not a.strip() for a in self.aliases):
            raise ValueError("aliases must contain non-empty strings")
        object.__setattr__(self, "aliases", tuple(self.aliases))
        if any(not isinstance(ref, ExternalGameReference) for ref in self.external_references):
            raise TypeError("external_references must contain ExternalGameReference")
        object.__setattr__(self, "external_references", tuple(self.external_references))


@dataclass(frozen=True)
class ReleaseIdentity:
    """A specific release/product; mutable names are deliberately absent."""

    game_id: str
    release_id: str
    platform: "Platform"
    edition: str = "standard"
    media_format: MediaFormat = MediaFormat.PHYSICAL
    status: IdentityStatus = IdentityStatus.CONFIRMED

    def __post_init__(self) -> None:
        from domain.entities.detected_game import Platform

        for value in (self.game_id, self.release_id, self.edition):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("release identifiers and edition must be non-empty strings")
        if not isinstance(self.platform, Platform):
            raise TypeError("platform must be Platform")
        if not isinstance(self.status, IdentityStatus) or not isinstance(self.media_format, MediaFormat):
            raise TypeError("invalid identity status or media format")
        if self.status is IdentityStatus.CONFIRMED and (
            self.platform is Platform.UNKNOWN or self.media_format is MediaFormat.UNKNOWN
        ):
            raise ValueError("confirmed releases require concrete platform and format")
