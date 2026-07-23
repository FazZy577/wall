"""Unit tests for DefaultArbitrageOpportunityDetector.

Tests arbitrage opportunity detection with various scenarios.
"""

from datetime import UTC, datetime
from decimal import Decimal
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
        price=Decimal("12.0"),
        currency="EUR",
        url="https://wallapop.com/item/test123",
    )


def create_market_estimate(
    game: DetectedGame,
    estimated_price: float,
    confidence_score: float,
    confidence_level: ConfidenceLevel,
    currency: str = "EUR",
) -> MarketPriceEstimate:
    """Helper to create market estimate."""
    return MarketPriceEstimate(
        estimated_price=Decimal(str(estimated_price)),
        currency=currency,
        confidence_score=confidence_score,
        confidence_level=confidence_level,
        strategy=EstimationStrategy.MEDIAN,
        reason_code=EstimateReasonCode.NORMAL,
        sample_size=20,
        observations_removed=2,
        outlier_percentage=10.0,
        minimum_price=Decimal("10.0"),
        maximum_price=Decimal("25.0"),
        standard_deviation=Decimal("3.5"),
        iqr=Decimal("5.0"),
        coefficient_of_variation=0.15,
        game=game,
        created_at=datetime.now(UTC),
    )


class TestNewFields:
    """Test new fields: acquisition_discount_to_reference_market_percentage and break_even_sale_revenue."""

    def test_required_net_economic_case(self, sample_game: DetectedGame) -> None:
        listing = CandidateListing("economic", "GTA V", "", Decimal("10.0"), "EUR", "url")
        estimate = create_market_estimate(
            sample_game, 20.0, 0.8, ConfidenceLevel.HIGH
        )
        configured_policy = ResaleEconomicPolicy(Decimal("3.0"), Decimal("0.10"), Decimal("1.0"), Decimal("2.0"), Decimal("0.05"))
        breakdown = configured_policy.calculate(
            [Decimal("20.0")], Decimal("10.0"), "EUR"
        )
        policy = Mock(spec=ResaleEconomicPolicy)
        policy.calculate.return_value = breakdown

        result = DefaultArbitrageOpportunityDetector(policy).detect(listing, estimate)

        policy.calculate.assert_called_once_with(
            reference_item_prices=[Decimal("20.0")],
            acquisition_price=Decimal("10.0"),
            currency="EUR",
        )
        assert result.economic_breakdown is breakdown
        assert result.economic_breakdown.net_profit == Decimal("1.45")
        assert result.net_profit == Decimal("1.45")
        assert result.net_roi_percentage == Decimal("1.45") / Decimal("12") * Decimal("100")
        assert result.net_profit_margin_percentage == Decimal("1.45") / Decimal("17") * Decimal("100")
        assert result.acquisition_discount_to_reference_market_percentage == 50.0
        assert result.break_even_sale_revenue == Decimal("13") / Decimal("0.85")

    def test_cost_policy_can_legitimately_lower_recommendation(
        self, sample_game: DetectedGame
    ) -> None:
        listing = CandidateListing("same", "GTA V", "", Decimal("5.0"), "EUR", "url")
        estimate = create_market_estimate(
            sample_game, 30.0, 0.8, ConfidenceLevel.HIGH
        )
        neutral = DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral())
        costly = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy(Decimal("10.0"), Decimal("0.20"), Decimal("2.0"), Decimal("5.0"), Decimal("0.10"))
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
        # Market: 40РІвЂљВ¬, Listing: 20РІвЂљВ¬ РІвЂ вЂ™ 50% discount
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=Decimal("20.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("40.0"),
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
            estimated_price=Decimal("22.0"),
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
            estimated_price=Decimal("22.0"),
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
        # Market: 40РІвЂљВ¬, Listing: 10РІвЂљВ¬ РІвЂ вЂ™ 75% margin, 30РІвЂљВ¬ profit, ROI 300%
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=Decimal("10.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("40.0"),
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
            price=Decimal("30.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("20.0"),
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
        # Deal 1: Good (Market: 30РІвЂљВ¬, Listing: 15РІвЂљВ¬ РІвЂ вЂ™ 50% margin, 15РІвЂљВ¬ profit)
        listing1 = CandidateListing(
            listing_id="deal1",
            title="GTA V PS4 - Good Deal",
            description="",
            price=Decimal("15.0"),
            currency="EUR",
            url="https://wallapop.com/item/deal1",
        )

        # Deal 2: Excellent (Market: 40РІвЂљВ¬, Listing: 10РІвЂљВ¬ РІвЂ вЂ™ 75% margin, 30РІвЂљВ¬ profit)
        listing2 = CandidateListing(
            listing_id="deal2",
            title="GTA V PS4 - Excellent Deal",
            description="",
            price=Decimal("10.0"),
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
        # Listing: 12РІвЂљВ¬, Market: 22РІвЂљВ¬, Profit: 10РІвЂљВ¬, Margin: 45%, Confidence: 0.80
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("22.0"),
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        assert result.recommendation == Recommendation.BUY
        assert result.reason == ReasonCode.UNDERVALUED
        assert result.net_profit == 10.0
        assert result.net_profit_margin_percentage == Decimal("10") / Decimal("22") * Decimal("100")
        assert result.confidence_score == 0.80

    def test_high_profit_buy(
        self,
        detector: DefaultArbitrageOpportunityDetector,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should recommend BUY for high profit margins."""
        # Listing: 12РІвЂљВ¬, Market: 30РІвЂљВ¬, Profit: 18РІвЂљВ¬, Margin: 60%
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("30.0"),
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
            price=Decimal("25.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("20.0"),
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
        # Even with good profit, low confidence РІвЂ вЂ™ SKIP
        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("25.0"),
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
            price=Decimal("0.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("20.0"),
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
        # Listing: 12РІвЂљВ¬, Market: 18РІвЂљВ¬, Profit: 6РІвЂљВ¬ (< 10РІвЂљВ¬ threshold)
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=Decimal("12.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("18.0"),
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
        # Listing: 16РІвЂљВ¬, Market: 28РІвЂљВ¬, Profit: 12РІвЂљВ¬ (>10РІвЂљВ¬), Margin: 42.9% but needs >25%
        # Wait, that would be BUY. Let me use: Listing: 23РІвЂљВ¬, Market: 28РІвЂљВ¬
        # Profit: 5РІвЂљВ¬ (<10РІвЂљВ¬) РІвЂ вЂ™ would be LOW_EXPECTED_PROFIT
        # Actually need: profit >= 10РІвЂљВ¬ but margin < 25%
        # Listing: 22РІвЂљВ¬, Market: 28РІвЂљВ¬, Profit: 6РІвЂљВ¬ РІвЂ вЂ™ LOW_EXPECTED_PROFIT
        # Let's try: Listing: 16РІвЂљВ¬, Market: 22РІвЂљВ¬, Profit: 6РІвЂљВ¬, Margin: 27.3%
        # Profit < 10РІвЂљВ¬ РІвЂ вЂ™ LOW_EXPECTED_PROFIT takes priority

        # To get FAIR_PRICE, need profit >= 10РІвЂљВ¬ but margin < 25%
        # Listing: 32РІвЂљВ¬, Market: 40РІвЂљВ¬, Profit: 8РІвЂљВ¬, Margin: 20% РІвЂ вЂ™ LOW_EXPECTED_PROFIT
        # Listing: 32РІвЂљВ¬, Market: 44РІвЂљВ¬, Profit: 12РІвЂљВ¬, Margin: 27.3% РІвЂ вЂ™ BUY
        # Listing: 34РІвЂљВ¬, Market: 44РІвЂљВ¬, Profit: 10РІвЂљВ¬, Margin: 22.7% РІвЂ вЂ™ should be MAYBE/FAIR_PRICE
        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=Decimal("34.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("44.0"),
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.MAYBE
        assert result.reason == ReasonCode.FAIR_PRICE
        assert result.net_profit == 10.0
        assert result.net_profit_margin_percentage == Decimal("10") / Decimal("44") * Decimal("100")


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
            estimated_price=Decimal("25.0"),
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
            estimated_price=Decimal("20.0"),
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
            estimated_price=Decimal("24.0"),
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
            estimated_price=Decimal("22.0"),
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
        assert isinstance(result.net_profit, Decimal)
        assert isinstance(result.net_profit_margin_percentage, Decimal)
        assert isinstance(result.net_roi_percentage, Decimal)

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

    def test_omitted_and_none_thresholds_use_unchanged_defaults(self) -> None:
        omitted = DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral())
        explicit_none = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency=None,
            min_net_profit_margin_percent=None,
            min_confidence_score=None,
        )

        for detector in (omitted, explicit_none):
            assert detector.min_net_profit_by_currency == {"EUR": Decimal("10.0")}
            assert detector.min_net_profit_margin_percent == Decimal("25.0")
            assert detector.min_confidence_score == 0.5

    def test_all_explicit_zero_thresholds_are_preserved(self) -> None:
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("0")},
            min_net_profit_margin_percent=Decimal("0"),
            min_confidence_score=0.0,
        )

        assert detector.min_net_profit_by_currency == {"EUR": Decimal("0")}
        assert detector.min_net_profit_margin_percent == Decimal("0")
        assert detector.min_confidence_score == 0.0

    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            (
                {"min_net_profit_by_currency": {"EUR": Decimal("0")}},
                ({"EUR": Decimal("0")}, Decimal("25.0"), 0.5),
            ),
            (
                {"min_net_profit_margin_percent": Decimal("0")},
                ({"EUR": Decimal("10.0")}, Decimal("0"), 0.5),
            ),
            (
                {"min_confidence_score": 0.0},
                ({"EUR": Decimal("10.0")}, Decimal("25.0"), 0.0),
            ),
        ],
    )
    def test_one_zero_does_not_change_other_thresholds(
        self,
        configured: dict[str, object],
        expected: tuple[dict[str, Decimal], Decimal, float],
    ) -> None:
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            **configured,  # type: ignore[arg-type]
        )

        assert (
            detector.min_net_profit_by_currency,
            detector.min_net_profit_margin_percent,
            detector.min_confidence_score,
        ) == expected

    def test_positive_custom_thresholds_are_preserved_exactly(self) -> None:
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("1.0")},
            min_net_profit_margin_percent=Decimal("2.0"),
            min_confidence_score=0.25,
        )

        assert detector.min_net_profit_by_currency == {"EUR": Decimal("1.0")}
        assert detector.min_net_profit_margin_percent == Decimal("2.0")
        assert detector.min_confidence_score == 0.25

    def test_none_and_zero_have_distinct_semantics(self) -> None:
        none_detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency=None
        )
        zero_detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("0")},
        )

        assert none_detector.min_net_profit_by_currency == {"EUR": Decimal("10.0")}
        assert zero_detector.min_net_profit_by_currency == {"EUR": Decimal("0")}

    def test_zero_profit_threshold_changes_only_decision(
        self,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        estimate = create_market_estimate(
            sample_game, 18.0, 0.8, ConfidenceLevel.HIGH
        )
        default_result = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral()
        ).detect(sample_listing, estimate)
        zero_result = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("0")},
        ).detect(sample_listing, estimate)

        assert (default_result.recommendation, default_result.reason) == (
            Recommendation.MAYBE,
            ReasonCode.LOW_EXPECTED_PROFIT,
        )
        assert (zero_result.recommendation, zero_result.reason) == (
            Recommendation.BUY,
            ReasonCode.UNDERVALUED,
        )
        assert zero_result.opportunity_score == default_result.opportunity_score

    def test_zero_margin_threshold_changes_only_decision(
        self,
        sample_game: DetectedGame,
    ) -> None:
        listing = CandidateListing(
            "margin-zero", "GTA V PS4", "", Decimal("34"), "EUR", ""
        )
        estimate = create_market_estimate(
            sample_game, 44.0, 0.8, ConfidenceLevel.HIGH
        )
        default_result = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral()
        ).detect(listing, estimate)
        zero_result = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_margin_percent=Decimal("0"),
        ).detect(listing, estimate)

        assert (default_result.recommendation, default_result.reason) == (
            Recommendation.MAYBE,
            ReasonCode.FAIR_PRICE,
        )
        assert (zero_result.recommendation, zero_result.reason) == (
            Recommendation.BUY,
            ReasonCode.UNDERVALUED,
        )
        assert zero_result.opportunity_score == default_result.opportunity_score

    def test_zero_confidence_threshold_accepts_exact_zero_boundary(
        self,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        estimate = create_market_estimate(
            sample_game, 25.0, 0.0, ConfidenceLevel.VERY_LOW
        )
        default_result = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral()
        ).detect(sample_listing, estimate)
        zero_result = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_confidence_score=0.0
        ).detect(sample_listing, estimate)

        assert (default_result.recommendation, default_result.reason) == (
            Recommendation.SKIP,
            ReasonCode.LOW_CONFIDENCE,
        )
        assert (zero_result.recommendation, zero_result.reason) == (
            Recommendation.BUY,
            ReasonCode.UNDERVALUED,
        )
        assert zero_result.opportunity_score == default_result.opportunity_score

    def test_zero_profit_still_obeys_prior_overpriced_rule(
        self,
        sample_game: DetectedGame,
    ) -> None:
        listing = CandidateListing(
            "zero-profit", "GTA V PS4", "", Decimal("20"), "EUR", ""
        )
        estimate = create_market_estimate(
            sample_game, 20.0, 0.8, ConfidenceLevel.HIGH
        )
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("0")},
            min_net_profit_margin_percent=Decimal("0"),
            min_confidence_score=0.0,
        )

        result = detector.detect(listing, estimate)

        assert result.net_profit == Decimal("0")
        assert result.recommendation is Recommendation.SKIP
        assert result.reason is ReasonCode.OVERPRICED

    def test_custom_min_profit(
        self,
        sample_listing: CandidateListing,
        sample_game: DetectedGame,
    ) -> None:
        """Should use custom minimum profit threshold."""
        # Custom threshold: 15РІвЂљВ¬ instead of 10РІвЂљВ¬
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("15.0")},
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("24.0"),  # Profit: 12РІвЂљВ¬ (below 15РІвЂљВ¬)
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(sample_listing, market_estimate)

        # Would be BUY with default (10РІвЂљВ¬), but not with 15РІвЂљВ¬ threshold
        assert result.recommendation == Recommendation.MAYBE
        assert result.net_profit == 12.0

    def test_custom_min_margin(
        self,
        sample_game: DetectedGame,
    ) -> None:
        """Should use custom minimum margin threshold."""
        # Custom threshold: 40% instead of 25%
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_net_profit_margin_percent=Decimal("40.0")
        )

        listing = CandidateListing(
            listing_id="test123",
            title="GTA V PS4",
            description="",
            price=Decimal("16.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("26.0"),  # Profit: 10РІвЂљВ¬, Margin: 38.5%
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        # Would be BUY with default (25%), but not with 40% threshold
        assert result.recommendation == Recommendation.MAYBE


class TestCurrencySpecificProfitThresholds:
    """Absolute profit thresholds are resolved in breakdown currency."""

    @staticmethod
    def _detect(
        currency: str,
        net_profit: str,
        thresholds: dict[str, Decimal] | None = None,
    ):
        game = DetectedGame(
            "Grand Theft Auto V",
            "gta v",
            Platform.PS4,
            1.0,
            DetectionMethod.EXACT_MATCH,
        )
        listing = CandidateListing(
            f"candidate-{currency}",
            "GTA V",
            "",
            Decimal("10"),
            currency,
            "url",
        )
        estimate = create_market_estimate(
            game,
            float(Decimal("10") + Decimal(net_profit)),
            0.8,
            ConfidenceLevel.HIGH,
            currency,
        )
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency=thresholds,
        )
        return detector.detect(listing, estimate)

    def test_default_and_none_configure_only_historical_eur(self) -> None:
        omitted = DefaultArbitrageOpportunityDetector(ResaleEconomicPolicy.neutral())
        explicit_none = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency=None
        )

        assert omitted.min_net_profit_by_currency == {"EUR": Decimal("10.0")}
        assert explicit_none.min_net_profit_by_currency == {
            "EUR": Decimal("10.0")
        }

    @pytest.mark.parametrize(
        ("profit", "recommendation", "reason"),
        [
            ("9", Recommendation.MAYBE, ReasonCode.LOW_EXPECTED_PROFIT),
            ("10", Recommendation.BUY, ReasonCode.UNDERVALUED),
            ("11", Recommendation.BUY, ReasonCode.UNDERVALUED),
        ],
    )
    def test_default_eur_behavior_is_unchanged(
        self, profit: str, recommendation: Recommendation, reason: ReasonCode
    ) -> None:
        result = self._detect("EUR", profit)
        assert (result.recommendation, result.reason) == (recommendation, reason)

    @pytest.mark.parametrize("currency", ["USD", "GBP"])
    def test_default_rejects_unconfigured_currency(self, currency: str) -> None:
        with pytest.raises(
            ValueError,
            match=f"No minimum net profit threshold configured for currency {currency}",
        ):
            self._detect(currency, "9")

    def test_each_currency_uses_only_its_own_threshold(self) -> None:
        thresholds = {
            "EUR": Decimal("10"),
            "USD": Decimal("8"),
            "GBP": Decimal("12"),
        }
        eur = self._detect("EUR", "9", thresholds)
        usd = self._detect("USD", "9", thresholds)
        gbp = self._detect("GBP", "9", thresholds)

        assert (eur.recommendation, eur.reason) == (
            Recommendation.MAYBE,
            ReasonCode.LOW_EXPECTED_PROFIT,
        )
        assert (usd.recommendation, usd.reason) == (
            Recommendation.BUY,
            ReasonCode.UNDERVALUED,
        )
        assert (gbp.recommendation, gbp.reason) == (
            Recommendation.MAYBE,
            ReasonCode.LOW_EXPECTED_PROFIT,
        )
        assert eur.opportunity_score == usd.opportunity_score == gbp.opportunity_score

    def test_empty_mapping_is_not_none_and_zero_is_preserved(self) -> None:
        empty = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency={}
        )
        zero = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={
                "EUR": Decimal("0"),
                "USD": Decimal("0"),
            },
        )

        assert empty.min_net_profit_by_currency == {}
        with pytest.raises(ValueError, match="currency EUR"):
            self._detect("EUR", "9", {})
        assert zero.min_net_profit_by_currency == {
            "EUR": Decimal("0"),
            "USD": Decimal("0"),
        }
        assert self._detect("EUR", "10", dict(zero.min_net_profit_by_currency)).recommendation is Recommendation.BUY
        assert self._detect("USD", "10", dict(zero.min_net_profit_by_currency)).recommendation is Recommendation.BUY
        with pytest.raises(ValueError, match="currency GBP"):
            self._detect("GBP", "1", dict(zero.min_net_profit_by_currency))

    @pytest.mark.parametrize(
        "currency", ["", "eur", " EUR", "EUR ", "€", "EURO", None, 123, True]
    )
    def test_invalid_currency_keys_are_rejected(self, currency: object) -> None:
        with pytest.raises((TypeError, ValueError), match="min_net_profit_by_currency key"):
            DefaultArbitrageOpportunityDetector(
                ResaleEconomicPolicy.neutral(),
                min_net_profit_by_currency={currency: Decimal("10")},  # type: ignore[dict-item]
            )

    @pytest.mark.parametrize(
        "threshold",
        [10.0, True, Decimal("NaN"), Decimal("Infinity")],
    )
    def test_invalid_threshold_values_are_rejected(self, threshold: object) -> None:
        with pytest.raises((TypeError, ValueError), match="min_net_profit_by_currency"):
            DefaultArbitrageOpportunityDetector(
                ResaleEconomicPolicy.neutral(),
                min_net_profit_by_currency={"EUR": threshold},  # type: ignore[dict-item]
            )

    def test_configuration_is_copied_defensively(self) -> None:
        config = {"EUR": Decimal("10")}
        detector = DefaultArbitrageOpportunityDetector(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency=config
        )
        config["EUR"] = Decimal("999")
        config["USD"] = Decimal("1")

        assert detector.min_net_profit_by_currency == {"EUR": Decimal("10")}
        with pytest.raises(TypeError):
            detector.min_net_profit_by_currency["EUR"] = Decimal("1")  # type: ignore[index]


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
            estimated_price=Decimal("22.0"),
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
            price=Decimal("8.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("20.0"),
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
            price=Decimal("15.0"),
            currency="EUR",
            url="https://wallapop.com/item/test123",
        )

        market_estimate = create_market_estimate(
            game=sample_game,
            estimated_price=Decimal("15.0"),
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
        )

        result = detector.detect(listing, market_estimate)

        assert result.recommendation == Recommendation.SKIP
        assert result.reason == ReasonCode.OVERPRICED
        assert result.net_profit == 0.0
