"""Default opportunity scanner implementation.

Orchestrates the complete arbitrage detection pipeline by coordinating
all existing modules in the correct order.

This module contains NO business logic - it only coordinates.
"""

import asyncio
import logging
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any, cast

from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    IArbitrageOpportunityDetector,
)
from domain.interfaces.game_detector import IGameDetector
from domain.interfaces.market_price_estimator import IMarketPriceEstimator
from domain.interfaces.opportunity_scanner import (
    FailureInfo,
    IOpportunityScanner,
    PipelineStage,
    ScanResult,
)
from domain.interfaces.outlier_removal import IOutlierRemoval
from domain.interfaces.price_collector import ComparableListing, IPriceCollector
from domain.interfaces.price_dataset_builder import IPriceDatasetBuilder
from domain.interfaces.price_statistics import IPriceStatistics

logger = logging.getLogger(__name__)

# Default coordinates (Barcelona city center)
DEFAULT_LATITUDE = 41.3874
DEFAULT_LONGITUDE = 2.1686


class DefaultOpportunityScanner(IOpportunityScanner):
    """Default implementation that orchestrates the complete pipeline.

    Coordinates all modules without containing any business logic.
    All decisions are delegated to the appropriate components.

    Pipeline:
    1. GameDetector — verify game is detected
    2. PriceCollector — collect comparable listings from marketplace
    3. PriceDatasetBuilder — build price dataset
    4. PriceStatistics — calculate initial statistics
    5. OutlierRemoval — remove outliers
    6. PriceStatistics — recalculate on clean data
    7. MarketPriceEstimator — estimate market price
    8. ArbitrageOpportunityDetector — detect opportunity
    9. Return result
    """

    def __init__(
        self,
        game_detector: IGameDetector,
        price_collector: IPriceCollector,
        dataset_builder: IPriceDatasetBuilder,
        statistics: IPriceStatistics,
        outlier_removal: IOutlierRemoval,
        market_estimator: IMarketPriceEstimator,
        arbitrage_detector: IArbitrageOpportunityDetector,
        latitude: float = DEFAULT_LATITUDE,
        longitude: float = DEFAULT_LONGITUDE,
    ) -> None:
        """Initialize scanner with all dependencies.

        All dependencies are injected — the scanner does not instantiate them.

        Args:
            game_detector: Detects games from listing text
            price_collector: Collects comparable listings from marketplace
            dataset_builder: Builds price datasets
            statistics: Calculates statistical metrics
            outlier_removal: Removes outliers from datasets
            market_estimator: Estimates market prices
            arbitrage_detector: Detects arbitrage opportunities
            latitude: Latitude for marketplace search (default: Barcelona)
            longitude: Longitude for marketplace search (default: Barcelona)
        """
        self.game_detector = game_detector
        self.price_collector = price_collector
        self.dataset_builder = dataset_builder
        self.statistics = statistics
        self.outlier_removal = outlier_removal
        self.market_estimator = market_estimator
        self.arbitrage_detector = arbitrage_detector
        self.latitude = latitude
        self.longitude = longitude

    def _run_async(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run an async coroutine synchronously.

        Args:
            coro: Coroutine to run

        Returns:
            Result of the coroutine
        """
        return asyncio.run(coro)

    def scan_listing(self, listing: ComparableListing) -> ArbitrageOpportunity | None:
        """Scan a single listing through the complete pipeline.

        Pipeline:
        1. GameDetector — verify game is detected
        2. PriceCollector — collect comparable listings
        3. PriceDatasetBuilder — build dataset
        4. PriceStatistics — calculate statistics
        5. OutlierRemoval — remove outliers
        6. PriceStatistics — recalculate on clean data
        7. MarketPriceEstimator — estimate market price
        8. ArbitrageOpportunityDetector — detect opportunity

        Args:
            listing: Listing to scan

        Returns:
            ArbitrageOpportunity if successful, None if failed
        """
        start_time = time.time()

        try:
            # Step 1: Game Detection
            logger.info(f"Scanning listing: {listing.listing_id}")

            if not listing.detected_game:
                logger.warning(
                    f"Listing {listing.listing_id} has no detected game — skipping"
                )
                return None

            game = listing.detected_game
            logger.info(f"Game detected: {game.canonical_name}")

            # Step 2: Price Collection
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
            logger.info(f"Collected {len(comparables)} comparable listings")

            # Step 3: Dataset Building
            dataset = self.dataset_builder.build(cast(list[object], comparables))

            if dataset.sample_size == 0:
                logger.warning(f"Empty dataset for {game.canonical_name}")
                return None

            logger.info(f"Dataset built with {dataset.sample_size} observations")

            # Step 4: Statistics Calculation
            stats = self.statistics.calculate(dataset)

            # Step 5: Outlier Removal
            logger.info("Removing outliers...")
            outlier_result = self.outlier_removal.remove_outliers(dataset, stats)
            logger.info(
                f"Removed {outlier_result.removed_count} outliers "
                f"({outlier_result.removed_count / dataset.sample_size * 100:.1f}%)"
            )

            # Step 6: Statistics Recalculation
            clean_stats = self.statistics.calculate(outlier_result.clean_dataset)

            # Step 7: Market Price Estimation
            logger.info("Estimating market price...")
            market_estimate = self.market_estimator.estimate(
                dataset=outlier_result.clean_dataset,
                statistics=clean_stats,
                observations_removed=outlier_result.removed_count,
            )
            logger.info(
                f"Market price: EUR {market_estimate.estimated_price:.2f} "
                f"(confidence: {market_estimate.confidence_score:.2f})"
            )

            # Step 8: Arbitrage Opportunity Detection
            opportunity = self.arbitrage_detector.detect(listing, market_estimate)
            logger.info(
                f"{opportunity.recommendation.upper()} detected "
                f"(score: {opportunity.opportunity_score:.1f}/100)"
            )

            processing_time = time.time() - start_time
            logger.info(f"Processing completed in {processing_time:.2f} s")

            return opportunity

        except Exception as e:
            logger.error(
                f"Failed to scan listing {listing.listing_id}: {e}", exc_info=True
            )
            return None

    def scan_multiple(self, listings: list[ComparableListing]) -> ScanResult:
        """Scan multiple listings through the complete pipeline.

        Continues processing even if individual listings fail.
        Tracks exactly where each failure occurred.

        Args:
            listings: List of listings to scan

        Returns:
            ScanResult with all opportunities, failures, and statistics
        """
        start_time = time.time()

        total = len(listings)
        successful = 0
        failed = 0
        opportunities: list[ArbitrageOpportunity] = []
        failures: list[FailureInfo] = []

        logger.info(f"Starting batch scan of {total} listings")

        for i, listing in enumerate(listings, 1):
            listing_start = time.time()
            current_stage = PipelineStage.GAME_DETECTION

            try:
                logger.info(f"Scanning listing {i}/{total}")

                # Step 1: Game Detection
                if not listing.detected_game:
                    failed += 1
                    failures.append(
                        FailureInfo(
                            listing_id=listing.listing_id,
                            stage=PipelineStage.GAME_DETECTION,
                            reason="No game detected in listing",
                        )
                    )
                    logger.warning("No game detected — skipping")
                    continue

                game = listing.detected_game
                logger.info(f"Game detected: {game.canonical_name}")

                # Step 2: Price Collection
                current_stage = PipelineStage.PRICE_COLLECTION
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

                # Include the original listing
                all_listings = [listing] + comparables

                # Step 3: Dataset Building
                current_stage = PipelineStage.DATASET_BUILDING
                dataset = self.dataset_builder.build(cast(list[object], all_listings))

                if dataset.sample_size == 0:
                    failed += 1
                    failures.append(
                        FailureInfo(
                            listing_id=listing.listing_id,
                            stage=PipelineStage.DATASET_BUILDING,
                            reason="Empty dataset — no valid observations",
                        )
                    )
                    logger.warning("Empty dataset — skipping")
                    continue

                # Step 4: Statistics Calculation
                current_stage = PipelineStage.STATISTICS
                stats = self.statistics.calculate(dataset)

                # Step 5: Outlier Removal
                current_stage = PipelineStage.OUTLIER_REMOVAL
                logger.info("Removing outliers...")
                outlier_result = self.outlier_removal.remove_outliers(dataset, stats)

                # Step 6: Statistics Recalculation
                current_stage = PipelineStage.STATISTICS_RECALCULATION
                clean_stats = self.statistics.calculate(outlier_result.clean_dataset)

                # Step 7: Market Price Estimation
                current_stage = PipelineStage.MARKET_ESTIMATION
                logger.info("Estimating market price...")
                market_estimate = self.market_estimator.estimate(
                    dataset=outlier_result.clean_dataset,
                    statistics=clean_stats,
                    observations_removed=outlier_result.removed_count,
                )

                # Step 8: Arbitrage Opportunity Detection
                current_stage = PipelineStage.OPPORTUNITY_DETECTION
                opportunity = self.arbitrage_detector.detect(listing, market_estimate)

                # Success!
                opportunities.append(opportunity)
                successful += 1

                listing_time = time.time() - listing_start
                logger.info(
                    f"{opportunity.recommendation.upper()} detected "
                    f"(score: {opportunity.opportunity_score:.1f}/100) "
                    f"in {listing_time:.2f} s"
                )

            except Exception as e:
                failed += 1
                failures.append(
                    FailureInfo(
                        listing_id=listing.listing_id,
                        stage=current_stage,
                        reason=f"Error during {current_stage}",
                        error_message=str(e),
                    )
                )
                logger.error(
                    f"Error scanning listing {i}/{total} ({listing.listing_id}) "
                    f"at stage {current_stage}: {e}",
                    exc_info=True,
                )

        processing_time = time.time() - start_time

        logger.info(
            f"Batch scan completed: {successful} successful, {failed} failed "
            f"in {processing_time:.2f} s"
        )

        return ScanResult(
            total_processed=total,
            successful=successful,
            failed=failed,
            opportunities=opportunities,
            failures=failures,
            processing_time=processing_time,
            created_at=datetime.now(UTC),
        )
