"""Default opportunity scanner implementation."""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from application.interfaces.opportunity_scanner import (
    FailureInfo,
    IOpportunityScanner,
    PipelineStage,
    RankingResult,
    ScanResult,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    IArbitrageOpportunityDetector,
)
from domain.interfaces.game_detector import IGameDetector, ListingText
from domain.interfaces.market_price_estimator import (
    IMarketPriceEstimator,
    MarketPriceEstimate,
)
from domain.interfaces.outlier_removal import IOutlierRemoval
from domain.interfaces.price_collector import IPriceCollector
from domain.interfaces.price_dataset_builder import IPriceDatasetBuilder
from domain.interfaces.price_statistics import IPriceStatistics

logger = logging.getLogger(__name__)

DEFAULT_LATITUDE = 41.3874
DEFAULT_LONGITUDE = 2.1686


@dataclass(frozen=True)
class _ComparableCacheKey:
    """Stable identity for comparable collection within one execution."""

    canonical_name: str
    platform: str


@dataclass(frozen=True)
class _ValuationFailure:
    """Reusable failure details without listing-specific state."""

    stage: PipelineStage
    reason: str
    error_message: str | None = None


@dataclass(frozen=True)
class _ValuationResult:
    """Success or failure from the expensive valuation pipeline."""

    estimate: MarketPriceEstimate | None = None
    failure: _ValuationFailure | None = None


@dataclass(frozen=True)
class _ComparableCollectionResult:
    """Cached network result, independent of any candidate listing."""

    comparables: list[ComparableListing] | None = None
    failure: _ValuationFailure | None = None


@dataclass
class _ScanExecutionContext:
    """Comparable cache and metrics owned by one public scan call."""

    comparable_collections: dict[
        _ComparableCacheKey, _ComparableCollectionResult
    ] = field(default_factory=dict)
    cache_hits: int = 0
    cache_misses: int = 0


class DefaultOpportunityScanner(IOpportunityScanner):
    """Coordinate valuation and per-listing opportunity detection."""

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
        self.game_detector = game_detector
        self.price_collector = price_collector
        self.dataset_builder = dataset_builder
        self.statistics = statistics
        self.outlier_removal = outlier_removal
        self.market_estimator = market_estimator
        self.arbitrage_detector = arbitrage_detector
        self.latitude = latitude
        self.longitude = longitude

    @staticmethod
    def _build_comparable_cache_key(game: DetectedGame) -> _ComparableCacheKey:
        """Build an alias-independent, platform-sensitive collection key."""
        normalized_name = " ".join(game.canonical_name.strip().casefold().split())
        return _ComparableCacheKey(normalized_name, game.platform.value)

    async def _get_or_collect_comparables(
        self,
        game: DetectedGame,
        context: _ScanExecutionContext,
    ) -> _ComparableCollectionResult:
        """Collect comparables once per game identity and execution."""
        key = self._build_comparable_cache_key(game)
        cached = context.comparable_collections.get(key)
        if cached is not None:
            context.cache_hits += 1
            logger.debug(
                "Comparable cache HIT: %s / %s",
                game.canonical_name,
                game.platform.value,
            )
            return cached

        context.cache_misses += 1
        logger.debug(
            "Comparable cache MISS: %s / %s",
            game.canonical_name,
            game.platform.value,
        )
        try:
            result = _ComparableCollectionResult(
                comparables=await self.price_collector.collect_comparables(
                    game=game,
                    latitude=self.latitude,
                    longitude=self.longitude,
                )
            )
        except Exception as error:
            result = _ComparableCollectionResult(
                failure=_ValuationFailure(
                    stage=PipelineStage.PRICE_COLLECTION,
                    reason=f"Error during {PipelineStage.PRICE_COLLECTION}",
                    error_message=str(error),
                )
            )
        context.comparable_collections[key] = result
        return result

    async def _get_or_create_market_valuation(
        self,
        game: DetectedGame,
        context: _ScanExecutionContext,
        candidate_listing_id: str,
    ) -> _ValuationResult:
        """Build a candidate-specific valuation from cached comparables."""
        collection = await self._get_or_collect_comparables(game, context)
        if collection.failure is not None:
            return _ValuationResult(failure=collection.failure)
        if collection.comparables is None:
            raise RuntimeError("Comparable collection has neither data nor failure")

        current_stage = PipelineStage.DATASET_BUILDING

        try:
            comparables = [
                comparable
                for comparable in collection.comparables
                if not (
                    candidate_listing_id
                    and comparable.listing_id
                    and comparable.listing_id == candidate_listing_id
                )
            ]

            dataset = self.dataset_builder.build(cast(list[object], comparables))
            if dataset.sample_size == 0:
                result = _ValuationResult(
                    failure=_ValuationFailure(
                        stage=current_stage,
                        reason="Empty dataset - no valid observations",
                    )
                )
                return result

            current_stage = PipelineStage.STATISTICS
            stats = self.statistics.calculate(dataset)

            current_stage = PipelineStage.OUTLIER_REMOVAL
            outlier_result = self.outlier_removal.remove_outliers(dataset, stats)

            current_stage = PipelineStage.STATISTICS_RECALCULATION
            clean_stats = self.statistics.calculate(outlier_result.clean_dataset)

            current_stage = PipelineStage.MARKET_ESTIMATION
            estimate = self.market_estimator.estimate(
                dataset=outlier_result.clean_dataset,
                statistics=clean_stats,
                observations_removed=outlier_result.removed_count,
            )
            result = _ValuationResult(estimate=estimate)
        except Exception as error:
            result = _ValuationResult(
                failure=_ValuationFailure(
                    stage=current_stage,
                    reason=f"Error during {current_stage}",
                    error_message=str(error),
                )
            )

        return result

    async def scan_listing(
        self, listing: CandidateListing
    ) -> ArbitrageOpportunity | None:
        """Scan one listing with a fresh, non-persistent valuation context."""
        context = _ScanExecutionContext()
        start_time = time.time()

        try:
            logger.info(f"Scanning listing: {listing.listing_id}")
            detected_games = self.game_detector.detect_games(
                ListingText(title=listing.title, description=listing.description)
            )
            if not detected_games:
                logger.warning(f"Listing {listing.listing_id} has no detected game")
                return None
            if len(detected_games) > 1:
                logger.warning(
                    "Listing %s contains multiple games; use LotOpportunityScanner",
                    listing.listing_id,
                )
                return None
            (detected_game,) = detected_games

            valuation = await self._get_or_create_market_valuation(
                detected_game, context, listing.listing_id
            )
            if valuation.failure is not None or valuation.estimate is None:
                return None

            opportunity = self.arbitrage_detector.detect(listing, valuation.estimate)
            logger.info(
                f"{opportunity.recommendation.upper()} detected "
                f"(score: {opportunity.opportunity_score:.1f}/100)"
            )
            logger.info(f"Processing completed in {time.time() - start_time:.2f} s")
            return opportunity
        except Exception as error:
            logger.error(
                f"Failed to scan listing {listing.listing_id}: {error}",
                exc_info=True,
            )
            return None

    async def scan_multiple(self, listings: list[CandidateListing]) -> ScanResult:
        """Scan listings, reusing valuations only within this invocation."""
        start_time = time.time()
        context = _ScanExecutionContext()
        opportunities: list[ArbitrageOpportunity] = []
        failures: list[FailureInfo] = []

        logger.info(f"Starting batch scan of {len(listings)} listings")
        for index, listing in enumerate(listings, 1):
            listing_start = time.time()
            logger.info(f"Scanning listing {index}/{len(listings)}")

            detected_games = self.game_detector.detect_games(
                ListingText(title=listing.title, description=listing.description)
            )
            if not detected_games:
                failures.append(
                    FailureInfo(
                        listing_id=listing.listing_id,
                        stage=PipelineStage.GAME_DETECTION,
                        reason="No game detected in listing",
                    )
                )
                continue
            if len(detected_games) > 1:
                failures.append(
                    FailureInfo(
                        listing_id=listing.listing_id,
                        stage=PipelineStage.GAME_DETECTION,
                        reason="Multiple games detected; use LotOpportunityScanner",
                    )
                )
                continue
            (detected_game,) = detected_games

            valuation = await self._get_or_create_market_valuation(
                detected_game, context, listing.listing_id
            )
            if valuation.failure is not None:
                failures.append(
                    FailureInfo(
                        listing_id=listing.listing_id,
                        stage=valuation.failure.stage,
                        reason=valuation.failure.reason,
                        error_message=valuation.failure.error_message,
                    )
                )
                continue

            try:
                if valuation.estimate is None:
                    raise RuntimeError("Valuation has neither estimate nor failure")
                opportunity = self.arbitrage_detector.detect(listing, valuation.estimate)
                opportunities.append(opportunity)
                logger.info(
                    f"{opportunity.recommendation.upper()} detected "
                    f"(score: {opportunity.opportunity_score:.1f}/100) "
                    f"in {time.time() - listing_start:.2f} s"
                )
            except Exception as error:
                failures.append(
                    FailureInfo(
                        listing_id=listing.listing_id,
                        stage=PipelineStage.OPPORTUNITY_DETECTION,
                        reason=f"Error during {PipelineStage.OPPORTUNITY_DETECTION}",
                        error_message=str(error),
                    )
                )

        processing_time = time.time() - start_time
        logger.info(
            f"Batch scan completed: {len(opportunities)} successful, "
            f"{len(failures)} failed in {processing_time:.2f} s"
        )
        ranked_opportunities = RankingResult.from_opportunities(opportunities)
        return ScanResult(
            total_processed=len(listings),
            successful=len(opportunities),
            failed=len(failures),
            opportunities=ranked_opportunities.ordered_opportunities,
            failures=failures,
            processing_time=processing_time,
            created_at=datetime.now(UTC),
            comparable_cache_hits=context.cache_hits,
            comparable_cache_misses=context.cache_misses,
        )
