"""Provider-neutral metadata and unknown-game resolution ports (never prices)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, Platform
from domain.entities.game_catalog_entry import GameCatalogEntry


@dataclass(frozen=True)
class GameMetadata:
    provider: str
    external_id: str
    name: str
    platforms: tuple[Platform, ...]
    aliases: tuple[str, ...] = ()
    content_type: str = "unknown"
    edition: bool = False
    source_url: str = ""

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip()
               for value in (self.provider, self.external_id, self.name, self.content_type)):
            raise ValueError("Metadata requires non-empty identifiers, name and content type")
        if not isinstance(self.source_url, str) or not isinstance(self.edition, bool):
            raise ValueError("Invalid metadata source URL or edition flag")
        if isinstance(self.aliases, (str, bytes)) or isinstance(self.platforms, (str, bytes)):
            raise ValueError("Metadata names and platforms require sequences")
        if any(not isinstance(p, Platform) or p is Platform.UNKNOWN for p in self.platforms):
            raise ValueError("Metadata platforms must be concrete")
        if any(not isinstance(alias, str) or not alias.strip() for alias in self.aliases):
            raise ValueError("Metadata aliases must be non-empty strings")
        object.__setattr__(self, "platforms", tuple(self.platforms))
        object.__setattr__(self, "aliases", tuple(self.aliases))


class MetadataUnavailable(RuntimeError):
    """Safe, credential-free provider failure."""


class MetadataDeferred(RuntimeError):
    """Query awaits the next run's budget or another worker's active request."""


class IMetadataSchedule(ABC):
    @abstractmethod
    def begin_run(self) -> None:
        """Reset the request budget for one explicit scan."""

    @abstractmethod
    def remember(self, listing: CandidateListing, query: str, platform: Platform) -> None:
        """Retain a representative observation for later identity-only maintenance."""

    @abstractmethod
    def due_listings(self, limit: int) -> tuple[CandidateListing, ...]:
        """Return bounded observations whose metadata is due for another attempt."""

    @abstractmethod
    def resolution_status(self, query: str, status: str) -> None:
        """Apply the pending interval without extending it on cache hits."""


class IGameMetadataProvider(ABC):
    @abstractmethod
    async def search(self, name: str) -> tuple[GameMetadata, ...]:
        """Return complete bounded candidate results or raise MetadataUnavailable."""


class IMetadataResolutionStore(ABC):
    @abstractmethod
    def record_resolution(
        self, listing: CandidateListing, query: str, platform: Platform,
        status: str, candidates: tuple[GameMetadata, ...],
        selected: GameMetadata | None = None,
    ) -> GameCatalogEntry | None:
        """Atomically persist evidence and an optional confirmed identity."""


class IUnknownGameResolver(ABC):
    async def begin_run(self) -> tuple[str, ...]:
        """Run bounded identity maintenance and return listing IDs with failures."""
        return ()

    @abstractmethod
    def needs_resolution(self, listing: CandidateListing, games: tuple[DetectedGame, ...]) -> bool:
        """Whether a locally matched title leaves a possible unknown sequel/subtitle."""

    @abstractmethod
    async def resolve(self, listing: CandidateListing) -> bool:
        """Confirm an unknown identity and refresh detection; return whether changed."""
