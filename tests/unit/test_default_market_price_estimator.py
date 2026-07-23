"""Unit tests for DefaultMarketPriceEstimator.

Tests market price estimation using MEDIAN strategy with confidence scoring.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    ReasonCode,
)
from domain.interfaces.price_dataset_builder import (
    PriceDataset,
    PriceObservation,
)
from domain.interfaces.price_statistics import EmptyDatasetError, PriceStatisticsResult
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)


@pytest.fixture
def estimator() -> DefaultMarketPriceEstimator:
    """Create DefaultMarketPriceEstimator instance."""
    return DefaultMarketPriceEstimator()


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
        created_at=datetime.now(UTC),
        sample_size=len(observations),
        currency="EUR",
    )


def create_statistics(
    count: int,
    min_price: float,
    max_price: float,
    mean_price: float,
    median_price: float,
    std_dev: float,
    iqr: float,
) -> PriceStatisticsResult:
    """Helper to create PriceStatisticsResult."""
    variance = std_dev**2
    q1 = median_price - iqr / 2
    q3 = median_price + iqr / 2

    return PriceStatisticsResult(
        count=count,
        min_price=Decimal(str(min_price)),
        max_price=Decimal(str(max_price)),
        mean_price=Decimal(str(mean_price)),
        median_price=Decimal(str(median_price)),
        standard_deviation=Decimal(str(std_dev)),
        variance=Decimal(str(variance)),
        q1=Decimal(str(q1)),
        q3=Decimal(str(q3)),
        iqr=Decimal(str(iqr)),
        percentile_10=Decimal(str(min_price)),
        percentile_25=Decimal(str(q1)),
        percentile_75=Decimal(str(q3)),
        percentile_90=Decimal(str(max_price)),
        currency="EUR",
    )


class TestEmptyDataset:
    """Test empty dataset handling."""

    def test_empty_dataset_raises_error(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should raise EmptyDatasetError for empty dataset."""
        dataset = create_dataset([], sample_game)
        statistics = create_statistics(0, 0, 0, 0, 0, 0, 0)

        with pytest.raises(EmptyDatasetError):
            estimator.estimate(dataset, statistics, observations_removed=0)


class TestSingleObservation:
    """Test single observation handling."""

    def test_single_observation(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should estimate from single observation."""
        prices = [15.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(1, 15.0, 15.0, 15.0, 15.0, 0.0, 0.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.estimated_price == 15.0
        assert result.sample_size == 1
        assert result.strategy == EstimationStrategy.MEDIAN


class TestMedianEstimation:
    """Test median price estimation."""

    def test_median_used_as_estimate(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should use median as estimated price."""
        prices = [10.0, 12.0, 15.0, 18.0, 20.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 10.0, 20.0, 15.0, 15.0, 3.74, 6.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.estimated_price == 15.0  # median
        assert result.strategy == EstimationStrategy.MEDIAN

    def test_median_with_outlier_in_original(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Median should be robust to extreme values in clean data."""
        # Clean data still has wide range, but median is stable
        prices = [10.0, 12.0, 15.0, 18.0, 25.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 10.0, 25.0, 16.0, 15.0, 5.70, 6.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.estimated_price == 15.0  # median stays at 15


class TestConfidenceScoreCalculation:
    """Test confidence score calculation."""

    def test_low_sample_size_low_confidence(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Low sample size should result in low confidence."""
        prices = [14.0, 15.0, 16.0]
        dataset = create_dataset(prices, sample_game)
        # Low std_dev (0.82) but only 3 observations
        statistics = create_statistics(3, 14.0, 16.0, 15.0, 15.0, 0.82, 1.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # size_factor = 3/20 = 0.15
        # cv = 0.82/15 = 0.055
        # dispersion_factor = 1 - 0.055 = 0.945
        # confidence = 0.15 * 0.945 РІвЂ°в‚¬ 0.14
        assert result.confidence_score < 0.20
        assert result.sample_size == 3

    def test_high_sample_size_high_confidence(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """High sample size with low dispersion should result in high confidence."""
        # 20 observations with low std_dev
        prices = [14.0 + i * 0.1 for i in range(20)]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(20, 14.0, 15.9, 14.95, 14.95, 0.58, 1.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # size_factor = 20/20 = 1.0
        # cv = 0.58/14.95 = 0.039
        # dispersion_factor = 1 - 0.039 = 0.961
        # confidence = 1.0 * 0.961 РІвЂ°в‚¬ 0.96
        assert result.confidence_score > 0.90
        assert result.sample_size == 20

    def test_high_volatility_low_confidence(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """High volatility should result in low confidence even with many observations."""
        # 20 observations but high std_dev
        prices = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
        prices += [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(20, 10.0, 28.0, 19.0, 19.0, 5.92, 9.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # size_factor = 20/20 = 1.0
        # cv = 5.92/19 = 0.31
        # dispersion_factor = 1 - 0.31 = 0.69
        # confidence = 1.0 * 0.69 = 0.69
        assert result.confidence_score < 0.75
        assert result.sample_size == 20

    def test_medium_confidence_scenario(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Medium sample with moderate dispersion should give medium confidence."""
        prices = [12.0, 14.0, 15.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(10, 12.0, 28.0, 19.5, 19.0, 5.24, 10.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # size_factor = 10/20 = 0.5
        # cv = 5.24/19.5 = 0.27
        # dispersion_factor = 1 - 0.27 = 0.73
        # confidence = 0.5 * 0.73 = 0.365
        assert 0.30 <= result.confidence_score <= 0.50


class TestReasonCodes:
    """Test reason code determination."""

    def test_insufficient_data_reason(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should return INSUFFICIENT_DATA for small datasets."""
        prices = [15.0, 16.0, 17.0]  # 3 observations (< 4 threshold)
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(3, 15.0, 17.0, 16.0, 16.0, 0.82, 1.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.reason_code == ReasonCode.INSUFFICIENT_DATA
        assert result.sample_size == 3

    def test_narrow_range_reason(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should return NARROW_RANGE when all prices are equal."""
        prices = [15.0, 15.0, 15.0, 15.0, 15.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 15.0, 15.0, 15.0, 15.0, 0.0, 0.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.reason_code == ReasonCode.NARROW_RANGE
        assert result.iqr == 0.0

    def test_high_volatility_reason(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should return HIGH_VOLATILITY for low confidence scores."""
        # Many observations but very high dispersion
        prices = [5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(10, 5.0, 50.0, 27.5, 27.5, 14.58, 22.5)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # cv = 14.58/27.5 = 0.53 РІвЂ вЂ™ very high
        # confidence will be low (< 0.50)
        assert result.reason_code == ReasonCode.HIGH_VOLATILITY
        assert result.confidence_score < 0.50

    def test_normal_reason(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should return NORMAL for good datasets."""
        # 15 observations with tight clustering
        prices = [14.5, 15.0, 15.0, 15.5, 15.5, 15.5, 16.0, 16.0, 16.0, 16.5]
        prices += [16.5, 16.5, 17.0, 17.0, 17.5]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(15, 14.5, 17.5, 16.0, 16.0, 0.91, 1.5)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # Good sample size (15), low dispersion (CV РІвЂ°в‚¬ 0.057)
        # size_factor = 15/20 = 0.75
        # cv = 0.91/16.0 = 0.057
        # dispersion_factor = 1 - 0.057 = 0.943
        # confidence = 0.75 * 0.943 = 0.71 (> 0.50)
        assert result.reason_code == ReasonCode.NORMAL
        assert result.confidence_score >= 0.50


class TestFieldPropagation:
    """Test that all fields are correctly propagated."""

    def test_all_fields_present(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should populate all fields in result."""
        prices = [10.0, 12.0, 15.0, 18.0, 20.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 10.0, 20.0, 15.0, 15.0, 3.74, 6.0)

        result = estimator.estimate(dataset, statistics, observations_removed=2)

        # Core fields
        assert result.estimated_price == 15.0
        assert result.currency == "EUR"
        assert isinstance(result.confidence_score, float)
        assert isinstance(result.confidence_level, ConfidenceLevel)
        assert result.strategy == EstimationStrategy.MEDIAN
        assert isinstance(result.reason_code, ReasonCode)

        # Sample info
        assert result.sample_size == 5
        assert result.observations_removed == 2
        assert isinstance(result.outlier_percentage, float)
        assert result.outlier_percentage > 0

        # Price range
        assert result.minimum_price == 10.0
        assert result.maximum_price == 20.0

        # Statistics propagated
        assert result.standard_deviation == Decimal("3.74")
        assert result.iqr == 6.0
        assert isinstance(result.coefficient_of_variation, float)

        # Game info
        assert result.game == sample_game

        # Timestamp
        assert isinstance(result.created_at, datetime)

    def test_observations_removed_default_zero(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """observations_removed should default to 0 if not provided."""
        prices = [15.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(1, 15.0, 15.0, 15.0, 15.0, 0.0, 0.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.observations_removed == 0

    def test_currency_from_observations(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Currency should come from dataset observations."""
        prices = [15.0, 16.0]
        dataset = create_dataset(prices, sample_game)
        # Manually set currency to verify it's propagated
        dataset.observations[0].currency = "USD"
        dataset.observations[1].currency = "USD"
        dataset.currency = "USD"
        statistics = create_statistics(2, 15.0, 16.0, 15.5, 15.5, 0.5, 0.5)
        statistics.currency = "USD"

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.currency == "USD"


class TestImmutability:
    """Test that original data is not modified."""

    def test_dataset_unchanged(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Original dataset should remain unchanged."""
        prices = [10.0, 15.0, 20.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(3, 10.0, 20.0, 15.0, 15.0, 4.08, 5.0)

        original_size = dataset.sample_size
        original_prices = [obs.price for obs in dataset.observations]

        estimator.estimate(dataset, statistics, observations_removed=0)

        # Dataset unchanged
        assert dataset.sample_size == original_size
        assert [obs.price for obs in dataset.observations] == original_prices

    def test_statistics_unchanged(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Original statistics should remain unchanged."""
        prices = [10.0, 15.0, 20.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(3, 10.0, 20.0, 15.0, 15.0, 4.08, 5.0)

        original_median = statistics.median_price
        original_std = statistics.standard_deviation

        estimator.estimate(dataset, statistics, observations_removed=0)

        # Statistics unchanged
        assert statistics.median_price == original_median
        assert statistics.standard_deviation == original_std


class TestConfidenceScoreExamples:
    """Test confidence score with real-world examples from documentation."""

    def test_example_5_obs_high_cv(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """5 observations, CV=0.45 РІвЂ вЂ™ confidence РІвЂ°в‚¬ 0.14."""
        prices = [8.0, 12.0, 15.0, 18.0, 22.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(5, 8.0, 22.0, 15.0, 15.0, 6.75, 6.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # size_factor = 5/20 = 0.25
        # cv = 6.75/15 = 0.45
        # dispersion_factor = 1 - 0.45 = 0.55
        # confidence = 0.25 * 0.55 = 0.1375 РІвЂ°в‚¬ 0.14
        assert result.confidence_score == pytest.approx(0.14, abs=0.01)

    def test_example_10_obs_low_cv(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """10 observations, CV=0.10 РІвЂ вЂ™ confidence РІвЂ°в‚¬ 0.45."""
        prices = [14.0, 14.5, 15.0, 15.0, 15.0, 15.0, 15.5, 16.0, 16.0, 16.5]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(10, 14.0, 16.5, 15.25, 15.0, 1.50, 1.5)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # size_factor = 10/20 = 0.50
        # cv = 1.50/15.25 = 0.098 РІвЂ°в‚¬ 0.10
        # dispersion_factor = 1 - 0.10 = 0.90
        # confidence = 0.50 * 0.90 = 0.45
        assert result.confidence_score == pytest.approx(0.45, abs=0.02)

    def test_example_20_obs_very_low_cv(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """20 observations, CV=0.09 РІвЂ вЂ™ confidence РІвЂ°в‚¬ 0.91."""
        prices = [14.0 + i * 0.15 for i in range(20)]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(20, 14.0, 16.85, 15.42, 15.43, 1.35, 2.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # size_factor = 20/20 = 1.0
        # cv = 1.35/15.42 = 0.0875 РІвЂ°в‚¬ 0.09
        # dispersion_factor = 1 - 0.09 = 0.91
        # confidence = 1.0 * 0.91 = 0.91
        assert result.confidence_score == pytest.approx(0.91, abs=0.02)


class TestRealWorldScenarios:
    """Test realistic market scenarios."""

    def test_stable_market_high_confidence(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Stable market with many listings should have high confidence."""
        # 25 listings, prices tightly clustered around 15РІвЂљВ¬
        prices = [14.0, 14.5, 14.5, 15.0, 15.0, 15.0, 15.0, 15.0]
        prices += [15.5, 15.5, 15.5, 15.5, 16.0, 16.0, 16.0]
        prices += [16.5, 16.5, 17.0, 14.0, 15.0, 16.0, 15.5, 15.0, 14.5, 16.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(25, 14.0, 17.0, 15.3, 15.5, 0.83, 1.5)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.confidence_score > 0.85
        assert result.confidence_level == ConfidenceLevel.VERY_HIGH
        assert result.reason_code == ReasonCode.NORMAL
        assert result.sample_size == 25

    def test_volatile_market_low_confidence(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Volatile market should have low confidence despite sample size."""
        # Wide price range
        prices = [5.0, 8.0, 10.0, 12.0, 15.0, 18.0, 20.0, 25.0, 30.0, 35.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(10, 5.0, 35.0, 17.8, 16.5, 9.54, 13.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.confidence_score < 0.50
        assert result.confidence_level in [ConfidenceLevel.LOW, ConfidenceLevel.VERY_LOW]
        assert result.reason_code == ReasonCode.HIGH_VOLATILITY

    def test_small_niche_market(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Small niche market with few listings."""
        prices = [45.0, 48.0, 50.0, 52.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(4, 45.0, 52.0, 48.75, 49.0, 2.87, 4.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # 4 observations = threshold, not INSUFFICIENT_DATA
        assert result.reason_code != ReasonCode.INSUFFICIENT_DATA
        assert result.sample_size == 4
        # But confidence should be low due to small sample
        assert result.confidence_score < 0.40


class TestConfidenceLevel:
    """Test confidence level calculation."""

    def test_very_high_confidence_level(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should return VERY_HIGH for confidence >= 0.90."""
        prices = [14.0 + i * 0.1 for i in range(20)]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(20, 14.0, 15.9, 14.95, 14.95, 0.58, 1.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.confidence_score >= 0.90
        assert result.confidence_level == ConfidenceLevel.VERY_HIGH

    def test_confidence_level_matches_score(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should assign confidence_level based on confidence_score thresholds."""
        # Test that confidence_level is consistent with confidence_score
        prices = [15.0, 16.0, 17.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(3, 15.0, 17.0, 16.0, 16.0, 0.82, 1.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        # Verify level matches score
        if result.confidence_score >= 0.90:
            assert result.confidence_level == ConfidenceLevel.VERY_HIGH
        elif result.confidence_score >= 0.75:
            assert result.confidence_level == ConfidenceLevel.HIGH
        elif result.confidence_score >= 0.50:
            assert result.confidence_level == ConfidenceLevel.MEDIUM
        elif result.confidence_score >= 0.30:
            assert result.confidence_level == ConfidenceLevel.LOW
        else:
            assert result.confidence_level == ConfidenceLevel.VERY_LOW


class TestOutlierPercentage:
    """Test outlier percentage calculation."""

    def test_outlier_percentage_calculated(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate outlier percentage correctly."""
        prices = [15.0, 16.0, 17.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(3, 15.0, 17.0, 16.0, 16.0, 0.82, 1.0)

        # 3 kept, 2 removed РІвЂ вЂ™ 2/5 = 40%
        result = estimator.estimate(dataset, statistics, observations_removed=2)

        assert result.outlier_percentage == pytest.approx(40.0, abs=0.1)

    def test_no_outliers_removed(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should return 0% when no outliers removed."""
        prices = [15.0, 16.0, 17.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(3, 15.0, 17.0, 16.0, 16.0, 0.82, 1.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)

        assert result.outlier_percentage == 0.0


class TestExplainMethod:
    """Test explain() method."""

    def test_explain_returns_string(
        self,
        estimator: DefaultMarketPriceEstimator,
        sample_game: DetectedGame,
    ) -> None:
        """Should return formatted explanation string."""
        prices = [15.0, 16.0, 17.0]
        dataset = create_dataset(prices, sample_game)
        statistics = create_statistics(3, 15.0, 17.0, 16.0, 16.0, 0.82, 1.0)

        result = estimator.estimate(dataset, statistics, observations_removed=0)
        explanation = result.explain()

        assert isinstance(explanation, str)
        assert "MARKET PRICE ESTIMATION EXPLANATION" in explanation
        assert "Grand Theft Auto V" in explanation
        assert "EUR 16.00" in explanation
        assert "MEDIAN" in explanation
        assert "CONFIDENCE" in explanation
