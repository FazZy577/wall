"""Unit tests for lot domain model entities.

Tests CandidateListing, GameValuation, and LotOpportunity.
No external calls. No Playwright. No Wallapop.
"""

from datetime import datetime

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity, LotReasonCode
from domain.interfaces.arbitrage_opportunity_detector import Recommendation
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    MarketPriceEstimate,
    ReasonCode,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(name: str, platform: Platform = Platform.PS4) -> DetectedGame:
    """Create a sample DetectedGame."""
    return DetectedGame(
        canonical_name=name,
        matched_text=name.lower(),
        platform=platform,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def _make_market_estimate(
    game: DetectedGame,
    estimated_price: float = 20.0,
    confidence_score: float = 0.80,
    sample_size: int = 25,
    observations_removed: int = 2,
) -> MarketPriceEstimate:
    """Create a sample MarketPriceEstimate."""
    return MarketPriceEstimate(
        estimated_price=estimated_price,
        currency="EUR",
        confidence_score=confidence_score,
        confidence_level=ConfidenceLevel.HIGH,
        strategy=EstimationStrategy.MEDIAN,
        reason_code=ReasonCode.NORMAL,
        sample_size=sample_size,
        observations_removed=observations_removed,
        outlier_percentage=round(observations_removed / sample_size * 100, 1),
        minimum_price=estimated_price * 0.8,
        maximum_price=estimated_price * 1.2,
        standard_deviation=5.0,
        iqr=7.0,
        coefficient_of_variation=0.25,
        game=game,
        created_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# CandidateListing
# ---------------------------------------------------------------------------


class TestCandidateListing:
    """Test CandidateListing entity."""

    def test_single_game_candidate(self) -> None:
        """Should create candidate with one game."""
        game = _make_game("GTA V")
        candidate = CandidateListing(
            listing_id="lst001",
            title="GTA V PS4",
            description="Good condition",
            price=15.0,
            currency="EUR",
            url="https://example.com/lst001",
            detected_games=[game],
        )

        assert candidate.listing_id == "lst001"
        assert candidate.price == 15.0
        assert candidate.is_lot is False
        assert candidate.game_count == 1

    def test_lot_with_three_games(self) -> None:
        """Should create lot candidate with three games."""
        games = [
            _make_game("GTA V"),
            _make_game("RDR2"),
            _make_game("Spider-Man"),
        ]
        candidate = CandidateListing(
            listing_id="lot001",
            title="Lote PS4 GTA V RDR2 Spider-Man",
            description="Bundle of 3 games",
            price=40.0,
            currency="EUR",
            url="https://example.com/lot001",
            detected_games=games,
        )

        assert candidate.is_lot is True
        assert candidate.game_count == 3

    def test_empty_games_is_not_lot(self) -> None:
        """Empty games list should not be a lot."""
        candidate = CandidateListing(
            listing_id="empty001",
            title="Unknown",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/empty001",
        )

        assert candidate.is_lot is False
        assert candidate.game_count == 0

    def test_two_games_is_lot(self) -> None:
        """Two games is already a lot."""
        candidate = CandidateListing(
            listing_id="lot2",
            title="2 games",
            description="",
            price=25.0,
            currency="EUR",
            url="https://example.com/lot2",
            detected_games=[_make_game("GTA V"), _make_game("RDR2")],
        )

        assert candidate.is_lot is True
        assert candidate.game_count == 2

    def test_empty_listing_id_raises(self) -> None:
        """Should raise for empty listing_id."""
        with pytest.raises(ValueError, match="listing_id"):
            CandidateListing(
                listing_id="",
                title="Test",
                description="",
                price=10.0,
                currency="EUR",
                url="https://example.com/test",
            )

    def test_empty_title_raises(self) -> None:
        """Should raise for empty title."""
        with pytest.raises(ValueError, match="title"):
            CandidateListing(
                listing_id="test",
                title="",
                description="",
                price=10.0,
                currency="EUR",
                url="https://example.com/test",
            )

    def test_negative_price_raises(self) -> None:
        """Should raise for negative price."""
        with pytest.raises(ValueError, match="price"):
            CandidateListing(
                listing_id="test",
                title="Test",
                description="",
                price=-5.0,
                currency="EUR",
                url="https://example.com/test",
            )

    def test_zero_price_is_valid(self) -> None:
        """Zero price should be valid (free listings)."""
        candidate = CandidateListing(
            listing_id="test",
            title="Free Game",
            description="",
            price=0.0,
            currency="EUR",
            url="https://example.com/test",
        )
        assert candidate.price == 0.0

    def test_empty_currency_raises(self) -> None:
        """Should raise for empty currency."""
        with pytest.raises(ValueError, match="currency"):
            CandidateListing(
                listing_id="test",
                title="Test",
                description="",
                price=10.0,
                currency="",
                url="https://example.com/test",
            )

    def test_raw_listing_immutable_from_outside(self) -> None:
        """raw_listing is a dict; the entity stores the reference but
        does not modify it. The caller should not mutate it after passing."""
        raw = {"id": "123", "price": {"amount": 40}}
        candidate = CandidateListing(
            listing_id="test",
            title="Test",
            description="",
            price=40.0,
            currency="EUR",
            url="https://example.com/test",
            raw_listing=raw,
        )

        # The entity stores the reference
        assert candidate.raw_listing is raw
        assert candidate.raw_listing["id"] == "123"

    def test_optional_fields_default_to_none(self) -> None:
        """published_at and seller_id should default to None."""
        candidate = CandidateListing(
            listing_id="test",
            title="Test",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/test",
        )

        assert candidate.published_at is None
        assert candidate.seller_id is None

    def test_optional_fields_can_be_set(self) -> None:
        """published_at and seller_id can be explicitly set."""
        now = datetime.now()
        candidate = CandidateListing(
            listing_id="test",
            title="Test",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/test",
            published_at=now,
            seller_id="seller123",
        )

        assert candidate.published_at == now
        assert candidate.seller_id == "seller123"


# ---------------------------------------------------------------------------
# GameValuation
# ---------------------------------------------------------------------------


class TestGameValuation:
    """Test GameValuation entity."""

    def test_from_market_estimate(self) -> None:
        """Should propagate values from MarketPriceEstimate."""
        game = _make_game("GTA V")
        estimate = _make_market_estimate(game, estimated_price=15.0, confidence_score=0.85)

        valuation = GameValuation.from_market_estimate(
            game=game,
            estimate=estimate,
            observations_removed=2,
        )

        assert valuation.game == game
        assert valuation.estimated_market_value == 15.0
        assert valuation.confidence_score == 0.85
        assert valuation.observations_used == 25
        assert valuation.observations_removed == 2
        assert isinstance(valuation.created_at, datetime)

    def test_estimated_market_value_matches_estimate(self) -> None:
        """estimated_market_value should equal estimate.estimated_price."""
        game = _make_game("RDR2")
        estimate = _make_market_estimate(game, estimated_price=20.0)

        valuation = GameValuation.from_market_estimate(game, estimate)

        assert valuation.estimated_market_value == estimate.estimated_price

    def test_confidence_score_propagated(self) -> None:
        """confidence_score should match the estimate."""
        game = _make_game("Spider-Man")
        estimate = _make_market_estimate(game, confidence_score=0.72)

        valuation = GameValuation.from_market_estimate(game, estimate)

        assert valuation.confidence_score == 0.72

    def test_observations_used_matches_sample_size(self) -> None:
        """observations_used should match sample_size after outlier removal."""
        game = _make_game("FIFA")
        estimate = _make_market_estimate(game, sample_size=30)

        valuation = GameValuation.from_market_estimate(game, estimate)

        assert valuation.observations_used == 30

    def test_observations_removed_defaults_to_zero(self) -> None:
        """observations_removed should default to 0."""
        game = _make_game("NBA")
        estimate = _make_market_estimate(game)

        valuation = GameValuation.from_market_estimate(game, estimate)

        assert valuation.observations_removed == 0


# ---------------------------------------------------------------------------
# LotOpportunity
# ---------------------------------------------------------------------------


class TestLotOpportunity:
    """Test LotOpportunity entity and calculations."""

    def _make_valuation(
        self, name: str, estimated_price: float, confidence_score: float = 0.80
    ) -> GameValuation:
        """Helper to create a GameValuation."""
        game = _make_game(name)
        estimate = _make_market_estimate(
            game, estimated_price=estimated_price, confidence_score=confidence_score
        )
        return GameValuation.from_market_estimate(game, estimate)

    def test_lot_with_three_games(self) -> None:
        """Canonical lot example: GTA V + RDR2 + Spider-Man at 40 EUR."""
        candidate = CandidateListing(
            listing_id="lot001",
            title="Lote PS4 GTA V RDR2 Spider-Man",
            description="Bundle of 3 games",
            price=40.0,
            currency="EUR",
            url="https://example.com/lot001",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        valuations = [
            self._make_valuation("GTA V", estimated_price=15.0, confidence_score=0.85),
            self._make_valuation("RDR2", estimated_price=20.0, confidence_score=0.90),
            self._make_valuation("Spider-Man", estimated_price=18.0, confidence_score=0.80),
        ]

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=valuations,
            recommendation=Recommendation.BUY,
            reason=LotReasonCode.UNDERVALUED_LOT,
            opportunity_score=85.0,
        )

        # total_market_value = 15 + 20 + 18 = 53
        assert lot.total_market_value == 53.0
        assert lot.lot_price == 40.0
        # estimated_profit = 53 - 40 = 13
        assert lot.estimated_profit == 13.0
        # profit_margin = 13 / 53 * 100 = 24.5283... ≈ 24.5
        assert lot.profit_margin_percentage == 24.5
        # roi = 13 / 40 * 100 = 32.5
        assert lot.roi_percentage == 32.5
        # aggregate_confidence = (0.85 + 0.90 + 0.80) / 3 = 0.85
        assert lot.aggregate_confidence_score == 0.85

    def test_overpriced_lot(self) -> None:
        """Lot priced above total market value."""
        candidate = CandidateListing(
            listing_id="overpriced",
            title="Overpriced Lot",
            description="",
            price=100.0,
            currency="EUR",
            url="https://example.com/overpriced",
            detected_games=[_make_game("GTA V"), _make_game("FIFA")],
        )

        valuations = [
            self._make_valuation("GTA V", estimated_price=15.0),
            self._make_valuation("FIFA", estimated_price=10.0),
        ]

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=valuations,
            recommendation=Recommendation.SKIP,
            reason=LotReasonCode.OVERPRICED_LOT,
            opportunity_score=10.0,
        )

        assert lot.total_market_value == 25.0
        assert lot.estimated_profit == -75.0
        assert lot.profit_margin_percentage == -300.0
        assert lot.roi_percentage == -75.0

    def test_low_aggregate_confidence(self) -> None:
        """Low confidence should result in lower aggregate."""
        candidate = CandidateListing(
            listing_id="lowconf",
            title="Low confidence lot",
            description="",
            price=30.0,
            currency="EUR",
            url="https://example.com/lowconf",
            detected_games=[_make_game("GTA V"), _make_game("RDR2")],
        )

        valuations = [
            self._make_valuation("GTA V", estimated_price=20.0, confidence_score=0.35),
            self._make_valuation("RDR2", estimated_price=20.0, confidence_score=0.25),
        ]

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=valuations,
            recommendation=Recommendation.SKIP,
            reason=LotReasonCode.LOW_AGGREGATE_CONFIDENCE,
            opportunity_score=20.0,
        )

        assert lot.aggregate_confidence_score == 0.3
        assert lot.total_market_value == 40.0
        assert lot.estimated_profit == 10.0

    def test_no_games_detected(self) -> None:
        """Lot with no detected games."""
        candidate = CandidateListing(
            listing_id="nogames",
            title="Unknown bundle",
            description="",
            price=20.0,
            currency="EUR",
            url="https://example.com/nogames",
        )

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=[],
            recommendation=Recommendation.SKIP,
            reason=LotReasonCode.NO_GAMES_DETECTED,
            opportunity_score=0.0,
        )

        assert lot.total_market_value == 0.0
        assert lot.estimated_profit == -20.0
        assert lot.profit_margin_percentage == 0.0
        assert lot.roi_percentage == -100.0
        assert lot.aggregate_confidence_score == 0.0

    def test_zero_lot_price(self) -> None:
        """Free lot should have infinite ROI edge case."""
        candidate = CandidateListing(
            listing_id="free",
            title="Free games",
            description="",
            price=0.0,
            currency="EUR",
            url="https://example.com/free",
            detected_games=[_make_game("GTA V")],
        )

        valuations = [
            self._make_valuation("GTA V", estimated_price=15.0),
        ]

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=valuations,
            recommendation=Recommendation.SKIP,
            reason=LotReasonCode.INVALID_LOT_PRICE,
            opportunity_score=0.0,
        )

        assert lot.lot_price == 0.0
        assert lot.total_market_value == 15.0
        assert lot.estimated_profit == 15.0
        # roi = 15 / 0 → edge case → 0.0
        assert lot.roi_percentage == 0.0
        assert lot.profit_margin_percentage == 100.0

    def test_incomplete_valuation(self) -> None:
        """Some games not yet valued."""
        candidate = CandidateListing(
            listing_id="incomplete",
            title="Partial lot",
            description="",
            price=30.0,
            currency="EUR",
            url="https://example.com/incomplete",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        # Only 2 of 3 games valued
        valuations = [
            self._make_valuation("GTA V", estimated_price=15.0),
            self._make_valuation("RDR2", estimated_price=20.0),
        ]

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=valuations,
            recommendation=Recommendation.MAYBE,
            reason=LotReasonCode.INCOMPLETE_VALUATION,
            opportunity_score=40.0,
        )

        assert lot.total_market_value == 35.0
        assert lot.estimated_profit == 5.0

    def test_aggregate_confidence_arithmetic_mean(self) -> None:
        """Should use arithmetic mean for aggregate confidence."""
        candidate = CandidateListing(
            listing_id="mean_test",
            title="Confidence test",
            description="",
            price=50.0,
            currency="EUR",
            url="https://example.com/test",
            detected_games=[_make_game("A"), _make_game("B"), _make_game("C"), _make_game("D")],
        )

        valuations = [
            self._make_valuation("A", estimated_price=20.0, confidence_score=1.0),
            self._make_valuation("B", estimated_price=20.0, confidence_score=0.5),
            self._make_valuation("C", estimated_price=20.0, confidence_score=0.5),
            self._make_valuation("D", estimated_price=20.0, confidence_score=0.0),
        ]

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=valuations,
            recommendation=Recommendation.MAYBE,
            reason=LotReasonCode.LOW_AGGREGATE_CONFIDENCE,
            opportunity_score=50.0,
        )

        # (1.0 + 0.5 + 0.5 + 0.0) / 4 = 0.5
        assert lot.aggregate_confidence_score == 0.5

    def test_market_value_zero_edge_case(self) -> None:
        """Zero market value should not divide by zero."""
        candidate = CandidateListing(
            listing_id="zero_market",
            title="Worthless",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/zero",
            detected_games=[_make_game("Bad Game")],
        )

        valuations = [
            self._make_valuation("Bad Game", estimated_price=0.0),
        ]

        lot = LotOpportunity.from_valuations(
            listing=candidate,
            game_valuations=valuations,
            recommendation=Recommendation.SKIP,
            reason=LotReasonCode.OVERPRICED_LOT,
            opportunity_score=5.0,
        )

        assert lot.total_market_value == 0.0
        assert lot.profit_margin_percentage == 0.0  # Not NaN
        assert lot.roi_percentage == -100.0

    def test_all_reason_codes_exist(self) -> None:
        """All LotReasonCode values should be defined."""
        codes = [
            LotReasonCode.UNDERVALUED_LOT,
            LotReasonCode.FAIR_VALUE_LOT,
            LotReasonCode.OVERPRICED_LOT,
            LotReasonCode.LOW_AGGREGATE_CONFIDENCE,
            LotReasonCode.INCOMPLETE_VALUATION,
            LotReasonCode.NO_GAMES_DETECTED,
            LotReasonCode.INVALID_LOT_PRICE,
        ]
        assert len(codes) == 7


# ---------------------------------------------------------------------------
# Dataset contamination regression test
# ---------------------------------------------------------------------------


class TestDatasetContamination:
    """Test that candidate listing does NOT contaminate price dataset."""

    def test_candidate_not_in_dataset_scan_listing(
        self,
    ) -> None:
        """scan_listing should build dataset from comparables only, not candidate."""
        from unittest.mock import Mock

        from infrastructure.scanners.default_opportunity_scanner import (
            DefaultOpportunityScanner,
        )

        # Setup
        game = _make_game("GTA V")
        from domain.interfaces.price_collector import ComparableListing

        candidate = ComparableListing(
            listing_id="candidate001",
            title="GTA V PS4 - Candidate",
            description="",
            price=40.0,  # This is the candidate price - should NOT be in dataset
            currency="EUR",
            detected_game=game,
            url="https://example.com/candidate001",
        )

        comparables = [
            ComparableListing(
                listing_id=f"comp{i}",
                title=f"GTA V PS4 {i}",
                description="",
                price=12.0 + i * 3,
                currency="EUR",
                detected_game=game,
                url=f"https://example.com/comp{i}",
            )
            for i in range(5)
        ]

        # Scanner with mocks
        scanner = DefaultOpportunityScanner(
            game_detector=Mock(),
            price_collector=Mock(),
            dataset_builder=Mock(),
            statistics=Mock(),
            outlier_removal=Mock(),
            market_estimator=Mock(),
            arbitrage_detector=Mock(),
        )
        scanner._run_async = Mock(return_value=comparables)

        # Capture what is passed to dataset_builder.build()
        captured_listings: list = []

        def capture_build(listings: list[object]) -> Mock:
            captured_listings.extend(listings)
            m = Mock()
            m.sample_size = 5
            return m

        scanner.dataset_builder.build.side_effect = capture_build

        # Setup remaining mocks for success
        scanner.statistics.calculate.return_value = Mock()
        mock_outlier = Mock()
        mock_outlier.removed_count = 1
        mock_outlier.clean_dataset = Mock()
        scanner.outlier_removal.remove_outliers.return_value = mock_outlier
        scanner.market_estimator.estimate.return_value = Mock()
        mock_opp = Mock()
        mock_opp.recommendation = "BUY"
        mock_opp.opportunity_score = 75.0
        scanner.arbitrage_detector.detect.return_value = mock_opp

        scanner.scan_listing(candidate)

        # Verify: candidate price (40.0) should NOT be in the dataset
        prices_in_dataset = [
            getattr(lst, "price", None) for lst in captured_listings
        ]
        assert 40.0 not in prices_in_dataset, (
            f"Candidate price 40.0 found in dataset! Prices: {prices_in_dataset}"
        )
        # Only comparable prices should be present
        assert len(captured_listings) == 5

    def test_candidate_not_in_dataset_small_sample(
        self,
    ) -> None:
        """Small sample: outlier removal should not hide the contamination."""
        from unittest.mock import Mock

        from infrastructure.scanners.default_opportunity_scanner import (
            DefaultOpportunityScanner,
        )

        game = _make_game("GTA V")
        from domain.interfaces.price_collector import ComparableListing

        candidate = ComparableListing(
            listing_id="candidate002",
            title="GTA V PS4 - Candidate",
            description="",
            price=40.0,  # Candidate price - should NOT be in dataset
            currency="EUR",
            detected_game=game,
            url="https://example.com/candidate002",
        )

        # Only 3 comparables - small sample where outlier removal matters
        comparables = [
            ComparableListing(
                listing_id=f"comp{i}",
                title=f"GTA V PS4 {i}",
                description="",
                price=12.0 + i * 3,
                currency="EUR",
                detected_game=game,
                url=f"https://example.com/comp{i}",
            )
            for i in range(3)
        ]

        scanner = DefaultOpportunityScanner(
            game_detector=Mock(),
            price_collector=Mock(),
            dataset_builder=Mock(),
            statistics=Mock(),
            outlier_removal=Mock(),
            market_estimator=Mock(),
            arbitrage_detector=Mock(),
        )
        scanner._run_async = Mock(return_value=comparables)

        captured_listings: list = []

        def capture_build(listings: list[object]) -> Mock:
            captured_listings.extend(listings)
            m = Mock()
            m.sample_size = len(listings)
            return m

        scanner.dataset_builder.build.side_effect = capture_build
        scanner.statistics.calculate.return_value = Mock()
        mock_outlier = Mock()
        mock_outlier.removed_count = 0
        mock_outlier.clean_dataset = Mock()
        scanner.outlier_removal.remove_outliers.return_value = mock_outlier
        scanner.market_estimator.estimate.return_value = Mock()
        mock_opp = Mock()
        mock_opp.recommendation = "BUY"
        mock_opp.opportunity_score = 75.0
        scanner.arbitrage_detector.detect.return_value = mock_opp

        scanner.scan_listing(candidate)

        prices_in_dataset = [
            getattr(lst, "price", None) for lst in captured_listings
        ]
        assert 40.0 not in prices_in_dataset, (
            f"Candidate price 40.0 found in small dataset! "
            f"Prices: {prices_in_dataset}"
        )
        assert len(captured_listings) == 3
