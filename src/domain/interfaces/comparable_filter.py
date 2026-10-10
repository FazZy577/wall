"""Comparable filter interface (port).

Defines the contract for filtering listings that can be used as comparables
for price estimation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from domain._decimal import require_decimal
from domain.currency import validate_currency_code
from domain.entities.detected_game import DetectedGame


@dataclass
class ComparableFilterInput:
    """Represents a marketplace listing to evaluate.

    Attributes:
        title: Listing title
        description: Listing description
        price: Listed price, when available, used to check sale terms
        detected_games: Complete detector snapshot; None requests detection
        currency: Currency of the asking price
    """

    title: str
    description: str = ""
    price: Decimal | None = None
    detected_games: tuple[DetectedGame, ...] | None = None
    currency: str = "EUR"

    def __post_init__(self) -> None:
        validate_currency_code(self.currency)
        if self.price is not None:
            require_decimal("price", self.price)
        if self.detected_games is not None:
            if any(not isinstance(game, DetectedGame) for game in self.detected_games):
                raise TypeError("detected_games must contain only DetectedGame")
            self.detected_games = tuple(self.detected_games)


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
        listing: ComparableFilterInput,
    ) -> bool:
        """Determine if a listing is valid as a comparable.

        Args:
            target_game: The game we want to price
            listing: The listing to evaluate

        Returns:
            True if listing can be used as comparable, False otherwise
        """
        pass
