"""Game detector interface (port).

Defines the contract for game detection implementations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform

# Compatibility re-exports: historical imports from this detector port resolve
# to the shared canonical domain models above.
__all__ = [
    "DetectedGame",
    "DetectionMethod",
    "IGameDetector",
    "ListingText",
    "Platform",
]


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
