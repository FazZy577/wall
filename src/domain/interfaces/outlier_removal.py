"""Outlier removal interface (port).

Defines the contract for detecting and removing anomalous price observations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from domain._decimal import require_decimal
from domain.currency import CurrencyMismatchError, validate_currency_code
from domain.interfaces.price_dataset_builder import (
    PriceDataset,
    PriceObservation,
)
from domain.interfaces.price_statistics import PriceStatisticsResult


class OutlierMethod(StrEnum):
    """Method used for outlier detection and removal."""

    IQR = "iqr"


class OutlierReason(StrEnum):
    """Reason why an observation was identified as an outlier."""

    ABOVE_UPPER_BOUND = "above_upper_bound"
    BELOW_LOWER_BOUND = "below_lower_bound"
    DATASET_TOO_SMALL = "dataset_too_small"
    ZERO_IQR = "zero_iqr"


@dataclass
class OutlierObservation:
    """An observation that was identified as an outlier and removed.

    Attributes:
        price: Price value of the outlier
        currency: Currency code
        reason: Specific reason for removal
        original_observation: Complete original PriceObservation
    """

    price: Decimal
    currency: str
    reason: OutlierReason
    original_observation: PriceObservation

    def __post_init__(self) -> None:
        require_decimal("price", self.price)
        validate_currency_code(self.currency)
        if self.original_observation.currency != self.currency:
            raise CurrencyMismatchError(
                self.currency,
                self.original_observation.currency,
                "OutlierObservation",
            )


@dataclass
class OutlierRemovalResult:
    """Result of outlier detection and removal process.

    Attributes:
        clean_dataset: New dataset with outliers removed
        removed_observations: List of observations that were removed
        removed_count: Number of observations removed
        kept_count: Number of observations kept
        lower_bound: Lower bound for valid prices
        upper_bound: Upper bound for valid prices
        method: Method used for outlier detection
    """

    clean_dataset: PriceDataset
    removed_observations: list[OutlierObservation]
    removed_count: int
    kept_count: int
    lower_bound: Decimal
    upper_bound: Decimal
    method: OutlierMethod

    def __post_init__(self) -> None:
        require_decimal("lower_bound", self.lower_bound)
        require_decimal("upper_bound", self.upper_bound)

    @property
    def currency(self) -> str:
        return self.clean_dataset.currency


class IOutlierRemoval(ABC):
    """Interface for outlier removal implementations.

    Detects and removes anomalous price observations from datasets
    using statistical methods.
    """

    @abstractmethod
    def remove_outliers(
        self,
        dataset: PriceDataset,
        statistics: PriceStatisticsResult,
    ) -> OutlierRemovalResult:
        """Remove outliers from a price dataset.

        Args:
            dataset: Original price dataset
            statistics: Pre-calculated statistical metrics

        Returns:
            Result containing clean dataset and removal details
        """
        pass
