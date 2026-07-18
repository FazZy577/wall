"""Price statistics interface (port).

Defines the contract for calculating statistical metrics from price datasets.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from domain.interfaces.price_dataset_builder import PriceDataset


class EmptyDatasetError(Exception):
    """Raised when attempting to calculate statistics on an empty dataset."""

    pass


@dataclass
class PriceStatisticsResult:
    """Statistical metrics calculated from a price dataset.

    All prices are in the original currency (no conversion).
    All values are unrounded floats (rounding is responsibility of upper layers).

    Attributes:
        count: Number of observations
        min_price: Minimum price
        max_price: Maximum price
        mean_price: Arithmetic mean (average)
        median_price: Median (50th percentile)
        standard_deviation: Standard deviation (sample)
        variance: Variance (sample)
        q1: First quartile (25th percentile)
        q3: Third quartile (75th percentile)
        iqr: Interquartile range (Q3 - Q1)
        percentile_10: 10th percentile
        percentile_25: 25th percentile (same as Q1)
        percentile_75: 75th percentile (same as Q3)
        percentile_90: 90th percentile
    """

    count: int
    min_price: float
    max_price: float
    mean_price: float
    median_price: float
    standard_deviation: float
    variance: float
    q1: float
    q3: float
    iqr: float
    percentile_10: float
    percentile_25: float
    percentile_75: float
    percentile_90: float


class IPriceStatistics(ABC):
    """Interface for price statistics calculation implementations.

    Calculates descriptive statistics from clean price datasets.
    Does NOT perform outlier removal, price estimation, or confidence scoring.
    """

    @abstractmethod
    def calculate(self, dataset: PriceDataset) -> PriceStatisticsResult:
        """Calculate statistical metrics from a price dataset.

        Args:
            dataset: Clean price dataset

        Returns:
            Statistical metrics

        Raises:
            EmptyDatasetError: If dataset has no observations
        """
        pass
