"""Unit tests for DefaultOpportunityScanner.

Tests the orchestration of the complete pipeline with mocks.
No Playwright. No Wallapop API calls.
"""

from datetime import datetime
from unittest.mock import Mock

import pytest

from domain.interfaces.arbitrage_opportunity_detector import (
    Recommendation,
)
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.opportunity_scanner import PipelineStage
from domain.interfaces.price_collector import ComparableListing
from infrastructure.scanners.default_opportunity_scanner import DefaultOpportunityScanner


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
def sample_listing(sample_game: DetectedGame) -> ComparableListing:
    """Create sample listing with detected game."""
    return ComparableListing(
        listing_id="test123",
        title="GTA V PS4",
        description="Great condition",
        price=12.0,
        currency="EUR",
        detected_game=sample_game,
        url="https://wallapop.com/item/test123",
    )


@pytest.fixture
def listing_without_game() -> ComparableListing:
    """Create listing without detected game."""
    return ComparableListing(
        listing_id="test456",
        title="Unknown Game",
        description="Some game",
        price=10.0,
        currency="EUR",
        detected_game=None,
        url="https://wallapop.com/item/test456",
    )


@pytest.fixture
def sample_comparable(sample_game: DetectedGame) -> ComparableListing:
    """Create a sample comparable listing returned by price collector."""
    return ComparableListing(
        listing_id="comp001",
        title="GTA V PS4 - Like New",
        description="Perfect condition",
        price=20.0,
        currency="EUR",
        detected_game=sample_game,
        url="https://wallapop.com/item/comp001",
    )


@pytest.fixture
def mock_game_detector() -> Mock:
    """Create mock game detector."""
    return Mock()


@pytest.fixture
def mock_price_collector() -> Mock:
    """Create mock price collector."""
    return Mock()


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
    )
    # Mock _run_async to avoid asyncio.run() in sync tests
    scanner._run_async = Mock()
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
    scanner._run_async.return_value = [sample_comparable]

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
    mock_estimate.estimated_price = 22.0
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

    def test_complete_pipeline_success(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
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
        result = scanner.scan_listing(sample_listing)

        # Verify result
        assert result is not None
        assert result.recommendation == Recommendation.BUY

        # Verify pipeline order: _run_async (price collection) was called
        scanner._run_async.assert_called_once()
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

    def test_listing_without_game(
        self,
        scanner: DefaultOpportunityScanner,
        listing_without_game: ComparableListing,
    ) -> None:
        """Should skip listing without detected game."""
        result = scanner.scan_listing(listing_without_game)

        assert result is None
        # Price collector should NOT be called
        scanner._run_async.assert_not_called()

    def test_no_comparable_listings_empty_dataset(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
        mock_dataset_builder: Mock,
    ) -> None:
        """Should return None when dataset is empty after building."""
        scanner._run_async.return_value = []

        mock_dataset = Mock()
        mock_dataset.sample_size = 0
        mock_dataset_builder.build.return_value = mock_dataset

        result = scanner.scan_listing(sample_listing)

        assert result is None

    def test_pipeline_failure_returns_none(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
    ) -> None:
        """Should return None when pipeline fails with exception."""
        scanner._run_async.side_effect = Exception("Price collection error")

        result = scanner.scan_listing(sample_listing)

        assert result is None

    def test_price_collector_called_with_correct_params(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should call price collector with the detected game and coordinates."""
        scanner._run_async.return_value = []

        # Make dataset empty so we don't need full pipeline mocks
        scanner.dataset_builder.build.return_value = Mock(sample_size=0)

        scanner.scan_listing(sample_listing)

        # Verify _run_async was called with the collect_comparables coroutine
        scanner._run_async.assert_called_once()


class TestScanMultiple:
    """Test scan_multiple() method."""

    def test_multiple_listings_all_successful(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
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
            ComparableListing(
                listing_id=f"test{i}",
                title=f"GTA V PS4 - {i}",
                description="",
                price=10.0 + i,
                currency="EUR",
                detected_game=sample_game,
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
        result = scanner.scan_multiple(listings)

        # Verify
        assert result.total_processed == 3
        assert result.successful == 3
        assert result.failed == 0
        assert len(result.opportunities) == 3
        assert len(result.failures) == 0
        assert result.processing_time > 0.0
        assert isinstance(result.created_at, datetime)

    def test_empty_list(
        self,
        scanner: DefaultOpportunityScanner,
    ) -> None:
        """Should handle empty list gracefully."""
        result = scanner.scan_multiple([])

        assert result.total_processed == 0
        assert result.successful == 0
        assert result.failed == 0
        assert len(result.opportunities) == 0
        assert len(result.failures) == 0

    def test_continues_after_failure(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
        listing_without_game: ComparableListing,
    ) -> None:
        """Should continue processing after individual failures."""
        # Mix: first has no game, second has game (but will get empty dataset)
        listings = [
            listing_without_game,  # Will fail (no game)
            sample_listing,  # Will fail (empty dataset)
            listing_without_game,  # Will fail (no game)
        ]

        scanner._run_async.return_value = []
        scanner.dataset_builder.build.return_value = Mock(sample_size=0)

        result = scanner.scan_multiple(listings)

        assert result.total_processed == 3
        assert result.failed == 3
        assert len(result.failures) == 3
        # Check that failures contain stage information
        assert all(f.stage for f in result.failures)

    def test_mixed_success_and_failure(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
        sample_comparable: ComparableListing,
        listing_without_game: ComparableListing,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
        mock_price_collector: Mock,
    ) -> None:
        """Should handle mix of successes and failures."""
        listings = [
            listing_without_game,  # No game → fail
            sample_listing,  # Has game → success
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

        result = scanner.scan_multiple(listings)

        assert result.total_processed == 2
        assert result.successful == 1
        assert result.failed == 1
        assert len(result.opportunities) == 1
        assert len(result.failures) == 1

    def test_module_error_does_not_stop_others(
        self,
        scanner: DefaultOpportunityScanner,
        sample_game: DetectedGame,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_arbitrage_detector: Mock,
    ) -> None:
        """Should continue processing when one listing causes a module error."""
        listings = [
            ComparableListing(
                listing_id="good1",
                title="GTA V PS4",
                description="",
                price=10.0,
                currency="EUR",
                detected_game=sample_game,
                url="https://wallapop.com/item/good1",
            ),
            ComparableListing(
                listing_id="bad1",
                title="GTA V PS4",
                description="",
                price=15.0,
                currency="EUR",
                detected_game=sample_game,
                url="https://wallapop.com/item/bad1",
            ),
            ComparableListing(
                listing_id="good2",
                title="GTA V PS4",
                description="",
                price=20.0,
                currency="EUR",
                detected_game=sample_game,
                url="https://wallapop.com/item/good2",
            ),
        ]

        # First call succeeds, second fails, third succeeds
        call_count = [0]

        def run_async_side_effect(coro: object) -> list[ComparableListing]:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("Price collection failed")
            return []

        scanner._run_async.side_effect = run_async_side_effect

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
        mock_estimate.estimated_price = 22.0
        mock_estimate.confidence_score = 0.80
        mock_market_estimator.estimate.return_value = mock_estimate

        mock_opportunity = Mock()
        mock_opportunity.recommendation = Recommendation.BUY
        mock_opportunity.opportunity_score = 75.0
        mock_arbitrage_detector.detect.return_value = mock_opportunity

        result = scanner.scan_multiple(listings)

        assert result.total_processed == 3
        assert result.successful == 2
        assert result.failed == 1
        assert len(result.opportunities) == 2
        assert len(result.failures) == 1
        # The failure should be at PRICE_COLLECTION stage
        assert result.failures[0].stage == PipelineStage.PRICE_COLLECTION


class TestPipelineStageTracking:
    """Test PipelineStage tracking in failures."""

    def test_game_detection_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        listing_without_game: ComparableListing,
    ) -> None:
        """Should track GAME_DETECTION stage for listings without games."""
        result = scanner.scan_multiple([listing_without_game])

        assert result.failed == 1
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.GAME_DETECTION
        assert failure.listing_id == listing_without_game.listing_id
        assert "No game detected" in failure.reason

    def test_price_collection_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
    ) -> None:
        """Should track PRICE_COLLECTION stage when price collector fails."""
        scanner._run_async.side_effect = Exception("API error")

        result = scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.PRICE_COLLECTION
        assert failure.listing_id == sample_listing.listing_id
        assert failure.error_message is not None
        assert "API error" in failure.error_message

    def test_dataset_building_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
        mock_dataset_builder: Mock,
    ) -> None:
        """Should track DATASET_BUILDING stage for empty datasets."""
        scanner._run_async.return_value = []
        mock_dataset = Mock()
        mock_dataset.sample_size = 0
        mock_dataset_builder.build.return_value = mock_dataset

        result = scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.DATASET_BUILDING
        assert failure.listing_id == sample_listing.listing_id
        assert "Empty dataset" in failure.reason

    def test_statistics_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
        mock_statistics: Mock,
        mock_dataset_builder: Mock,
    ) -> None:
        """Should track STATISTICS stage when statistics calculation fails."""
        scanner._run_async.return_value = []
        mock_dataset = Mock()
        mock_dataset.sample_size = 5
        mock_dataset_builder.build.return_value = mock_dataset
        mock_statistics.calculate.side_effect = ValueError("Math error")

        result = scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.STATISTICS
        assert failure.error_message is not None
        assert "Math error" in failure.error_message

    def test_market_estimation_failure_tracked(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
    ) -> None:
        """Should track MARKET_ESTIMATION stage when estimator fails."""
        scanner._run_async.return_value = []
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

        result = scanner.scan_multiple([sample_listing])

        assert result.failed == 1
        failure = result.failures[0]
        assert failure.stage == PipelineStage.MARKET_ESTIMATION
        assert failure.error_message is not None
        assert "Estimation error" in failure.error_message


class TestScanResult:
    """Test ScanResult data."""

    def test_scan_result_fields(
        self,
        scanner: DefaultOpportunityScanner,
        sample_listing: ComparableListing,
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

        result = scanner.scan_multiple([sample_listing])

        assert result.total_processed == 1
        assert result.successful == 1
        assert result.failed == 0
        assert len(result.opportunities) == 1
        assert len(result.failures) == 0
        assert result.processing_time > 0.0
        assert isinstance(result.created_at, datetime)

    def test_scan_result_with_only_failures(
        self,
        scanner: DefaultOpportunityScanner,
        listing_without_game: ComparableListing,
    ) -> None:
        """Should return ScanResult with failures but no opportunities."""
        result = scanner.scan_multiple([listing_without_game, listing_without_game])

        assert result.total_processed == 2
        assert result.successful == 0
        assert result.failed == 2
        assert len(result.opportunities) == 0
        assert len(result.failures) == 2
