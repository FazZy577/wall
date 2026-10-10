"""Application port for recording unrecognized catalog candidates."""

from abc import ABC, abstractmethod
from datetime import datetime


class ICatalogDiscoveryRecorder(ABC):
    """Record minimal evidence that may identify a missing catalog game.

    Implementations own title normalization, textual-platform extraction, and
    persistence.  The narrow signature intentionally prevents descriptions,
    prices, seller data, and raw marketplace payloads from crossing this port.
    """

    @abstractmethod
    async def record_unrecognized_candidate(
        self,
        *,
        listing_id: str,
        original_title: str,
        observed_at: datetime,
    ) -> None:
        """Record one observation without changing candidate-routing semantics."""
        pass


class NullCatalogDiscoveryRecorder(ICatalogDiscoveryRecorder):
    """Disabled recorder that performs no persistence or validation."""

    async def record_unrecognized_candidate(
        self,
        *,
        listing_id: str,
        original_title: str,
        observed_at: datetime,
    ) -> None:
        """Ignore an observation while preserving the async port contract."""
        del listing_id, original_title, observed_at


__all__ = ("ICatalogDiscoveryRecorder", "NullCatalogDiscoveryRecorder")
