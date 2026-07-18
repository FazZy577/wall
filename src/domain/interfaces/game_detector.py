"""Game detector interface (port).

Defines the contract for game detection implementations.
"""

from abc import ABC, abstractmethod
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
    """Represents a game detected in a listing.

    Attributes:
        canonical_name: Official game name
        matched_text: Text fragment that matched
        platform: Gaming platform
        confidence: Detection confidence (0.0 - 1.0)
        detection_method: Method used for detection
    """

    canonical_name: str
    matched_text: str
    platform: Platform
    confidence: float
    detection_method: DetectionMethod

    def __post_init__(self) -> None:
        """Validate confidence is between 0 and 1."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")


@dataclass
class ListingText:
    """Text content from a listing to analyze.

    Attributes:
        title: Listing title
        description: Listing description
    """

    title: str
    description: str = ""


class IGameDetector(ABC):
    """Interface for game detection implementations.

    Different implementations can use different strategies:
    - Rule-based (fuzzy matching against catalog)
    - AI-based (LLM analysis)
    - Image-based (OCR/computer vision)
    - Hybrid (combination of methods)
    """

    @abstractmethod
    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        """Detect games in listing text.

        Args:
            listing_text: Text content to analyze

        Returns:
            List of detected games with confidence scores
        """
        pass
