"""Default lot opportunity scanner implementation.

Orchestrates the valuation pipeline for each game in a candidate listing,
then calls the analyzer to produce the final LotOpportunity.

Contains NO business logic — only coordination.
"""

import asyncio
import logging
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast

from application.interfaces.lot_opportunity_scanner import (
    GameValuationFailure,
    ILotOpportunityScanner,
    LotPipelineStage,
    LotScanResult,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity
from domain.interfaces.lot_opportunity_analyzer import ILotOpportunityAnalyzer
from domain.interfaces.market_price_estimator import IMarketPriceEstimator
from domain.interfaces.outlier_removal import IOutlierRemoval
from domain.interfaces.price_collector import IPriceCollector
from domain.interfaces.price_dataset_builder import IPriceDatasetBuilder
from domain.interfaces.price_statistics import IPriceStatistics

logger = logging.getLogger(__name__)

# Default coordinates (Barcelona city center)
_DEFAULT_LATITUDE = 41.3874
_DEFAULT_LONGITUDE = 2.1686


class DefaultLotOpportunityScanner(ILotOpportunityScanner):
    """Default implementation that orchestrates lot valuation.

    Processes each game in a candidate listing through the full
    valuation pipeline, collecting GameValuations. Then calls the
    analyzer to produce the final LotOpportunity.

    The scanner contains NO business logic — only coordination.
    """

    def __init__(
        self,
        price_collector: IPriceCollector,
        dataset_builder: IPriceDatasetBuilder,
        statistics: IPriceStatistics,
        outlier_removal: IOutlierRemoval,
        market_estimator: IMarketPriceEstimator,
        lot_analyzer: ILotOpportunityAnalyzer,
        latitude: float = _DEFAULT_LATITUDE,
        longitude: float = _DEFAULT_LONGITUDE,
    ) -> None:
        """Initialize scanner with all dependencies.

        All dependencies are injected — the scanner does not instantiate them.

        Args:
            price_collector: Collects comparable listings from marketplace
            dataset_builder: Builds price datasets
            statistics: Calculates statistical metrics
            outlier_removal: Removes outliers from datasets
            market_estimator: Estimates market prices
            lot_analyzer: Analyzes lot opportunities
            latitude: Latitude for marketplace search (default: Barcelona)
            longitude: Longitude for marketplace search (default: Barcelona)
        """
        self.price_collector = price_collector
        self.dataset_builder = dataset_builder
        self.statistics = statistics
        self.outlier_removal = outlier_removal
        self.market_estimator = market_estimator
        self.lot_analyzer = lot_analyzer
        self.latitude = latitude
        self.longitude = longitude

    def _run_async(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run an async coroutine synchronously."""
        return asyncio.run(coro)

    def scan_lot(self, listing: CandidateListing) -> LotScanResult:
        """Scan a candidate listing through the complete lot pipeline.

        For each detected game, runs the full valuation pipeline.
        After all games are processed, calls the analyzer.

        Args:
            listing: Candidate listing to scan

        Returns:
            LotScanResult with opportunity, valuations, and failures
        """
        start_time = time.time()

        total_detected_games = listing.game_count
        game_valuations: list[GameValuation] = []
        failures: list[GameValuationFailure] = []

        # Process each game
        for i, game in enumerate(listing.detected_games, 1):
            logger.info(
                f"Valuing game {i}/{total_detected_games}: "
                f"{game.canonical_name} ({game.platform})"
            )

            valuation, failure = self._value_game(game)

            if valuation is not None:
                game_valuations.append(valuation)
            if failure is not None:
                failures.append(failure)

        # Call analyzer
        opportunity: LotOpportunity | None = None

        if total_detected_games > 0:
            try:
                opportunity = self.lot_analyzer.analyze(
                    listing=listing,
                    game_valuations=game_valuations,
                    total_detected_games=total_detected_games,
                )
                logger.info(
                    f"Lot analysis completed: {opportunity.recommendation.upper()} "
                    f"(score: {opportunity.opportunity_score:.1f}/100)"
                )
            except Exception as e:
                logger.error(f"Lot analysis failed: {e}", exc_info=True)

        return self._build_result(
            listing=listing,
            opportunity=opportunity,
            game_valuations=game_valuations,
            failures=failures,
            total_detected_games=total_detected_games,
            start_time=start_time,
        )

    def _value_game(
        self, game: DetectedGame
    ) -> tuple[GameValuation | None, GameValuationFailure | None]:
        """Run the full valuation pipeline for a single game.

        Pipeline stages:
        1. PriceCollector → collect comparables
        2. DatasetBuilder → build price dataset
        3. Statistics → calculate initial statistics
        4. OutlierRemoval → remove outliers
        5. Statistics → recalculate on clean data
        6. MarketPriceEstimator → estimate market price
        7. GameValuation → wrap result

        The candidate listing NEVER enters the dataset.

        Args:
            game: The game to value

        Returns:
            Tuple of (valuation, failure) — exactly one is non-None
        """
        current_stage = LotPipelineStage.PRICE_COLLECTION

        try:
            # Step 1: Price Collection
            logger.info("Collecting comparables...")
            comparables = cast(
                list[ComparableListing],
                self._run_async(
                    self.price_collector.collect_comparables(
                        game=game,
                        latitude=self.latitude,
                        longitude=self.longitude,
                    )
                ),
            )

            if not comparables:
                return None, GameValuationFailure(
                    game=game,
                    stage=LotPipelineStage.PRICE_COLLECTION,
                    reason="No comparable listings found",
                )

            # Step 2: Dataset Building (comparables ONLY)
            current_stage = LotPipelineStage.DATASET_BUILDING
            dataset = self.dataset_builder.build(cast(list[object], comparables))

            if dataset.sample_size == 0:
                return None, GameValuationFailure(
                    game=game,
                    stage=LotPipelineStage.DATASET_BUILDING,
                    reason="Empty dataset — no valid observations",
                )

            # Step 3: Statistics Calculation
            current_stage = LotPipelineStage.STATISTICS
            stats = self.statistics.calculate(dataset)

            # Step 4: Outlier Removal
            current_stage = LotPipelineStage.OUTLIER_REMOVAL
            logger.info("Removing outliers...")
            outlier_result = self.outlier_removal.remove_outliers(dataset, stats)
            logger.info(
                f"Removed {outlier_result.removed_count} outliers from "
                f"{dataset.sample_size} observations"
            )

            # Step 5: Statistics Recalculation
            current_stage = LotPipelineStage.STATISTICS_RECALCULATION
            clean_stats = self.statistics.calculate(outlier_result.clean_dataset)

            # Step 6: Market Price Estimation
            current_stage = LotPipelineStage.MARKET_ESTIMATION
            logger.info("Estimating market price...")
            market_estimate = self.market_estimator.estimate(
                dataset=outlier_result.clean_dataset,
                statistics=clean_stats,
                observations_removed=outlier_result.removed_count,
            )
            logger.info(
                f"Market price estimated: EUR {market_estimate.estimated_price:.2f}"
            )

            # Step 7: GameValuation
            current_stage = LotPipelineStage.GAME_VALUATION
            valuation = GameValuation.from_market_estimate(
                game=game,
                estimate=market_estimate,
                observations_removed=outlier_result.removed_count,
            )

            return valuation, None

        except Exception as e:
            logger.error(
                f"Failed to value {game.canonical_name} at stage {current_stage}: {e}",
                exc_info=True,
            )
            return None, GameValuationFailure(
                game=game,
                stage=current_stage,
                reason=f"Error during {current_stage}",
                error_message=str(e),
            )

    @staticmethod
    def _build_result(
        listing: CandidateListing,
        opportunity: LotOpportunity | None,
        game_valuations: list[GameValuation],
        failures: list[GameValuationFailure],
        total_detected_games: int,
        start_time: float,
    ) -> LotScanResult:
        """Build the LotScanResult from collected data."""
        successfully_valued = len(game_valuations)
        failed = len(failures)
        is_complete = (
            total_detected_games > 0
            and successfully_valued == total_detected_games
        )
        processing_time = time.time() - start_time

        return LotScanResult(
            listing=listing,
            opportunity=opportunity,
            game_valuations=game_valuations,
            failures=failures,
            total_detected_games=total_detected_games,
            successfully_valued_games=successfully_valued,
            failed_games=failed,
            is_complete=is_complete,
            processing_time=processing_time,
            created_at=datetime.now(UTC),
        )
