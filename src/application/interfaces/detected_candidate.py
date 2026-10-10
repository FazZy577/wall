"""Application contract for a candidate with an existing game detection."""

from dataclasses import dataclass

from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame


@dataclass(frozen=True)
class DetectedCandidate:
    """Snapshot a purchase candidate and its already detected games."""

    listing: CandidateListing
    detected_games: tuple[DetectedGame, ...]
    quantities: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.listing, CandidateListing):
            raise TypeError("listing must be CandidateListing")
        object.__setattr__(self, "detected_games", tuple(self.detected_games))
        if self.quantities and (
            type(self.quantities) is not tuple
            or len(self.quantities) != len(self.detected_games)
            or any(type(quantity) is not int or quantity < 1 for quantity in self.quantities)
        ):
            raise ValueError("quantities must contain one positive integer per detected game")
