"""Default price dataset builder implementation.

Transforms ComparableListing objects into clean PriceDataset
without performing any statistical calculations.
"""

import logging
from datetime import UTC, datetime

from domain.interfaces.price_collector import ComparableListing
from domain.interfaces.price_dataset_builder import (
    IPriceDatasetBuilder,
    PriceDataset,
    PriceObservation,
)

logger = logging.getLogger(__name__)


class DefaultPriceDatasetBuilder(IPriceDatasetBuilder):
    """Default implementation of price dataset builder.

    Transforms comparable listings into clean price observations.
    Does NOT perform any statistical calculations or filtering.
    """

    # Known valid currencies
    VALID_CURRENCIES = {"EUR", "USD", "GBP"}

    def __init__(self, source: str = "wallapop") -> None:
        """Initialize dataset builder.

        Args:
            source: Data source identifier (e.g., "wallapop")
        """
        self.source = source

    def build(self, comparable_listings: list[object]) -> PriceDataset:
        """Build a price dataset from comparable listings.

        Args:
            comparable_listings: List of ComparableListing objects

        Returns:
            PriceDataset with valid observations
        """
        logger.info("Building dataset...")
        logger.info(f"Comparable listings: {len(comparable_listings)}")

        if not comparable_listings:
            # Empty dataset
            logger.warning("No comparable listings provided")
            return self._build_empty_dataset()

        # Cast to ComparableListing for type safety
        listings = [listing for listing in comparable_listings if isinstance(listing, ComparableListing)]

        if not listings:
            logger.warning("No valid ComparableListing objects provided")
            return self._build_empty_dataset()

        # Extract game from first listing (all should have same game)
        target_game = listings[0].detected_game

        observations: list[PriceObservation] = []
        discarded = 0

        for listing in listings:
            try:
                observation = self._extract_observation(listing)
                if observation:
                    observations.append(observation)
                else:
                    discarded += 1
            except Exception as e:
                # Log error but continue processing
                logger.warning(
                    f"Failed to extract observation from listing {listing.listing_id}: {e}"
                )
                discarded += 1
                continue

        logger.info(f"Valid observations: {len(observations)}")
        logger.info(f"Discarded: {discarded}")

        return PriceDataset(
            observations=observations,
            game=target_game,
            created_at=datetime.now(UTC),
            sample_size=len(observations),
        )

    def _build_empty_dataset(self) -> PriceDataset:
        """Build an empty dataset for error cases.

        Returns:
            Empty PriceDataset
        """
        from domain.interfaces.game_detector import (
            DetectedGame,
            DetectionMethod,
            Platform,
        )

        # Create placeholder game
        placeholder_game = DetectedGame(
            canonical_name="Unknown",
            matched_text="",
            platform=Platform.UNKNOWN,
            confidence=0.0,
            detection_method=DetectionMethod.FUZZY_MATCH,
        )

        return PriceDataset(
            observations=[],
            game=placeholder_game,
            created_at=datetime.now(UTC),
            sample_size=0,
        )

    def _extract_observation(
        self,
        listing: ComparableListing,
    ) -> PriceObservation | None:
        """Extract a price observation from a comparable listing.

        Validates:
        - Price exists
        - Price > 0
        - Currency is valid

        Args:
            listing: ComparableListing to extract from

        Returns:
            PriceObservation if valid, None if should be discarded
        """
        # Validate price exists
        if listing.price is None:
            logger.debug(f"Listing {listing.listing_id}: missing price")
            return None

        # Validate price > 0
        if listing.price <= 0:
            logger.debug(f"Listing {listing.listing_id}: invalid price {listing.price}")
            return None

        # Validate currency
        currency = listing.currency.upper()
        if currency not in self.VALID_CURRENCIES:
            logger.debug(f"Listing {listing.listing_id}: unknown currency {currency}")
            return None

        # Build raw listing dict for reference
        raw_listing: dict[str, str | float] = {
            "listing_id": listing.listing_id,
            "title": listing.title,
            "description": listing.description,
            "price": listing.price,
            "currency": listing.currency,
            "url": listing.url,
        }

        return PriceObservation(
            price=listing.price,
            currency=currency,
            listing_id=listing.listing_id,
            title=listing.title,
            platform=listing.detected_game.platform,
            source=self.source,
            raw_listing=raw_listing,
        )
