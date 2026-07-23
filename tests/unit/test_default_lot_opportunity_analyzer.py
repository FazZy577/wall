"""Unit tests for DefaultLotOpportunityAnalyzer.

Tests decision rules, opportunity score calculation, and edge cases.
No external calls. No Playwright. No Wallapop.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from domain.currency import CurrencyMismatchError
from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotReasonCode
from domain.entities.resale_economics import (
    ResaleAbsoluteCosts,
    ResaleEconomicPolicy,
)
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


def _make_game(name: str, platform: Platform = Platform.PS4) -> DetectedGame:
    return DetectedGame(
        canonical_name=name,
        matched_text=name.lower(),
        platform=platform,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def _make_estimate(
    game: DetectedGame,
    estimated_price: float,
    confidence_score: float = 0.80,
    sample_size: int = 25,
    currency: str = "EUR",
) -> MarketPriceEstimate:
    amount = Decimal(str(estimated_price))
    return MarketPriceEstimate(
        estimated_price=amount,
        currency=currency,
        confidence_score=confidence_score,
        confidence_level=ConfidenceLevel.HIGH,
        strategy=EstimationStrategy.MEDIAN,
        reason_code=ReasonCode.NORMAL,
        sample_size=sample_size,
        observations_removed=2,
        outlier_percentage=8.0,
        minimum_price=amount * Decimal("0.8"),
        maximum_price=amount * Decimal("1.2"),
        standard_deviation=Decimal("5.0"),
        iqr=Decimal("7.0"),
        coefficient_of_variation=0.25,
        game=game,
        created_at=datetime.now(),
    )


def _make_valuation(
    name: str,
    estimated_price: float,
    confidence_score: float = 0.80,
    currency: str = "EUR",
    platform: Platform = Platform.PS4,
) -> GameValuation:
    game = _make_game(name, platform)
    estimate = _make_estimate(
        game, estimated_price, confidence_score, currency=currency
    )
    return GameValuation.from_market_estimate(game, estimate)


@pytest.fixture
def analyzer() -> DefaultLotOpportunityAnalyzer:
    return DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral())


@pytest.mark.parametrize(
    ("prices", "expected"),
    [
        (
            [15.0, 20.0, 10.0],
            (45.0, 5.0, 11.1, 12.5, Recommendation.MAYBE, LotReasonCode.FAIR_VALUE_LOT, 41.8),
        ),
        (
            [15.0, 20.0],
            (35.0, -5.0, -14.3, -12.5, Recommendation.SKIP, LotReasonCode.INCOMPLETE_VALUATION, 26.0),
        ),
        (
            [],
            (0.0, -40.0, 0.0, -100.0, Recommendation.SKIP, LotReasonCode.INCOMPLETE_VALUATION, 0.0),
        ),
    ],
)
def test_p16_detection_source_change_preserves_economic_results(
    analyzer: DefaultLotOpportunityAnalyzer,
    prices: list[float],
    expected: tuple[float, float, float, float, Recommendation, LotReasonCode, float],
) -> None:
    candidate = CandidateListing("lot-40", "Lot", "", Decimal("40.0"), "EUR", "https://test/lot")
    valuations = [
        _make_valuation(f"Game {index}", price)
        for index, price in enumerate(prices)
    ]

    opportunity = analyzer.analyze(candidate, valuations, total_detected_games=3)

    actual = (
        opportunity.reference_market_value,
        opportunity.net_profit,
        opportunity.net_profit_margin_percentage,
        opportunity.net_roi_percentage,
        opportunity.recommendation,
        opportunity.reason,
        opportunity.opportunity_score,
    )
    expected_decimal = tuple(Decimal(str(value)) for value in expected[:4])
    assert actual[:2] == expected_decimal[:2]
    assert actual[2:4] == pytest.approx(
        expected_decimal[2:4], abs=Decimal("0.02")
    )
    assert actual[4:] == expected[4:]


def test_quick_sale_policy_builds_one_aggregate_lot_breakdown() -> None:
    analyzer = DefaultLotOpportunityAnalyzer(
        ResaleEconomicPolicy(
            {"EUR": ResaleAbsoluteCosts(Decimal("3.0"), Decimal("0.0"), Decimal("0.0"))},
            Decimal("0.0"),
            Decimal("0.0"),
        )
    )
    candidate = CandidateListing("lot", "Lot", "", Decimal("40.0"), "EUR", "url")
    valuations = [
        _make_valuation("GTA V", 15.0),
        _make_valuation("RDR2", 20.0),
        _make_valuation("FIFA 24", 10.0),
    ]

    opportunity = analyzer.analyze(candidate, valuations, 3)

    assert opportunity.economic_breakdown.expected_item_sale_prices == (12.0, 17.0, 7.0)
    assert opportunity.economic_breakdown.expected_sale_revenue == 36.0
    assert opportunity.economic_breakdown.net_profit == -4.0
    assert opportunity.net_profit == -4.0
    assert opportunity.economic_breakdown.item_count == 3


def test_partial_and_empty_valuations_only_charge_successful_items() -> None:
    analyzer = DefaultLotOpportunityAnalyzer(
        ResaleEconomicPolicy(
            {"EUR": ResaleAbsoluteCosts(Decimal("3.0"), Decimal("1.0"), Decimal("2.0"))},
            Decimal("0.0"),
            Decimal("0.0"),
        )
    )
    candidate = CandidateListing("lot", "Lot", "", Decimal("40.0"), "EUR", "url")
    valuations = [_make_valuation("GTA V", 15.0), _make_valuation("RDR2", 20.0)]

    partial = analyzer.analyze(candidate, valuations, 3)
    empty = analyzer.analyze(candidate, [], 3)

    assert partial.economic_breakdown.item_count == 2
    assert partial.economic_breakdown.expected_item_sale_prices == (12.0, 17.0)
    assert partial.economic_breakdown.fixed_selling_costs == 2.0
    assert partial.economic_breakdown.acquisition_overhead == 2.0
    assert partial.reason is LotReasonCode.INCOMPLETE_VALUATION
    assert empty.economic_breakdown.reference_market_value == 0
    assert empty.economic_breakdown.item_count == 0
    assert empty.economic_breakdown.total_acquisition_cost == 42.0
    assert empty.economic_breakdown.net_profit == -42.0
    assert empty.recommendation is Recommendation.SKIP
    assert empty.reason is LotReasonCode.INCOMPLETE_VALUATION


# ---------------------------------------------------------------------------
# Clear BUY
# ---------------------------------------------------------------------------


class TestBuyRecommendation:
    def test_clear_buy_lot(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """35РІвЂљВ¬ lot with 53РІвЂљВ¬ market value РІвЂ вЂ™ BUY."""
        candidate = CandidateListing(
            listing_id="lot001",
            title="Lote PS4 GTA V RDR2 Spider-Man",
            description="",
            price=Decimal("35.0"),
            currency="EUR",
            url="https://example.com/lot001",
        )

        valuations = [
            _make_valuation("GTA V", 15.0, 0.80),
            _make_valuation("RDR2", 20.0, 0.90),
            _make_valuation("Spider-Man", 18.0, 0.70),
        ]

        lot = analyzer.analyze(candidate, valuations, 3)

        # reference_market_value = Decimal("53"), profit = 18, margin = 33.96%
        assert lot.reference_market_value == 53.0
        assert lot.net_profit == 18.0
        assert lot.net_profit_margin_percentage == Decimal("18") / Decimal("53") * Decimal("100")
        assert lot.net_roi_percentage == Decimal("18") / Decimal("35") * Decimal("100")
        assert lot.recommendation == Recommendation.BUY
        assert lot.reason == LotReasonCode.UNDERVALUED_LOT


# ---------------------------------------------------------------------------
# Margin below threshold РІвЂ вЂ™ MAYBE
# ---------------------------------------------------------------------------


class TestMarginThreshold:
    def test_margin_below_threshold_returns_maybe(
        self, analyzer: DefaultLotOpportunityAnalyzer
    ) -> None:
        """40РІвЂљВ¬ lot with 53РІвЂљВ¬ market value РІвЂ вЂ™ margin 24.5% < 25% РІвЂ вЂ™ MAYBE."""
        candidate = CandidateListing(
            listing_id="lot002",
            title="Lote PS4 GTA V RDR2 Spider-Man",
            description="",
            price=Decimal("40.0"),
            currency="EUR",
            url="https://example.com/lot002",
        )

        valuations = [
            _make_valuation("GTA V", 15.0, 0.80),
            _make_valuation("RDR2", 20.0, 0.90),
            _make_valuation("Spider-Man", 18.0, 0.70),
        ]

        lot = analyzer.analyze(candidate, valuations, 3)

        # reference_market_value = Decimal("53"), profit = 13, margin = 24.5%
        assert lot.reference_market_value == 53.0
        assert lot.net_profit == 13.0
        assert lot.net_profit_margin_percentage == Decimal("13") / Decimal("53") * Decimal("100")
        assert lot.recommendation == Recommendation.MAYBE
        assert lot.reason == LotReasonCode.FAIR_VALUE_LOT


# ---------------------------------------------------------------------------
# Overpriced РІвЂ вЂ™ SKIP
# ---------------------------------------------------------------------------


class TestOverpriced:
    def test_overpriced_lot(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """100РІвЂљВ¬ lot with 25РІвЂљВ¬ market value РІвЂ вЂ™ SKIP."""
        candidate = CandidateListing(
            listing_id="overpriced",
            title="Overpriced Lot",
            description="",
            price=Decimal("100.0"),
            currency="EUR",
            url="https://example.com/overpriced",
        )

        valuations = [
            _make_valuation("GTA V", 15.0),
            _make_valuation("FIFA", 10.0),
        ]

        lot = analyzer.analyze(candidate, valuations, 2)

        assert lot.reference_market_value == 25.0
        assert lot.net_profit == -75.0
        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.OVERPRICED_LOT

    def test_fair_value_exact(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Price exactly equals market value РІвЂ вЂ™ SKIP/FAIR_VALUE_LOT."""
        candidate = CandidateListing(
            listing_id="fair",
            title="Fair Value Lot",
            description="",
            price=Decimal("35.0"),
            currency="EUR",
            url="https://example.com/fair",
        )

        valuations = [
            _make_valuation("GTA V", 15.0),
            _make_valuation("RDR2", 20.0),
        ]

        lot = analyzer.analyze(candidate, valuations, 2)

        assert lot.reference_market_value == 35.0
        assert lot.net_profit == 0.0
        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.FAIR_VALUE_LOT


# ---------------------------------------------------------------------------
# Low confidence
# ---------------------------------------------------------------------------


class TestLowConfidence:
    def test_low_aggregate_confidence(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Confidence 0.30 < 0.50 РІвЂ вЂ™ SKIP."""
        candidate = CandidateListing(
            listing_id="lowconf",
            title="Low confidence lot",
            description="",
            price=Decimal("30.0"),
            currency="EUR",
            url="https://example.com/lowconf",
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
        """2 of 3 valued, known profit positive РІвЂ вЂ™ MAYBE."""
        candidate = CandidateListing(
            listing_id="incomplete",
            title="Partial lot",
            description="",
            price=Decimal("30.0"),
            currency="EUR",
            url="https://example.com/incomplete",
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
        """2 of 3 valued, known profit negative РІвЂ вЂ™ SKIP."""
        candidate = CandidateListing(
            listing_id="incomplete_neg",
            title="Bad partial lot",
            description="",
            price=Decimal("50.0"),
            currency="EUR",
            url="https://example.com/incomplete_neg",
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
        """No games valued РІвЂ вЂ™ SKIP/INCOMPLETE_VALUATION."""
        candidate = CandidateListing(
            listing_id="no_vals",
            title="Failed lot",
            description="",
            price=Decimal("30.0"),
            currency="EUR",
            url="https://example.com/no_vals",
        )

        lot = analyzer.analyze(candidate, [], 2)

        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.INCOMPLETE_VALUATION


# ---------------------------------------------------------------------------
# No games / invalid price
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_games_detected(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Empty detected_games РІвЂ вЂ™ SKIP/NO_GAMES_DETECTED."""
        candidate = CandidateListing(
            listing_id="nogames",
            title="Unknown",
            description="",
            price=Decimal("10.0"),
            currency="EUR",
            url="https://example.com/nogames",
        )

        lot = analyzer.analyze(candidate, [], 0)

        assert lot.recommendation == Recommendation.SKIP
        assert lot.reason == LotReasonCode.NO_GAMES_DETECTED

    def test_zero_price(self, analyzer: DefaultLotOpportunityAnalyzer) -> None:
        """Price 0 РІвЂ вЂ™ SKIP/INVALID_LOT_PRICE."""
        candidate = CandidateListing(
            listing_id="free",
            title="Free games",
            description="",
            price=Decimal("0.0"),
            currency="EUR",
            url="https://example.com/free",
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
            price=Decimal("35.0"),
            currency="EUR",
            url="https://example.com/score",
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
            price=Decimal("10.0"),
            currency="EUR",
            url="https://example.com/incomplete",
        )

        # Only 1 of 3 valued, but very profitable
        valuations = [_make_valuation("A", 50.0, 1.0)]

        lot = analyzer.analyze(candidate, valuations, 3)

        # Must NOT be BUY РІР‚вЂќ incomplete
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
            price=Decimal("10.0"),
            currency="EUR",
            url="https://example.com/lowconf",
        )

        # Very profitable but low confidence
        valuations = [
            _make_valuation("A", 30.0, 0.30),
            _make_valuation("B", 30.0, 0.30),
        ]

        lot = analyzer.analyze(candidate, valuations, 2)

        # Must NOT be BUY РІР‚вЂќ low confidence
        assert lot.recommendation != Recommendation.BUY
        assert lot.reason == LotReasonCode.LOW_AGGREGATE_CONFIDENCE


class TestCurrencySpecificLotProfitThresholds:
    """Absolute lot-profit thresholds are resolved per breakdown currency."""

    @staticmethod
    def _analyze(
        currency: str,
        net_profit: str,
        thresholds: dict[str, Decimal] | None = None,
    ):
        listing = CandidateListing(
            f"lot-{currency}", "Lot", "", Decimal("10"), currency, "url"
        )
        valuation = _make_valuation(
            "Game", float(Decimal("10") + Decimal(net_profit)), currency=currency
        )
        analyzer = DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy.neutral(currency),
            min_net_profit_by_currency=thresholds,
        )
        return analyzer.analyze(listing, [valuation], 1)

    def test_default_and_none_configure_only_historical_eur(self) -> None:
        omitted = DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral())
        explicit_none = DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency=None
        )

        assert omitted.min_net_profit_by_currency == {"EUR": Decimal("10.0")}
        assert explicit_none.min_net_profit_by_currency == {
            "EUR": Decimal("10.0")
        }

    @pytest.mark.parametrize(
        ("profit", "recommendation", "reason"),
        [
            ("9", Recommendation.MAYBE, LotReasonCode.FAIR_VALUE_LOT),
            ("10", Recommendation.BUY, LotReasonCode.UNDERVALUED_LOT),
            ("11", Recommendation.BUY, LotReasonCode.UNDERVALUED_LOT),
        ],
    )
    def test_default_eur_boundary_is_unchanged(
        self,
        profit: str,
        recommendation: Recommendation,
        reason: LotReasonCode,
    ) -> None:
        lot = self._analyze("EUR", profit)
        assert lot.currency == "EUR"
        assert (lot.recommendation, lot.reason) == (recommendation, reason)

    @pytest.mark.parametrize("currency", ["USD", "GBP"])
    def test_default_rejects_unconfigured_currency(self, currency: str) -> None:
        with pytest.raises(
            ValueError,
            match=(
                "No minimum lot net profit threshold configured for currency "
                f"{currency}"
            ),
        ):
            self._analyze(currency, "9")

    def test_each_currency_uses_only_its_threshold(self) -> None:
        thresholds = {
            "EUR": Decimal("10"),
            "USD": Decimal("8"),
            "GBP": Decimal("12"),
        }
        eur = self._analyze("EUR", "9", thresholds)
        usd = self._analyze("USD", "9", thresholds)
        gbp = self._analyze("GBP", "9", thresholds)

        assert (eur.recommendation, eur.reason) == (
            Recommendation.MAYBE,
            LotReasonCode.FAIR_VALUE_LOT,
        )
        assert (usd.recommendation, usd.reason) == (
            Recommendation.BUY,
            LotReasonCode.UNDERVALUED_LOT,
        )
        assert (gbp.recommendation, gbp.reason) == (
            Recommendation.MAYBE,
            LotReasonCode.FAIR_VALUE_LOT,
        )
        assert eur.opportunity_score == usd.opportunity_score == gbp.opportunity_score

    def test_empty_mapping_is_not_none_and_zero_is_preserved(self) -> None:
        empty = DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency={}
        )
        zero = DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={
                "EUR": Decimal("0"),
                "USD": Decimal("0"),
            },
        )

        assert empty.min_net_profit_by_currency == {}
        with pytest.raises(ValueError, match="currency EUR"):
            self._analyze("EUR", "9", {})
        assert zero.min_net_profit_by_currency == {
            "EUR": Decimal("0"),
            "USD": Decimal("0"),
        }
        assert self._analyze(
            "EUR", "10", dict(zero.min_net_profit_by_currency)
        ).recommendation is Recommendation.BUY
        assert self._analyze(
            "USD", "10", dict(zero.min_net_profit_by_currency)
        ).recommendation is Recommendation.BUY
        with pytest.raises(ValueError, match="currency GBP"):
            self._analyze("GBP", "10", dict(zero.min_net_profit_by_currency))

    @pytest.mark.parametrize(
        "currency", ["", " ", "eur", " EUR", "EUR ", "€", "EURO", None, 123, True]
    )
    def test_invalid_currency_keys_are_rejected(self, currency: object) -> None:
        with pytest.raises((TypeError, ValueError), match="min_net_profit_by_currency key"):
            DefaultLotOpportunityAnalyzer(
                ResaleEconomicPolicy.neutral(),
                min_net_profit_by_currency={currency: Decimal("10")},  # type: ignore[dict-item]
            )

    @pytest.mark.parametrize(
        "threshold",
        [10.0, True, None, Decimal("NaN"), Decimal("Infinity"), object()],
    )
    def test_invalid_threshold_values_are_rejected(self, threshold: object) -> None:
        with pytest.raises((TypeError, ValueError), match="min_net_profit_by_currency"):
            DefaultLotOpportunityAnalyzer(
                ResaleEconomicPolicy.neutral(),
                min_net_profit_by_currency={"EUR": threshold},  # type: ignore[dict-item]
            )

    def test_negative_threshold_remains_valid(self) -> None:
        analyzer = DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy.neutral(),
            min_net_profit_by_currency={"EUR": Decimal("-1")},
        )
        assert analyzer.min_net_profit_by_currency == {"EUR": Decimal("-1")}

    def test_configuration_is_copied_defensively(self) -> None:
        config = {"EUR": Decimal("10")}
        analyzer = DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency=config
        )
        config["EUR"] = Decimal("999")
        config["USD"] = Decimal("1")

        assert analyzer.min_net_profit_by_currency == {"EUR": Decimal("10")}
        with pytest.raises(TypeError):
            analyzer.min_net_profit_by_currency["EUR"] = Decimal("1")  # type: ignore[index]
        with pytest.raises(ValueError, match="currency USD"):
            self._analyze("USD", "9", dict(analyzer.min_net_profit_by_currency))

    def test_currency_mismatch_precedes_threshold_resolution(self) -> None:
        listing = CandidateListing("lot", "Lot", "", Decimal("10"), "EUR", "url")
        valuation = _make_valuation("Game", 20.0, currency="USD")
        analyzer = DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy.neutral(), min_net_profit_by_currency={}
        )

        with pytest.raises(CurrencyMismatchError, match="Currency mismatch"):
            analyzer.analyze(listing, [valuation], 1)

    def test_mixed_platforms_share_only_homogeneous_currency_threshold(self) -> None:
        listing = CandidateListing("lot", "Mixed platforms", "", Decimal("10"), "EUR", "url")
        valuations = [
            _make_valuation("Spider-Man", 8.0, currency="EUR", platform=Platform.PS5),
            _make_valuation("Minecraft", 7.0, currency="EUR", platform=Platform.PS4),
            _make_valuation("God of War", 6.0, currency="EUR", platform=Platform.PS4),
        ]
        analyzer = DefaultLotOpportunityAnalyzer(ResaleEconomicPolicy.neutral())

        lot = analyzer.analyze(listing, valuations, 3)

        assert lot.currency == "EUR"
        assert [valuation.game.platform for valuation in lot.game_valuations] == [
            Platform.PS5,
            Platform.PS4,
            Platform.PS4,
        ]
        assert lot.recommendation is Recommendation.BUY
