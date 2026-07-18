"""Default price statistics calculator implementation.

Calculates descriptive statistics from price datasets using
deterministic statistical methods.
"""

import statistics
from collections.abc import Sequence

from domain.interfaces.price_dataset_builder import PriceDataset
from domain.interfaces.price_statistics import (
    EmptyDatasetError,
    IPriceStatistics,
    PriceStatisticsResult,
)


class DefaultPriceStatistics(IPriceStatistics):
    """Default implementation of price statistics calculator.

    Uses Python's statistics module for deterministic calculations.
    Does NOT perform outlier removal or price estimation.
    """

    def calculate(self, dataset: PriceDataset) -> PriceStatisticsResult:
        """Calculate statistical metrics from a price dataset.

        Args:
            dataset: Clean price dataset

        Returns:
            Statistical metrics

        Raises:
            EmptyDatasetError: If dataset has no observations
        """
        # Validate dataset has observations
        if dataset.sample_size == 0 or len(dataset.observations) == 0:
            raise EmptyDatasetError("Cannot calculate statistics on empty dataset")

        # Extract prices
        prices = [obs.price for obs in dataset.observations]

        # Calculate basic metrics
        count = len(prices)
        min_price = min(prices)
        max_price = max(prices)
        mean_price = statistics.mean(prices)

        # Calculate median
        median_price = statistics.median(prices)

        # Calculate standard deviation and variance
        if count == 1:
            # Single observation: no variance
            standard_deviation = 0.0
            variance = 0.0
        else:
            # Sample standard deviation and variance
            standard_deviation = statistics.stdev(prices)
            variance = statistics.variance(prices)

        # Calculate quartiles and percentiles
        q1 = self._percentile(prices, 25)
        q3 = self._percentile(prices, 75)
        iqr = q3 - q1

        percentile_10 = self._percentile(prices, 10)
        percentile_25 = q1  # Same as Q1
        percentile_75 = q3  # Same as Q3
        percentile_90 = self._percentile(prices, 90)

        return PriceStatisticsResult(
            count=count,
            min_price=min_price,
            max_price=max_price,
            mean_price=mean_price,
            median_price=median_price,
            standard_deviation=standard_deviation,
            variance=variance,
            q1=q1,
            q3=q3,
            iqr=iqr,
            percentile_10=percentile_10,
            percentile_25=percentile_25,
            percentile_75=percentile_75,
            percentile_90=percentile_90,
        )

    def _percentile(self, data: Sequence[float], percentile: float) -> float:
        """Calculate percentile using linear interpolation.

        Args:
            data: Sequence of numeric values
            percentile: Percentile to calculate (0-100)

        Returns:
            Percentile value
        """
        return statistics.quantiles(data, n=100)[int(percentile) - 1]
