"""Candidate listing entity.

Represents a marketplace listing being considered for purchase.
This is separate from ComparableListing, which is used as a price reference.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from domain._decimal import require_decimal
from domain.currency import validate_currency_code


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
        raw_listing: Original raw data from marketplace (immutable)
        published_at: When the listing was published (None if unknown)
        seller_id: Marketplace seller identifier (None if unknown)
    """

    listing_id: str
    title: str
    description: str
    price: Decimal
    currency: str
    url: str
    raw_listing: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None
    seller_id: str | None = None

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        if not self.listing_id:
            raise ValueError("listing_id must not be empty")
        if not self.title:
            raise ValueError("title must not be empty")
        require_decimal("price", self.price, non_negative=True)
        if self.price < Decimal("0"):
            raise ValueError(f"price must be >= 0, got {self.price}")
        validate_currency_code(self.currency)
