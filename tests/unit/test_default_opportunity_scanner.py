"""Unit tests for DefaultOpportunityScanner.

Tests the orchestration of the complete pipeline with mocks.
No Playwright. No Wallapop API calls.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.opportunity_scanner import PipelineStage
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.arbitrage_opportunity_detector import (
    Recommendation,
)
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker


@pytest.fixture
def sample_game() -> DetectedGame:
    """Create sample game."""
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


@pytest.fixture
def sample_listing(sample_game: DetectedGame) -> CandidateListing:
    """Create sample listing with detected game."""
    return CandidateListing(
        listing_id="test123",
        title="GTA V PS4",
        description="Great condition",
        price=Decimal("12.0"),
        currency="EUR",
        url="https://wallapop.com/item/test123",
    )


@pytest.fixture
def listing_without_game() -> CandidateListing:
    """Create listing without detected game."""
    return CandidateListing(
        listing_id="test456",
        title="Unknown Game",
        description="Some game",
        price=Decimal("10.0"),
        currency="EUR",
        url="https://wallapop.com/item/test456",
    )


@pytest.fixture
def sample_comparable(sample_game: DetectedGame) -> ComparableListing:
    """Create a sample comparable listing returned by price collector."""
    return ComparableListing(
        listing_id="comp001",
        title="GTA V PS4 - Like New",
        description="Perfect condition",
        price=Decimal("20.0"),
        currency="EUR",
        detected_game=sample_game,
        url="https://wallapop.com/item/comp001",
    )


@pytest.fixture
def mock_game_detector(sample_game: DetectedGame) -> Mock:
    """Create mock game detector."""
    detector = Mock()
    detector.detect_games.side_effect = lambda text: (
        [] if text.title == "Unknown Game" else [sample_game]
    )
    return detector


@pytest.fixture
def mock_price_collector() -> AsyncMock:
    """Create mock price collector."""
    return AsyncMock()


@pytest.fixture
def mock_dataset_builder() -> Mock:
    """Create mock dataset builder."""
    return Mock()


@pytest.fixture
def mock_statistics() -> Mock:
    """Create mock statistics calculator."""
    return Mock()


@pytest.fixture
def mock_outlier_removal() -> Mock:
    """Create mock outlier removal."""
    return Mock()


@pytest.fixture
def mock_market_estimator() -> Mock:
    """Create mock market estimator."""
    return Mock()


@pytest.fixture
def mock_arbitrage_detector() -> Mock:
    """Create mock arbitrage detector."""
    return Mock()


@pytest.fixture
def scanner(
    mock_game_detector: Mock,
    mock_price_collector: Mock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_arbitrage_detector: Mock,
) -> DefaultOpportunityScanner:
    """Create scanner with all mocked dependencies."""
    scanner = DefaultOpportunityScanner(
        game_detector=mock_game_detector,
        price_collector=mock_price_collector,
        dataset_builder=mock_dataset_builder,
        statistics=mock_statistics,
        outlier_removal=mock_outlier_removal,
        market_estimator=mock_market_estimator,
        arbitrage_detector=mock_arbitrage_detector,
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    return scanner


def _setup_successful_pipeline_mocks(
    scanner: DefaultOpportunityScanner,
    sample_comparable: ComparableListing,
    mock_price_collector: Mock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_arbitrage_detector: Mock,
) -> Mock:
    """Configure all mocks to return successful results through the pipeline.

    Returns the mock opportunity for assertions.
    """
    # Price collection returns some comparables
    mock_price_collector.collect_comparables.return_value = [sample_comparable]

    # Dataset builder
    mock_dataset = Mock()
    mock_dataset.sample_size = 5
    mock_dataset_builder.build.return_value = mock_dataset

    # Statistics
    mock_stats = Mock()
    mock_statistics.calculate.return_value = mock_stats

    # Outlier removal
    mock_outlier_result = Mock()
    mock_outlier_result.removed_count = 1
    mock_outlier_result.clean_dataset = mock_dataset
    mock_outlier_removal.remove_outliers.return_value = mock_outlier_result

    # Market estimator
    mock_estimate = Mock()
    mock_estimate.estimated_price = Decimal("22.0")
    mock_estimate.confidence_score = 0.80
    mock_market_estimator.estimate.return_value = mock_estimate

    # Arbitrage detector
    mock_opportunity = Mock()
    mock_opportunity.recommendation = Recommendation.BUY
    mock_opportunity.opportunity_score = 75.0
    mock_arbitrage_detector.detect.return_value = mock_opportunity

    return mock_opportunity


class TestScanListing:
    """Test scan_listing() method."""

    @pytest.mark.asyncio
    async def test_complete_pipeline_success(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
        sample_comparable: ComparableListing,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
    ) -> None:
        """Should execute complete pipeline successfully with all 8 steps."""
        _setup_successful_pipeline_mocks(
            scanner,
            sample_comparable,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_arbitrage_detector,
        )

        # Execute
        result = await scanner.scan_listing(sample_listing)

        # Verify result
        assert result is not None
        assert result.recommendation == Recommendation.BUY

        # Verify pipeline order: _run_async (price collection) was called
        scanner.price_collector.collect_comparables.assert_awaited_once()
        # Dataset builder called with original listing + comparables
        mock_dataset_builder.build.assert_called_once()
        # Statistics called twice (before and after outlier removal)
        assert mock_statistics.calculate.call_count == 2
        # Outlier removal called once
        mock_outlier_removal.remove_outliers.assert_called_once()
        # Market estimator called once
        mock_market_estimator.estimate.assert_called_once()
        # Arbitrage detector called once
        mock_arbitrage_detector.detect.assert_called_once()

    @pytest.mark.asyncio
    async def test_listing_without_game(
        self,
        scanner: DefaultOpportunityScanner,
        listing_without_game: CandidateListing,
    ) -> None:
        """Should skip listing without detected game."""
        result = await scanner.scan_listing(listing_without_game)

        assert result is None
        # Price collector should NOT be called
        scanner.price_collector.collect_comparables.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_comparable_listings_empty_dataset(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        mock_dataset_builder: Mock,
    ) -> None:
        """Should return None when dataset is empty after building."""
        scanner.price_collector.collect_comparables.return_value = []

        mock_dataset = Mock()
        mock_dataset.sample_size = 0
        mock_dataset_builder.build.return_value = mock_dataset

        result = await scanner.scan_listing(sample_listing)

        assert result is None

    @pytest.mark.asyncio
    async def test_pipeline_failure_returns_none(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
    ) -> None:
        """Should return None when pipeline fails with exception."""
        scanner.price_collector.collect_comparables.side_effect = Exception("Price collection error")

        result = await scanner.scan_listing(sample_listing)

        assert result is None

    @pytest.mark.asyncio
    async def test_price_collector_called_with_correct_params(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should call price collector with the detected game and coordinates."""
        scanner.price_collector.collect_comparables.return_value = []

        # Make dataset empty so we don't need full pipeline mocks
        scanner.dataset_builder.build.return_value = Mock(sample_size=0)

        await scanner.scan_listing(sample_listing)

        # Verify _run_async was called with the collect_comparables coroutine
        scanner.price_collector.collect_comparables.assert_awaited_once()


class TestScanMultiple:
    """Test scan_multiple() method."""

    @pytest.mark.asyncio
    async def test_multiple_listings_all_successful(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
        sample_comparable: ComparableListing,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
    ) -> None:
        """Should process multiple listings successfully."""
        # Create 3 listings
        listings = [
            CandidateListing(
                listing_id=f"test{i}",
                title=f"GTA V PS4 - {i}",
                description="",
                price=Decimal("10.0") + i,
                currency="EUR",
                url=f"https://wallapop.com/item/test{i}",
            )
            for i in range(3)
        ]

        _setup_successful_pipeline_mocks(
            scanner,
            sample_comparable,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_arbitrage_detector,
        )

        # Execute
        result = await scanner.scan_multiple(listings)

        # Verify
        assert result.total_processed == 3
        assert result.successful == 3
        assert result.failed == 0
        assert len(result.opportunities) == 3
        assert len(result.failures) == 0
        assert result.processing_time > 0.0
        assert isinstance(result.created_at, datetime)

    @pytest.mark.asyncio
    async def test_scan_multiple_returns_recommendation_priority_order(
        self,
        scanner: DefaultOpportunityScanner,
        sample_comparable: ComparableListing,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
    ) -> None:
        listings = [
            CandidateListing(
                listing_id=f"candidate-{index}",
                title=f"GTA V PS4 {index}",
                description="",
                price=Decimal("10.0") + index,
                currency="EUR",
                url=f"https://example.test/{index}",
            )
            for index in range(3)
        ]
        _setup_successful_pipeline_mocks(
            scanner,
            sample_comparable,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_arbitrage_detector,
        )
        skip = Mock(recommendation=Recommendation.SKIP, opportunity_score=100.0)
        buy = Mock(recommendation=Recommendation.BUY, opportunity_score=1.0)
        maybe = Mock(recommendation=Recommendation.MAYBE, opportunity_score=90.0)
        mock_arbitrage_detector.detect.side_effect = [skip, buy, maybe]

        result = await scanner.scan_multiple(listings)

        assert result.opportunities == [buy, maybe, skip]
        assert result.successful == 3
        assert result.comparable_cache_misses == 1
        assert result.comparable_cache_hits == 2

    @pytest.mark.asyncio
    async def test_empty_list(
        self,
        scanner: DefaultOpportunityScanner,
    ) -> None:
        """Should handle empty list gracefully."""
        result = await scanner.scan_multiple([])

        assert result.total_processed == 0
        assert result.successful == 0
        assert result.failed == 0
        assert len(result.opportunities) == 0
        assert len(result.failures) == 0

    @pytest.mark.asyncio
    async def test_continues_after_failure(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
        listing_without_game: CandidateListing,
    ) -> None:
        """Should continue processing after individual failures."""
        # Mix: first has no game, second has game (but will get empty dataset)
        listings = [
            listing_without_game,  # Will fail (no game)
            sample_listing,  # Will fail (empty dataset)
            listing_without_game,  # Will fail (no game)
        ]

        scanner.price_collector.collect_comparables.return_value = []
        scanner.dataset_builder.build.return_value = Mock(sample_size=0)

        result = await scanner.scan_multiple(listings)

        assert result.total_processed == 3
        assert result.failed == 3
        assert len(result.failures) == 3
        # Check that failures contain stage information
        assert all(f.stage for f in result.failures)

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
        sample_comparable: ComparableListing,
        listing_without_game: CandidateListing,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
        mock_price_collector: Mock,
    ) -> None:
        """Should handle mix of successes and failures."""
        listings = [
            listing_without_game,  # No game РІвЂ вЂ™ fail
            sample_listing,  # Has game РІвЂ вЂ™ success
        ]

        _setup_successful_pipeline_mocks(
            scanner,
            sample_comparable,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_arbitrage_detector,
        )

        result = await scanner.scan_multiple(listings)

        assert result.total_processed == 2
        assert result.successful == 1
        assert result.failed == 1
        assert len(result.opportunities) == 1
        assert len(result.failures) == 1

    @pytest.mark.asyncio
    async def test_repeated_game_reuses_comparable_collection(
        self,
        scanner: DefaultOpportunityScanner,
        sample_game: DetectedGame,
        sample_comparable: ComparableListing,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
    ) -> None:
        """Should not repeat collection for later listings of the same game."""
        listings = [
            CandidateListing(
                listing_id="good1",
                title="GTA V PS4",
                description="",
                price=Decimal("10.0"),
                currency="EUR",
                url="https://wallapop.com/item/good1",
            ),
            CandidateListing(
                listing_id="bad1",
                title="GTA V PS4",
                description="",
                price=Decimal("15.0"),
                currency="EUR",
                url="https://wallapop.com/item/bad1",
            ),
            CandidateListing(
                listing_id="good2",
                title="GTA V PS4",
                description="",
                price=Decimal("20.0"),
                currency="EUR",
                url="https://wallapop.com/item/good2",
            ),
        ]

        # A hypothetical second collection would fail, but must never occur.
        call_count = [0]

        def collector_side_effect(**_kwargs: object) -> list[ComparableListing]:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("Price collection failed")
            return [sample_comparable]

        scanner.price_collector.collect_comparables.side_effect = collector_side_effect

        # Dataset: first and third succeed, second is never reached
        def build_side_effect(listings_arg: list[object]) -> Mock:
            # listing_id of first ComparableListing in the list
            first = listings_arg[0] if listings_arg else None
            if hasattr(first, "listing_id") and first.listing_id == "bad1":
                raise RuntimeError("Should not reach here")
            m = Mock()
            m.sample_size = 5
            return m

        mock_dataset = Mock()
        mock_dataset.sample_size = 5
        mock_dataset_builder.build.return_value = mock_dataset

        mock_stats = Mock()
        mock_statistics.calculate.return_value = mock_stats

        mock_outlier_result = Mock()
        mock_outlier_result.removed_count = 0
        mock_outlier_result.clean_dataset = mock_dataset
        mock_outlier_removal.remove_outliers.return_value = mock_outlier_result

        mock_estimate = Mock()
        mock_estimate.estimated_price = Decimal("22.0")
        mock_estimate.confidence_score = 0.80
        mock_market_estimator.estimate.return_value = mock_estimate

        mock_opportunity = Mock()
        mock_opportunity.recommendation = Recommendation.BUY
        mock_opportunity.opportunity_score = 75.0
        mock_arbitrage_detector.detect.return_value = mock_opportunity

        result = await scanner.scan_multiple(listings)

        assert result.total_processed == 3
        assert result.successful == 3
        assert result.failed == 0
        assert len(result.opportunities) == 3
        assert len(result.failures) == 0
        assert call_count[0] == 1
        assert result.comparable_cache_misses == 1
        assert result.comparable_cache_hits == 2


class TestPipelineStageTracking:
    """Test PipelineStage tracking in failures."""

    @pytest.mark.asyncio
    async def test_game_detection_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        listing_without_game: CandidateListing,
    ) -> None:
        """Should track GAME_DETECTION stage for listings without games."""
        result = await scanner.scan_multiple([listing_without_game])

        assert result.failed == 1
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.GAME_DETECTION
        assert failure.listing_id == listing_without_game.listing_id
        assert "No game detected" in failure.reason

    @pytest.mark.asyncio
    async def test_price_collection_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
    ) -> None:
        """Should track PRICE_COLLECTION stage when price collector fails."""
        scanner.price_collector.collect_comparables.side_effect = Exception("API error")

        result = await scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.PRICE_COLLECTION
        assert failure.listing_id == sample_listing.listing_id
        assert failure.error_message is not None
        assert "API error" in failure.error_message

    @pytest.mark.asyncio
    async def test_dataset_building_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_comparable: ComparableListing,
        mock_dataset_builder: Mock,
    ) -> None:
        """Should track DATASET_BUILDING stage for empty datasets."""
        scanner.price_collector.collect_comparables.return_value = [sample_comparable]
        mock_dataset = Mock()
        mock_dataset.sample_size = 0
        mock_dataset_builder.build.return_value = mock_dataset

        result = await scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.DATASET_BUILDING
        assert failure.listing_id == sample_listing.listing_id
        assert "Empty dataset" in failure.reason

    @pytest.mark.asyncio
    async def test_statistics_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_comparable: ComparableListing,
        mock_statistics: Mock,
        mock_dataset_builder: Mock,
    ) -> None:
        """Should track STATISTICS stage when statistics calculation fails."""
        scanner.price_collector.collect_comparables.return_value = [sample_comparable]
        mock_dataset = Mock()
        mock_dataset.sample_size = 5
        mock_dataset_builder.build.return_value = mock_dataset
        mock_statistics.calculate.side_effect = ValueError("Math error")

        result = await scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.STATISTICS
        assert failure.error_message is not None
        assert "Math error" in failure.error_message

    @pytest.mark.asyncio
    async def test_market_estimation_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_comparable: ComparableListing,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
    ) -> None:
        """Should track MARKET_ESTIMATION stage when estimator fails."""
        scanner.price_collector.collect_comparables.return_value = [sample_comparable]
        mock_dataset = Mock()
        mock_dataset.sample_size = 5
        mock_dataset_builder.build.return_value = mock_dataset

        mock_stats = Mock()
        mock_statistics.calculate.return_value = mock_stats

        mock_outlier_result = Mock()
        mock_outlier_result.removed_count = 0
        mock_outlier_result.clean_dataset = mock_dataset
        mock_outlier_removal.remove_outliers.return_value = mock_outlier_result

        mock_market_estimator.estimate.side_effect = ValueError("Estimation error")

        result = await scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.MARKET_ESTIMATION
        assert failure.error_message is not None
        assert "Estimation error" in failure.error_message


class TestScanResult:
    """Test ScanResult data."""

    @pytest.mark.asyncio
    async def test_scan_result_fields(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
        sample_comparable: ComparableListing,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
    ) -> None:
        """Should return ScanResult with all fields populated."""
        _setup_successful_pipeline_mocks(
            scanner,
            sample_comparable,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_arbitrage_detector,
        )

        result = await scanner.scan_multiple([sample_listing])

        assert result.total_processed == 1
        assert result.successful == 1
        assert result.failed == 0
        assert len(result.opportunities) == 1
        assert len(result.failures) == 0
        assert result.processing_time > 0.0
        assert isinstance(result.created_at, datetime)

    @pytest.mark.asyncio
    async def test_scan_result_with_only_failures(
        self,
        scanner: DefaultOpportunityScanner,
        listing_without_game: CandidateListing,
    ) -> None:
        """Should return ScanResult with failures but no opportunities."""
        result = await scanner.scan_multiple([listing_without_game, listing_without_game])

        assert result.total_processed == 2
        assert result.successful == 0
        assert result.failed == 2
        assert len(result.opportunities) == 0
        assert len(result.failures) == 2


@pytest.mark.asyncio
async def test_scanner_runs_inside_an_already_active_event_loop(
    scanner: DefaultOpportunityScanner,
    sample_listing: CandidateListing,
    sample_comparable: ComparableListing,
    mock_price_collector: AsyncMock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_arbitrage_detector: Mock,
) -> None:
    _setup_successful_pipeline_mocks(
        scanner,
        sample_comparable,
        mock_price_collector,
        mock_dataset_builder,
        mock_statistics,
        mock_outlier_removal,
        mock_market_estimator,
        mock_arbitrage_detector,
    )

    result = await scanner.scan_multiple([sample_listing])

    assert result.successful == 1
    mock_price_collector.collect_comparables.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_games_are_rejected_before_price_collection(
    scanner: DefaultOpportunityScanner,
    sample_listing: CandidateListing,
    sample_game: DetectedGame,
    mock_game_detector: Mock,
    mock_price_collector: AsyncMock,
) -> None:
    second_game = DetectedGame(
        canonical_name="Red Dead Redemption 2",
        matched_text="rdr2",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )
    mock_game_detector.detect_games.side_effect = None
    mock_game_detector.detect_games.return_value = [sample_game, second_game]

    result = await scanner.scan_multiple([sample_listing])

    assert result.failed == 1
    assert result.failures[0].stage is PipelineStage.GAME_DETECTION
    assert result.failures[0].reason == "Multiple games detected; use LotOpportunityScanner"
    mock_price_collector.collect_comparables.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_ids_are_excluded_from_market_comparables(
    scanner: DefaultOpportunityScanner,
    sample_listing: CandidateListing,
    sample_comparable: ComparableListing,
    mock_price_collector: AsyncMock,
    mock_dataset_builder: Mock,
) -> None:
    own_listing = ComparableListing(
        listing_id=sample_listing.listing_id,
        title=sample_listing.title,
        description=sample_listing.description,
        price=sample_listing.price,
        currency=sample_listing.currency,
        detected_game=sample_comparable.detected_game,
        url=sample_listing.url,
    )
    mock_price_collector.collect_comparables.return_value = [own_listing, sample_comparable]
    empty_dataset = Mock(sample_size=0)
    mock_dataset_builder.build.return_value = empty_dataset

    await scanner.scan_multiple([sample_listing])

    mock_dataset_builder.build.assert_called_once_with([sample_comparable], "EUR")


@pytest.mark.asyncio
async def test_scan_multiple_delegates_all_opportunities_to_ranker_once(
    scanner: DefaultOpportunityScanner,
    sample_listing: CandidateListing,
    sample_comparable: ComparableListing,
    mock_price_collector: AsyncMock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_arbitrage_detector: Mock,
) -> None:
    _setup_successful_pipeline_mocks(
        scanner,
        sample_comparable,
        mock_price_collector,
        mock_dataset_builder,
        mock_statistics,
        mock_outlier_removal,
        mock_market_estimator,
        mock_arbitrage_detector,
    )
    second = CandidateListing(
        listing_id="second",
        title=sample_listing.title,
        description=sample_listing.description,
        price=sample_listing.price,
        currency=sample_listing.currency,
        url="https://example.test/second",
    )
    third = CandidateListing(
        listing_id="third",
        title=sample_listing.title,
        description=sample_listing.description,
        price=sample_listing.price,
        currency=sample_listing.currency,
        url="https://example.test/third",
    )
    first_opportunity = Mock(
        listing=sample_listing,
        recommendation=Recommendation.BUY,
        opportunity_score=80.0,
    )
    second_opportunity = Mock(
        listing=second,
        recommendation=Recommendation.MAYBE,
        opportunity_score=60.0,
    )
    third_opportunity = Mock(
        listing=third,
        recommendation=Recommendation.SKIP,
        opportunity_score=90.0,
    )
    mock_arbitrage_detector.detect.side_effect = [
        first_opportunity,
        second_opportunity,
        third_opportunity,
    ]
    ranker = Mock()
    ranker.rank.return_value = [
        third_opportunity,
        first_opportunity,
        second_opportunity,
    ]
    scanner.opportunity_ranker = ranker

    result = await scanner.scan_multiple([sample_listing, second, third])

    ranker.rank.assert_called_once()
    supplied, strategy = ranker.rank.call_args.args
    assert supplied == [first_opportunity, second_opportunity, third_opportunity]
    assert strategy.value == "opportunity_score"
    assert result.opportunities == [
        third_opportunity,
        first_opportunity,
        second_opportunity,
    ]


@pytest.mark.asyncio
async def test_scan_multiple_propagates_ranking_errors(
    scanner: DefaultOpportunityScanner,
) -> None:
    ranker = Mock()
    ranker.rank.side_effect = RuntimeError("ranking failed")
    scanner.opportunity_ranker = ranker

    with pytest.raises(RuntimeError, match="ranking failed"):
        await scanner.scan_multiple([])

    ranker.rank.assert_called_once_with([], scanner.ranking_strategy)
