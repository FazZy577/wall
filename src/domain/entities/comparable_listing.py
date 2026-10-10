"""Canonical market-comparable listing entity."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from domain._decimal import require_decimal
from domain.currency import validate_currency_code
from domain.entities.detected_game import DetectedGame
from domain.listing_id import validate_listing_id


@dataclass
class ComparableListing:
    """A marketplace listing validated as a comparable for price estimation."""

    listing_id: str
    title: str
    description: str
    price: Decimal
    currency: str
    detected_game: DetectedGame
    url: str
    raw_listing: dict[str, Any] = field(default_factory=dict)
    source_query: str | None = None

    def __post_init__(self) -> None:
        validate_listing_id(self.listing_id)
        require_decimal("price", self.price)
        validate_currency_code(self.currency)
        if self.source_query is not None and (
            not isinstance(self.source_query, str) or not self.source_query.strip()
        ):
            raise ValueError("source_query must be a non-empty string or None")
