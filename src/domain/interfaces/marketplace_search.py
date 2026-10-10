"""Marketplace listing search interface (port)."""

from abc import ABC, abstractmethod
from typing import Any

from domain.entities.search_coverage import (
    MarketplaceCategory,
    MarketplaceSearchBatch,
    SearchCoverage,
)


class IMarketplaceSearch(ABC):
    """Minimal async contract for searching marketplace listings."""

    async def search_with_scope(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
        *,
        category: MarketplaceCategory | None = None,
    ) -> MarketplaceSearchBatch:
        """Compatibility path reports unknown coverage; never drops category filters."""
        if category is not None:
            raise NotImplementedError("This marketplace client does not support discovery categories")
        listings = await self.search_listings(
            keywords=keywords, latitude=latitude, longitude=longitude, max_results=max_results
        )
        return MarketplaceSearchBatch(tuple(listings), SearchCoverage())

    @abstractmethod
    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Return normalized raw listings matching the search criteria."""
        pass
