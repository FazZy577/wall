"""Default market price estimator implementation using MEDIAN strategy.

Estimates fair market price using the median (robust to extremes).
Calculates confidence score based on sample size and price dispersion.
"""

from datetime import UTC, datetime

from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    IMarketPriceEstimator,
    MarketPriceEstimate,
    ReasonCode,
)
from domain.interfaces.price_dataset_builder import PriceDataset
from domain.interfaces.price_statistics import EmptyDatasetError, PriceStatisticsResult


class DefaultMarketPriceEstimator(IMarketPriceEstimator):
    """Default implementation using MEDIAN strategy.

    Always uses median (robust to extremes).
    Confidence calculated from sample_size and dispersion.

    Confidence Formula:
        confidence_score = sample_size_factor × dispersion_factor

        where:
            sample_size_factor = min(sample_size / 20, 1.0)
            dispersion_factor = max(0, 1 - CV)
            CV = standard_deviation / mean_price
    """

    # Confidence calculation constants
    MIN_OBSERVATIONS_HIGH_CONFIDENCE = 20
    MIN_OBSERVATIONS_MEDIUM_CONFIDENCE = 10
    HIGH_VOLATILITY_THRESHOLD = 0.50

    # Confidence level thresholds
    CONFIDENCE_VERY_HIGH_THRESHOLD = 0.90
    CONFIDENCE_HIGH_THRESHOLD = 0.75
    CONFIDENCE_MEDIUM_THRESHOLD = 0.50
    CONFIDENCE_LOW_THRESHOLD = 0.30

    # Reason code thresholds
    INSUFFICIENT_DATA_THRESHOLD = 4
    LOW_CONFIDENCE_THRESHOLD = 0.50

    def __init__(self) -> None:
        """Initialize with MEDIAN strategy (only strategy implemented)."""
        self.strategy = EstimationStrategy.MEDIAN

    def estimate(
        self,
        dataset: PriceDataset,
        statistics: PriceStatisticsResult,
        observations_removed: int,
    ) -> MarketPriceEstimate:
        """Estimate market price using MEDIAN.

        Args:
            dataset: Clean price dataset (post-outlier-removal)
            statistics: Pre-calculated statistical metrics
            observations_removed: Number of outliers removed (required, use 0 if none)

        Returns:
            Market price estimate with confidence score and justification

        Raises:
            EmptyDatasetError: If dataset has no observations
        """
        # Validate dataset
        if dataset.sample_size == 0:
            msg = "Cannot estimate price from empty dataset"
            raise EmptyDatasetError(msg)

        # Get estimated price (median)
        estimated_price = statistics.median_price

        # Get currency from first observation (all observations have same currency)
        currency = dataset.observations[0].currency

        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(
            sample_size=dataset.sample_size,
            standard_deviation=statistics.standard_deviation,
            mean_price=statistics.mean_price,
        )

        # Determine confidence level
        confidence_level = self._determine_confidence_level(confidence_score)

        # Calculate coefficient of variation
        coefficient_of_variation = (
            statistics.standard_deviation / statistics.mean_price
            if statistics.mean_price > 0
            else 0.0
        )

        # Calculate outlier percentage
        total_original = dataset.sample_size + observations_removed
        outlier_percentage = (
            (observations_removed / total_original * 100.0)
            if total_original > 0
            else 0.0
        )

        # Determine reason code
        reason_code = self._determine_reason_code(
            sample_size=dataset.sample_size,
            iqr=statistics.iqr,
            confidence_score=confidence_score,
        )

        # Build result
        return MarketPriceEstimate(
            estimated_price=estimated_price,
            currency=currency,
            confidence_score=confidence_score,
            confidence_level=confidence_level,
            strategy=self.strategy,
            reason_code=reason_code,
            sample_size=dataset.sample_size,
            observations_removed=observations_removed,
            outlier_percentage=outlier_percentage,
            minimum_price=statistics.min_price,
            maximum_price=statistics.max_price,
            standard_deviation=statistics.standard_deviation,
            iqr=statistics.iqr,
            coefficient_of_variation=coefficient_of_variation,
            game=dataset.game,
            created_at=datetime.now(UTC),
        )

    def _calculate_sample_size_factor(self, sample_size: int) -> float:
        """Calculate confidence factor based on sample size.

        Returns value between 0.0 and 1.0.
        Reaches 1.0 at MIN_OBSERVATIONS_HIGH_CONFIDENCE (20 observations).

        Args:
            sample_size: Number of observations

        Returns:
            Sample size factor (0.0 to 1.0)

        Examples:
            1 observation  → 0.05
            5 observations → 0.25
            10 observations → 0.50
            20+ observations → 1.00
        """
        return min(sample_size / self.MIN_OBSERVATIONS_HIGH_CONFIDENCE, 1.0)

    def _calculate_dispersion_factor(
        self,
        standard_deviation: float,
        mean_price: float,
    ) -> float:
        """Calculate confidence factor based on price dispersion.

        Uses coefficient of variation (CV = std_dev / mean).
        Returns value between 0.0 and 1.0.
        Lower CV = higher confidence.

        Args:
            standard_deviation: Price standard deviation
            mean_price: Mean price

        Returns:
            Dispersion factor (0.0 to 1.0)

        Examples:
            CV = 0.05 (5%) → 0.95 (very stable)
            CV = 0.20 (20%) → 0.80 (moderate)
            CV = 0.50 (50%) → 0.50 (volatile)
            CV = 1.00 (100%) → 0.00 (extremely volatile)
        """
        if mean_price == 0:
            return 0.0

        cv = standard_deviation / mean_price
        return max(0.0, 1.0 - cv)

    def _calculate_confidence_score(
        self,
        sample_size: int,
        standard_deviation: float,
        mean_price: float,
    ) -> float:
        """Calculate overall confidence score (0.0 to 1.0).

        Combines sample size and dispersion factors.
        Both factors must be good for high confidence.

        Args:
            sample_size: Number of observations
            standard_deviation: Price standard deviation
            mean_price: Mean price

        Returns:
            Confidence score (0.0 to 1.0), rounded to 2 decimals
        """
        size_factor = self._calculate_sample_size_factor(sample_size)
        dispersion_factor = self._calculate_dispersion_factor(
            standard_deviation,
            mean_price,
        )

        confidence = size_factor * dispersion_factor
        return round(confidence, 2)

    def _determine_confidence_level(self, confidence_score: float) -> ConfidenceLevel:
        """Determine human-readable confidence level from score.

        Args:
            confidence_score: Confidence score (0.0 to 1.0)

        Returns:
            Confidence level enum
        """
        if confidence_score >= self.CONFIDENCE_VERY_HIGH_THRESHOLD:
            return ConfidenceLevel.VERY_HIGH
        if confidence_score >= self.CONFIDENCE_HIGH_THRESHOLD:
            return ConfidenceLevel.HIGH
        if confidence_score >= self.CONFIDENCE_MEDIUM_THRESHOLD:
            return ConfidenceLevel.MEDIUM
        if confidence_score >= self.CONFIDENCE_LOW_THRESHOLD:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.VERY_LOW

    def _determine_reason_code(
        self,
        sample_size: int,
        iqr: float,
        confidence_score: float,
    ) -> ReasonCode:
        """Determine reason code based on dataset characteristics.

        Args:
            sample_size: Number of observations
            iqr: Interquartile range
            confidence_score: Calculated confidence score

        Returns:
            Reason code explaining estimation context
        """
        # Insufficient data
        if sample_size < self.INSUFFICIENT_DATA_THRESHOLD:
            return ReasonCode.INSUFFICIENT_DATA

        # Narrow range (all prices very similar)
        if iqr == 0.0:
            return ReasonCode.NARROW_RANGE

        # High volatility (low confidence)
        if confidence_score < self.LOW_CONFIDENCE_THRESHOLD:
            return ReasonCode.HIGH_VOLATILITY

        # Normal case
        return ReasonCode.NORMAL
