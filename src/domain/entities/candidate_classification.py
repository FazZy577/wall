"""Canonical candidate-classification domain value objects."""

from dataclasses import dataclass
from enum import StrEnum

from domain.entities.detected_game import DetectedGame
from domain.entities.game_identity import GameIdentity


class CandidateDisposition(StrEnum):
    """Expected routing dispositions for one candidate listing."""

    ELIGIBLE_INDIVIDUAL = "eligible_individual"
    ELIGIBLE_LOT = "eligible_lot"
    IGNORED = "ignored"
    AMBIGUOUS = "ambiguous"


class CandidateClassificationReason(StrEnum):
    """Stable reasons supporting a candidate disposition."""

    ELIGIBLE_SINGLE_GAME = "eligible_single_game"
    ELIGIBLE_MULTI_GAME_LOT = "eligible_multi_game_lot"
    NO_INCLUDED_GAME = "no_included_game"
    UNSUPPORTED_HARDWARE = "unsupported_hardware"
    ACCESSORY_OR_CONTROLLER = "accessory_or_controller"
    AMBIGUOUS_MULTIPLATFORM = "ambiguous_multiplatform"
    UNSUPPORTED_EDITION = "unsupported_edition"
    CONTEXTUAL_REFERENCE_ONLY = "contextual_reference_only"
    UNRESOLVED_SALE_TERMS = "unresolved_sale_terms"
    UNCONFIRMED_IDENTITY = "unconfirmed_identity"


_IGNORED_REASONS = frozenset(
    {
        CandidateClassificationReason.NO_INCLUDED_GAME,
        CandidateClassificationReason.UNSUPPORTED_HARDWARE,
        CandidateClassificationReason.ACCESSORY_OR_CONTROLLER,
        CandidateClassificationReason.UNSUPPORTED_EDITION,
        CandidateClassificationReason.CONTEXTUAL_REFERENCE_ONLY,
    }
)
_AMBIGUOUS_REASONS = frozenset(
    {
        CandidateClassificationReason.UNCONFIRMED_IDENTITY,
        CandidateClassificationReason.UNRESOLVED_SALE_TERMS,
        CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
        CandidateClassificationReason.UNSUPPORTED_EDITION,
        CandidateClassificationReason.CONTEXTUAL_REFERENCE_ONLY,
    }
)


@dataclass(frozen=True)
class CandidateClassification:
    """Immutable classification result used to route one candidate.

    ``detected_games`` supplied to a future policy are preliminary detector
    observations.  ``included_games`` contains only games that the policy has
    accepted as physically included and therefore safe for routing.
    """

    disposition: CandidateDisposition
    reason: CandidateClassificationReason
    included_games: tuple[DetectedGame, ...]
    quantities: tuple[int, ...] = ()

    @property
    def total_units(self) -> int:
        return sum(self.quantities)

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, CandidateDisposition):
            raise TypeError("disposition must be CandidateDisposition")
        if not isinstance(self.reason, CandidateClassificationReason):
            raise TypeError("reason must be CandidateClassificationReason")
        if type(self.included_games) is not tuple:
            raise TypeError("included_games must be tuple")
        if any(not isinstance(game, DetectedGame) for game in self.included_games):
            raise TypeError("included_games must contain only DetectedGame")
        if type(self.quantities) is not tuple:
            raise TypeError("quantities must be tuple")
        if not self.quantities:
            object.__setattr__(self, "quantities", (1,) * len(self.included_games))
        if len(self.quantities) != len(self.included_games) or any(
            type(quantity) is not int or quantity < 1 for quantity in self.quantities
        ):
            raise ValueError("quantities must contain one positive integer per identity")

        identities: set[GameIdentity] = set()
        for game in self.included_games:
            identity = GameIdentity.from_game(game)
            if identity in identities:
                raise ValueError(
                    "included_games must not contain duplicate game identities"
                )
            identities.add(identity)

        if self.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL:
            if len(self.included_games) != 1 or self.total_units != 1:
                raise ValueError(
                    "ELIGIBLE_INDIVIDUAL requires exactly one included game"
                )
            if self.reason is not CandidateClassificationReason.ELIGIBLE_SINGLE_GAME:
                raise ValueError(
                    "ELIGIBLE_INDIVIDUAL requires ELIGIBLE_SINGLE_GAME reason"
                )
            return

        if self.disposition is CandidateDisposition.ELIGIBLE_LOT:
            if self.total_units < 2:
                raise ValueError("ELIGIBLE_LOT requires at least two included games")
            if self.reason is not CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT:
                raise ValueError(
                    "ELIGIBLE_LOT requires ELIGIBLE_MULTI_GAME_LOT reason"
                )
            return

        if self.included_games:
            raise ValueError(
                f"{self.disposition.name} classification cannot include games"
            )
        if self.disposition is CandidateDisposition.IGNORED:
            if self.reason not in _IGNORED_REASONS:
                raise ValueError("reason is not valid for IGNORED disposition")
            return
        if self.reason not in _AMBIGUOUS_REASONS:
            raise ValueError("reason is not valid for AMBIGUOUS disposition")


__all__ = (
    "CandidateClassification",
    "CandidateClassificationReason",
    "CandidateDisposition",
)
