"""Canonical market-comparable listing entity."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from domain._decimal import require_decimal
from domain.entities.detected_game import DetectedGame


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

    def __post_init__(self) -> None:
        require_decimal("price", self.price)
