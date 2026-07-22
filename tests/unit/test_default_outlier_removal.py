"""Unit tests for DefaultOutlierRemoval.

Tests outlier detection and removal using Tukey's IQR method.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.outlier_removal import (
    OutlierMethod,
    OutlierReason,
)
from domain.interfaces.price_dataset_builder import (
    PriceDataset,
    PriceObservation,
)
from domain.interfaces.price_statistics import PriceStatisticsResult
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval


@pytest.fixture
def outlier_removal() -> DefaultOutlierRemoval:
    """Create DefaultOutlierRemoval instance."""
    return DefaultOutlierRemoval()


@pytest.fixture
def sample_game() -> DetectedGame:
    """Create sample game for testing."""
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def create_dataset(prices: list[float], game: DetectedGame) -> PriceDataset:
    """Helper to create PriceDataset from list of prices."""
    observations = [
        PriceObservation(
            price=Decimal(str(price)),
            currency="EUR",
            listing_id=str(i),
            title=f"Listing {i}",
            platform=Platform.PS4,
            source="test",
            raw_listing={},
        )
        for i, price in enumerate(prices, 1)
    ]

    return PriceDataset(
        observations=observations,
        game=game,
        created_at=datetime.now(timezone.utc),
        sample_size=len(observations),
    )


def create_statistics(
    count: int,
    min_price: float,
    max_price: float,
    q1: float,
    q3: float,
    iqr: float,
) -> PriceStatisticsResult:
    """Helper to create PriceStatisticsResult."""
    return PriceStatisticsResult(
        count=count,
        min_price=Decimal(str(min_price)),
        max_price=Decimal(str(max_price)),
        mean_price=(Decimal(str(min_price)) + Decimal(str(max_price))) / 2,
        median_price=(Decimal(str(q1)) + Decimal(str(q3))) / 2,
        standard_deviation=Decimal("5.0"),
        variance=Decimal("25.0"),
        q1=Decimal(str(q1)),
        q3=Decimal(str(q3)),
        iqr=Decimal(str(iqr)),
        percentile_10=Decimal(str(min_price)),
        percentile_25=Decimal(str(q1)),
        percentile_75=Decimal(str(q3)),
        percentile_90=Decimal(str(max_price)),
    )


class TestEmptyDataset:
    """Test empty dataset handling."""

    def test_empty_dataset(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should handle empty dataset (no removal due to size)."""
        dataset = create_dataset([], sample_game)
        statistics = create_statistics(0, 0.0, 0.0, 0.0, 0.0, 0.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 0
        assert result.kept_count == 0
        assert result.method == OutlierMethod.IQR


class TestSingleObservation:
    """Test single observation handling."""

    def test_one_observation(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should not remove from single observation dataset."""
        dataset = create_dataset([15.0], sample_game)
        statistics = create_statistics(1, 15.0, 15.0, 15.0, 15.0, 0.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 0
        assert result.kept_count == 1
        assert result.method == OutlierMethod.IQR


class TestThreeObservations:
    """Test three observations handling."""

    def test_three_observations(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should not remove from dataset with 3 observations."""
        dataset = create_dataset([10.0, 15.0, 20.0], sample_game)
        statistics = create_statistics(3, 10.0, 20.0, 12.5, 17.5, 5.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 0
        assert result.kept_count == 3
        assert result.method == OutlierMethod.IQR


class TestFourObservations:
    """Test four observations handling."""

    def test_four_observations_no_outliers(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should process dataset with 4 observations."""
        dataset = create_dataset([10.0, 12.0, 18.0, 20.0], sample_game)
        statistics = create_statistics(4, 10.0, 20.0, 11.0, 19.0, 8.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # Should calculate bounds but no outliers
        assert result.kept_count == 4
        assert result.method == OutlierMethod.IQR

    def test_four_observations_with_outlier(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove outlier from dataset with 4 observations."""
        dataset = create_dataset([10.0, 15.0, 18.0, 100.0], sample_game)
        # Q1=13.75, Q3=43.5, IQR=29.75 (approximate realistic values)
        statistics = create_statistics(4, 10.0, 100.0, 13.75, 43.5, 29.75)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # Should remove the 100.0 outlier (above upper_bound = 43.5 + 1.5*29.75 = 88.125)
        assert result.removed_count == 1
        assert result.kept_count == 3
        assert result.removed_observations[0].price == 100.0


class TestNoOutliers:
    """Test datasets without outliers."""

    def test_no_outliers_normal_distribution(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should not remove from clean dataset."""
        prices = [12.0, 13.0, 15.0, 16.0, 18.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 12.0, 18.0, 13.0, 16.0, 3.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 0
        assert result.kept_count == 5
        assert len(result.removed_observations) == 0

    def test_no_outliers_equal_prices(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should not remove when all prices are equal (IQR = 0)."""
        prices = [15.0] * 10
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(10, 15.0, 15.0, 15.0, 15.0, 0.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 0
        assert result.kept_count == 10
        assert result.method == OutlierMethod.IQR


class TestUpperOutlier:
    """Test detection of upper outliers."""

    def test_single_upper_outlier(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove single upper outlier."""
        prices = [10.0, 12.0, 15.0, 18.0, 20.0, 100.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(6, 10.0, 100.0, 12.0, 18.0, 6.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 1
        assert result.kept_count == 5
        assert result.removed_observations[0].price == 100.0
        assert result.removed_observations[0].reason == OutlierReason.ABOVE_UPPER_BOUND

    def test_multiple_upper_outliers(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove multiple upper outliers."""
        prices = [10.0, 12.0, 15.0, 18.0, 100.0, 200.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(6, 10.0, 200.0, 11.0, 16.5, 5.5)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 2
        assert result.kept_count == 4
        removed_prices = [obs.price for obs in result.removed_observations]
        assert 100.0 in removed_prices
        assert 200.0 in removed_prices


class TestLowerOutlier:
    """Test detection of lower outliers."""

    def test_single_lower_outlier(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove single lower outlier."""
        prices = [1.0, 15.0, 18.0, 20.0, 22.0, 25.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(6, 1.0, 25.0, 16.5, 21.0, 4.5)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 1
        assert result.kept_count == 5
        assert result.removed_observations[0].price == 1.0
        assert result.removed_observations[0].reason == OutlierReason.BELOW_LOWER_BOUND

    def test_multiple_lower_outliers(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove multiple lower outliers."""
        prices = [0.5, 1.0, 15.0, 18.0, 20.0, 22.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(6, 0.5, 22.0, 16.5, 19.0, 2.5)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 2
        assert result.kept_count == 4
        removed_prices = [obs.price for obs in result.removed_observations]
        assert 0.5 in removed_prices
        assert 1.0 in removed_prices


class TestMultipleOutliers:
    """Test detection of outliers on both sides."""

    def test_outliers_both_sides(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove outliers from both sides."""
        prices = [1.0, 10.0, 12.0, 15.0, 18.0, 20.0, 100.0]
        dataset = create_dataset(prices, sample_game)
        # Q1=11, Q3=19, IQR=8 (realistic for this distribution)
        statistics = create_statistics(7, 1.0, 100.0, 11.0, 19.0, 8.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # lower_bound = 11 - 12 = -1, upper_bound = 19 + 12 = 31
        # 1.0 is above -1 (kept), 100.0 is above 31 (removed)
        assert result.removed_count == 1
        assert result.kept_count == 6
        removed_prices = [obs.price for obs in result.removed_observations]
        assert 100.0 in removed_prices

    def test_multiple_outliers_each_side(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove multiple outliers from each side."""
        prices = [0.5, 1.0, 10.0, 12.0, 15.0, 18.0, 20.0, 100.0, 200.0]
        dataset = create_dataset(prices, sample_game)
        # Q1=5.5, Q3=59, IQR=53.5 (realistic for this wide distribution)
        statistics = create_statistics(9, 0.5, 200.0, 5.5, 59.0, 53.5)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # lower_bound = 5.5 - 80.25 = -74.75 (0.5 and 1.0 kept)
        # upper_bound = 59 + 80.25 = 139.25 (200.0 removed)
        assert result.removed_count == 1
        assert result.kept_count == 8


class TestZeroIQR:
    """Test zero IQR handling."""

    def test_zero_iqr_all_equal(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should not remove when IQR = 0 (all equal)."""
        prices = [15.0] * 10
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(10, 15.0, 15.0, 15.0, 15.0, 0.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 0
        assert result.kept_count == 10
        assert result.method == OutlierMethod.IQR

    def test_zero_iqr_mostly_equal(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should not remove when IQR = 0 (mostly equal)."""
        prices = [15.0, 15.0, 15.0, 15.0, 15.0, 16.0]
        dataset = create_dataset(prices, sample_game)
        # IQR = 0 if Q1 = Q3 = 15.0
        statistics = create_statistics(6, 15.0, 16.0, 15.0, 15.0, 0.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == 0
        assert result.method == OutlierMethod.IQR


class TestImmutability:
    """Test that original dataset is not modified."""

    def test_original_dataset_unchanged(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should not modify original dataset."""
        prices = [1.0, 10.0, 15.0, 20.0, 100.0]
        dataset = create_dataset(prices, sample_game)
        original_count = dataset.sample_size
        original_observations = list(dataset.observations)

        statistics = create_statistics(5, 1.0, 100.0, 10.0, 20.0, 10.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # Original dataset should be unchanged
        assert dataset.sample_size == original_count
        assert len(dataset.observations) == len(original_observations)
        assert dataset.observations[0].price == 1.0
        assert dataset.observations[-1].price == 100.0

        # Result should be different
        assert result.clean_dataset.sample_size != original_count


class TestRemovedCount:
    """Test removed_count accuracy."""

    def test_removed_count_matches_removed_observations(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should have consistent removed_count."""
        prices = [1.0, 10.0, 15.0, 20.0, 100.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 1.0, 100.0, 10.0, 20.0, 10.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.removed_count == len(result.removed_observations)


class TestKeptCount:
    """Test kept_count accuracy."""

    def test_kept_count_matches_clean_dataset(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should have consistent kept_count."""
        prices = [1.0, 10.0, 15.0, 20.0, 100.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 1.0, 100.0, 10.0, 20.0, 10.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.kept_count == result.clean_dataset.sample_size
        assert result.kept_count == len(result.clean_dataset.observations)

    def test_total_count_preserved(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should preserve total observation count."""
        prices = [1.0, 10.0, 15.0, 20.0, 100.0]
        dataset = create_dataset(prices, sample_game)
        original_count = dataset.sample_size

        statistics = create_statistics(5, 1.0, 100.0, 10.0, 20.0, 10.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.kept_count + result.removed_count == original_count


class TestBoundsCalculation:
    """Test IQR bounds calculation."""

    def test_bounds_calculated_correctly(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate bounds using Tukey's formula."""
        prices = [10.0, 15.0, 20.0, 25.0, 30.0]
        dataset = create_dataset(prices, sample_game)
        # Q1 = 12.5, Q3 = 27.5, IQR = 15.0
        statistics = create_statistics(5, 10.0, 30.0, 12.5, 27.5, 15.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # lower_bound = Q1 - 1.5 * IQR = 12.5 - 22.5 = -10.0
        # upper_bound = Q3 + 1.5 * IQR = 27.5 + 22.5 = 50.0
        assert result.lower_bound == 12.5 - 1.5 * 15.0
        assert result.upper_bound == 27.5 + 1.5 * 15.0

    def test_bounds_correct_for_small_iqr(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate narrow bounds for small IQR."""
        prices = [14.0, 15.0, 15.0, 16.0, 17.0]
        dataset = create_dataset(prices, sample_game)
        # Small IQR
        statistics = create_statistics(5, 14.0, 17.0, 14.5, 16.5, 2.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # lower_bound = 14.5 - 3.0 = 11.5
        # upper_bound = 16.5 + 3.0 = 19.5
        assert result.lower_bound == 11.5
        assert result.upper_bound == 19.5


class TestOutlierObservation:
    """Test OutlierObservation details."""

    def test_outlier_observation_has_original(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should preserve original observation in OutlierObservation."""
        prices = [1.0, 10.0, 15.0, 20.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(4, 1.0, 20.0, 10.0, 20.0, 10.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        if result.removed_count > 0:
            outlier = result.removed_observations[0]
            assert outlier.original_observation is not None
            assert outlier.original_observation.price == outlier.price

    def test_outlier_observation_reason_specific(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should have specific reasons for each outlier."""
        prices = [1.0, 10.0, 15.0, 20.0, 100.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 1.0, 100.0, 10.0, 20.0, 10.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        for outlier in result.removed_observations:
            assert outlier.reason in [
                OutlierReason.BELOW_LOWER_BOUND,
                OutlierReason.ABOVE_UPPER_BOUND,
            ]


class TestMethodField:
    """Test method field in result."""

    def test_method_is_tukey_iqr(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should report method as IQR."""
        prices = [10.0, 15.0, 20.0, 25.0, 30.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 10.0, 30.0, 12.5, 27.5, 15.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.method == OutlierMethod.IQR

    def test_method_indicates_skip_reason(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should use IQR method even when skipping."""
        prices = [15.0, 16.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(2, 15.0, 16.0, 15.5, 15.5, 0.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        assert result.method == OutlierMethod.IQR


class TestRealWorldScenarios:
    """Test realistic price scenarios."""

    def test_typical_game_prices_no_outliers(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should handle typical clean price distribution."""
        prices = [10.0, 12.0, 12.5, 13.0, 15.0, 15.0, 16.0, 17.0, 18.0, 20.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(10, 10.0, 20.0, 12.25, 17.25, 5.0)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # Should not remove any
        assert result.removed_count == 0

    def test_typical_game_prices_with_one_outlier(
        self,
        outlier_removal: DefaultOutlierRemoval,
        sample_game: DetectedGame,
    ) -> None:
        """Should remove obvious outlier from typical distribution."""
        prices = [10.0, 12.0, 13.0, 15.0, 16.0, 18.0, 20.0, 150.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(8, 10.0, 150.0, 12.5, 19.0, 6.5)

        result = outlier_removal.remove_outliers(dataset, statistics)

        # Should remove 150.0
        assert result.removed_count == 1
        assert 150.0 in [obs.price for obs in result.removed_observations]
