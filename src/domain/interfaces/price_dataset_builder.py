"""Price dataset builder interface (port).

Defines the contract for transforming comparable listings into clean price datasets.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from domain.entities.detected_game import DetectedGame


class InvalidComparableListingError(TypeError):
    """Raised when a non-comparable domain type crosses the market boundary."""


@dataclass
class PriceObservation:
    """A single price observation extracted from a marketplace listing.

    Attributes:
        price: Price value
        currency: Currency code (e.g., "EUR")
        listing_id: Unique marketplace listing ID
        title: Listing title
        platform: Gaming platform
        source: Data source identifier (e.g., "wallapop")
        raw_listing: Original listing data for reference
    """

    price: float
    currency: str
    listing_id: str
    title: str
    platform: str
    source: str
    raw_listing: dict[str, str | float]


@dataclass
class PriceDataset:
    """A clean dataset of price observations for a specific game.

    This dataset is ready for statistical analysis by the pricing engine.

    Attributes:
        observations: List of valid price observations
        game: Target game for these observations
        created_at: Dataset creation timestamp
        sample_size: Number of observations
    """

    observations: list[PriceObservation]
    game: DetectedGame
    created_at: datetime
    sample_size: int


class IPriceDatasetBuilder(ABC):
    """Interface for price dataset builder implementations.

    Transforms comparable listings into clean, homogeneous price datasets
    ready for statistical analysis.
    """

    @abstractmethod
    def build(self, comparable_listings: list[object]) -> PriceDataset:
        """Build a price dataset from comparable listings.

        Args:
            comparable_listings: List of ComparableListing objects

        Returns:
            PriceDataset with valid observations
        """
        pass
