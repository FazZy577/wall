"""Comparable filter interface (port).

Defines the contract for filtering listings that can be used as comparables
for price estimation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain.interfaces.game_detector import DetectedGame


@dataclass
class Listing:
    """Represents a marketplace listing to evaluate.

    Attributes:
        title: Listing title
        description: Listing description
        price: Listed price (optional, not used in filtering)
    """

    title: str
    description: str = ""
    price: float | None = None


class IComparableFilter(ABC):
    """Interface for comparable filtering implementations.

    Determines whether a listing can be used as a comparable
    for estimating the price of a target game.

    Different implementations can use different strategies:
    - Rule-based (keyword matching, pattern detection)
    - ML-based (classification models)
    - Hybrid (combination of methods)
    """

    @abstractmethod
    def is_valid_comparable(
        self,
        target_game: DetectedGame,
        listing: Listing,
    ) -> bool:
        """Determine if a listing is valid as a comparable.

        Args:
            target_game: The game we want to price
            listing: The listing to evaluate

        Returns:
            True if listing can be used as comparable, False otherwise
        """
        pass
