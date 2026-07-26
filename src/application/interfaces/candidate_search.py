"""Canonical application contract for searching purchase candidates."""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

from domain.entities.candidate_listing import CandidateListing


@dataclass(frozen=True)
class SearchQuery:
    """One explicit marketplace query for purchase candidates."""

    keywords: str
    latitude: float
    longitude: float
    max_results: int

    def __post_init__(self) -> None:
        if not isinstance(self.keywords, str):
            raise TypeError("keywords must be str")
        normalized_keywords = self.keywords.strip()
        if not normalized_keywords:
            raise ValueError("keywords must not be empty")
        object.__setattr__(self, "keywords", normalized_keywords)

        self._validate_coordinate("latitude", self.latitude, -90.0, 90.0)
        self._validate_coordinate("longitude", self.longitude, -180.0, 180.0)

        if isinstance(self.max_results, bool) or not isinstance(self.max_results, int):
            raise TypeError("max_results must be int")
        if self.max_results <= 0:
            raise ValueError("max_results must be greater than zero")

    @staticmethod
    def _validate_coordinate(
        name: str,
        value: float,
        minimum: float,
        maximum: float,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a real number")
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        if not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")


class CandidateItemFailureKind(StrEnum):
    """Reason category for rejecting one marketplace search item."""

    INVALID_RAW_ITEM = "invalid_raw_item"
    INVALID_CANDIDATE = "invalid_candidate"


@dataclass(frozen=True)
class CandidateItemFailure:
    """Safe details about one item that could not become a candidate."""

    item_index: int
    kind: CandidateItemFailureKind
    reason: str
    listing_id: str | None
    error_message: str | None


@dataclass(frozen=True)
class CandidateSearchResult:
    """Immutable result of one canonical candidate search."""

    query: SearchQuery
    candidates: tuple[CandidateListing, ...]
    failures: tuple[CandidateItemFailure, ...]
    total_items_received: int

    def __post_init__(self) -> None:
        if isinstance(self.total_items_received, bool) or not isinstance(
            self.total_items_received, int
        ):
            raise TypeError("total_items_received must be int")
        if self.total_items_received < 0:
            raise ValueError("total_items_received must be non-negative")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "failures", tuple(self.failures))


class ICandidateSearch(ABC):
    """Application output port for obtaining canonical candidates."""

    @abstractmethod
    async def search_candidates(self, query: SearchQuery) -> CandidateSearchResult:
        """Search once and isolate malformed individual items."""
        pass
