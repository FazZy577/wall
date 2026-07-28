"""Port for reading the canonical game catalog."""

from abc import ABC, abstractmethod

from domain.entities.game_catalog_entry import GameCatalogEntry


class IGameCatalog(ABC):
    """Read-only access to an immutable game-catalog snapshot."""

    @abstractmethod
    def list_games(self) -> tuple[GameCatalogEntry, ...]:
        """Return the complete immutable catalog snapshot."""
        pass
