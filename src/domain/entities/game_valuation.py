"""Game valuation entity.

Represents the valuation of a single game within a lot or candidate listing.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from domain._decimal import require_decimal
from domain.entities.detected_game import DetectedGame
from domain.interfaces.market_price_estimator import MarketPriceEstimate


@dataclass
class GameValuation:
    """Valuation of a single game detected within a candidate listing.

    Wraps the MarketPriceEstimate with additional context about the
    observations used. Does NOT contain ComparableListing objects —
    only aggregated statistics.

    Attributes:
        game: The detected game being valued
        market_price_estimate: Full market price estimate from the pipeline
        estimated_market_value: Convenience alias for market_price_estimate.estimated_price
        confidence_score: Confidence in this valuation (0.0 - 1.0)
        observations_used: Number of comparable listings used (after outlier removal)
        observations_removed: Number of outliers removed
        created_at: Valuation timestamp
    """

    game: DetectedGame
    market_price_estimate: MarketPriceEstimate
    estimated_market_value: Decimal
    confidence_score: float
    observations_used: int
    observations_removed: int
    created_at: datetime

    def __post_init__(self) -> None:
        require_decimal("estimated_market_value", self.estimated_market_value)

    @property
    def currency(self) -> str:
        return self.market_price_estimate.currency

    @classmethod
    def from_market_estimate(
        cls,
        game: DetectedGame,
        estimate: MarketPriceEstimate,
        observations_removed: int = 0,
    ) -> "GameValuation":
        """Create a GameValuation from a MarketPriceEstimate.

        Args:
            game: The detected game
            estimate: Market price estimate from the pipeline
            observations_removed: Number of outliers removed

        Returns:
            GameValuation with propagated values
        """
        return cls(
            game=game,
            market_price_estimate=estimate,
            estimated_market_value=estimate.estimated_price,
            confidence_score=estimate.confidence_score,
            observations_used=estimate.sample_size,
            observations_removed=observations_removed,
            created_at=datetime.now(),
        )
