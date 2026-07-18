"""Marketplace listing search interface (port)."""

from abc import ABC, abstractmethod
from typing import Any


class IMarketplaceSearch(ABC):
    """Minimal async contract for searching marketplace listings."""

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
