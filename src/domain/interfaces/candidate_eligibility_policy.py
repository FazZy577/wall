"""Port for classifying candidate listings before opportunity routing."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from domain.entities.candidate_classification import CandidateClassification
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame


class ICandidateEligibilityPolicy(ABC):
    """Classify preliminary game detections for one purchase candidate.

    ``detected_games`` contains observations produced by a game detector.
    Implementations decide which observations, if any, are physically
    included and expose them through ``CandidateClassification.included_games``.
    ``IGNORED`` and ``AMBIGUOUS`` are expected non-technical outcomes, not
    exceptions or scanner failures.
    """

    @abstractmethod
    def classify(
        self,
        listing: CandidateListing,
        detected_games: Sequence[DetectedGame],
    ) -> CandidateClassification:
        """Return the routing classification without mutating either input."""
        pass
