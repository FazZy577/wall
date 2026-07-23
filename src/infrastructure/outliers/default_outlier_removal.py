"""Default outlier removal implementation using Tukey's IQR method.

Detects and removes anomalous price observations using the classic
Interquartile Range (IQR) method.
"""

from datetime import UTC, datetime
from decimal import Decimal

from domain.currency import CurrencyMismatchError
from domain.interfaces.outlier_removal import (
    IOutlierRemoval,
    OutlierMethod,
    OutlierObservation,
    OutlierReason,
    OutlierRemovalResult,
)
from domain.interfaces.price_dataset_builder import PriceDataset
from domain.interfaces.price_statistics import PriceStatisticsResult


class DefaultOutlierRemoval(IOutlierRemoval):
    """Default implementation using Tukey's IQR method.

    Uses the classic Interquartile Range (IQR) method to detect outliers:
    - lower_bound = Q1 - 1.5 * IQR
    - upper_bound = Q3 + 1.5 * IQR

    Observations outside [lower_bound, upper_bound] are removed.
    """

    def __init__(self, multiplier: Decimal = Decimal("1.5")) -> None:
        """Initialize outlier removal.

        Args:
            multiplier: IQR multiplier (default: 1.5 for Tukey's method)
        """
        self.multiplier = multiplier

    def remove_outliers(
        self,
        dataset: PriceDataset,
        statistics: PriceStatisticsResult,
    ) -> OutlierRemovalResult:
        """Remove outliers from a price dataset using Tukey's IQR method.

        Args:
            dataset: Original price dataset
            statistics: Pre-calculated statistical metrics

        Returns:
            Result containing clean dataset and removal details
        """
        if dataset.currency != statistics.currency:
            raise CurrencyMismatchError(
                dataset.currency, statistics.currency, "OutlierRemoval"
            )

        # Special case: dataset too small (< 4 observations)
        if dataset.sample_size < 4:
            return self._no_removal_result(
                dataset=dataset,
                lower_bound=statistics.min_price,
                upper_bound=statistics.max_price,
            )

        # Special case: zero IQR (all prices similar)
        if statistics.iqr == Decimal("0"):
            return self._no_removal_result(
                dataset=dataset,
                lower_bound=statistics.q1,
                upper_bound=statistics.q3,
            )

        # Calculate bounds using Tukey's method
        lower_bound = statistics.q1 - self.multiplier * statistics.iqr
        upper_bound = statistics.q3 + self.multiplier * statistics.iqr

        # Separate observations into kept and removed
        kept_observations = []
        removed_observations = []

        for obs in dataset.observations:
            if obs.price < lower_bound:
                # Below lower bound
                outlier = OutlierObservation(
                    price=obs.price,
                    currency=obs.currency,
                    reason=OutlierReason.BELOW_LOWER_BOUND,
                    original_observation=obs,
                )
                removed_observations.append(outlier)
            elif obs.price > upper_bound:
                # Above upper bound
                outlier = OutlierObservation(
                    price=obs.price,
                    currency=obs.currency,
                    reason=OutlierReason.ABOVE_UPPER_BOUND,
                    original_observation=obs,
                )
                removed_observations.append(outlier)
            else:
                # Within bounds - keep it
                kept_observations.append(obs)

        # Create new clean dataset (immutable - don't modify original)
        clean_dataset = PriceDataset(
            observations=kept_observations,
            game=dataset.game,
            created_at=datetime.now(UTC),
            sample_size=len(kept_observations),
            currency=dataset.currency,
        )

        return OutlierRemovalResult(
            clean_dataset=clean_dataset,
            removed_observations=removed_observations,
            removed_count=len(removed_observations),
            kept_count=len(kept_observations),
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            method=OutlierMethod.IQR,
        )

    def _no_removal_result(
        self,
        dataset: PriceDataset,
        lower_bound: Decimal,
        upper_bound: Decimal,
    ) -> OutlierRemovalResult:
        """Create result when no outliers can be removed.

        Args:
            dataset: Original dataset
            lower_bound: Lower bound (for reporting)
            upper_bound: Upper bound (for reporting)

        Returns:
            Result with original dataset unchanged
        """
        # Create new dataset with same observations (immutable pattern)
        clean_dataset = PriceDataset(
            observations=list(dataset.observations),  # Copy list
            game=dataset.game,
            created_at=datetime.now(UTC),
            sample_size=dataset.sample_size,
            currency=dataset.currency,
        )

        return OutlierRemovalResult(
            clean_dataset=clean_dataset,
            removed_observations=[],
            removed_count=0,
            kept_count=dataset.sample_size,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            method=OutlierMethod.IQR,
        )
