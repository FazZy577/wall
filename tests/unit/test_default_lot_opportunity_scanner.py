"""Unit tests for DefaultLotOpportunityScanner.

Tests the orchestration of the lot valuation pipeline with mocks.
No Playwright. No Wallapop API calls.
"""

from dataclasses import asdict, fields
from decimal import Decimal
from typing import get_type_hints
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.lot_opportunity_scanner import (
    GameValuationFailure,
    LotPipelineStage,
    LotScanResult,
)
from application.interfaces.opportunity_scanner import FailureInfo, PipelineStage
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


def _make_game_for_platform(name: str, platform: Platform) -> DetectedGame:
    game = _make_game(name)
    return DetectedGame(
        canonical_name=game.canonical_name,
        matched_text=game.matched_text,
        platform=platform,
        confidence=game.confidence,
        detection_method=game.detection_method,
    )


def _make_comparable(game: DetectedGame, price: float, listing_id: str) -> ComparableListing:
    return ComparableListing(
        listing_id=listing_id,
        title=f"{game.canonical_name} PS4",
        description="Good condition",
        price=Decimal(str(price)),
        currency="EUR",
        detected_game=game,
        url=f"https://wallapop.com/item/{listing_id}",
    )


@pytest.fixture
def mock_price_collector() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_game_detector() -> Mock:
    detector = Mock()

    def detect(listing_text: object) -> list[DetectedGame]:
        title = str(getattr(listing_text, "title", ""))
        if title == "No games":
            return []
        if "Two GTA V copies" in title:
            game = _make_game("GTA V")
            return [game, game]
        if "GTA V RDR2 Spider-Man" in title:
            return [_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")]
        if "GTA V RDR2" in title or title == "2 games":
            return [_make_game("GTA V"), _make_game("RDR2")]
        if title.startswith("3 games"):
            return [_make_game("A"), _make_game("B"), _make_game("C")]
        return [_make_game("GTA V")]

    detector.detect_games.side_effect = detect
    return detector


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
    mock_game_detector: Mock,
    mock_price_collector: Mock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_lot_analyzer: Mock,
) -> DefaultLotOpportunityScanner:
    return DefaultLotOpportunityScanner(
        game_detector=mock_game_detector,
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
    mock_price_collector.collect_comparables.return_value = comparables

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
    mock_estimate.estimated_price = sum(
        (Decimal(str(price)) for price in comparable_prices),
        start=Decimal("0"),
    ) / len(comparable_prices)
    mock_estimate.currency = "EUR"
    mock_estimate.confidence_score = 0.80
    mock_estimate.sample_size = len(comparable_prices)
    mock_market_estimator.estimate.return_value = mock_estimate

    mock_opportunity = Mock()
    mock_opportunity.recommendation = Recommendation.BUY
    mock_opportunity.reason = "undervalued_lot"
    mock_opportunity.opportunity_score = 85.0
    mock_opportunity.reference_market_value = Decimal("53.0")
    mock_opportunity.lot_price = Decimal("35.0")
    mock_opportunity.net_profit = Decimal("18.0")
    mock_opportunity.net_profit_margin_percentage = 34.0
    mock_opportunity.net_roi_percentage = 51.4
    mock_opportunity.aggregate_confidence_score = 0.80
    mock_lot_analyzer.analyze.return_value = mock_opportunity


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def test_lot_scan_result_exposes_optional_analysis_failure_at_end() -> None:
    result_fields = fields(LotScanResult)

    assert result_fields[-1].name == "analysis_failure"
    assert result_fields[-1].default is None
    assert get_type_hints(LotScanResult)["analysis_failure"] == FailureInfo | None
    assert PipelineStage.LOT_ANALYSIS.value == "lot_analysis"
    assert sum(stage is PipelineStage.LOT_ANALYSIS for stage in PipelineStage) == 1


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_complete_pipeline_three_games(
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
            price=Decimal("35.0"),
            currency="EUR",
            url="https://example.com/lot001",
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

        result = await scanner.scan_lot(candidate)

        assert result.total_detected_games == 3
        assert result.successfully_valued_games == 3
        assert result.failed_games == 0
        assert result.is_complete is True
        assert result.opportunity is not None
        assert result.opportunity.recommendation == Recommendation.BUY
        assert len(result.game_valuations) == 3
        assert len(result.failures) == 0

    @pytest.mark.asyncio
    async def test_each_game_gets_own_dataset(
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
            price=Decimal("30.0"),
            currency="EUR",
            url="https://example.com/lot002",
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

        await scanner.scan_lot(candidate)

        # Dataset builder called once per game (2 times)
        assert mock_dataset_builder.build.call_count == 2
        # Price collector called once per game
        assert scanner.price_collector.collect_comparables.await_count == 2

    @pytest.mark.asyncio
    async def test_statistics_called_before_and_after_outlier(
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
            price=Decimal("20.0"),
            currency="EUR",
            url="https://example.com/lot003",
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

        await scanner.scan_lot(candidate)

        # 2 calls per game (before + after outlier removal)
        assert mock_statistics.calculate.call_count == 2

    @pytest.mark.asyncio
    async def test_observations_removed_passed_to_estimator(
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
            price=Decimal("20.0"),
            currency="EUR",
            url="https://example.com/lot004",
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

        await scanner.scan_lot(candidate)

        # Verify observations_removed was passed
        call_kwargs = mock_market_estimator.estimate.call_args.kwargs
        assert call_kwargs["observations_removed"] == 1

    @pytest.mark.asyncio
    async def test_analyzer_called_with_correct_params(
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
            price=Decimal("35.0"),
            currency="EUR",
            url="https://example.com/lot005",
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

        await scanner.scan_lot(candidate)

        call_kwargs = mock_lot_analyzer.analyze.call_args.kwargs
        assert call_kwargs["listing"] == candidate
        assert call_kwargs["total_detected_games"] == 3
        assert len(call_kwargs["game_valuations"]) == 3


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_price_collector_failure_continues(
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
            price=Decimal("30.0"),
            currency="EUR",
            url="https://example.com/fail1",
        )

        # Game B fails price collection, A and C succeed
        game_a = _make_game("A")
        game_c = _make_game("C")
        comparables_a = [_make_comparable(game_a, 12.0, "comp_a")]
        comparables_c = [_make_comparable(game_c, 14.0, "comp_c")]

        call_count = [0]

        def side_effect(**_kwargs: object) -> list[ComparableListing]:
            call_count[0] += 1
            if call_count[0] == 2:  # Second call (game B) fails
                return []
            if call_count[0] == 3:  # Third call (game C)
                return comparables_c
            return comparables_a

        scanner.price_collector.collect_comparables = AsyncMock(side_effect=side_effect)

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
        mock_estimate.estimated_price = Decimal("15.0")
        mock_estimate.confidence_score = 0.80
        mock_estimate.sample_size = 3
        mock_market_estimator.estimate.return_value = mock_estimate

        mock_opportunity = Mock()
        mock_opportunity.recommendation = Recommendation.MAYBE
        mock_opportunity.opportunity_score = 50.0
        mock_lot_analyzer.analyze.return_value = mock_opportunity

        result = await scanner.scan_lot(candidate)

        assert result.successfully_valued_games == 2
        assert result.failed_games == 1
        assert result.is_complete is False
        assert len(result.failures) == 1
        assert result.failures[0].stage == LotPipelineStage.PRICE_COLLECTION
        assert result.analysis_failure is None

    @pytest.mark.asyncio
    async def test_market_estimator_failure(
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
            price=Decimal("20.0"),
            currency="EUR",
            url="https://example.com/fail_est",
        )

        comparables = [_make_comparable(_make_game("A"), 12.0, "comp_1")]
        scanner.price_collector.collect_comparables = AsyncMock(return_value=comparables)

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

        result = await scanner.scan_lot(candidate)

        assert result.successfully_valued_games == 0
        assert result.failed_games == 1
        assert result.failures[0].stage == LotPipelineStage.MARKET_ESTIMATION
        assert "Estimation failed" in (result.failures[0].error_message or "")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("analyzer_error", "expected_error"),
        [
            (RuntimeError("Analyzer crashed"), "RuntimeError: Analyzer crashed"),
            (RuntimeError(), "RuntimeError"),
            (
                ValueError(
                    "No minimum lot net profit threshold configured for currency USD"
                ),
                "ValueError: No minimum lot net profit threshold configured for currency USD",
            ),
            (
                ValueError("No resale absolute costs configured for currency USD"),
                "ValueError: No resale absolute costs configured for currency USD",
            ),
        ],
    )
    async def test_analyzer_failure_preserves_valuations_and_is_structured(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
        analyzer_error: Exception,
        expected_error: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Ordinary analyzer failures are observable without losing valuations."""
        candidate = CandidateListing(
            listing_id="analyzer_fail",
            title="Analyzer fails",
            description="",
            price=Decimal("20.0"),
            currency="EUR",
            url="https://example.com/analyzer_fail",
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

        mock_lot_analyzer.analyze.side_effect = analyzer_error

        result = await scanner.scan_lot(candidate)

        assert result.opportunity is None
        assert len(result.game_valuations) == 1  # Valuations preserved
        assert result.failures == []
        assert result.analysis_failure == FailureInfo(
            listing_id=candidate.listing_id,
            stage=PipelineStage.LOT_ANALYSIS,
            reason="Lot opportunity analysis failed",
            error_message=expected_error,
        )
        assert "Lot analysis failed" in caplog.text
        assert "Traceback" not in (result.analysis_failure.error_message or "")
        assert asdict(result)["analysis_failure"] == asdict(result.analysis_failure)
        assert "analysis_failure=FailureInfo(" in repr(result)
        if not str(analyzer_error):
            assert not expected_error.endswith(": ")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "recommendation",
        [Recommendation.BUY, Recommendation.MAYBE, Recommendation.SKIP],
    )
    async def test_successful_recommendations_are_not_analysis_failures(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
        recommendation: Recommendation,
    ) -> None:
        candidate = CandidateListing(
            "valid-result", "GTA V", "", Decimal("20"), "EUR", "url"
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
        opportunity = mock_lot_analyzer.analyze.return_value
        opportunity.recommendation = recommendation

        result = await scanner.scan_lot(candidate)

        assert result.opportunity is opportunity
        assert result.analysis_failure is None
        assert asdict(result)["analysis_failure"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("base_error", [KeyboardInterrupt(), SystemExit()])
    async def test_analyzer_baseexceptions_propagate(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
        base_error: BaseException,
    ) -> None:
        candidate = CandidateListing(
            "base-error", "Analyzer fails", "", Decimal("20"), "EUR", "url"
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
        mock_lot_analyzer.analyze.side_effect = base_error

        with pytest.raises(type(base_error)):
            await scanner.scan_lot(candidate)

    @pytest.mark.asyncio
    async def test_game_failure_and_analysis_failure_remain_separate(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_lot_analyzer: Mock,
    ) -> None:
        candidate = CandidateListing(
            "combined", "GTA V RDR2", "", Decimal("20"), "EUR", "url"
        )
        valuation = Mock()
        game_failure = GameValuationFailure(
            game=_make_game("RDR2"),
            stage=LotPipelineStage.PRICE_COLLECTION,
            reason="No comparables",
            listing_id=candidate.listing_id,
        )
        scanner._value_game = AsyncMock(  # type: ignore[method-assign]
            side_effect=[(valuation, None), (None, game_failure)]
        )
        mock_lot_analyzer.analyze.side_effect = RuntimeError("analysis boom")

        result = await scanner.scan_lot(candidate)

        assert result.game_valuations == [valuation]
        assert result.failures == [game_failure]
        assert result.analysis_failure is not None
        assert result.analysis_failure.stage is PipelineStage.LOT_ANALYSIS
        assert result.opportunity is None

    @pytest.mark.asyncio
    async def test_empty_detected_games(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_lot_analyzer: Mock,
        mock_price_collector: AsyncMock,
    ) -> None:
        """Empty detected_games should produce safe result."""
        candidate = CandidateListing(
            listing_id="empty",
            title="No games",
            description="",
            price=Decimal("10.0"),
            currency="EUR",
            url="https://example.com/empty",
        )

        mock_opportunity = Mock()
        mock_opportunity.recommendation = Recommendation.SKIP
        mock_lot_analyzer.analyze.return_value = mock_opportunity

        result = await scanner.scan_lot(candidate)

        assert result.total_detected_games == 0
        assert result.successfully_valued_games == 0
        assert result.is_complete is False
        assert result.failures[0].stage is LotPipelineStage.GAME_DETECTION
        assert result.failures[0].listing_id == candidate.listing_id
        assert result.analysis_failure is None
        mock_price_collector.collect_comparables.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_original_detected_games_not_modified(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
        mock_game_detector: Mock,
    ) -> None:
        """detected_games list should not be modified by the scanner."""
        games = [_make_game("A"), _make_game("B")]
        mock_game_detector.detect_games.side_effect = None
        mock_game_detector.detect_games.return_value = games
        candidate = CandidateListing(
            listing_id="immutable",
            title="Immutable test",
            description="",
            price=Decimal("20.0"),
            currency="EUR",
            url="https://example.com/immutable",
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

        result = await scanner.scan_lot(candidate)

        assert result.detected_games == games
        assert mock_game_detector.detect_games.return_value is games

    @pytest.mark.asyncio
    async def test_duplicate_detected_games_are_deduplicated(
        self,
        scanner: DefaultLotOpportunityScanner,
        mock_price_collector: Mock,
        mock_dataset_builder: Mock,
        mock_statistics: Mock,
        mock_outlier_removal: Mock,
        mock_market_estimator: Mock,
        mock_lot_analyzer: Mock,
    ) -> None:
        """Duplicate detector results should be valued once."""
        candidate = CandidateListing(
            listing_id="dup",
            title="Two GTA V copies",
            description="",
            price=Decimal("30.0"),
            currency="EUR",
            url="https://example.com/dup",
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

        result = await scanner.scan_lot(candidate)

        assert result.total_detected_games == 1
        assert result.successfully_valued_games == 1
        assert scanner.price_collector.collect_comparables.await_count == 1


class TestLotScanExplanation:
    @pytest.mark.asyncio
    async def test_explain_includes_required_lot_fields(
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
            price=Decimal("35.0"),
            currency="EUR",
            url="https://example.com/explain_lot",
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

        result = await scanner.scan_lot(candidate)
        explanation = result.explain()

        assert "LOT OPPORTUNITY SCAN" in explanation
        assert "Listing ID: explain_lot" in explanation
        assert "Total Detected Games: 2" in explanation
        assert "Successfully Valued: 2" in explanation
        assert "Failed: 0" in explanation
        assert "Complete: True" in explanation
        assert "Completion Ratio: 100.00%" in explanation
        assert "- GTA V: EUR 13.50" in explanation
        assert "Reference Market Value: EUR 53.00" in explanation
        assert "Lot Price: EUR 35.00" in explanation
        assert "Net Profit: EUR 18.00" in explanation
        assert "Margin: 34.00%" in explanation
        assert "ROI: 51.40%" in explanation
        assert "Confidence: 0.80" in explanation
        assert "Opportunity Score: 85.0/100" in explanation
        assert "Recommendation: BUY" in explanation
        assert "Reason: UNDERVALUED_LOT" in explanation


@pytest.mark.asyncio
async def test_lot_scanner_runs_inside_an_already_active_event_loop(
    scanner: DefaultLotOpportunityScanner,
    mock_price_collector: AsyncMock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_lot_analyzer: Mock,
) -> None:
    _setup_pipeline_mocks(
        scanner,
        mock_price_collector,
        mock_dataset_builder,
        mock_statistics,
        mock_outlier_removal,
        mock_market_estimator,
        mock_lot_analyzer,
        [12.0, 15.0, 18.0],
    )
    candidate = CandidateListing(
        listing_id="active-loop-lot",
        title="GTA V PS4",
        description="",
        price=Decimal("10.0"),
        currency="EUR",
        url="https://example.test/active-loop-lot",
    )

    result = await scanner.scan_lot(candidate)

    assert result.successfully_valued_games == 1
    mock_price_collector.collect_comparables.assert_awaited_once()


@pytest.mark.asyncio
async def test_lot_candidate_is_excluded_from_market_comparables(
    scanner: DefaultLotOpportunityScanner,
    mock_price_collector: AsyncMock,
    mock_dataset_builder: Mock,
) -> None:
    game = _make_game("GTA V")
    candidate = CandidateListing(
        listing_id="candidate-id",
        title="GTA V PS4",
        description="",
        price=Decimal("10.0"),
        currency="EUR",
        url="https://example.test/candidate-id",
    )
    own_listing = _make_comparable(game, 10.0, candidate.listing_id)
    gta_1 = _make_comparable(game, 12.0, "gta-1")
    gta_2 = _make_comparable(game, 15.0, "gta-2")
    mock_price_collector.collect_comparables.return_value = [
        own_listing,
        gta_1,
        gta_2,
    ]
    mock_dataset_builder.build.return_value = Mock(sample_size=0)

    await scanner.scan_lot(candidate)

    mock_dataset_builder.build.assert_called_once_with([gta_1, gta_2], "EUR")


@pytest.mark.asyncio
async def test_lot_game_with_only_foreign_currency_comparables_fails_partially(
    scanner: DefaultLotOpportunityScanner,
    mock_price_collector: AsyncMock,
    mock_dataset_builder: Mock,
    mock_statistics: Mock,
    mock_outlier_removal: Mock,
    mock_market_estimator: Mock,
    mock_lot_analyzer: Mock,
) -> None:
    candidate = CandidateListing(
        "mixed-lot",
        "Lote PS4 GTA V RDR2 Spider-Man",
        "",
        Decimal("35"),
        "EUR",
        "url",
    )
    _setup_pipeline_mocks(
        scanner,
        mock_price_collector,
        mock_dataset_builder,
        mock_statistics,
        mock_outlier_removal,
        mock_market_estimator,
        mock_lot_analyzer,
        comparable_prices=[12, 15, 18],
    )

    async def collect(*, game: DetectedGame, **_kwargs: object) -> list[ComparableListing]:
        currency = "USD" if game.canonical_name == "RDR2" else "EUR"
        return [
            ComparableListing(
                f"{game.canonical_name}-1",
                game.canonical_name,
                "",
                Decimal("20"),
                currency,
                game,
                "url",
            )
        ]

    mock_price_collector.collect_comparables.side_effect = collect
    result = await scanner.scan_lot(candidate)

    assert result.total_detected_games == 3
    assert result.successfully_valued_games == 2
    assert result.failed_games == 1
    assert result.failures[0].game.canonical_name == "RDR2"
    assert "currency EUR" in result.failures[0].reason


def test_lot_game_identity_normalizes_aliases_but_separates_platforms() -> None:
    ps4_aliases = [
        DetectedGame(" Grand  Theft Auto V ", alias, Platform.PS4, 1.0, DetectionMethod.ALIAS_MATCH)
        for alias in ("GTA V", "GTA5", "Grand Theft Auto V")
    ]
    ps5 = _make_game_for_platform("Grand Theft Auto V", Platform.PS5)

    unique = DefaultLotOpportunityScanner._deduplicate_games([*ps4_aliases, ps5])

    assert unique == [ps4_aliases[0], ps5]
