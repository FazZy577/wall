"""Unit tests for DefaultPriceDatasetBuilder.

Tests the transformation of ComparableListing into PriceDataset
using mocks (no real data).
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from domain.currency import CurrencyMismatchError
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.price_dataset_builder import (
    InvalidComparableListingError,
    PriceDataset,
)
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)


@pytest.fixture
def dataset_builder() -> DefaultPriceDatasetBuilder:
    """Create DefaultPriceDatasetBuilder instance."""
    return DefaultPriceDatasetBuilder(source="wallapop")


@pytest.fixture
def target_game() -> DetectedGame:
    """Create target game for testing."""
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def create_comparable_listing(
    listing_id: str,
    title: str,
    price: float,
    currency: str = "EUR",
    game: DetectedGame | None = None,
) -> ComparableListing:
    """Helper to create ComparableListing for tests."""
    if game is None:
        game = DetectedGame(
            canonical_name="Grand Theft Auto V",
            matched_text="gta v",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )

    return ComparableListing(
        listing_id=listing_id,
        title=title,
        description="Test listing",
        price=Decimal(str(price)),
        currency=currency,
        detected_game=game,
        url=f"https://example.com/item/{listing_id}",
    )


class TestEmptyDataset:
    """Test empty dataset handling."""

    def test_empty_list(self, dataset_builder: DefaultPriceDatasetBuilder) -> None:
        """Should return empty dataset when no listings provided."""
        result = dataset_builder.build([], "EUR")

        assert isinstance(result, PriceDataset)
        assert result.sample_size == 0
        assert len(result.observations) == 0
        assert result.game.canonical_name == "Unknown"
        assert isinstance(result.created_at, datetime)


class TestNormalDataset:
    """Test normal dataset building."""

    def test_single_listing(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should build dataset from single listing."""
        listing = create_comparable_listing("123", "GTA V PS4", 15.0, game=target_game)

        result = dataset_builder.build([listing], "EUR")

        assert result.sample_size == 1
        assert len(result.observations) == 1
        assert result.game == target_game

        obs = result.observations[0]
        assert obs.price == 15.0
        assert obs.currency == "EUR"
        assert obs.listing_id == "123"
        assert obs.title == "GTA V PS4"
        assert obs.platform == Platform.PS4
        assert obs.source == "wallapop"

    def test_multiple_listings(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should build dataset from multiple listings."""
        listings = [
            create_comparable_listing("1", "GTA V PS4", 15.0, game=target_game),
            create_comparable_listing("2", "GTA V Premium", 18.0, game=target_game),
            create_comparable_listing("3", "GTA V", 12.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        assert result.sample_size == 3
        assert len(result.observations) == 3
        assert result.game == target_game

        prices = [obs.price for obs in result.observations]
        assert prices == [15.0, 18.0, 12.0]

    def test_preserves_all_data(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should preserve all relevant data in observations."""
        listing = create_comparable_listing("999", "Test Title", 25.5, game=target_game)

        result = dataset_builder.build([listing], "EUR")

        obs = result.observations[0]
        assert obs.price == 25.5
        assert obs.currency == "EUR"
        assert obs.listing_id == "999"
        assert obs.title == "Test Title"
        assert obs.platform == Platform.PS4
        assert obs.source == "wallapop"
        assert "listing_id" in obs.raw_listing
        assert obs.raw_listing["price"] == 25.5


class TestInvalidPrices:
    """Test invalid price handling."""

    def test_missing_price(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should discard listing with missing price."""
        listing = ComparableListing(
            listing_id="1",
            title="GTA V",
            description="",
            price=Decimal("1"),
            currency="EUR",
            detected_game=target_game,
            url="",
        )
        listing.price = None  # type: ignore[assignment]

        result = dataset_builder.build([listing], "EUR")

        assert result.sample_size == 0
        assert len(result.observations) == 0

    def test_zero_price(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should discard listing with zero price."""
        listing = create_comparable_listing("1", "GTA V", 0.0, game=target_game)

        result = dataset_builder.build([listing], "EUR")

        assert result.sample_size == 0
        assert len(result.observations) == 0

    def test_negative_price(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should discard listing with negative price."""
        listing = create_comparable_listing("1", "GTA V", -10.0, game=target_game)

        result = dataset_builder.build([listing], "EUR")

        assert result.sample_size == 0
        assert len(result.observations) == 0

    def test_mixed_valid_invalid(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should keep valid listings and discard invalid ones."""
        listings = [
            create_comparable_listing("1", "Valid 1", 15.0, game=target_game),
            create_comparable_listing("2", "Invalid", 0.0, game=target_game),
            create_comparable_listing("3", "Valid 2", 18.0, game=target_game),
            create_comparable_listing("4", "Invalid", -5.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        assert result.sample_size == 2
        assert len(result.observations) == 2
        assert result.observations[0].price == 15.0
        assert result.observations[1].price == 18.0


class TestCurrencyHandling:
    """Test currency validation."""

    def test_valid_eur(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should accept EUR currency."""
        listing = create_comparable_listing("1", "GTA V", Decimal("15.0"), "EUR", game=target_game)

        result = dataset_builder.build([listing], "EUR")

        assert result.sample_size == 1
        assert result.observations[0].currency == "EUR"

    def test_valid_usd(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should accept USD currency."""
        listing = create_comparable_listing("1", "GTA V", 15.0, "USD", game=target_game)

        result = dataset_builder.build([listing], "USD")

        assert result.sample_size == 1
        assert result.observations[0].currency == "USD"

    def test_valid_gbp(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should accept GBP currency."""
        listing = create_comparable_listing("1", "GTA V", 15.0, "GBP", game=target_game)

        result = dataset_builder.build([listing], "GBP")

        assert result.sample_size == 1
        assert result.observations[0].currency == "GBP"

    def test_lowercase_currency(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Domain rejects non-canonical lowercase currency."""
        with pytest.raises(ValueError, match="currency"):
            create_comparable_listing("1", "GTA V", 15.0, "eur", game=target_game)

    def test_invalid_currency(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Domain rejects malformed currency."""
        with pytest.raises(ValueError, match="currency"):
            create_comparable_listing("1", "GTA V", 15.0, "€", game=target_game)

    def test_mixed_currencies(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should reject mixed currencies explicitly."""
        listings = [
            create_comparable_listing("1", "Valid EUR", Decimal("15.0"), "EUR", game=target_game),
            create_comparable_listing("3", "Valid USD", 18.0, "USD", game=target_game),
        ]

        with pytest.raises(CurrencyMismatchError, match="expected EUR, got USD"):
            dataset_builder.build(listings, "EUR")


class TestIndividualErrors:
    """Test error handling for individual listings."""

    def test_corrupted_listing_continues(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should continue processing after individual listing error."""
        # Create one valid listing
        valid_listing = create_comparable_listing("1", "Valid", 15.0, game=target_game)

        # Create corrupted listing (mock will raise exception)
        corrupted_listing = Mock(spec=ComparableListing)
        corrupted_listing.listing_id = "999"
        corrupted_listing.currency = "EUR"
        corrupted_listing.price = property(Mock(side_effect=Exception("Corrupted")))

        # Create another valid listing
        valid_listing_2 = create_comparable_listing("2", "Valid 2", 18.0, game=target_game)

        result = dataset_builder.build([valid_listing, corrupted_listing, valid_listing_2], "EUR")

        # Should have processed both valid listings
        assert result.sample_size == 2
        assert result.observations[0].price == 15.0
        assert result.observations[1].price == 18.0

    def test_all_listings_fail(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should return empty dataset if all listings fail."""
        corrupted_1 = Mock(spec=ComparableListing)
        corrupted_1.listing_id = "1"
        corrupted_1.detected_game = target_game
        corrupted_1.currency = "EUR"
        corrupted_1.price = property(Mock(side_effect=Exception("Error")))

        corrupted_2 = Mock(spec=ComparableListing)
        corrupted_2.listing_id = "2"
        corrupted_2.detected_game = target_game
        corrupted_2.currency = "EUR"
        corrupted_2.price = property(Mock(side_effect=Exception("Error")))

        result = dataset_builder.build([corrupted_1, corrupted_2], "EUR")

        assert result.sample_size == 0
        assert len(result.observations) == 0


class TestSampleSize:
    """Test sample_size field."""

    def test_sample_size_matches_observations(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should set sample_size equal to number of observations."""
        listings = [
            create_comparable_listing("1", "L1", 15.0, game=target_game),
            create_comparable_listing("2", "L2", 18.0, game=target_game),
            create_comparable_listing("3", "L3", 12.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        assert result.sample_size == len(result.observations)
        assert result.sample_size == 3

    def test_sample_size_after_filtering(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should set sample_size based on valid observations only."""
        listings = [
            create_comparable_listing("1", "Valid", 15.0, game=target_game),
            create_comparable_listing("2", "Invalid", 0.0, game=target_game),
            create_comparable_listing("3", "Valid", 18.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        assert result.sample_size == 2


class TestDatasetMetadata:
    """Test dataset metadata fields."""

    def test_created_at_timestamp(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should set created_at to current UTC timestamp."""
        listing = create_comparable_listing("1", "GTA V", 15.0, game=target_game)

        before = datetime.now(timezone.utc)
        result = dataset_builder.build([listing], "EUR")
        after = datetime.now(timezone.utc)

        assert before <= result.created_at <= after
        assert result.created_at.tzinfo == timezone.utc

    def test_game_reference(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should store reference to target game."""
        listing = create_comparable_listing("1", "GTA V", 15.0, game=target_game)

        result = dataset_builder.build([listing], "EUR")

        assert result.game == target_game
        assert result.game.canonical_name == "Grand Theft Auto V"
        assert result.game.platform == Platform.PS4


class TestRawListingData:
    """Test raw_listing field preservation."""

    def test_raw_listing_contains_all_fields(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should include all listing fields in raw_listing."""
        listing = create_comparable_listing("123", "Test Title", 25.0, game=target_game)

        result = dataset_builder.build([listing], "EUR")

        raw = result.observations[0].raw_listing
        assert raw["listing_id"] == "123"
        assert raw["title"] == "Test Title"
        assert raw["description"] == "Test listing"
        assert raw["price"] == 25.0
        assert raw["currency"] == "EUR"
        assert "url" in raw


class TestSourceField:
    """Test source field in observations."""

    def test_default_source(
        self,
        target_game: DetectedGame,
    ) -> None:
        """Should use default source from constructor."""
        builder = DefaultPriceDatasetBuilder(source="wallapop")
        listing = create_comparable_listing("1", "GTA V", 15.0, game=target_game)

        result = builder.build([listing], "EUR")

        assert result.observations[0].source == "wallapop"

    def test_custom_source(
        self,
        target_game: DetectedGame,
    ) -> None:
        """Should use custom source from constructor."""
        builder = DefaultPriceDatasetBuilder(source="vinted")
        listing = create_comparable_listing("1", "GTA V", 15.0, game=target_game)

        result = builder.build([listing], "EUR")

        assert result.observations[0].source == "vinted"


class TestNoStatisticalCalculations:
    """Test that builder does NOT perform statistical calculations."""

    def test_does_not_calculate_mean(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should NOT calculate mean price."""
        listings = [
            create_comparable_listing("1", "L1", 10.0, game=target_game),
            create_comparable_listing("2", "L2", 20.0, game=target_game),
            create_comparable_listing("3", "L3", 30.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        # Dataset should not have mean field
        assert not hasattr(result, "mean")
        assert not hasattr(result, "average")

    def test_does_not_calculate_median(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should NOT calculate median price."""
        listings = [
            create_comparable_listing("1", "L1", 10.0, game=target_game),
            create_comparable_listing("2", "L2", 20.0, game=target_game),
            create_comparable_listing("3", "L3", 30.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        # Dataset should not have median field
        assert not hasattr(result, "median")

    def test_does_not_sort_observations(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should NOT sort observations by price."""
        listings = [
            create_comparable_listing("1", "L1", 30.0, game=target_game),
            create_comparable_listing("2", "L2", 10.0, game=target_game),
            create_comparable_listing("3", "L3", 20.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        # Observations should be in original order
        prices = [obs.price for obs in result.observations]
        assert prices == [30.0, 10.0, 20.0]

    def test_does_not_filter_outliers(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should NOT filter statistical outliers."""
        listings = [
            create_comparable_listing("1", "L1", 15.0, game=target_game),
            create_comparable_listing("2", "L2", 16.0, game=target_game),
            create_comparable_listing("3", "Outlier", 500.0, game=target_game),
            create_comparable_listing("4", "L4", 17.0, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        # All valid observations should be included (even outlier)
        assert result.sample_size == 4
        prices = [obs.price for obs in result.observations]
        assert 500.0 in prices

    def test_does_not_modify_prices(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        """Should NOT modify original prices."""
        listings = [
            create_comparable_listing("1", "L1", 15.99, game=target_game),
            create_comparable_listing("2", "L2", 20.50, game=target_game),
        ]

        result = dataset_builder.build(listings, "EUR")

        # Prices should be exactly as provided
        assert result.observations[0].price == Decimal("15.99")
        assert result.observations[1].price == Decimal("20.50")


class TestCanonicalComparableDeduplication:
    """A marketplace publication contributes at most one observation."""

    def test_exact_duplicates_keep_first_and_do_not_mutate_input(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        first = create_comparable_listing("a", "A", Decimal("10"), game=target_game)
        repeated = create_comparable_listing("a", "A", Decimal("10"), game=target_game)
        second = create_comparable_listing("b", "B", Decimal("20"), game=target_game)
        listings = [first, repeated, second]

        result = dataset_builder.build(listings, "EUR")

        assert [(item.listing_id, item.price) for item in result.observations] == [
            ("a", Decimal("10")),
            ("b", Decimal("20")),
        ]
        assert result.sample_size == 2
        assert listings == [first, repeated, second]

    def test_first_occurrence_wins_when_duplicate_prices_disagree(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        first = create_comparable_listing("a", "First", Decimal("10"), game=target_game)
        repeated = create_comparable_listing("a", "Later", Decimal("99"), game=target_game)

        result = dataset_builder.build([first, repeated], "EUR")

        assert result.sample_size == 1
        assert result.observations[0].price == Decimal("10")
        assert result.observations[0].title == "First"

    def test_same_listing_id_on_different_platforms_is_distinct(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        ps5_game = DetectedGame(
            canonical_name=target_game.canonical_name,
            matched_text="gta v",
            platform=Platform.PS5,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        ps4 = create_comparable_listing("123", "GTA V", Decimal("10"), game=target_game)
        ps5 = create_comparable_listing("123", "GTA V", Decimal("20"), game=ps5_game)

        result = dataset_builder.build([ps4, ps5], "EUR")

        assert [(item.platform, item.price) for item in result.observations] == [
            (Platform.PS4, Decimal("10")),
            (Platform.PS5, Decimal("20")),
        ]

    def test_similar_listings_with_different_ids_are_distinct(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        first = create_comparable_listing("a", "Same title", Decimal("10"), game=target_game)
        second = create_comparable_listing("b", "Same title", Decimal("10"), game=target_game)

        result = dataset_builder.build([first, second], "EUR")

        assert [item.listing_id for item in result.observations] == ["a", "b"]

    def test_currency_validation_precedes_duplicate_elimination(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        eur = create_comparable_listing("a", "A", Decimal("10"), "EUR", target_game)
        usd = create_comparable_listing("a", "A", Decimal("10"), "USD", target_game)

        with pytest.raises(CurrencyMismatchError, match="expected EUR, got USD"):
            dataset_builder.build([eur, usd], "EUR")

    def test_wrong_domain_type_is_not_hidden_after_valid_comparable(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        comparable = create_comparable_listing("a", "A", Decimal("10"), game=target_game)
        candidate = CandidateListing(
            listing_id="a",
            title="A candidate",
            description="",
            price=Decimal("10"),
            currency="EUR",
            url="https://example.com/candidate/a",
        )

        with pytest.raises(
            InvalidComparableListingError,
            match="CandidateListing cannot be used as a market comparable",
        ):
            dataset_builder.build([comparable, candidate], "EUR")

    def test_deduplication_state_is_local_to_each_build(
        self,
        dataset_builder: DefaultPriceDatasetBuilder,
        target_game: DetectedGame,
    ) -> None:
        comparable = create_comparable_listing("a", "A", Decimal("10"), game=target_game)

        first = dataset_builder.build([comparable, comparable], "EUR")
        second = dataset_builder.build([comparable], "EUR")

        assert first.sample_size == 1
        assert second.sample_size == 1
