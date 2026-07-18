"""Unit tests for DefaultLotOpportunityAnalyzer.

Tests decision rules, opportunity score calculation, and edge cases.
No external calls. No Playwright. No Wallapop.
"""

from datetime import datetime

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotReasonCode
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
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
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


def _make_estimate(
    game: DetectedGame,
    estimated_price: float,
    confidence_score: float = 0.80,
    sample_size: int = 25,
) -> MarketPriceEstimate:
    return MarketPriceEstimate(
        estimated_price=estimated_price,
        currency="EUR",
        confidence_score=confidence_score,
        confidence_level=ConfidenceLevel.HIGH,
        strategy=EstimationStrategy.MEDIAN,
        reason_code=ReasonCode.NORMAL,
        sample_size=sample_size,
        observations_removed=2,
        outlier_percentage=8.0,
        minimum_price=estimated_price * 0.8,
        maximum_price=estimated_price * 1.2,
        standard_deviation=5.0,
        iqr=7.0,
        coefficient_of_variation=0.25,
        game=game,
        created_at=datetime.now(),
    )


def _make_valuation(
    name: str, estimated_price: float, confidence_score: float = 0.80
) -> GameValuation:
    game = _make_game(name)
    estimate = _make_estimate(game, estimated_price, confidence_score)
    return GameValuation.from_market_estimate(game, estimate)


@pytest.fixture
def analyzer() -> DefaultLotOpportunityAnalyzer:
    return DefaultLotOpportunityAnalyzer()


# ---------------------------------------------------------------------------
# Clear BUY
# ---------------------------------------------------------------------------


class TestBuyRecommendation:
    def test_clear_buy_lot(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """35€ lot with 53€ market value → BUY."""
        candidate = CandidateListing(
            listing_id="lot001",
            title="Lote PS4 GTA V RDR2 Spider-Man",
            description="",
            price=35.0,
            currency="EUR",
            url="https://example.com/lot001",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        valuations = [
            _make_valuation("GTA V", 15.0, 0.80),
            _make_valuation("RDR2", 20.0, 0.90),
            _make_valuation("Spider-Man", 18.0, 0.70),
        ]

        lot = analyzer.analyze(candidate, valuations, 3)

        # total_market_value = 53, profit = 18, margin = 33.96%
        assert lot.total_market_value == 53.0
        assert lot.estimated_profit == 18.0
        assert lot.profit_margin_percentage == 34.0  # 18/53*100 = 33.96... → 34.0
        assert lot.roi_percentage == 51.4  # 18/35*100 = 51.4
        assert lot.recommendation == Recommendation.BUY
        assert lot.reason == LotReasonCode.UNDERVALUED_LOT


# ---------------------------------------------------------------------------
# Margin below threshold → MAYBE
# ---------------------------------------------------------------------------


class TestMarginThreshold:
    def test_margin_below_threshold_returns_maybe(
        self, analyzer: DefaultLotOpportunityAnalyzer
    ) -> None:
        """40€ lot with 53€ market value → margin 24.5% < 25% → MAYBE."""
        candidate = CandidateListing(
            listing_id="lot002",
            title="Lote PS4 GTA V RDR2 Spider-Man",
            description="",
            price=40.0,
            currency="EUR",
            url="https://example.com/lot002",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        valuations = [
            _make_valuation("GTA V", 15.0, 0.80),
            _make_valuation("RDR2", 20.0, 0.90),
            _make_valuation("Spider-Man", 18.0, 0.70),
        ]

        lot = analyzer.analyze(candidate, valuations, 3)

        # total_market_value = 53, profit = 13, margin = 24.5%
        assert lot.total_market_value == 53.0
        assert lot.estimated_profit == 13.0
        assert lot.profit_margin_percentage == 24.5  # 13/53*100 = 24.5283... → 24.5
        assert lot.recommendation == Recommendation.MAYBE
        assert lot.reason == LotReasonCode.FAIR_VALUE_LOT


# ---------------------------------------------------------------------------
# Overpriced → SKIP
# ---------------------------------------------------------------------------


class TestOverpriced:
    def test_overpriced_lot(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """100€ lot with 25€ market value → SKIP."""
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
            _make_valuation("GTA V", 15.0),
            _make_valuation("FIFA", 10.0),
        ]

        lot = analyzer.analyze(candidate, valuations, 2)

        assert lot.total_market_value == 25.0
        assert lot.estimated_profit == -75.0
        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.OVERPRICED_LOT

    def test_fair_value_exact(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Price exactly equals market value → SKIP/FAIR_VALUE_LOT."""
        candidate = CandidateListing(
            listing_id="fair",
            title="Fair Value Lot",
            description="",
            price=35.0,
            currency="EUR",
            url="https://example.com/fair",
            detected_games=[_make_game("GTA V"), _make_game("RDR2")],
        )

        valuations = [
            _make_valuation("GTA V", 15.0),
            _make_valuation("RDR2", 20.0),
        ]

        lot = analyzer.analyze(candidate, valuations, 2)

        assert lot.total_market_value == 35.0
        assert lot.estimated_profit == 0.0
        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.FAIR_VALUE_LOT


# ---------------------------------------------------------------------------
# Low confidence
# ---------------------------------------------------------------------------


class TestLowConfidence:
    def test_low_aggregate_confidence(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Confidence 0.30 < 0.50 → SKIP."""
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
            _make_valuation("GTA V", 20.0, 0.35),
            _make_valuation("RDR2", 20.0, 0.25),
        ]

        lot = analyzer.analyze(candidate, valuations, 2)

        assert lot.aggregate_confidence_score == 0.3
        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.LOW_AGGREGATE_CONFIDENCE


# ---------------------------------------------------------------------------
# Incomplete valuation
# ---------------------------------------------------------------------------


class TestIncompleteValuation:
    def test_incomplete_positive_profit(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """2 of 3 valued, known profit positive → MAYBE."""
        candidate = CandidateListing(
            listing_id="incomplete",
            title="Partial lot",
            description="",
            price=30.0,
            currency="EUR",
            url="https://example.com/incomplete",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        valuations = [
            _make_valuation("GTA V", 15.0),
            _make_valuation("RDR2", 20.0),
        ]

        lot = analyzer.analyze(candidate, valuations, 3)

        # Only 2 of 3 valued, known profit = 35 - 30 = 5 > 0
        assert lot.recommendation == Recommendation.MAYBE
        assert lot.reason == LotReasonCode.INCOMPLETE_VALUATION

    def test_incomplete_negative_profit(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """2 of 3 valued, known profit negative → SKIP."""
        candidate = CandidateListing(
            listing_id="incomplete_neg",
            title="Bad partial lot",
            description="",
            price=50.0,
            currency="EUR",
            url="https://example.com/incomplete_neg",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        valuations = [
            _make_valuation("GTA V", 15.0),
            _make_valuation("RDR2", 20.0),
        ]

        lot = analyzer.analyze(candidate, valuations, 3)

        # Known profit = 35 - 50 = -15 < 0
        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.INCOMPLETE_VALUATION

    def test_no_valuations(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """No games valued → SKIP/INCOMPLETE_VALUATION."""
        candidate = CandidateListing(
            listing_id="no_vals",
            title="Failed lot",
            description="",
            price=30.0,
            currency="EUR",
            url="https://example.com/no_vals",
            detected_games=[_make_game("GTA V"), _make_game("RDR2")],
        )

        lot = analyzer.analyze(candidate, [], 2)

        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.INCOMPLETE_VALUATION


# ---------------------------------------------------------------------------
# No games / invalid price
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_games_detected(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Empty detected_games → SKIP/NO_GAMES_DETECTED."""
        candidate = CandidateListing(
            listing_id="nogames",
            title="Unknown",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/nogames",
        )

        lot = analyzer.analyze(candidate, [], 0)

        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.NO_GAMES_DETECTED

    def test_zero_price(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Price 0 → SKIP/INVALID_LOT_PRICE."""
        candidate = CandidateListing(
            listing_id="free",
            title="Free games",
            description="",
            price=0.0,
            currency="EUR",
            url="https://example.com/free",
            detected_games=[_make_game("GTA V")],
        )

        valuations = [_make_valuation("GTA V", 15.0)]

        lot = analyzer.analyze(candidate, valuations, 1)

        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.INVALID_LOT_PRICE


# ---------------------------------------------------------------------------
# Opportunity score
# ---------------------------------------------------------------------------


class TestOpportunityScore:
    def test_score_in_range(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Score should be between 0 and 100."""
        candidate = CandidateListing(
            listing_id="score_test",
            title="Score test",
            description="",
            price=35.0,
            currency="EUR",
            url="https://example.com/score",
            detected_games=[_make_game("GTA V"), _make_game("RDR2"), _make_game("Spider-Man")],
        )

        valuations = [
            _make_valuation("GTA V", 15.0, 0.80),
            _make_valuation("RDR2", 20.0, 0.90),
            _make_valuation("Spider-Man", 18.0, 0.70),
        ]

        lot = analyzer.analyze(candidate, valuations, 3)

        assert 0.0 <= lot.opportunity_score <= 100.0

    def test_score_does_not_override_safety(
        self, analyzer: DefaultLotOpportunityAnalyzer
    ) -> None:
        """Incomplete valuation should never be BUY even with high score."""
        candidate = CandidateListing(
            listing_id="incomplete_high_score",
            title="Incomplete but high score",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/incomplete",
            detected_games=[_make_game("A"), _make_game("B"), _make_game("C")],
        )

        # Only 1 of 3 valued, but very profitable
        valuations = [_make_valuation("A", 50.0, 1.0)]

        lot = analyzer.analyze(candidate, valuations, 3)

        # Must NOT be BUY — incomplete
        assert lot.recommendation != Recommendation.BUY
        assert lot.reason == LotReasonCode.INCOMPLETE_VALUATION

    def test_low_confidence_not_buy_despite_score(
        self, analyzer: DefaultLotOpportunityAnalyzer
    ) -> None:
        """Low confidence should block BUY regardless of score."""
        candidate = CandidateListing(
            listing_id="lowconf_buy",
            title="Low confidence",
            description="",
            price=10.0,
            currency="EUR",
            url="https://example.com/lowconf",
            detected_games=[_make_game("A"), _make_game("B")],
        )

        # Very profitable but low confidence
        valuations = [
            _make_valuation("A", 30.0, 0.30),
            _make_valuation("B", 30.0, 0.30),
        ]

        lot = analyzer.analyze(candidate, valuations, 2)

        # Must NOT be BUY — low confidence
        assert lot.recommendation != Recommendation.BUY
        assert lot.reason == LotReasonCode.LOW_AGGREGATE_CONFIDENCE
