"""Unit tests for DefaultPriceStatistics.

Tests statistical calculations on various price datasets.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.price_dataset_builder import (
    PriceDataset,
    PriceObservation,
)
from domain.interfaces.price_statistics import (
    EmptyDatasetError,
    PriceStatisticsResult,
)
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


@pytest.fixture
def statistics_calculator() -> DefaultPriceStatistics:
    """Create DefaultPriceStatistics instance."""
    return DefaultPriceStatistics()


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


class TestEmptyDataset:
    """Test empty dataset handling."""

    def test_empty_observations(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should raise EmptyDatasetError for dataset with no observations."""
        dataset = PriceDataset(
            observations=[],
            game=sample_game,
            created_at=datetime.now(timezone.utc),
            sample_size=0,
        )

        with pytest.raises(EmptyDatasetError) as exc_info:
            statistics_calculator.calculate(dataset)

        assert "empty dataset" in str(exc_info.value).lower()

    def test_zero_sample_size(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should raise EmptyDatasetError for dataset with sample_size=0."""
        dataset = PriceDataset(
            observations=[],
            game=sample_game,
            created_at=datetime.now(timezone.utc),
            sample_size=0,
        )

        with pytest.raises(EmptyDatasetError):
            statistics_calculator.calculate(dataset)


class TestSinglePrice:
    """Test statistics with single observation."""

    def test_single_observation(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate statistics for single price."""
        dataset = create_dataset([15.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 1
        assert result.min_price == 15.0
        assert result.max_price == 15.0
        assert result.mean_price == 15.0
        assert result.median_price == 15.0
        assert result.standard_deviation == 0.0
        assert result.variance == 0.0

    def test_single_price_percentiles(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should set all percentiles to same value for single price."""
        dataset = create_dataset([20.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.q1 == 20.0
        assert result.q3 == 20.0
        assert result.iqr == 0.0
        assert result.percentile_10 == 20.0
        assert result.percentile_25 == 20.0
        assert result.percentile_75 == 20.0
        assert result.percentile_90 == 20.0


class TestTwoPrices:
    """Test statistics with two observations."""

    def test_two_observations(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate statistics for two prices."""
        dataset = create_dataset([10.0, 20.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 2
        assert result.min_price == 10.0
        assert result.max_price == 20.0
        assert result.mean_price == 15.0
        assert result.median_price == 15.0
        assert result.standard_deviation > 0.0
        assert result.variance > 0.0

    def test_two_equal_prices(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should handle two identical prices."""
        dataset = create_dataset([15.0, 15.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 2
        assert result.min_price == 15.0
        assert result.max_price == 15.0
        assert result.mean_price == 15.0
        assert result.median_price == 15.0
        assert result.standard_deviation == 0.0
        assert result.variance == 0.0


class TestFivePrices:
    """Test statistics with five observations."""

    def test_five_observations(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate statistics for five prices."""
        dataset = create_dataset([10.0, 12.0, 15.0, 18.0, 20.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 5
        assert result.min_price == 10.0
        assert result.max_price == 20.0
        assert result.mean_price == 15.0
        assert result.median_price == 15.0

    def test_five_observations_median(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate correct median for odd number of observations."""
        dataset = create_dataset([5.0, 10.0, 15.0, 20.0, 100.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        # Median should be middle value
        assert result.median_price == 15.0
        # Mean should be affected by outlier
        assert result.mean_price == 30.0


class TestTwentyPrices:
    """Test statistics with twenty observations."""

    def test_twenty_observations(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate statistics for twenty prices."""
        prices = list(range(1, 21))  # 1, 2, 3, ..., 20
        dataset = create_dataset([float(p) for p in prices], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 20
        assert result.min_price == 1.0
        assert result.max_price == 20.0
        assert result.mean_price == 10.5
        assert result.median_price == 10.5

    def test_twenty_observations_percentiles(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate correct percentiles for twenty prices."""
        prices = list(range(1, 21))
        dataset = create_dataset([float(p) for p in prices], sample_game)

        result = statistics_calculator.calculate(dataset)

        # Check percentiles are in correct order
        assert result.percentile_10 < result.percentile_25
        assert result.percentile_25 < result.median_price
        assert result.median_price < result.percentile_75
        assert result.percentile_75 < result.percentile_90


class TestEqualPrices:
    """Test statistics with all equal prices."""

    def test_all_equal_small(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should handle small dataset with all equal prices."""
        dataset = create_dataset([15.0, 15.0, 15.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 3
        assert result.min_price == 15.0
        assert result.max_price == 15.0
        assert result.mean_price == 15.0
        assert result.median_price == 15.0
        assert result.standard_deviation == 0.0
        assert result.variance == 0.0
        assert result.iqr == 0.0

    def test_all_equal_large(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should handle large dataset with all equal prices."""
        dataset = create_dataset([20.0] * 50, sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 50
        assert result.min_price == 20.0
        assert result.max_price == 20.0
        assert result.mean_price == 20.0
        assert result.median_price == 20.0
        assert result.standard_deviation == 0.0
        assert result.variance == 0.0


class TestDispersedPrices:
    """Test statistics with highly dispersed prices."""

    def test_high_variance(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate high variance for dispersed prices."""
        dataset = create_dataset([1.0, 100.0, 200.0, 500.0, 1000.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 5
        assert result.min_price == 1.0
        assert result.max_price == 1000.0
        # Variance should be very high
        assert result.variance > 100000.0
        assert result.standard_deviation > 300.0

    def test_extreme_outlier(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should include extreme outlier in calculations (no removal)."""
        dataset = create_dataset([10.0, 12.0, 15.0, 18.0, 10000.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        # Outlier should affect mean but not median
        assert result.mean_price > 2000.0
        assert result.median_price == 15.0
        # Max should be the outlier
        assert result.max_price == 10000.0


class TestPercentileCalculations:
    """Test percentile calculations."""

    def test_percentile_10(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate 10th percentile correctly."""
        prices = list(range(1, 101))  # 1 to 100
        dataset = create_dataset([float(p) for p in prices], sample_game)

        result = statistics_calculator.calculate(dataset)

        # 10th percentile should be around 10
        assert 9.0 <= result.percentile_10 <= 11.0

    def test_percentile_90(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate 90th percentile correctly."""
        prices = list(range(1, 101))
        dataset = create_dataset([float(p) for p in prices], sample_game)

        result = statistics_calculator.calculate(dataset)

        # 90th percentile should be around 90
        assert 89.0 <= result.percentile_90 <= 91.0

    def test_quartiles_match_percentiles(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should have Q1 = P25 and Q3 = P75."""
        dataset = create_dataset([10.0, 15.0, 20.0, 25.0, 30.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.q1 == result.percentile_25
        assert result.q3 == result.percentile_75


class TestMedianCalculations:
    """Test median calculations."""

    def test_median_odd_count(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate median as middle value for odd count."""
        dataset = create_dataset([1.0, 2.0, 3.0, 4.0, 5.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.median_price == 3.0

    def test_median_even_count(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate median as average of two middle values for even count."""
        dataset = create_dataset([1.0, 2.0, 3.0, 4.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.median_price == 2.5


class TestStandardDeviationAndVariance:
    """Test standard deviation and variance calculations."""

    def test_variance_calculation(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate variance correctly."""
        dataset = create_dataset([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        # Variance should be standard deviation squared
        assert abs(result.variance - result.standard_deviation**2) < 0.0001

    def test_standard_deviation_zero_for_equal(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should have zero standard deviation for equal values."""
        dataset = create_dataset([10.0, 10.0, 10.0, 10.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.standard_deviation == 0.0
        assert result.variance == 0.0

    def test_standard_deviation_positive_for_different(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should have positive standard deviation for different values."""
        dataset = create_dataset([10.0, 20.0, 30.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.standard_deviation > 0.0
        assert result.variance > 0.0


class TestIQRCalculations:
    """Test interquartile range calculations."""

    def test_iqr_calculation(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate IQR as Q3 - Q1."""
        dataset = create_dataset([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.iqr == result.q3 - result.q1

    def test_iqr_zero_for_equal(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should have zero IQR for equal values."""
        dataset = create_dataset([15.0] * 10, sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.iqr == 0.0


class TestNoPrecisionLoss:
    """Test that calculations preserve float precision."""

    def test_no_rounding(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should not round values internally."""
        dataset = create_dataset([10.123, 20.456, 30.789], sample_game)

        result = statistics_calculator.calculate(dataset)

        # Mean should preserve precision
        expected_mean = (
            Decimal("10.123") + Decimal("20.456") + Decimal("30.789")
        ) / Decimal("3")
        assert result.mean_price == expected_mean

    def test_float_precision(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should work with high precision floats."""
        dataset = create_dataset([15.999999, 16.000001], sample_game)

        result = statistics_calculator.calculate(dataset)

        # Should preserve precision
        assert result.min_price == Decimal("15.999999")
        assert result.max_price == Decimal("16.000001")


class TestResultStructure:
    """Test PriceStatisticsResult structure."""

    def test_result_has_all_fields(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should return result with all required fields."""
        dataset = create_dataset([10.0, 15.0, 20.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert hasattr(result, "count")
        assert hasattr(result, "min_price")
        assert hasattr(result, "max_price")
        assert hasattr(result, "mean_price")
        assert hasattr(result, "median_price")
        assert hasattr(result, "standard_deviation")
        assert hasattr(result, "variance")
        assert hasattr(result, "q1")
        assert hasattr(result, "q3")
        assert hasattr(result, "iqr")
        assert hasattr(result, "percentile_10")
        assert hasattr(result, "percentile_25")
        assert hasattr(result, "percentile_75")
        assert hasattr(result, "percentile_90")

    def test_result_is_dataclass(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should return PriceStatisticsResult instance."""
        dataset = create_dataset([10.0], sample_game)

        result = statistics_calculator.calculate(dataset)

        assert isinstance(result, PriceStatisticsResult)


class TestRealWorldScenarios:
    """Test realistic price scenarios."""

    def test_typical_game_prices(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should handle typical video game price distribution."""
        # Realistic GTA V prices in EUR
        prices = [10.0, 12.0, 12.5, 13.0, 15.0, 15.0, 16.0, 17.0, 18.0, 20.0, 25.0]
        dataset = create_dataset(prices, sample_game)

        result = statistics_calculator.calculate(dataset)

        assert result.count == 11
        assert result.min_price == 10.0
        assert result.max_price == 25.0
        assert 14.0 <= result.mean_price <= 16.0
        assert 14.0 <= result.median_price <= 16.0

    def test_prices_with_outlier_but_not_removed(
        self,
        statistics_calculator: DefaultPriceStatistics,
        sample_game: DetectedGame,
    ) -> None:
        """Should include outliers in calculations (no removal)."""
        # Normal prices + one outlier
        prices = [12.0, 13.0, 15.0, 16.0, 18.0, 100.0]
        dataset = create_dataset(prices, sample_game)

        result = statistics_calculator.calculate(dataset)

        # Outlier should be included
        assert result.count == 6
        assert result.max_price == 100.0
        # Mean affected by outlier
        assert result.mean_price > 25.0
        # Median less affected
        assert 15.0 <= result.median_price <= 16.0
