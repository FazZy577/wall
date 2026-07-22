"""Market price estimator interface (port).

Defines the contract for estimating fair market prices from clean datasets.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from domain._decimal import require_decimal
from domain.entities.detected_game import DetectedGame
from domain.interfaces.price_dataset_builder import PriceDataset
from domain.interfaces.price_statistics import PriceStatisticsResult


class EstimationStrategy(StrEnum):
    """Strategy used to estimate market price."""

    MEDIAN = "median"
    # Future strategies (not implemented yet):
    # MEAN = "mean"
    # TRIMMED_MEAN = "trimmed_mean"
    # PERCENTILE_25 = "percentile_25"
    # PERCENTILE_75 = "percentile_75"


class ConfidenceLevel(StrEnum):
    """Human-readable confidence level."""

    VERY_HIGH = "very_high"  # >= 0.90
    HIGH = "high"            # >= 0.75
    MEDIUM = "medium"        # >= 0.50
    LOW = "low"              # >= 0.30
    VERY_LOW = "very_low"    # < 0.30


class ReasonCode(StrEnum):
    """Reason code explaining estimation context."""

    NORMAL = "normal"
    INSUFFICIENT_DATA = "insufficient_data"
    HIGH_VOLATILITY = "high_volatility"
    NARROW_RANGE = "narrow_range"


@dataclass
class MarketPriceEstimate:
    """Result of market price estimation.

    Attributes:
        estimated_price: Estimated fair market price
        currency: Currency code
        confidence_score: Confidence in estimate (0.0 = none, 1.0 = max)
        confidence_level: Human-readable confidence level
        strategy: Strategy used for estimation
        reason_code: Why this strategy/score was chosen
        sample_size: Number of observations used
        observations_removed: Outliers removed before estimation
        outlier_percentage: Percentage of observations removed as outliers
        minimum_price: Minimum price in clean dataset
        maximum_price: Maximum price in clean dataset
        standard_deviation: Price standard deviation
        iqr: Interquartile range
        coefficient_of_variation: CV (std_dev / mean)
        game: Target game
        created_at: Estimation timestamp
    """

    estimated_price: Decimal
    currency: str
    confidence_score: float
    confidence_level: ConfidenceLevel
    strategy: EstimationStrategy
    reason_code: ReasonCode
    sample_size: int
    observations_removed: int
    outlier_percentage: float
    minimum_price: Decimal
    maximum_price: Decimal
    standard_deviation: Decimal
    iqr: Decimal
    coefficient_of_variation: float
    game: DetectedGame
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "estimated_price", "minimum_price", "maximum_price",
            "standard_deviation", "iqr",
        ):
            require_decimal(name, getattr(self, name))

    def explain(self) -> str:
        """Generate human-readable explanation of the estimation.

        Returns:
            Multi-line string explaining the estimation decision
        """
        lines = []
        lines.append("=" * 60)
        lines.append("MARKET PRICE ESTIMATION EXPLANATION")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Game: {self.game.canonical_name} ({self.game.platform})")
        lines.append(f"Estimated Price: {self.currency} {self.estimated_price:.2f}")
        lines.append("")
        lines.append("DECISION DETAILS")
        lines.append("-" * 60)
        lines.append(f"Strategy: {self.strategy.upper()}")
        lines.append(f"Reason Code: {self.reason_code}")
        lines.append("")
        lines.append("CONFIDENCE ASSESSMENT")
        lines.append("-" * 60)
        lines.append(f"Confidence Score: {self.confidence_score:.2f}")
        lines.append(f"Confidence Level: {self.confidence_level.upper()}")
        lines.append(f"Coefficient of Variation: {self.coefficient_of_variation:.2%}")
        lines.append("")
        lines.append("DATA QUALITY")
        lines.append("-" * 60)
        lines.append(f"Sample Size: {self.sample_size} observations")
        lines.append(f"Outliers Removed: {self.observations_removed} ({self.outlier_percentage:.1f}%)")
        lines.append(f"Remaining Listings: {self.sample_size} valid comparables")
        lines.append("")
        lines.append("PRICE STATISTICS")
        lines.append("-" * 60)
        lines.append(f"Median (Estimated): {self.currency} {self.estimated_price:.2f}")

        # Calculate mean from std_dev and CV
        if self.coefficient_of_variation > 0:
            mean = self.standard_deviation / Decimal(
                str(self.coefficient_of_variation)
            )
            lines.append(f"Mean: {self.currency} {mean:.2f}")

        lines.append(f"Standard Deviation: {self.currency} {self.standard_deviation:.2f}")
        lines.append(f"IQR: {self.currency} {self.iqr:.2f}")
        lines.append(f"Price Range: {self.currency} {self.minimum_price:.2f} - {self.currency} {self.maximum_price:.2f}")
        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


class IMarketPriceEstimator(ABC):
    """Interface for market price estimation implementations.

    Estimates the fair market price for a game based on clean data.
    """

    @abstractmethod
    def estimate(
        self,
        dataset: PriceDataset,
        statistics: PriceStatisticsResult,
        observations_removed: int,
    ) -> MarketPriceEstimate:
        """Estimate market price from clean dataset.

        Args:
            dataset: Clean price dataset (post-outlier-removal)
            statistics: Pre-calculated statistical metrics
            observations_removed: Number of outliers removed (required, use 0 if none)

        Returns:
            Market price estimate with confidence score and justification

        Raises:
            EmptyDatasetError: If dataset has no observations
        """
        pass
