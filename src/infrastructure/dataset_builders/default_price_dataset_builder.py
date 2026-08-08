"""Default price dataset builder implementation.

Transforms ComparableListing objects into clean PriceDataset
without performing any statistical calculations.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from domain.currency import CurrencyMismatchError, validate_currency_code
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.game_identity import GameIdentity
from domain.interfaces.price_dataset_builder import (
    InvalidComparableListingError,
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

    def __init__(self, source: str = "wallapop") -> None:
        """Initialize dataset builder.

        Args:
            source: Data source identifier (e.g., "wallapop")
        """
        self.source = source

    def build(self, comparable_listings: list[object], currency: str) -> PriceDataset:
        """Build a price dataset from comparable listings.

        Args:
            comparable_listings: List of ComparableListing objects

        Returns:
            PriceDataset with valid observations
        """
        validate_currency_code(currency)
        logger.info("Building dataset...")
        logger.info(f"Comparable listings: {len(comparable_listings)}")

        if not comparable_listings:
            # Empty dataset
            logger.warning("No comparable listings provided")
            return self._build_empty_dataset(currency)

        listings: list[ComparableListing] = []
        for listing in comparable_listings:
            if isinstance(listing, CandidateListing):
                raise InvalidComparableListingError(
                    "CandidateListing cannot be used as a market comparable"
                )
            if not isinstance(listing, ComparableListing):
                raise InvalidComparableListingError(
                    "Only ComparableListing can be used as a market comparable"
                )
            listings.append(listing)

        if not listings:
            logger.warning("No valid ComparableListing objects provided")
            return self._build_empty_dataset(currency)

        self._validate_homogeneous_identity(listings)

        for listing in listings:
            if listing.currency != currency:
                raise CurrencyMismatchError(currency, listing.currency, "PriceDataset")

        # Extract game from first listing (all should have same game)
        target_game = listings[0].detected_game

        observations: list[PriceObservation] = []
        seen_identities: set[tuple[Platform, str]] = set()
        discarded = 0

        for listing in listings:
            try:
                observation = self._extract_observation(listing)
                if observation:
                    identity = (listing.detected_game.platform, listing.listing_id)
                    if identity in seen_identities:
                        discarded += 1
                        continue
                    seen_identities.add(identity)
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
            currency=currency,
        )

    @staticmethod
    def _validate_homogeneous_identity(
        listings: list[ComparableListing],
    ) -> None:
        """Fail fast when comparables cross a game-market boundary."""
        identities: list[GameIdentity] = []
        for listing in listings:
            try:
                detected_game = listing.detected_game
            except AttributeError:
                # Preserve the existing corrupt-comparable behavior: extraction
                # will discard this item without weakening identity checks for
                # well-formed comparables.
                continue
            try:
                identities.append(
                    GameIdentity(
                        detected_game.canonical_name,
                        detected_game.platform,
                    )
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError(
                    "Comparable listings must have a concrete GameIdentity"
                ) from error

        if not identities:
            return
        target_identity = identities[0]
        if any(identity != target_identity for identity in identities[1:]):
            raise ValueError(
                "All comparable listings must share the same GameIdentity"
            )

    def _build_empty_dataset(self, currency: str) -> PriceDataset:
        """Build an empty dataset for error cases.

        Returns:
            Empty PriceDataset
        """
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
            currency=currency,
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

        # Build raw listing dict for reference
        raw_listing: dict[str, str | Decimal] = {
            "listing_id": listing.listing_id,
            "title": listing.title,
            "description": listing.description,
            "price": listing.price,
            "currency": listing.currency,
            "url": listing.url,
        }

        return PriceObservation(
            price=listing.price,
            currency=listing.currency,
            listing_id=listing.listing_id,
            title=listing.title,
            platform=listing.detected_game.platform,
            source=self.source,
            raw_listing=raw_listing,
        )
