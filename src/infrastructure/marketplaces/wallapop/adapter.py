"""Convert raw Wallapop search results into canonical purchase candidates."""

import logging
from decimal import Decimal
from typing import Any, cast

from application.interfaces.candidate_search import (
    CandidateItemFailure,
    CandidateItemFailureKind,
    CandidateSearchResult,
    ICandidateSearch,
    SearchQuery,
)
from domain.currency import validate_currency_code
from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.marketplaces.wallapop.listing_id import (
    normalize_wallapop_listing_id,
)

logger = logging.getLogger(__name__)

_INVALID_RAW_ITEM_REASON = "Marketplace search item is not an object"
_INVALID_CANDIDATE_REASON = "Marketplace item could not be converted to CandidateListing"


class WallapopCandidateSearchAdapter(ICandidateSearch):
    """Adapt one raw Wallapop search into canonical candidate listings."""

    def __init__(self, marketplace_search: IMarketplaceSearch) -> None:
        self.marketplace_search = marketplace_search

    async def search_candidates(self, query: SearchQuery) -> CandidateSearchResult:
        """Execute one search and isolate conversion failures by item."""
        raw_items = await self.marketplace_search.search_listings(
            keywords=query.keywords,
            latitude=query.latitude,
            longitude=query.longitude,
            max_results=query.max_results,
        )

        candidates: list[CandidateListing] = []
        failures: list[CandidateItemFailure] = []

        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict):
                logger.warning(
                    "Ignoring malformed candidate item at index %d: type=%s",
                    index,
                    type(raw_item).__name__,
                )
                failures.append(
                    CandidateItemFailure(
                        item_index=index,
                        kind=CandidateItemFailureKind.INVALID_RAW_ITEM,
                        reason=_INVALID_RAW_ITEM_REASON,
                        listing_id=None,
                        error_message=None,
                    )
                )
                continue

            try:
                candidates.append(self._to_candidate(raw_item))
            except Exception as error:
                listing_id = self._safe_listing_id(raw_item)
                error_message = self._safe_error_message(error)
                logger.warning(
                    "Ignoring invalid candidate item at index %d: "
                    "listing_id=%s error=%s",
                    index,
                    listing_id or "unknown",
                    error_message,
                )
                failures.append(
                    CandidateItemFailure(
                        item_index=index,
                        kind=CandidateItemFailureKind.INVALID_CANDIDATE,
                        reason=_INVALID_CANDIDATE_REASON,
                        listing_id=listing_id,
                        error_message=error_message,
                    )
                )

        return CandidateSearchResult(
            query=query,
            candidates=tuple(candidates),
            failures=tuple(failures),
            total_items_received=len(raw_items),
        )

    @staticmethod
    def _to_candidate(raw_item: dict[str, Any]) -> CandidateListing:
        listing_id = normalize_wallapop_listing_id(raw_item.get("id"))
        title = raw_item.get("title", "")
        description = raw_item.get("description", "")
        raw_price = raw_item.get("price")
        raw_currency = raw_item.get("currency")
        web_slug = raw_item.get("web_slug", "")

        price = Decimal(str(raw_price))
        normalized_currency = (
            raw_currency.strip().upper()
            if isinstance(raw_currency, str)
            else raw_currency
        )
        currency = validate_currency_code(normalized_currency)
        url = f"https://es.wallapop.com/item/{web_slug}" if web_slug else ""

        return CandidateListing(
            listing_id=cast(str, listing_id),
            title=title,
            description=description,
            price=price,
            currency=currency,
            url=url,
            raw_listing=dict(raw_item),
        )

    @staticmethod
    def _safe_listing_id(raw_item: dict[str, Any]) -> str | None:
        try:
            return normalize_wallapop_listing_id(raw_item.get("id"))
        except Exception:
            return None

    @staticmethod
    def _safe_error_message(error: Exception) -> str:
        try:
            return str(error)
        except Exception:
            return f"<unprintable {type(error).__name__}>"
