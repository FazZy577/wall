"""Candidate listing entity.

Represents a marketplace listing being considered for purchase.
This is separate from ComparableListing, which is used as a price reference.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from domain.interfaces.game_detector import DetectedGame


@dataclass
class CandidateListing:
    """A marketplace listing considered as a purchase candidate.

    Can represent a single game or a lot (bundle) of multiple games.
    This is NOT the same as ComparableListing — ComparableListing is used
    to estimate market prices, CandidateListing is what we might buy.

    Attributes:
        listing_id: Unique identifier from marketplace
        title: Listing title
        description: Listing description
        price: Listed price in currency
        currency: Currency code (e.g., "EUR")
        url: Direct URL to the listing
        detected_games: Games detected in this listing (may be multiple for lots)
        raw_listing: Original raw data from marketplace (immutable)
        published_at: When the listing was published (None if unknown)
        seller_id: Marketplace seller identifier (None if unknown)
    """

    listing_id: str
    title: str
    description: str
    price: float
    currency: str
    url: str
    detected_games: list[DetectedGame] = field(default_factory=list)
    raw_listing: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    seller_id: str | None = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        if not self.listing_id:
            raise ValueError("listing_id must not be empty")
        if not self.title:
            raise ValueError("title must not be empty")
        if self.price < 0:
            raise ValueError(f"price must be >= 0, got {self.price}")
        if not self.currency:
            raise ValueError("currency must not be empty")

    @property
    def is_lot(self) -> bool:
        """True when the listing contains more than one detected game."""
        return len(self.detected_games) > 1

    @property
    def game_count(self) -> int:
        """Number of games detected in this listing."""
        return len(self.detected_games)
