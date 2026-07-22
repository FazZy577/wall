"""Canonical market-comparable listing entity."""

from dataclasses import dataclass, field
from typing import Any

from domain.entities.detected_game import DetectedGame


@dataclass
class ComparableListing:
    """A marketplace listing validated as a comparable for price estimation."""

    listing_id: str
    title: str
    description: str
    price: float
    currency: str
    detected_game: DetectedGame
    url: str
    raw_listing: dict[str, Any] = field(default_factory=dict)
