"""Public contracts for search-plan generation."""

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from application.interfaces.search_orchestrator import SearchPlan
from domain.entities.detected_game import Platform


@dataclass(frozen=True)
class GameSearchTarget:
    """Canonical game and platform requested for search-plan generation."""

    canonical_name: str
    platform: Platform

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_name, str):
            raise TypeError("canonical_name must be str")
        canonical_name = self.canonical_name.strip()
        if not canonical_name:
            raise ValueError("canonical_name must not be empty")
        object.__setattr__(self, "canonical_name", canonical_name)

        if not isinstance(self.platform, Platform):
            raise TypeError("platform must be Platform")
        if self.platform is Platform.UNKNOWN:
            raise ValueError("platform must not be UNKNOWN")


class SearchPlanGenerationStrategy(StrEnum):
    """Supported strategies for generating explicit search queries."""

    CANONICAL_ONLY = "canonical_only"


@dataclass(frozen=True)
class SearchPlanGenerationRequest:
    """Validated input for one search-plan generation."""

    targets: tuple[GameSearchTarget, ...]
    latitude: float
    longitude: float
    max_results: int
    max_queries: int
    strategy: SearchPlanGenerationStrategy = (
        SearchPlanGenerationStrategy.CANONICAL_ONLY
    )

    def __post_init__(self) -> None:
        if isinstance(self.targets, (str, bytes)) or not isinstance(
            self.targets, Sequence
        ):
            raise TypeError("targets must be a sequence of GameSearchTarget")
        targets = tuple(self.targets)
        if any(not isinstance(target, GameSearchTarget) for target in targets):
            raise TypeError("targets must contain only GameSearchTarget")
        object.__setattr__(self, "targets", targets)

        self._validate_coordinate("latitude", self.latitude, -90.0, 90.0)
        self._validate_coordinate("longitude", self.longitude, -180.0, 180.0)
        self._validate_positive_integer("max_results", self.max_results)
        self._validate_positive_integer("max_queries", self.max_queries)

        if not isinstance(self.strategy, SearchPlanGenerationStrategy):
            raise TypeError("strategy must be SearchPlanGenerationStrategy")

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

    @staticmethod
    def _validate_positive_integer(name: str, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be int")
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True)
class SearchPlanGenerationResult:
    """Validated output metadata for one generated search plan."""

    plan: SearchPlan
    targets_received: int
    queries_generated: int
    duplicate_queries_removed: int

    def __post_init__(self) -> None:
        if not isinstance(self.plan, SearchPlan):
            raise TypeError("plan must be SearchPlan")

        counter_names = (
            "targets_received",
            "queries_generated",
            "duplicate_queries_removed",
        )
        for name in counter_names:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be int")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

        if self.queries_generated != len(self.plan.queries):
            raise ValueError("queries_generated must equal len(plan.queries)")
        if self.duplicate_queries_removed > self.targets_received:
            raise ValueError(
                "duplicate_queries_removed cannot exceed targets_received"
            )
        if (
            self.queries_generated + self.duplicate_queries_removed
            > self.targets_received
        ):
            raise ValueError(
                "queries_generated + duplicate_queries_removed cannot exceed "
                "targets_received"
            )


class SearchPlanGenerationError(Exception):
    """Base error for search-plan generation failures."""


class UnknownGameSearchTargetError(SearchPlanGenerationError):
    """Raised when a requested game target is not known by the generator."""


class SearchPlanLimitExceededError(SearchPlanGenerationError):
    """Raised when generating a plan would exceed its configured limit."""


class ISearchPlanGenerator(ABC):
    """Application input port for deterministic search-plan generation."""

    @abstractmethod
    def generate(
        self,
        request: SearchPlanGenerationRequest,
    ) -> SearchPlanGenerationResult:
        """Generate one explicit search plan."""
        pass
