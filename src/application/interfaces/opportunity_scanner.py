"""Opportunity scanner interface (port).

Defines the contract for orchestrating the complete arbitrage detection pipeline.
"""

import statistics as std_stats
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    Recommendation,
)


class PipelineStage(StrEnum):
    """Pipeline stages for tracking progress and failures."""

    GAME_DETECTION = "game_detection"
    PRICE_COLLECTION = "price_collection"
    DATASET_BUILDING = "dataset_building"
    STATISTICS = "statistics"
    OUTLIER_REMOVAL = "outlier_removal"
    STATISTICS_RECALCULATION = "statistics_recalculation"
    MARKET_ESTIMATION = "market_estimation"
    OPPORTUNITY_DETECTION = "opportunity_detection"


@dataclass
class FailureInfo:
    """Information about a failed listing scan.

    Attributes:
        listing_id: ID of the failed listing
        stage: Pipeline stage where failure occurred
        reason: Human-readable failure reason
        error_message: Technical error message (optional)
    """

    listing_id: str
    stage: PipelineStage
    reason: str
    error_message: str | None = None


@dataclass
class ScanResult:
    """Result of scanning one or more listings.

    Attributes:
        total_processed: Total number of listings processed
        successful: Number of successfully processed listings
        failed: Number of failed listings
        opportunities: List of detected arbitrage opportunities
        failures: Detailed information about each failure
        processing_time: Time taken to process (seconds)
        created_at: Scan timestamp
        valuation_cache_hits: Later listings that reused a valuation outcome
        valuation_cache_misses: Unique game valuations attempted
    """

    total_processed: int
    successful: int
    failed: int
    opportunities: list[ArbitrageOpportunity]
    failures: list[FailureInfo]
    processing_time: float
    created_at: datetime
    valuation_cache_hits: int = 0
    valuation_cache_misses: int = 0


class RankingStrategy(StrEnum):
    """Strategy for ranking arbitrage opportunities.

    Defines the sorting key used when ordering opportunities.
    Only OPPORTUNITY_SCORE is implemented initially — the rest are
    placeholders for future use, following the same pattern as
    EstimationStrategy.MEDIAN in the market price estimator.

    Attributes:
        OPPORTUNITY_SCORE: Sort by opportunity_score descending
        ABSOLUTE_PROFIT: Sort by estimated_profit descending (future)
        ROI: Sort by roi_percentage descending (future)
        MARKET_DISCOUNT: Sort by market_discount_percentage descending (future)
        CUSTOM: Custom ranking function (future)
    """

    OPPORTUNITY_SCORE = "opportunity_score"
    ABSOLUTE_PROFIT = "absolute_profit"
    ROI = "roi"
    MARKET_DISCOUNT = "market_discount"
    CUSTOM = "custom"


@dataclass
class RankingResult:
    """Result of ranking a list of arbitrage opportunities.

    Provides both the ordered list and summary statistics useful
    for dashboards, alerts, and reporting.

    Attributes:
        ordered_opportunities: Opportunities sorted by the ranking strategy
        buy_count: Number of BUY recommendations
        maybe_count: Number of MAYBE recommendations
        skip_count: Number of SKIP recommendations
        best_score: Highest opportunity score in the list
        average_score: Mean opportunity score across all opportunities
        created_at: Timestamp when ranking was computed
    """

    ordered_opportunities: list[ArbitrageOpportunity]
    buy_count: int
    maybe_count: int
    skip_count: int
    best_score: float
    average_score: float
    created_at: datetime

    @classmethod
    def from_opportunities(
        cls,
        opportunities: list[ArbitrageOpportunity],
        strategy: RankingStrategy = RankingStrategy.OPPORTUNITY_SCORE,
    ) -> "RankingResult":
        """Create a RankingResult from a list of opportunities.

        Sorts opportunities by the given strategy and computes summary stats.

        Args:
            opportunities: List of arbitrage opportunities to rank
            strategy: Ranking strategy to use for sorting

        Returns:
            RankingResult with ordered opportunities and summary statistics
        """
        sorted_opps = _sort_by_strategy(opportunities, strategy)

        buy_count = sum(1 for o in sorted_opps if o.recommendation == Recommendation.BUY)
        maybe_count = sum(1 for o in sorted_opps if o.recommendation == Recommendation.MAYBE)
        skip_count = sum(1 for o in sorted_opps if o.recommendation == Recommendation.SKIP)

        scores = [o.opportunity_score for o in sorted_opps]
        best_score = max(scores) if scores else 0.0
        average_score = std_stats.mean(scores) if scores else 0.0

        return cls(
            ordered_opportunities=sorted_opps,
            buy_count=buy_count,
            maybe_count=maybe_count,
            skip_count=skip_count,
            best_score=round(best_score, 1),
            average_score=round(average_score, 1),
            created_at=datetime.now(),
        )


def _sort_by_strategy(
    opportunities: list[ArbitrageOpportunity],
    strategy: RankingStrategy,
) -> list[ArbitrageOpportunity]:
    """Sort opportunities by the given ranking strategy.

    Only OPPORTUNITY_SCORE is implemented. Other strategies fall back
    to OPPORTUNITY_SCORE with a warning.

    Args:
        opportunities: List of opportunities to sort
        strategy: Ranking strategy to use

    Returns:
        New list sorted by the strategy (descending)
    """
    if strategy == RankingStrategy.OPPORTUNITY_SCORE:
        return sorted(opportunities, key=lambda o: o.opportunity_score, reverse=True)

    # Fallback for unimplemented strategies — same pattern as
    # DefaultMarketPriceEstimator which only implements MEDIAN.
    import logging

    logger = logging.getLogger(__name__)
    logger.warning(
        f"Ranking strategy '{strategy}' is not yet implemented. "
        f"Falling back to {RankingStrategy.OPPORTUNITY_SCORE}."
    )
    return sorted(opportunities, key=lambda o: o.opportunity_score, reverse=True)


class IOpportunityScanner(ABC):
    """Interface for opportunity scanner implementations.

    Orchestrates the complete pipeline:
    1. Game Detection
    2. Price Collection
    3. Dataset Building
    4. Statistics Calculation
    5. Outlier Removal
    6. Statistics Recalculation
    7. Market Price Estimation
    8. Arbitrage Opportunity Detection

    The scanner contains NO business logic, only coordination.
    """

    @abstractmethod
    async def scan_listing(self, listing: CandidateListing) -> ArbitrageOpportunity | None:
        """Scan a single listing through the complete pipeline.

        Args:
            listing: Listing to scan

        Returns:
            ArbitrageOpportunity if successful, None if failed
        """
        pass

    @abstractmethod
    async def scan_multiple(self, listings: list[CandidateListing]) -> ScanResult:
        """Scan multiple listings through the complete pipeline.

        Continues processing even if individual listings fail.

        Args:
            listings: List of listings to scan

        Returns:
            ScanResult with all opportunities and statistics
        """
        pass
