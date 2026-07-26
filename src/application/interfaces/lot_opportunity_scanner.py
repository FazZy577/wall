"""Lot opportunity scanner interface (port).

Defines the contract for orchestrating the valuation pipeline
for candidate listings that may contain multiple games (lots).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity

from .detected_candidate import DetectedCandidate
from .opportunity_scanner import FailureInfo


class LotPipelineStage(StrEnum):
    """Pipeline stages for lot valuation tracking."""

    VALIDATION = "validation"
    GAME_DETECTION = "game_detection"
    PRICE_COLLECTION = "price_collection"
    DATASET_BUILDING = "dataset_building"
    STATISTICS = "statistics"
    OUTLIER_REMOVAL = "outlier_removal"
    STATISTICS_RECALCULATION = "statistics_recalculation"
    MARKET_ESTIMATION = "market_estimation"
    GAME_VALUATION = "game_valuation"
    LOT_ANALYSIS = "lot_analysis"


@dataclass
class GameValuationFailure:
    """Information about a failed game valuation within a lot.

    Attributes:
        game: The game that failed to be valued
        stage: Pipeline stage where the failure occurred
        reason: Human-readable failure reason
        error_message: Technical error message (optional)
    """

    game: DetectedGame | None
    stage: LotPipelineStage
    reason: str
    error_message: str | None = None
    listing_id: str = ""


@dataclass
class LotScanResult:
    """Result of scanning a candidate listing through the lot pipeline.

    Attributes:
        listing: The candidate listing that was scanned
        opportunity: LotOpportunity if analysis succeeded, None if failed
        game_valuations: Successfully obtained game valuations
        failures: Detailed information about each failed game valuation
        total_detected_games: Total games detected in the listing
        successfully_valued_games: Number of games successfully valued
        failed_games: Number of games that failed valuation
        is_complete: Whether all detected games were valued
        processing_time: Time taken to process (seconds)
        created_at: Scan timestamp
        analysis_failure: Structured aggregate analyzer failure, if any
    """

    listing: CandidateListing
    opportunity: LotOpportunity | None
    game_valuations: list[GameValuation]
    failures: list[GameValuationFailure]
    total_detected_games: int
    successfully_valued_games: int
    failed_games: int
    is_complete: bool
    processing_time: float
    created_at: datetime
    detected_games: list[DetectedGame] = field(default_factory=list)
    analysis_failure: FailureInfo | None = None

    def explain(self) -> str:
        """Generate deterministic human-readable lot scan explanation."""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("LOT OPPORTUNITY SCAN")
        lines.append("=" * 60)
        lines.append("")
        lines.append("LOT")
        lines.append("-" * 60)
        lines.append(f"Listing ID: {self.listing.listing_id}")
        lines.append(f"Title: {self.listing.title}")
        lines.append(f"Lot Price: {self.listing.currency} {self.listing.price:.2f}")
        lines.append("")
        lines.append("DETECTED GAMES")
        lines.append("-" * 60)
        lines.append(f"Total Detected Games: {self.total_detected_games}")
        for index, game in enumerate(self.detected_games, 1):
            lines.append(f"{index}. {game.canonical_name} ({game.platform})")
        lines.append("")
        lines.append("VALUATION STATUS")
        lines.append("-" * 60)
        lines.append(f"Successfully Valued: {self.successfully_valued_games}")
        lines.append(f"Failed: {self.failed_games}")
        lines.append(f"Complete: {self.is_complete}")
        completion_ratio = (
            self.successfully_valued_games / self.total_detected_games
            if self.total_detected_games > 0
            else 0.0
        )
        lines.append(f"Completion Ratio: {completion_ratio:.2%}")
        lines.append("")
        lines.append("INDIVIDUAL VALUATIONS")
        lines.append("-" * 60)
        if self.game_valuations:
            for valuation in self.game_valuations:
                lines.append(
                    f"- {valuation.game.canonical_name}: "
                    f"{valuation.market_price_estimate.currency} "
                    f"{valuation.estimated_market_value:.2f} "
                    f"(confidence {valuation.confidence_score:.2f}, "
                    f"observations {valuation.observations_used}, "
                    f"outliers removed {valuation.observations_removed})"
                )
        else:
            lines.append("No games valued.")
        lines.append("")
        lines.append("FAILED GAMES")
        lines.append("-" * 60)
        if self.failures:
            for failure in self.failures:
                if failure.game is None:
                    lines.append(
                        f"- {failure.listing_id}: {failure.stage} - {failure.reason}"
                    )
                    if failure.error_message:
                        lines.append(f"  Error: {failure.error_message}")
                    continue
                lines.append(
                    f"- {failure.game.canonical_name}: {failure.stage} — {failure.reason}"
                )
                if failure.error_message:
                    lines.append(f"  Error: {failure.error_message}")
        else:
            lines.append("No failures.")
        lines.append("")
        lines.append("AGGREGATE OPPORTUNITY")
        lines.append("-" * 60)
        if self.opportunity is None:
            lines.append("No LotOpportunity produced.")
        else:
            lines.append(
                f"Reference Market Value: {self.listing.currency} "
                f"{self.opportunity.reference_market_value:.2f}"
            )
            lines.append(f"Lot Price: {self.listing.currency} {self.opportunity.lot_price:.2f}")
            lines.append(
                f"Net Profit: {self.listing.currency} "
                f"{self.opportunity.net_profit:.2f}"
            )
            lines.append(f"Net Margin: {self.opportunity.net_profit_margin_percentage:.2f}%")
            lines.append(f"Net ROI: {self.opportunity.net_roi_percentage:.2f}%")
            lines.append(f"Confidence: {self.opportunity.aggregate_confidence_score:.2f}")
            lines.append(f"Opportunity Score: {self.opportunity.opportunity_score:.1f}/100")
            lines.append(f"Recommendation: {self.opportunity.recommendation.upper()}")
            lines.append(f"Reason: {self.opportunity.reason.upper()}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)


class ILotOpportunityScanner(ABC):
    """Interface for lot opportunity scanner implementations.

    Orchestrates the valuation pipeline for each game in a candidate listing.
    The scanner contains NO business logic — only coordination.
    """

    @abstractmethod
    async def scan_lot(self, listing: CandidateListing) -> LotScanResult:
        """Scan a candidate listing through the complete lot pipeline.

        For each detected game in the listing, runs the full valuation
        pipeline: PriceCollector → DatasetBuilder → Statistics →
        OutlierRemoval → Statistics(recalc) → MarketEstimator →
        GameValuation.

        After all games are processed, calls the LotOpportunityAnalyzer
        to produce the final LotOpportunity.

        Args:
            listing: Candidate listing to scan (may contain multiple games)

        Returns:
            LotScanResult with opportunity, valuations, and failures
        """
        pass

    @abstractmethod
    async def scan_detected_lot(
        self,
        candidate: DetectedCandidate,
    ) -> LotScanResult:
        """Scan a lot without repeating game detection."""
        pass
