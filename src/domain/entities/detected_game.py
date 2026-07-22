"""Canonical shared game-detection domain models."""

from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    """Gaming platforms."""

    PS4 = "PS4"
    PS5 = "PS5"
    XBOX_ONE = "Xbox One"
    XBOX_SERIES = "Xbox Series"
    SWITCH = "Nintendo Switch"
    UNKNOWN = "Unknown"


class DetectionMethod(StrEnum):
    """Method used to detect a game."""

    EXACT_MATCH = "EXACT_MATCH"
    ALIAS_MATCH = "ALIAS_MATCH"
    FUZZY_MATCH = "FUZZY_MATCH"


@dataclass
class DetectedGame:
    """A game detected in listing text."""

    canonical_name: str
    matched_text: str
    platform: Platform
    confidence: float
    detection_method: DetectionMethod

    def __post_init__(self) -> None:
        """Validate confidence is between 0 and 1."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")
