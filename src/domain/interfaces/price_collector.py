"""Price collector interface (port).

Defines the contract for price collection implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from domain.interfaces.game_detector import DetectedGame


@dataclass
class ComparableListing:
    """A marketplace listing validated as a comparable for price estimation.

    Attributes:
        listing_id: Unique identifier from marketplace
        title: Listing title
        description: Listing description
        price: Listed price in currency
        currency: Currency code (e.g., "EUR")
        detected_game: The game detected in this listing
        url: Direct URL to the listing
    """

    listing_id: str
    title: str
    description: str
    price: float
    currency: str
    detected_game: DetectedGame
    url: str
    raw_listing: dict[str, Any] = field(default_factory=dict)


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
