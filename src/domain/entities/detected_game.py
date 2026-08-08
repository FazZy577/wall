"""Canonical shared game-detection domain models."""

from dataclasses import dataclass
from enum import StrEnum


class Platform(StrEnum):
    """Gaming platforms."""

    PS2 = "PS2"
    PS3 = "PS3"
    PS4 = "PS4"
    PS5 = "PS5"
    XBOX = "Xbox"
    XBOX_360 = "Xbox 360"
    XBOX_ONE = "Xbox One"
    XBOX_SERIES = "Xbox Series"
    GAMECUBE = "Nintendo GameCube"
    WII = "Nintendo Wii"
    WII_U = "Nintendo Wii U"
    SWITCH = "Nintendo Switch"
    NINTENDO_DS = "Nintendo DS"
    NINTENDO_3DS = "Nintendo 3DS"
    PSP = "PSP"
    PS_VITA = "PS Vita"
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
