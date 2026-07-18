"""Unit tests for DefaultArbitrageOpportunityDetector.

Tests arbitrage opportunity detection with various scenarios.
"""

from datetime import UTC, datetime

import pytest

from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    Recommendation,
    ReasonCode,
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
    ReasonCode as EstimateReasonCode,
)
from domain.interfaces.price_collector import ComparableListing
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)


@pytest.fixture
def detector() -> DefaultArbitrageOpportunityDetector:
    """Create detector with default thresholds."""
    return DefaultArbitrageOpportunityDetector()


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
    """Create sample listing."""
    return ComparableListing(
        listing_id="test123",
        title="GTA V PS4",
        description="Great condition",
        price=12.0,
        currency="EUR",
        detected_game=sample_game,
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
    """Test new fields: market_discount_percentage and break_even_price."""

    def test_market_discount_percentage_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should calculate market discount correctly."""
        # Market: 40€, Listing: 20€ → 50% discount
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=20.0,
            currency="EUR",
            detected_game=sample_game,
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
        assert result.market_discount_percentage == 50.0

    def test_break_even_price_equals_listing_price(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should set break_even_price equal to listing_price."""
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=22.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.break_even_price == result.listing_price
        assert result.break_even_price == 12.0

    def test_opportunity_score_range(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
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
        # Market: 40€, Listing: 10€ → 75% margin, 30€ profit, ROI 300%
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=10.0,
            currency="EUR",
            detected_game=sample_game,
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
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=30.0,
            currency="EUR",
            detected_game=sample_game,
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
        # Deal 1: Good (Market: 30€, Listing: 15€ → 50% margin, 15€ profit)
        listing1 = ComparableListing(
            listing_id="deal1",
            title="GTA V PS4 - Good Deal",
            description="",
            price=15.0,
            currency="EUR",
            detected_game=sample_game,
            url="https://wallapop.com/item/deal1",
        )

        # Deal 2: Excellent (Market: 40€, Listing: 10€ → 75% margin, 30€ profit)
        listing2 = ComparableListing(
            listing_id="deal2",
            title="GTA V PS4 - Excellent Deal",
            description="",
            price=10.0,
            currency="EUR",
            detected_game=sample_game,
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
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should recommend BUY when all criteria are met."""
        # Listing: 12€, Market: 22€, Profit: 10€, Margin: 45%, Confidence: 0.80
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=22.0,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.recommendation == Recommendation.BUY
        assert result.reason == ReasonCode.UNDERVALUED
        assert result.estimated_profit == 10.0
        assert result.profit_margin_percentage == pytest.approx(45.45, abs=0.1)
        assert result.confidence_score == 0.80

    def test_high_profit_buy(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should recommend BUY for high profit margins."""
        # Listing: 12€, Market: 30€, Profit: 18€, Margin: 60%
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=30.0,
            confidence_score=0.75,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.recommendation == Recommendation.BUY
        assert result.reason == ReasonCode.UNDERVALUED
        assert result.estimated_profit == 18.0
        assert result.profit_margin_percentage == 60.0


class TestSkipRecommendation:
    """Test SKIP recommendation scenarios."""

    def test_overpriced_listing(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should SKIP when listing price exceeds market price."""
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=25.0,
            currency="EUR",
            detected_game=sample_game,
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
        assert result.estimated_profit == -5.0

    def test_low_confidence(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should SKIP when confidence is below threshold."""
        # Even with good profit, low confidence → SKIP
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=25.0,
            confidence_score=0.40,
            confidence_level=ConfidenceLevel.LOW,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.recommendation == Recommendation.SKIP
        assert result.reason == ReasonCode.LOW_CONFIDENCE
        assert result.estimated_profit == 13.0  # Would be profitable
        assert result.confidence_score == 0.40

    def test_invalid_listing_price(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should SKIP when listing price is zero or negative."""
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=0.0,
            currency="EUR",
            detected_game=sample_game,
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
        # Listing: 12€, Market: 18€, Profit: 6€ (< 10€ threshold)
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=12.0,
            currency="EUR",
            detected_game=sample_game,
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
        assert result.estimated_profit == 6.0

    def test_fair_price(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Should return MAYBE for fair prices with low margins."""
        # Listing: 16€, Market: 28€, Profit: 12€ (>10€), Margin: 42.9% but needs >25%
        # Wait, that would be BUY. Let me use: Listing: 23€, Market: 28€
        # Profit: 5€ (<10€) → would be LOW_EXPECTED_PROFIT
        # Actually need: profit >= 10€ but margin < 25%
        # Listing: 22€, Market: 28€, Profit: 6€ → LOW_EXPECTED_PROFIT
        # Let's try: Listing: 16€, Market: 22€, Profit: 6€, Margin: 27.3%
        # Profit < 10€ → LOW_EXPECTED_PROFIT takes priority

        # To get FAIR_PRICE, need profit >= 10€ but margin < 25%
        # Listing: 32€, Market: 40€, Profit: 8€, Margin: 20% → LOW_EXPECTED_PROFIT
        # Listing: 32€, Market: 44€, Profit: 12€, Margin: 27.3% → BUY
        # Listing: 34€, Market: 44€, Profit: 10€, Margin: 22.7% → should be MAYBE/FAIR_PRICE
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=34.0,
            currency="EUR",
            detected_game=sample_game,
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
        assert result.estimated_profit == 10.0
        assert result.profit_margin_percentage == pytest.approx(22.73, abs=0.1)


class TestProfitabilityCalculations:
    """Test profitability metric calculations."""

    def test_profit_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
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
        assert result.estimated_profit == 13.0

    def test_margin_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
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
        assert result.profit_margin_percentage == 40.0

    def test_roi_calculation(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
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
        assert result.roi_percentage == 100.0


class TestFieldPropagation:
    """Test that all fields are correctly propagated."""

    def test_all_fields_present(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: ComparableListing,
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
        assert isinstance(result.estimated_profit, float)
        assert isinstance(result.profit_margin_percentage, float)
        assert isinstance(result.roi_percentage, float)

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
        sample_listing: ComparableListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should use custom minimum profit threshold."""
        # Custom threshold: 15€ instead of 10€
        detector = DefaultArbitrageOpportunityDetector(min_profit_eur=15.0)

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=24.0,  # Profit: 12€ (below 15€)
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        # Would be BUY with default (10€), but not with 15€ threshold
        assert result.recommendation == Recommendation.MAYBE
        assert result.estimated_profit == 12.0

    def test_custom_min_margin(
        self,
        sample_game: DetectedGame,
    ) -> None:
        """Should use custom minimum margin threshold."""
        # Custom threshold: 40% instead of 25%
        detector = DefaultArbitrageOpportunityDetector(min_margin_percent=40.0)

        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=16.0,
            currency="EUR",
            detected_game=sample_game,
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=26.0,  # Profit: 10€, Margin: 38.5%
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
        sample_listing: ComparableListing,
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
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=8.0,
            currency="EUR",
            detected_game=sample_game,
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
        assert result.estimated_profit == 12.0
        assert result.roi_percentage == 150.0

    def test_market_price_listing(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_game: DetectedGame,
    ) -> None:
        """Test listing at market price (no arbitrage)."""
        listing = ComparableListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=15.0,
            currency="EUR",
            detected_game=sample_game,
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
        assert result.estimated_profit == 0.0
