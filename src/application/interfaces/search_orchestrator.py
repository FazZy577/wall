"""Public contracts for the future search orchestration use case."""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from application.interfaces.candidate_search import (
    CandidateItemFailure,
    SearchQuery,
)
from application.interfaces.lot_opportunity_scanner import LotScanResult
from application.interfaces.opportunity_scanner import ScanResult
from domain.listing_id import validate_listing_id


def _require_non_negative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_non_empty_string(name: str, value: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str")
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True)
class SearchPlan:
    """Ordered queries explicitly supplied for one orchestration execution."""

    queries: tuple[SearchQuery, ...]

    def __post_init__(self) -> None:
        query_snapshot = tuple(self.queries)
        if any(not isinstance(query, SearchQuery) for query in query_snapshot):
            raise TypeError("queries must contain only SearchQuery")
        object.__setattr__(self, "queries", query_snapshot)


@dataclass(frozen=True)
class SearchQueryFailure:
    """Technical failure from executing one complete search query."""

    query: SearchQuery
    query_index: int
    reason: str
    error_type: str
    error_message: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.query, SearchQuery):
            raise TypeError("query must be SearchQuery")
        _require_non_negative_integer("query_index", self.query_index)
        _require_non_empty_string("reason", self.reason)
        _require_non_empty_string("error_type", self.error_type)


@dataclass(frozen=True)
class CandidateItemFailureRecord:
    """Associate one existing item-conversion failure with its query."""

    query: SearchQuery
    query_index: int
    failure: CandidateItemFailure

    def __post_init__(self) -> None:
        if not isinstance(self.query, SearchQuery):
            raise TypeError("query must be SearchQuery")
        _require_non_negative_integer("query_index", self.query_index)
        if not isinstance(self.failure, CandidateItemFailure):
            raise TypeError("failure must be CandidateItemFailure")


class CandidateRoutingFailureKind(StrEnum):
    """Failure categories while detecting or routing canonical candidates."""

    GAME_DETECTION_ERROR = "game_detection_error"
    NO_GAME_DETECTED = "no_game_detected"
    INDIVIDUAL_SCANNER_ERROR = "individual_scanner_error"
    LOT_SCANNER_ERROR = "lot_scanner_error"


@dataclass(frozen=True)
class CandidateRoutingFailure:
    """Safe failure details from candidate detection or scanner routing."""

    listing_id: str | None
    kind: CandidateRoutingFailureKind
    reason: str
    error_type: str | None
    error_message: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CandidateRoutingFailureKind):
            raise TypeError("kind must be CandidateRoutingFailureKind")
        _require_non_empty_string("reason", self.reason)

        if self.kind is CandidateRoutingFailureKind.INDIVIDUAL_SCANNER_ERROR:
            if self.listing_id is not None:
                raise ValueError(
                    "listing_id must be None for INDIVIDUAL_SCANNER_ERROR"
                )
            return

        if self.listing_id is None:
            raise ValueError(f"listing_id is required for {self.kind.name}")
        validate_listing_id(self.listing_id)


@dataclass(frozen=True)
class SearchOrchestrationResult:
    """Aggregate existing scanner results and orchestration-level failures."""

    individual_result: ScanResult | None
    lot_results: tuple[LotScanResult, ...]
    query_failures: tuple[SearchQueryFailure, ...]
    item_failures: tuple[CandidateItemFailureRecord, ...]
    routing_failures: tuple[CandidateRoutingFailure, ...]
    total_queries: int
    executed_queries: int
    duplicate_queries: int
    total_items_received: int
    valid_candidates_received: int
    duplicate_candidates: int
    unique_candidates: int
    individual_candidates: int
    lot_candidates: int
    undetected_candidates: int
    processing_time: float
    created_at: datetime

    def __post_init__(self) -> None:
        lot_results = tuple(self.lot_results)
        query_failures = tuple(self.query_failures)
        item_failures = tuple(self.item_failures)
        routing_failures = tuple(self.routing_failures)
        object.__setattr__(self, "lot_results", lot_results)
        object.__setattr__(self, "query_failures", query_failures)
        object.__setattr__(self, "item_failures", item_failures)
        object.__setattr__(self, "routing_failures", routing_failures)

        if self.individual_result is not None and not isinstance(
            self.individual_result, ScanResult
        ):
            raise TypeError("individual_result must be ScanResult or None")
        if any(not isinstance(result, LotScanResult) for result in lot_results):
            raise TypeError("lot_results must contain only LotScanResult")
        if any(
            not isinstance(failure, SearchQueryFailure)
            for failure in query_failures
        ):
            raise TypeError("query_failures must contain only SearchQueryFailure")
        if any(
            not isinstance(failure, CandidateItemFailureRecord)
            for failure in item_failures
        ):
            raise TypeError(
                "item_failures must contain only CandidateItemFailureRecord"
            )
        if any(
            not isinstance(failure, CandidateRoutingFailure)
            for failure in routing_failures
        ):
            raise TypeError(
                "routing_failures must contain only CandidateRoutingFailure"
            )

        counter_names = (
            "total_queries",
            "executed_queries",
            "duplicate_queries",
            "total_items_received",
            "valid_candidates_received",
            "duplicate_candidates",
            "unique_candidates",
            "individual_candidates",
            "lot_candidates",
            "undetected_candidates",
        )
        for name in counter_names:
            _require_non_negative_integer(name, getattr(self, name))

        if self.executed_queries + self.duplicate_queries != self.total_queries:
            raise ValueError(
                "executed_queries + duplicate_queries must equal total_queries"
            )
        if self.duplicate_candidates > self.valid_candidates_received:
            raise ValueError(
                "duplicate_candidates cannot exceed valid_candidates_received"
            )
        if (
            self.unique_candidates
            != self.valid_candidates_received - self.duplicate_candidates
        ):
            raise ValueError(
                "unique_candidates must equal valid_candidates_received "
                "- duplicate_candidates"
            )
        if (
            self.individual_candidates
            + self.lot_candidates
            + self.undetected_candidates
            != self.unique_candidates
        ):
            raise ValueError(
                "individual_candidates + lot_candidates + undetected_candidates "
                "must equal unique_candidates"
            )

        if isinstance(self.processing_time, bool) or not isinstance(
            self.processing_time, (int, float)
        ):
            raise TypeError("processing_time must be a real number")
        if not math.isfinite(self.processing_time) or self.processing_time < 0:
            raise ValueError("processing_time must be finite and non-negative")


class ISearchOrchestrator(ABC):
    """Application input port for the future search orchestration use case."""

    @abstractmethod
    async def execute(
        self,
        plan: SearchPlan,
    ) -> SearchOrchestrationResult:
        """Execute one explicit search plan."""
        pass
