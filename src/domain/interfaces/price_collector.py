"""Price collector interface (port).

Defines the contract for price collection implementations.
"""

from abc import ABC, abstractmethod

from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame

# Compatibility re-export: old imports resolve to the canonical entity above.


class IPriceCollector(ABC):
    """Interface for price collection implementations.

    Implementations orchestrate marketplace search, game detection,
    and comparable filtering to obtain valid comparable listings.
    """

    @abstractmethod
    async def collect_comparables(
        self,
        game: DetectedGame,
        latitude: float,
        longitude: float,
        max_results: int | None = None,
    ) -> list[ComparableListing]:
        """Collect comparable listings for a game.

        Args:
            game: Target game to find comparables for
            latitude: Search location latitude
            longitude: Search location longitude
            max_results: Maximum number of comparables to collect (None for all)

        Returns:
            List of validated comparable listings
        """
        pass
