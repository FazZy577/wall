"""Unit tests for DefaultLotOpportunityScanner.

Tests the orchestration of the lot valuation pipeline with mocks.
No Playwright. No Wallapop API calls.
"""

from unittest.mock import Mock

import pytest

from application.interfaces.lot_opportunity_scanner import LotPipelineStage
from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.arbitrage_opportunity_detector import Recommendation
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(name: str) -> DetectedGame:
    return DetectedGame(
        canonical_name=name,
        matched_text=name.lower(),
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def _make_comparable(game: DetectedGame, price: float, listing_id: str) -> ComparableListing:
    return ComparableListing(
        listing_id=listing_id,
        title=f"{game.canonical_name} PS4",
        description="Good condition",
        price=price,
        currency="EUR",
        detected_game=game,
        url=f"https://wallapop.com/item/{listing_id}",
    )


@pytest.fixture
def mock_price_collector() -> Mock:
    return Mock()


@pytest.fixture
def mock_dataset_builder() -> Mock:
    return Mock()


@pytest.fixture
def mock_statistics() -> Mock:
    return Mock()


@pytest.fixture
def mock_outlier_removal() -> Mock:
    return Mock()


@pytest.fixture
def mock_market_estimator() -> Mock:
    return Mock()


@pytest.fixture
def mock_lot_analyzer() -> Mock:
    return Mock()


@pytest.fixture
def scanner(
    mock_price_collector: Mock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_lot_analyzer: Mock,
) -> DefaultLotOpportunityScanner:
    return DefaultLotOpportunityScanner(
        price_collector=mock_price_collector,
        dataset_builder=mock_dataset_builder,
        statistics=mock_statistics,
        outlier_removal=mock_outlier_removal,
        market_estimator=mock_market_estimator,
        lot_analyzer=mock_lot_analyzer,
    )


def _setup_pipeline_mocks(
    scanner: DefaultLotOpportunityScanner,
    mock_price_collector: Mock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_lot_analyzer: Mock,
    comparable_prices: list[float],
) -> None:
    """Configure all pipeline mocks for successful game valuation."""
    game = _make_game("GTA V")
    comparables = [
        _make_comparable(game, p, f"comp_{i}") for i, p in enumerate(comparable_prices)
    ]
    scanner._run_async = Mock(return_value=comparables)

    mock_dataset = Mock()
    mock_dataset.sample_size = len(comparable_prices)
    mock_dataset_builder.build.return_value = mock_dataset

    mock_stats = Mock()
    mock_statistics.calculate.return_value = mock_stats

    mock_outlier_result = Mock()
    mock_outlier_result.removed_count = 1
    mock_outlier_result.clean_dataset = mock_dataset
    mock_outlier_removal.remove_outliers.return_value = mock_outlier_result

    mock_estimate = Mock()
    mock_estimate.estimated_price = sum(comparable_prices) / len(comparable_prices)
    mock_estimate.currency = "EUR"
    mock_estimate.confidence_score = 0.80
    mock_estimate.sample_size = len(comparable_prices)
    mock_market_estimator.estimate.return_value = mock_estimate

    mock_opportunity = Mock()
    mock_opportunity.recommendation = Recommendation.BUY
    mock_opportunity.reason = "undervalued_lot"
    mock_opportunity.opportunity_score = 85.0
    mock_opportunity.total_market_value = 53.0
    mock_opportunity.lot_price = 35.0
    mock_opportunity.estimated_profit = 18.0
    mock_opportunity.profit_margin_percentage = 34.0
    mock_opportunity.roi_percentage = 51.4
    mock_opportunity.aggregate_confidence_score = 0.80
    mock_lot_analyzer.analyze.return_value = mock_opportunity


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_complete_pipeline_three_games(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Should process 3 games and produce LotOpportunity."""
        candidate = CandidateListing(
            listing_id="lot001",
            title="Lote PS4 GTA V RDR2 Spider-Man",
            description="",
            price=35.0,
            currency="EUR",
            url="https://example.com/lot001",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0, 18.0, 20.0, 14.0],
        )

        result = scanner.scan_lot(candidate)

        assert result.total_detected_games == 3
        assert result.successfully_valued_games == 3
        assert result.failed_games == 0
        assert result.is_complete is True
        assert result.opportunity is not None
        assert result.opportunity.recommendation == Recommendation.BUY
        assert len(result.game_valuations) == 3
        assert len(result.failures) == 0

    def test_each_game_gets_own_dataset(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Each game should get its own dataset built from comparables."""
        candidate = CandidateListing(
            listing_id="lot002",
            title="2 games",
            description="",
            price=30.0,
            currency="EUR",
            url="https://example.com/lot002",
            detected_games=[_make_game("GTA V"), _make_game("RDR2")],
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0, 18.0],
        )

        scanner.scan_lot(candidate)

        # Dataset builder called once per game (2 times)
        assert mock_dataset_builder.build.call_count == 2
        # Price collector called once per game
        assert scanner._run_async.call_count == 2

    def test_statistics_called_before_and_after_outlier(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Statistics should be called twice per game (before + after outliers)."""
        candidate = CandidateListing(
            listing_id="lot003",
            title="1 game",
            description="",
            price=20.0,
            currency="EUR",
            url="https://example.com/lot003",
            detected_games=[_make_game("GTA V")],
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0],
        )

        scanner.scan_lot(candidate)

        # 2 calls per game (before + after outlier removal)
        assert mock_statistics.calculate.call_count == 2

    def test_observations_removed_passed_to_estimator(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """observations_removed should be passed to market_estimator.estimate."""
        candidate = CandidateListing(
            listing_id="lot004",
            title="1 game",
            description="",
            price=20.0,
            currency="EUR",
            url="https://example.com/lot004",
            detected_games=[_make_game("GTA V")],
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0],
        )

        scanner.scan_lot(candidate)

        # Verify observations_removed was passed
        call_kwargs = mock_market_estimator.estimate.call_args.kwargs
        assert call_kwargs["observations_removed"] == 1

    def test_analyzer_called_with_correct_params(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Analyzer should receive listing, valuations, and total_detected_games."""
        candidate = CandidateListing(
            listing_id="lot005",
            title="3 games",
            description="",
            price=35.0,
            currency="EUR",
            url="https://example.com/lot005",
            detected_games=[_make_game("A"), _make_game("B"), _make_game("C")],
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[10.0, 12.0, 14.0],
        )

        scanner.scan_lot(candidate)

        call_kwargs = mock_lot_analyzer.analyze.call_args.kwargs
        assert call_kwargs["listing"] == candidate
        assert call_kwargs["total_detected_games"] == 3
        assert len(call_kwargs["game_valuations"]) == 3


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class TestFailureHandling:
    def test_price_collector_failure_continues(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """When PriceCollector fails for one game, others continue."""
        candidate = CandidateListing(
            listing_id="fail1",
            title="3 games, 1 fails",
            description="",
            price=30.0,
            currency="EUR",
            url="https://example.com/fail1",
            detected_games=[_make_game("A"), _make_game("B"), _make_game("C")],
        )

        # Game B fails price collection, A and C succeed
        game_a = _make_game("A")
        game_c = _make_game("C")
        comparables_a = [_make_comparable(game_a, 12.0, "comp_a")]
        comparables_c = [_make_comparable(game_c, 14.0, "comp_c")]

        call_count = [0]

        def side_effect(coro: object) -> list[ComparableListing]:
            call_count[0] += 1
            if call_count[0] == 2:  # Second call (game B) fails
                return []
            if call_count[0] == 3:  # Third call (game C)
                return comparables_c
            return comparables_a

        scanner._run_async = Mock(side_effect=side_effect)

        mock_dataset = Mock()
        mock_dataset.sample_size = 3
        mock_dataset_builder.build.return_value = mock_dataset

        mock_stats = Mock()
        mock_statistics.calculate.return_value = mock_stats

        mock_outlier_result = Mock()
        mock_outlier_result.removed_count = 0
        mock_outlier_result.clean_dataset = mock_dataset
        mock_outlier_removal.remove_outliers.return_value = mock_outlier_result

        mock_estimate = Mock()
        mock_estimate.estimated_price = 15.0
        mock_estimate.confidence_score = 0.80
        mock_estimate.sample_size = 3
        mock_market_estimator.estimate.return_value = mock_estimate

        mock_opportunity = Mock()
        mock_opportunity.recommendation = Recommendation.MAYBE
        mock_opportunity.opportunity_score = 50.0
        mock_lot_analyzer.analyze.return_value = mock_opportunity

        result = scanner.scan_lot(candidate)

        assert result.successfully_valued_games == 2
        assert result.failed_games == 1
        assert result.is_complete is False
        assert len(result.failures) == 1
        assert result.failures[0].stage == LotPipelineStage.PRICE_COLLECTION

    def test_market_estimator_failure(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Market estimator failure should be tracked."""
        candidate = CandidateListing(
            listing_id="fail_est",
            title="1 game, estimator fails",
            description="",
            price=20.0,
            currency="EUR",
            url="https://example.com/fail_est",
            detected_games=[_make_game("A")],
        )

        comparables = [_make_comparable(_make_game("A"), 12.0, "comp_1")]
        scanner._run_async = Mock(return_value=comparables)

        mock_dataset = Mock()
        mock_dataset.sample_size = 3
        mock_dataset_builder.build.return_value = mock_dataset

        mock_stats = Mock()
        mock_statistics.calculate.return_value = mock_stats

        mock_outlier_result = Mock()
        mock_outlier_result.removed_count = 0
        mock_outlier_result.clean_dataset = mock_dataset
        mock_outlier_removal.remove_outliers.return_value = mock_outlier_result

        mock_market_estimator.estimate.side_effect = ValueError("Estimation failed")

        mock_opportunity = Mock()
        mock_lot_analyzer.analyze.return_value = mock_opportunity

        result = scanner.scan_lot(candidate)

        assert result.successfully_valued_games == 0
        assert result.failed_games == 1
        assert result.failures[0].stage == LotPipelineStage.MARKET_ESTIMATION
        assert "Estimation failed" in (result.failures[0].error_message or "")

    def test_analyzer_failure_preserves_valuations(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """When analyzer fails, opportunity is None but valuations preserved."""
        candidate = CandidateListing(
            listing_id="analyzer_fail",
            title="Analyzer fails",
            description="",
            price=20.0,
            currency="EUR",
            url="https://example.com/analyzer_fail",
            detected_games=[_make_game("A")],
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0],
        )

        mock_lot_analyzer.analyze.side_effect = RuntimeError("Analyzer crashed")

        result = scanner.scan_lot(candidate)

        assert result.opportunity is None
        assert len(result.game_valuations) == 1  # Valuations preserved

    def test_empty_detected_games(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Empty detected_games should produce safe result."""
        candidate = CandidateListing(
            listing_id="empty",
            title="No games",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/empty",
        )

        mock_opportunity = Mock()
        mock_opportunity.recommendation = Recommendation.SKIP
        mock_lot_analyzer.analyze.return_value = mock_opportunity

        result = scanner.scan_lot(candidate)

        assert result.total_detected_games == 0
        assert result.successfully_valued_games == 0
        assert result.is_complete is False

    def test_original_detected_games_not_modified(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """detected_games list should not be modified by the scanner."""
        games = [_make_game("A"), _make_game("B")]
        candidate = CandidateListing(
            listing_id="immutable",
            title="Immutable test",
            description="",
            price=20.0,
            currency="EUR",
            url="https://example.com/immutable",
            detected_games=games,
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0],
        )

        scanner.scan_lot(candidate)

        assert len(candidate.detected_games) == 2
        assert candidate.detected_games is games

    def test_no_silent_deduplication(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Duplicate games should not be silently removed."""
        gta = _make_game("GTA V")
        candidate = CandidateListing(
            listing_id="dup",
            title="Two GTA V copies",
            description="",
            price=30.0,
            currency="EUR",
            url="https://example.com/dup",
            detected_games=[gta, gta],  # Two copies
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0],
        )

        result = scanner.scan_lot(candidate)

        # Both copies should be processed
        assert result.total_detected_games == 2
        assert result.successfully_valued_games == 2
        assert scanner._run_async.call_count == 2


class TestLotScanExplanation:
    def test_explain_includes_required_lot_fields(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Scan explanation should be deterministic and complete."""
        candidate = CandidateListing(
            listing_id="explain_lot",
            title="Lote PS4 GTA V RDR2",
            description="",
            price=35.0,
            currency="EUR",
            url="https://example.com/explain_lot",
            detected_games=[_make_game("GTA V"), _make_game("RDR2")],
        )

        _setup_pipeline_mocks(
            scanner,
            mock_price_collector,
            mock_dataset_builder,
            mock_statistics,
            mock_outlier_removal,
            mock_market_estimator,
            mock_lot_analyzer,
            comparable_prices=[12.0, 15.0],
        )

        result = scanner.scan_lot(candidate)
        explanation = result.explain()

        assert "LOT OPPORTUNITY SCAN" in explanation
        assert "Listing ID: explain_lot" in explanation
        assert "Total Detected Games: 2" in explanation
        assert "Successfully Valued: 2" in explanation
        assert "Failed: 0" in explanation
        assert "Complete: True" in explanation
        assert "Completion Ratio: 100.00%" in explanation
        assert "- GTA V: EUR 13.50" in explanation
        assert "Total Market Value: EUR 53.00" in explanation
        assert "Lot Price: EUR 35.00" in explanation
        assert "Estimated Profit: EUR 18.00" in explanation
        assert "Margin: 34.00%" in explanation
        assert "ROI: 51.40%" in explanation
        assert "Confidence: 0.80" in explanation
        assert "Opportunity Score: 85.0/100" in explanation
        assert "Recommendation: BUY" in explanation
        assert "Reason: UNDERVALUED_LOT" in explanation
