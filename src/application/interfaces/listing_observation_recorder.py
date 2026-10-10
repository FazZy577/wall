"""Persistence port for observed listing versions and identification evidence."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from application.interfaces.candidate_search import QueryScan
from domain.entities.candidate_classification import CandidateClassification
from domain.entities.detected_game import DetectedGame

IdentificationStatus = Literal["resolved", "unknown", "ambiguous", "ignored", "error"]


class ObservationStorageError(RuntimeError):
    """Observation storage could not be initialized or written."""


@dataclass(frozen=True)
class ListingObservation:
    """An observed product snapshot, without seller or raw marketplace data.

    Attempts count local processing, not external catalog-provider requests.
    Identification evidence may change even when the listing text does not.
    """

    listing_id: str
    title: str
    description: str
    price: Decimal
    currency: str
    observed_at: datetime
    status: IdentificationStatus
    detected_games: tuple[DetectedGame, ...] = ()
    classification: CandidateClassification | None = None
    error_type: str | None = None
    source_query: str | None = None
    role: Literal["candidate", "comparable"] = "candidate"
    marketplace: str = "wallapop"


class IListingObservationRecorder(ABC):
    """Persist observations atomically; storage failures must propagate."""

    async def record_query_scan(self, scan: QueryScan) -> None:
        """Optional coverage persistence for legacy observation-only recorders."""
        del scan

    @abstractmethod
    async def record_observation(self, observation: ListingObservation) -> None:
        pass


class NullListingObservationRecorder(IListingObservationRecorder):
    """Explicitly disabled persistence."""

    async def record_observation(self, observation: ListingObservation) -> None:
        del observation
