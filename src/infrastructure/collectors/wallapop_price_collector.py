"""Wallapop price collector implementation.

Orchestrates WallapopClient → GameDetector → ComparableFilter
to collect valid comparable listings.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from domain.currency import validate_currency_code
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame
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
    ) -> None:
        """Initialize price collector.

        Args:
            marketplace_search: Marketplace listing search implementation
            game_detector: Game detection implementation
            comparable_filter: Comparable filtering implementation
        """
        self.marketplace_search = marketplace_search
        self.game_detector = game_detector
        self.comparable_filter = comparable_filter

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
        # Step 1: Generate search query
        search_query = self._generate_search_query(game)
        logger.info(f"Searching for '{search_query}' (game: {game.canonical_name})")

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
                comparable = self._process_listing(raw_listing, game)
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

        logger.info(f"Collected {len(comparables)} valid comparables for {game.canonical_name}")
        return comparables

    def _generate_search_query(self, game: DetectedGame) -> str:
        """Generate search query from game.

        Uses the best alias for the game (shortest, most common).
        For example, "GTA V" instead of "Grand Theft Auto V".

        Args:
            game: Target game

        Returns:
            Search query string
        """
        # Use the matched_text if it's already a good query
        # Otherwise, try to extract a good alias from canonical name

        # If matched_text is short and looks good, use it
        if len(game.matched_text.split()) <= 3:
            return game.matched_text

        # Otherwise, try to create a concise query from canonical name
        # Handle common patterns:
        # "Grand Theft Auto V" -> "GTA V"
        # "Call of Duty: Black Ops 6" -> "COD Black Ops 6"
        # "EA Sports FC 24" -> "FC 24"

        canonical = game.canonical_name.lower()

        # GTA
        if "grand theft auto" in canonical:
            # Extract version (V, 5, IV, etc.)
            version = ""
            if " v" in canonical or canonical.endswith("v"):
                version = "V"
            elif " 5" in canonical or canonical.endswith("5"):
                version = "5"
            elif " iv" in canonical:
                version = "IV"
            elif " 4" in canonical:
                version = "4"
            return f"GTA {version}".strip() if version else "GTA"

        # Call of Duty
        if "call of duty" in canonical:
            # Extract the rest (e.g., "Black Ops 6", "Modern Warfare III")
            rest = canonical.replace("call of duty", "").strip()
            rest = rest.lstrip(":").strip()
            return f"COD {rest}" if rest else "COD"

        # EA Sports FC / FIFA
        if "ea sports fc" in canonical or "fifa" in canonical:
            # Extract year
            import re

            year_match = re.search(r"\b(20\d{2}|2[0-9])\b", canonical)
            if year_match:
                year = year_match.group(1)
                if "fifa" in canonical:
                    return f"FIFA {year}"
                else:
                    return f"FC {year}"
            return "FIFA" if "fifa" in canonical else "FC"

        # Default: use canonical name but include platform
        # "Red Dead Redemption 2" -> "Red Dead Redemption 2 PS4"
        return f"{game.canonical_name} {game.platform}"

    def _process_listing(
        self,
        raw_listing: dict[str, Any],
        target_game: DetectedGame,
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

        # Check if target game is detected
        target_detected = None
        for detected_game in detected_games:
            if (
                detected_game.canonical_name == target_game.canonical_name
                and detected_game.platform == target_game.platform
            ):
                target_detected = detected_game
                break

        if not target_detected:
            return None

        # Filter with comparable filter
        listing_obj = ComparableFilterInput(
            title=title, description=description, price=price_decimal
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
        )
