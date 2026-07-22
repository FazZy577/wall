"""Opportunity scanner application contract and execution results."""

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
from domain.interfaces.opportunity_ranker import RankingStrategy


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
    """Information about a failed candidate scan."""

    listing_id: str
    stage: PipelineStage
    reason: str
    error_message: str | None = None


@dataclass
class ScanResult:
    """Result of scanning one or more candidate listings."""

    total_processed: int
    successful: int
    failed: int
    opportunities: list[ArbitrageOpportunity]
    failures: list[FailureInfo]
    processing_time: float
    created_at: datetime
    comparable_cache_hits: int = 0
    comparable_cache_misses: int = 0


@dataclass
class RankingResult:
    """Summary metadata for opportunities already ordered by the ranker."""

    ordered_opportunities: list[ArbitrageOpportunity]
    strategy: RankingStrategy
    total_opportunities: int
    buy_count: int
    maybe_count: int
    skip_count: int
    best_score: float
    average_score: float
    created_at: datetime

    @classmethod
    def from_ranked_opportunities(
        cls,
        ranked_opportunities: list[ArbitrageOpportunity],
        strategy: RankingStrategy = RankingStrategy.OPPORTUNITY_SCORE,
    ) -> "RankingResult":
        """Compute metadata without filtering or changing the supplied order."""
        opportunities = list(ranked_opportunities)
        scores = [opportunity.opportunity_score for opportunity in opportunities]
        return cls(
            ordered_opportunities=opportunities,
            strategy=strategy,
            total_opportunities=len(opportunities),
            buy_count=sum(
                opportunity.recommendation == Recommendation.BUY
                for opportunity in opportunities
            ),
            maybe_count=sum(
                opportunity.recommendation == Recommendation.MAYBE
                for opportunity in opportunities
            ),
            skip_count=sum(
                opportunity.recommendation == Recommendation.SKIP
                for opportunity in opportunities
            ),
            best_score=round(max(scores), 1) if scores else 0.0,
            average_score=round(std_stats.mean(scores), 1) if scores else 0.0,
            created_at=datetime.now(),
        )


class IOpportunityScanner(ABC):
    """Application input port for the opportunity scanning use case."""

    @abstractmethod
    async def scan_listing(self, listing: CandidateListing) -> ArbitrageOpportunity | None:
        """Scan one candidate through the valuation pipeline."""
        pass

    @abstractmethod
    async def scan_multiple(self, listings: list[CandidateListing]) -> ScanResult:
        """Scan candidates and continue after candidate-specific failures."""
        pass
