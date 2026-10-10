"""Observed search bounds; exhaustion refers only to the requested search."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MarketplaceCategory(StrEnum):
    CONSOLES_AND_VIDEO_GAMES = "consoles_and_video_games"


class SearchStopReason(StrEnum):
    EXHAUSTED = "exhausted"
    RESULT_LIMIT = "result_limit"
    PAGE_LIMIT = "page_limit"
    PAGINATION_UNKNOWN = "pagination_unknown"
    UNREPORTED = "unreported"
    ERROR = "error"


@dataclass(frozen=True)
class SearchCoverage:
    pages_received: int | None = None
    max_pages: int | None = None
    items_received: int | None = None
    stop_reason: SearchStopReason = SearchStopReason.UNREPORTED

    def __post_init__(self) -> None:
        if not isinstance(self.stop_reason, SearchStopReason):
            raise TypeError("stop_reason must be SearchStopReason")
        for name in ("pages_received", "max_pages", "items_received"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if self.max_pages == 0:
            raise ValueError("max_pages must be positive")
        if (self.pages_received is not None and self.max_pages is not None
                and self.pages_received > self.max_pages):
            raise ValueError("pages_received exceeds max_pages")
        if self.stop_reason is SearchStopReason.EXHAUSTED and not self.pages_received:
            raise ValueError("exhaustion requires at least one received page")


@dataclass(frozen=True)
class MarketplaceSearchBatch:
    listings: tuple[dict[str, Any], ...]
    coverage: SearchCoverage

    def __post_init__(self) -> None:
        object.__setattr__(self, "listings", tuple(self.listings))
        if not isinstance(self.coverage, SearchCoverage):
            raise TypeError("coverage must be SearchCoverage")


class MarketplaceSearchFailure(Exception):
    """Technical search failure carrying any coverage observed before failing."""

    coverage: SearchCoverage = SearchCoverage(stop_reason=SearchStopReason.ERROR)
