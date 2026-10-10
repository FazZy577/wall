"""Wallapop price collector implementation.

Orchestrates WallapopClient → GameDetector → ComparableFilter
to collect valid comparable listings.
"""

import logging
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from application.interfaces.listing_observation_recorder import (
    IListingObservationRecorder,
    ListingObservation,
    NullListingObservationRecorder,
)
from domain.currency import validate_currency_code
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.game_identity import GameIdentity
from domain.interfaces.comparable_filter import ComparableFilterInput, IComparableFilter
from domain.interfaces.game_detector import IGameDetector, ListingText
from domain.interfaces.marketplace_search import IMarketplaceSearch
from domain.interfaces.price_collector import IPriceCollector
from infrastructure.marketplaces.wallapop.listing_id import (
    normalize_wallapop_listing_id,
)

logger = logging.getLogger(__name__)


class WallapopPriceCollector(IPriceCollector):
    """Collects comparable listings from Wallapop.

    Orchestrates:
    1. Generate search query from game
    2. Search Wallapop with WallapopClient
    3. Detect games in each listing with GameDetector
    4. Filter valid comparables with ComparableFilter
    5. Return ComparableListing objects
    """

    def __init__(
        self,
        marketplace_search: IMarketplaceSearch,
        game_detector: IGameDetector,
        comparable_filter: IComparableFilter,
        *,
        verified_search_aliases: Mapping[GameIdentity, Sequence[str]] | None = None,
        observation_recorder: IListingObservationRecorder | None = None,
    ) -> None:
        """Initialize price collector.

        Args:
            marketplace_search: Marketplace listing search implementation
            game_detector: Game detection implementation
            comparable_filter: Comparable filtering implementation
            verified_search_aliases: Optional fallback names keyed by resolved
                identity. Each name is independently checked by the detector;
                fallbacks are tried only when earlier queries yield no comparables.
        """
        self.marketplace_search = marketplace_search
        self.observation_recorder = (
            observation_recorder if observation_recorder is not None
            else NullListingObservationRecorder()
        )
        self.game_detector = game_detector
        self.comparable_filter = comparable_filter
        self._verified_search_aliases: dict[GameIdentity, tuple[str, ...]] = {}
        for identity, aliases in (verified_search_aliases or {}).items():
            if not isinstance(identity, GameIdentity):
                raise TypeError("search alias keys must be GameIdentity")
            if isinstance(aliases, (str, bytes)) or not isinstance(aliases, Sequence):
                raise TypeError("search aliases must be a sequence of names")
            if any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
                raise ValueError("search aliases must be non-empty strings")
            self._verified_search_aliases[identity] = tuple(" ".join(alias.split()) for alias in aliases)

    async def collect_comparables(
        self,
        game: DetectedGame,
        latitude: float,
        longitude: float,
        max_results: int | None = None,
    ) -> list[ComparableListing]:
        """Collect comparable listings for a game.

        Args:
            game: Target game to find comparables for
            latitude: Search location latitude
            longitude: Search location longitude
            max_results: Maximum number of comparables to collect (None for all)

        Returns:
            List of validated comparable listings. Empty means the search
            completed without valid comparables.

        Raises:
            Exception: The original technical exception from the injected
                marketplace search operation.
        """
        for search_query in self._search_queries(game):
            comparables = await self._collect_for_query(
                game, search_query, latitude, longitude, max_results
            )
            if comparables:
                return comparables
        return []

    async def _collect_for_query(
        self,
        game: DetectedGame,
        search_query: str,
        latitude: float,
        longitude: float,
        max_results: int | None,
    ) -> list[ComparableListing]:
        logger.info("Searching for %r (game: %s)", search_query, game.canonical_name)
        # Step 2: Search Wallapop. Whole-operation failures propagate so
        # application scanners can distinguish them from a successful empty search.
        raw_listings = await self.marketplace_search.search_listings(
            keywords=search_query,
            latitude=latitude,
            longitude=longitude,
            max_results=max_results * 3 if max_results else 100,
        )
        logger.info(f"Found {len(raw_listings)} raw listings from Wallapop")

        # Step 3 & 4 & 5: Process each listing
        comparables: list[ComparableListing] = []

        for index, raw_listing in enumerate(raw_listings):
            if not isinstance(raw_listing, dict):
                logger.warning(
                    "Ignoring malformed marketplace listing at index %d: type=%s",
                    index,
                    type(raw_listing).__name__,
                )
                continue

            try:
                comparable = self._process_listing(raw_listing, game, source_query=search_query)
                if comparable:
                    comparables.append(comparable)
                    logger.debug(
                        "Valid comparable: %s - %s %s",
                        comparable.title,
                        comparable.currency,
                        comparable.price,
                    )

                    # Stop if we reached max_results
                    if max_results and len(comparables) >= max_results:
                        break

            except Exception as e:
                # Log but continue processing other listings
                try:
                    listing_id = (
                        normalize_wallapop_listing_id(raw_listing.get("id"))
                        or "unknown"
                    )
                except Exception:
                    listing_id = "unknown"
                try:
                    error_message = str(e)
                except Exception:
                    error_message = f"<unprintable {type(e).__name__}>"
                logger.warning(
                    "Failed to process listing %s: %s",
                    listing_id,
                    error_message,
                )
                continue

        # Storage failures must reach the scanner, not the malformed-item handler.
        for comparable in comparables:
            await self.observation_recorder.record_observation(ListingObservation(
                listing_id=comparable.listing_id, title=comparable.title,
                description=comparable.description, price=comparable.price,
                currency=comparable.currency, observed_at=datetime.now(UTC),
                status="resolved", detected_games=(comparable.detected_game,),
                source_query=comparable.source_query, role="comparable",
            ))
        logger.info(f"Collected {len(comparables)} valid comparables for {game.canonical_name}")
        return comparables

    def _generate_search_query(self, game: DetectedGame) -> str:
        """Use the resolved name, preserving every title token and subtitle."""
        GameIdentity.from_game(game)
        return self._append_platform(" ".join(game.canonical_name.split()), game.platform)

    def _search_queries(self, game: DetectedGame) -> Iterator[str]:
        """Try the canonical query first, then independently verified aliases.

        Seller matched_text is never used as query authority. An optional alias
        registry is copied at construction, and each fallback must resolve via
        the injected detector to exactly this identity before any search is sent.
        """
        canonical = self._generate_search_query(game)
        yield canonical
        identity = GameIdentity.from_game(game)
        seen = {canonical.casefold()}
        for alias in self._verified_search_aliases.get(identity, ()):
            query = self._append_platform(alias, game.platform)
            if query.casefold() in seen:
                continue
            seen.add(query.casefold())
            detected = self.game_detector.detect_games(ListingText(query, ""))
            if len(detected) != 1:
                continue
            candidate = detected[0]
            if candidate.detection_method is not DetectionMethod.EXACT_MATCH:
                continue
            try:
                candidate_identity = GameIdentity.from_game(candidate)
            except (TypeError, ValueError):
                continue
            if candidate_identity == identity:
                yield query

    @staticmethod
    def _append_platform(search_terms: str, platform: Platform) -> str:
        """Append the canonical platform unless it is already explicit."""
        normalized_terms = " ".join(search_terms.strip().casefold().split())
        normalized_platform = " ".join(platform.value.casefold().split())
        platform_pattern = re.compile(
            rf"(?<!\w){re.escape(normalized_platform)}(?!\w)"
        )
        if platform_pattern.search(normalized_terms) is not None:
            return search_terms.strip()
        return f"{search_terms.strip()} {platform.value}"

    def _process_listing(
        self,
        raw_listing: dict[str, Any],
        target_game: DetectedGame,
        *,
        source_query: str | None = None,
    ) -> ComparableListing | None:
        """Process a single raw listing.

        Steps:
        1. Extract listing data
        2. Detect games in listing
        3. Check if target game is detected
        4. Filter with comparable filter
        5. Return ComparableListing if valid

        Args:
            raw_listing: Raw listing data from Wallapop API
            target_game: Target game we're searching for

        Returns:
            ComparableListing if valid comparable, None otherwise
        """
        # Extract listing data
        listing_id = normalize_wallapop_listing_id(raw_listing.get("id"))
        title = raw_listing.get("title", "")
        description = raw_listing.get("description", "")
        price = raw_listing.get("price")
        raw_currency = raw_listing.get("currency")
        web_slug = raw_listing.get("web_slug", "")

        # Validate required fields
        if listing_id is None or not title or price is None:
            return None

        # Normalize external numeric data exactly once at the infrastructure edge.
        try:
            price_decimal = Decimal(str(price))
            if not price_decimal.is_finite():
                return None
            if not isinstance(raw_currency, str):
                return None
            currency = raw_currency.strip().upper()
            validate_currency_code(currency)
        except (InvalidOperation, ValueError, TypeError):
            return None

        # Detect games in listing
        listing_text = ListingText(title=title, description=description)
        detected_games = self.game_detector.detect_games(listing_text)

        # Check if the complete target identity is detected.
        target_identity = GameIdentity.from_game(target_game)
        target_detected = None
        for detected_game in detected_games:
            try:
                detected_identity = GameIdentity.from_game(detected_game)
            except (TypeError, ValueError):
                continue
            if detected_identity == target_identity:
                target_detected = detected_game
                break

        if not target_detected:
            return None

        # Filter with comparable filter
        listing_obj = ComparableFilterInput(
            title=title, description=description, price=price_decimal,
            detected_games=tuple(detected_games),
            currency=currency,
        )
        is_valid = self.comparable_filter.is_valid_comparable(target_game, listing_obj)

        if not is_valid:
            return None

        # Build URL
        url = f"https://es.wallapop.com/item/{web_slug}" if web_slug else ""

        return ComparableListing(
            listing_id=listing_id,
            title=title,
            description=description,
            price=price_decimal,
            currency=currency,
            detected_game=target_detected,
            url=url,
            raw_listing=raw_listing,
            source_query=source_query,
        )
