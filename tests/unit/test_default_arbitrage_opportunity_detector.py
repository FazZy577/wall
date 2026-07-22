"""Unit tests for DefaultArbitrageOpportunityDetector.

Tests arbitrage opportunity detection with various scenarios.
"""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.arbitrage_opportunity_detector import (
    ReasonCode,
    Recommendation,
)
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    MarketPriceEstimate,
)
from domain.interfaces.market_price_estimator import (
    ReasonCode as EstimateReasonCode,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)


@pytest.fixture
def detector() -> DefaultArbitrageOpportunityDetector:
    """Create detector with default thresholds."""
    return DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral())


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
    """Create sample listing."""
    return CandidateListing(
        listing_id="test123",
        title="GTA V PS4",
        description="Great condition",
        price=12.0,
        currency="EUR",
        url="https://wallapop.com/item/test123",
    )


def create_market_estimate(
    game: DetectedGame,
    estimated_price: float,
    confidence_score: float,
    confidence_level: ConfidenceLevel,
) -> MarketPriceEstimate:
    """Helper to create market estimate."""
    return MarketPriceEstimate(
        estimated_price=estimated_price,
        currency="EUR",
        confidence_score=confidence_score,
        confidence_level=confidence_level,
        strategy=EstimationStrategy.MEDIAN,
        reason_code=EstimateReasonCode.NORMAL,
        sample_size=20,
        observations_removed=2,
        outlier_percentage=10.0,
        minimum_price=10.0,
        maximum_price=25.0,
        standard_deviation=3.5,
        iqr=5.0,
        coefficient_of_variation=0.15,
        game=game,
        created_at=datetime.now(UTC),
    )


class TestNewFields:
    """Test new fields: acquisition_discount_to_reference_market_percentage and break_even_sale_revenue."""

    def test_required_net_economic_case(self, sample_game: DetectedGame) -> None:
        listing = CandidateListing("economic", "GTA V", "", 10.0, "EUR", "url")
        estimate = create_market_estimate(
            sample_game, 20.0, 0.8, ConfidenceLevel.HIGH
        )
        configured_policy = ResaleEconomicPolicy(3.0, 0.10, 1.0, 2.0, 0.05)
        breakdown = configured_policy.calculate([20.0], 10.0)
        policy = Mock(spec=ResaleEconomicPolicy)
        policy.calculate.return_value = breakdown

        result = DefaultArbitrageOpportunityDetector(policy).detect(listing, estimate)

        policy.calculate.assert_called_once_with(
            reference_item_prices=[20.0], acquisition_price=10.0
        )
        assert result.economic_breakdown is breakdown
        assert result.economic_breakdown.net_profit == pytest.approx(1.45)
        assert result.net_profit == pytest.approx(1.45)
        assert result.net_roi_percentage == pytest.approx(1.45 / 12 * 100)
        assert result.net_profit_margin_percentage == pytest.approx(1.45 / 17 * 100)
        assert result.acquisition_discount_to_reference_market_percentage == 50.0
        assert result.break_even_sale_revenue == pytest.approx(13 / 0.85)

    def test_cost_policy_can_legitimately_lower_recommendation(
        self, sample_game: DetectedGame
    ) -> None:
        listing = CandidateListing("same", "GTA V", "", 5.0, "EUR", "url")
        estimate = create_market_estimate(
            sample_game, 30.0, 0.8, ConfidenceLevel.HIGH
        )
        neutral = DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral())
        costly = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy(10.0, 0.20, 2.0, 5.0, 0.10)
        )

        neutral_result = neutral.detect(listing, estimate)
        costly_result = costly.detect(listing, estimate)

        assert neutral_result.market_price == costly_result.market_price == 30.0
        assert neutral_result.listing is costly_result.listing is listing
        assert neutral_result.recommendation is Recommendation.BUY
        assert costly_result.recommendation is Recommendation.MAYBE
        assert costly_result.opportunity_score < neutral_result.opportunity_score

    def test_acquisition_discount_to_reference_market_percentage_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate market discount correctly."""
        # Market: 40в‚¬, Listing: 20в‚¬ в†’ 50% discount
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=20.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=40.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        # (40 - 20) / 40 * 100 = 50%
        assert result.acquisition_discount_to_reference_market_percentage == 50.0

    def test_break_even_sale_revenue_equals_listing_price(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should set break_even_sale_revenue equal to listing_price."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=22.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.break_even_sale_revenue == result.listing_price
        assert result.break_even_sale_revenue == 12.0

    def test_opportunity_score_range(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate opportunity_score in range 0-100."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=22.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert 0.0 <= result.opportunity_score <= 100.0

    def test_opportunity_score_excellent_deal(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should give high score to excellent deals."""
        # Market: 40в‚¬, Listing: 10в‚¬ в†’ 75% margin, 30в‚¬ profit, ROI 300%
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=10.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=40.0,
            confidence_score=0.95,
            confidence_level=ConfidenceLevel.VERY_HIGH,
        )

        result = detector.detect(listing, market_estimate)

        # Should be a very high score
        assert result.opportunity_score >= 85.0
        assert result.recommendation == Recommendation.BUY

    def test_opportunity_score_poor_deal(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should give low score to poor deals."""
        # Overpriced listing
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=30.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=20.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        # Negative profit should give score of 0
        assert result.opportunity_score == 0.0
        assert result.recommendation == Recommendation.SKIP

    def test_opportunity_score_ordering(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should rank better deals with higher scores."""
        # Deal 1: Good (Market: 30в‚¬, Listing: 15в‚¬ в†’ 50% margin, 15в‚¬ profit)
        listing1 = CandidateListing(
            listing_id="deal1",
            title="GTA V PS4 - Good Deal",
            description="",
            price=15.0,
            currency="EUR",
            url="https://wallapop.com/item/deal1",
        )

        # Deal 2: Excellent (Market: 40в‚¬, Listing: 10в‚¬ в†’ 75% margin, 30в‚¬ profit)
        listing2 = CandidateListing(
            listing_id="deal2",
            title="GTA V PS4 - Excellent Deal",
            description="",
            price=10.0,
            currency="EUR",
            url="https://wallapop.com/item/deal2",
        )

        estimate1 = create_market_estimate(sample_game, 30.0, 0.80, ConfidenceLevel.HIGH)
        estimate2 = create_market_estimate(sample_game, 40.0, 0.85, ConfidenceLevel.HIGH)

        result1 = detector.detect(listing1, estimate1)
        result2 = detector.detect(listing2, estimate2)

        # Both should be BUY
        assert result1.recommendation == Recommendation.BUY
        assert result2.recommendation == Recommendation.BUY

        # But deal 2 should have higher score
        assert result2.opportunity_score > result1.opportunity_score


class TestBuyRecommendation:
    """Test BUY recommendation scenarios."""

    def test_clear_buy_opportunity(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should recommend BUY when all criteria are met."""
        # Listing: 12в‚¬, Market: 22в‚¬, Profit: 10в‚¬, Margin: 45%, Confidence: 0.80
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=22.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.recommendation == Recommendation.BUY
        assert result.reason == ReasonCode.UNDERVALUED
        assert result.net_profit == 10.0
        assert result.net_profit_margin_percentage == pytest.approx(45.45, abs=0.1)
        assert result.confidence_score == 0.80

    def test_high_profit_buy(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should recommend BUY for high profit margins."""
        # Listing: 12в‚¬, Market: 30в‚¬, Profit: 18в‚¬, Margin: 60%
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=30.0,
            confidence_score=0.75,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.recommendation == Recommendation.BUY
        assert result.reason == ReasonCode.UNDERVALUED
        assert result.net_profit == 18.0
        assert result.net_profit_margin_percentage == 60.0


class TestSkipRecommendation:
    """Test SKIP recommendation scenarios."""

    def test_overpriced_listing(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should SKIP when listing price exceeds market price."""
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=25.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=20.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.SKIP
        assert result.reason == ReasonCode.OVERPRICED
        assert result.net_profit == -5.0

    def test_low_confidence(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should SKIP when confidence is below threshold."""
        # Even with good profit, low confidence в†’ SKIP
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=25.0,
            confidence_score=0.40,
            confidence_level=ConfidenceLevel.LOW,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.recommendation == Recommendation.SKIP
        assert result.reason == ReasonCode.LOW_CONFIDENCE
        assert result.net_profit == 13.0  # Would be profitable
        assert result.confidence_score == 0.40

    def test_invalid_listing_price(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should SKIP when listing price is zero or negative."""
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=0.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=20.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.SKIP
        assert result.reason == ReasonCode.INVALID_LISTING_PRICE


class TestMaybeRecommendation:
    """Test MAYBE recommendation scenarios."""

    def test_low_expected_profit(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should return MAYBE when profit is positive but below threshold."""
        # Listing: 12в‚¬, Market: 18в‚¬, Profit: 6в‚¬ (< 10в‚¬ threshold)
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=12.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=18.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.MAYBE
        assert result.reason == ReasonCode.LOW_EXPECTED_PROFIT
        assert result.net_profit == 6.0

    def test_fair_price(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should return MAYBE for fair prices with low margins."""
        # Listing: 16в‚¬, Market: 28в‚¬, Profit: 12в‚¬ (>10в‚¬), Margin: 42.9% but needs >25%
        # Wait, that would be BUY. Let me use: Listing: 23в‚¬, Market: 28в‚¬
        # Profit: 5в‚¬ (<10в‚¬) в†’ would be LOW_EXPECTED_PROFIT
        # Actually need: profit >= 10в‚¬ but margin < 25%
        # Listing: 22в‚¬, Market: 28в‚¬, Profit: 6в‚¬ в†’ LOW_EXPECTED_PROFIT
        # Let's try: Listing: 16в‚¬, Market: 22в‚¬, Profit: 6в‚¬, Margin: 27.3%
        # Profit < 10в‚¬ в†’ LOW_EXPECTED_PROFIT takes priority

        # To get FAIR_PRICE, need profit >= 10в‚¬ but margin < 25%
        # Listing: 32в‚¬, Market: 40в‚¬, Profit: 8в‚¬, Margin: 20% в†’ LOW_EXPECTED_PROFIT
        # Listing: 32в‚¬, Market: 44в‚¬, Profit: 12в‚¬, Margin: 27.3% в†’ BUY
        # Listing: 34в‚¬, Market: 44в‚¬, Profit: 10в‚¬, Margin: 22.7% в†’ should be MAYBE/FAIR_PRICE
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=34.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=44.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.MAYBE
        assert result.reason == ReasonCode.FAIR_PRICE
        assert result.net_profit == 10.0
        assert result.net_profit_margin_percentage == pytest.approx(22.73, abs=0.1)


class TestProfitabilityCalculations:
    """Test profitability metric calculations."""

    def test_profit_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate profit correctly."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=25.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        # 25 - 12 = 13
        assert result.net_profit == 13.0

    def test_margin_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate profit margin correctly."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=20.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        # (20 - 12) / 20 * 100 = 40%
        assert result.net_profit_margin_percentage == 40.0

    def test_roi_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate ROI correctly."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=24.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        # (24 - 12) / 12 * 100 = 100%
        assert result.net_roi_percentage == 100.0


class TestFieldPropagation:
    """Test that all fields are correctly propagated."""

    def test_all_fields_present(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should populate all fields correctly."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=22.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        # Listing info
        assert result.listing == sample_listing
        assert result.game == sample_game

        # Prices
        assert result.market_price == 22.0
        assert result.listing_price == 12.0

        # Metrics
        assert isinstance(result.net_profit, float)
        assert isinstance(result.net_profit_margin_percentage, float)
        assert isinstance(result.net_roi_percentage, float)

        # Confidence
        assert result.confidence_score == 0.80
        assert result.confidence_level == ConfidenceLevel.HIGH

        # Decision
        assert isinstance(result.recommendation, Recommendation)
        assert isinstance(result.reason, ReasonCode)

        # Timestamp
        assert isinstance(result.created_at, datetime)


class TestCustomThresholds:
    """Test custom threshold configuration."""

    def test_custom_min_profit(
        self,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should use custom minimum profit threshold."""
        # Custom threshold: 15в‚¬ instead of 10в‚¬
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_net_profit_eur=15.0
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=24.0,  # Profit: 12в‚¬ (below 15в‚¬)
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        # Would be BUY with default (10в‚¬), but not with 15в‚¬ threshold
        assert result.recommendation == Recommendation.MAYBE
        assert result.net_profit == 12.0

    def test_custom_min_margin(
        self,
        sample_game: DetectedGame,
    ) -> None:
        """Should use custom minimum margin threshold."""
        # Custom threshold: 40% instead of 25%
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_net_profit_margin_percent=40.0
        )

        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=16.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=26.0,  # Profit: 10в‚¬, Margin: 38.5%
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        # Would be BUY with default (25%), but not with 40% threshold
        assert result.recommendation == Recommendation.MAYBE


class TestExplainMethod:
    """Test explain() method."""

    def test_explain_returns_string(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should return formatted explanation string."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=22.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)
        explanation = result.explain()

        assert isinstance(explanation, str)
        assert "ARBITRAGE OPPORTUNITY" in explanation
        assert "Grand Theft Auto V" in explanation
        assert "EUR 12.00" in explanation
        assert "EUR 22.00" in explanation
        assert "BUY" in explanation or "MAYBE" in explanation or "SKIP" in explanation


class TestRealWorldScenarios:
    """Test realistic arbitrage scenarios."""

    def test_excellent_deal(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Test excellent deal: cheap listing, high market price."""
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=8.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=20.0,
            confidence_score=0.90,
            confidence_level=ConfidenceLevel.VERY_HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.BUY
        assert result.reason == ReasonCode.UNDERVALUED
        assert result.net_profit == 12.0
        assert result.net_roi_percentage == 150.0

    def test_market_price_listing(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Test listing at market price (no arbitrage)."""
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=15.0,
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=15.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.SKIP
        assert result.reason == ReasonCode.OVERPRICED
        assert result.net_profit == 0.0
