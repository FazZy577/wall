"""Unit tests for DefaultOpportunityRanker.

Tests deterministic ranking, tie-breaking, limit handling,
SKIP filtering, summary statistics, explainability, and immutability.
No external calls. No Playwright. No Wallapop.
"""

from datetime import datetime

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    ReasonCode,
    Recommendation,
)
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.interfaces.opportunity_ranker import (
    InvalidRankingLimitError,
    RankingStrategy,
    UnsupportedRankingStrategyError,
)
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_game(name: str = "Test Game") -> DetectedGame:
    """Create a sample DetectedGame."""
    return DetectedGame(
        canonical_name=name,
        matched_text=name.lower(),
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def _make_opportunity(
    *,
    listing_id: str = "test001",
    title: str = "Test Game PS4",
    opportunity_score: float = 70.0,
    estimated_profit: float = 20.0,
    confidence_score: float = 0.80,
    roi_percentage: float = 50.0,
    market_discount_percentage: float = 30.0,
    recommendation: Recommendation = Recommendation.BUY,
    reason: ReasonCode = ReasonCode.UNDERVALUED,
    market_price: float = 30.0,
    listing_price: float = 10.0,
) -> ArbitrageOpportunity:
    """Create an ArbitrageOpportunity with explicit fields.

    All parameters are keyword-only to avoid positional confusion.
    """
    listing = CandidateListing(
        listing_id=listing_id,
        title=title,
        description="Good condition",
        price=listing_price,
        currency="EUR",
        url=f"https://wallapop.com/item/{listing_id}",
    )
    return ArbitrageOpportunity(
        listing=listing,
        game=_make_game(),
        market_price=market_price,
        listing_price=listing_price,
        estimated_profit=estimated_profit,
        profit_margin_percentage=round(estimated_profit / market_price * 100, 1),
        roi_percentage=roi_percentage,
        market_discount_percentage=market_discount_percentage,
        break_even_price=listing_price,
        confidence_score=confidence_score,
        confidence_level="high",  # type: ignore[arg-type]
        opportunity_score=opportunity_score,
        recommendation=recommendation,
        reason=reason,
        created_at=datetime.now(),
    )


@pytest.fixture
def ranker() -> DefaultOpportunityRanker:
    """Create a ranker with default strategy."""
    return DefaultOpportunityRanker()


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    """Test ranker construction."""

    def test_default_strategy(self) -> None:
        """Should use OPPORTUNITY_SCORE by default."""
        ranker = DefaultOpportunityRanker()
        assert ranker.strategy == RankingStrategy.OPPORTUNITY_SCORE

    def test_explicit_strategy(self) -> None:
        """Should accept explicit strategy."""
        ranker = DefaultOpportunityRanker(RankingStrategy.OPPORTUNITY_SCORE)
        assert ranker.strategy == RankingStrategy.OPPORTUNITY_SCORE


# ---------------------------------------------------------------------------
# Recommendation-aware ranking (NEW behavior)
# ---------------------------------------------------------------------------


class TestRecommendationOrdering:
    """Test that Recommendation is the primary sort key."""

    def test_buy_before_skip_regardless_of_score(self, ranker: DefaultOpportunityRanker) -> None:
        """BUY score 75 should appear before SKIP score 90."""
        opps = [
            _make_opportunity(
                listing_id="skip_high",
                recommendation=Recommendation.SKIP,
                opportunity_score=90.0,
                reason=ReasonCode.LOW_CONFIDENCE,
            ),
            _make_opportunity(
                listing_id="buy_low",
                recommendation=Recommendation.BUY,
                opportunity_score=75.0,
            ),
        ]

        result = ranker.rank(opps, include_skip=True)

        # BUY must come before SKIP regardless of score
        assert result.ordered_opportunities[0].listing.listing_id == "buy_low"
        assert result.ordered_opportunities[1].listing.listing_id == "skip_high"

    def test_maybe_before_skip_regardless_of_score(self, ranker: DefaultOpportunityRanker) -> None:
        """MAYBE should appear before SKIP regardless of score."""
        opps = [
            _make_opportunity(
                listing_id="skip_high",
                recommendation=Recommendation.SKIP,
                opportunity_score=95.0,
            ),
            _make_opportunity(
                listing_id="maybe_low",
                recommendation=Recommendation.MAYBE,
                opportunity_score=30.0,
            ),
        ]

        result = ranker.rank(opps, include_skip=True)

        assert result.ordered_opportunities[0].listing.listing_id == "maybe_low"
        assert result.ordered_opportunities[1].listing.listing_id == "skip_high"

    def test_buy_before_maybe_before_skip(self, ranker: DefaultOpportunityRanker) -> None:
        """Full order: BUY > MAYBE > SKIP."""
        opps = [
            _make_opportunity(
                listing_id="skip1",
                recommendation=Recommendation.SKIP,
                opportunity_score=90.0,
            ),
            _make_opportunity(
                listing_id="buy1",
                recommendation=Recommendation.BUY,
                opportunity_score=50.0,
            ),
            _make_opportunity(
                listing_id="maybe1",
                recommendation=Recommendation.MAYBE,
                opportunity_score=80.0,
            ),
        ]

        result = ranker.rank(opps, include_skip=True)

        ids = [o.listing.listing_id for o in result.ordered_opportunities]
        assert ids == ["buy1", "maybe1", "skip1"]

    def test_within_buy_sorted_by_score_desc(self, ranker: DefaultOpportunityRanker) -> None:
        """Within BUY, sort by opportunity_score descending."""
        opps = [
            _make_opportunity(
                listing_id="buy_low",
                recommendation=Recommendation.BUY,
                opportunity_score=60.0,
            ),
            _make_opportunity(
                listing_id="buy_high",
                recommendation=Recommendation.BUY,
                opportunity_score=92.0,
            ),
        ]

        result = ranker.rank(opps)

        ids = [o.listing.listing_id for o in result.ordered_opportunities]
        assert ids == ["buy_high", "buy_low"]


# ---------------------------------------------------------------------------
# SKIP filtering
# ---------------------------------------------------------------------------


class TestSkipFiltering:
    """Test include_skip parameter behavior."""

    def test_include_skip_false_excludes_skip(self, ranker: DefaultOpportunityRanker) -> None:
        """Default (include_skip=False) should exclude SKIP."""
        opps = [
            _make_opportunity(
                listing_id="buy1",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
            ),
            _make_opportunity(
                listing_id="skip1",
                recommendation=Recommendation.SKIP,
                opportunity_score=90.0,
            ),
            _make_opportunity(
                listing_id="maybe1",
                recommendation=Recommendation.MAYBE,
                opportunity_score=70.0,
            ),
        ]

        result = ranker.rank(opps)  # include_skip=False by default

        ids = [o.listing.listing_id for o in result.ordered_opportunities]
        assert "skip1" not in ids
        assert ids == ["buy1", "maybe1"]
        assert result.total_input == 3
        assert result.total_eligible == 2
        assert result.total_excluded == 1
        assert result.total_returned == 2
        assert result.skip_count == 1  # counted over input
        assert result.include_skip is False

    def test_include_skip_true_includes_skip(self, ranker: DefaultOpportunityRanker) -> None:
        """include_skip=True should include SKIP after BUY and MAYBE."""
        opps = [
            _make_opportunity(
                listing_id="skip1",
                recommendation=Recommendation.SKIP,
                opportunity_score=90.0,
            ),
            _make_opportunity(
                listing_id="buy1",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
            ),
            _make_opportunity(
                listing_id="maybe1",
                recommendation=Recommendation.MAYBE,
                opportunity_score=70.0,
            ),
        ]

        result = ranker.rank(opps, include_skip=True)

        ids = [o.listing.listing_id for o in result.ordered_opportunities]
        assert ids == ["buy1", "maybe1", "skip1"]
        assert result.total_input == 3
        assert result.total_eligible == 3
        assert result.total_excluded == 0
        assert result.include_skip is True

    def test_only_skip_with_include_skip_false(self, ranker: DefaultOpportunityRanker) -> None:
        """All SKIP with include_skip=False should return empty."""
        opps = [
            _make_opportunity(
                listing_id="skip1",
                recommendation=Recommendation.SKIP,
                opportunity_score=90.0,
            ),
            _make_opportunity(
                listing_id="skip2",
                recommendation=Recommendation.SKIP,
                opportunity_score=80.0,
            ),
        ]

        result = ranker.rank(opps)  # include_skip=False

        assert len(result.ordered_opportunities) == 0
        assert result.total_input == 2
        assert result.total_eligible == 0
        assert result.total_excluded == 2
        assert result.total_returned == 0
        assert result.buy_count == 0
        assert result.maybe_count == 0
        assert result.skip_count == 2
        assert result.best_score == 0.0
        assert result.average_score == 0.0

    def test_skip_never_displaces_buy_with_limit(self, ranker: DefaultOpportunityRanker) -> None:
        """With limit, SKIP should never push BUY out of the TOP."""
        opps = [
            _make_opportunity(
                listing_id="skip_high",
                recommendation=Recommendation.SKIP,
                opportunity_score=95.0,
            ),
            _make_opportunity(
                listing_id="buy1",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
            ),
            _make_opportunity(
                listing_id="buy2",
                recommendation=Recommendation.BUY,
                opportunity_score=75.0,
            ),
        ]

        # With include_skip=False, limit=2 в†’ both BUYs returned
        result = ranker.rank(opps, limit=2, include_skip=False)

        ids = [o.listing.listing_id for o in result.ordered_opportunities]
        assert ids == ["buy1", "buy2"]
        assert "skip_high" not in ids
        assert result.total_returned == 2

        # With include_skip=True, limit=2 в†’ BUY first, then SKIP
        # The SKIP at 95 still comes AFTER both BUYs because Recommendation is primary
        result2 = ranker.rank(opps, limit=2, include_skip=True)

        ids2 = [o.listing.listing_id for o in result2.ordered_opportunities]
        assert ids2 == ["buy1", "buy2"]  # SKIP doesn't displace BUY
        assert "skip_high" not in ids2


# ---------------------------------------------------------------------------
# Limit applied after filtering
# ---------------------------------------------------------------------------


class TestLimitAfterFilter:
    """Test that limit is applied after filtering and sorting."""

    def test_limit_applied_after_filtering(self, ranker: DefaultOpportunityRanker) -> None:
        """limit should count eligible opportunities, not input."""
        opps = [
            _make_opportunity(
                listing_id="skip1",
                recommendation=Recommendation.SKIP,
                opportunity_score=90.0,
            ),
            _make_opportunity(
                listing_id="buy_low",
                recommendation=Recommendation.BUY,
                opportunity_score=60.0,
            ),
            _make_opportunity(
                listing_id="buy_high",
                recommendation=Recommendation.BUY,
                opportunity_score=92.0,
            ),
            _make_opportunity(
                listing_id="skip2",
                recommendation=Recommendation.SKIP,
                opportunity_score=80.0,
            ),
        ]

        result = ranker.rank(opps, limit=1)  # include_skip=False

        # Only 1 returned (limit=1 applied to 2 eligible BUYs)
        assert result.total_input == 4
        assert result.total_eligible == 2
        assert result.total_excluded == 2
        assert result.total_returned == 1
        assert len(result.ordered_opportunities) == 1
        assert result.ordered_opportunities[0].listing.listing_id == "buy_high"


# ---------------------------------------------------------------------------
# Tie-breaking
# ---------------------------------------------------------------------------


class TestTieBreaking:
    """Test deterministic tie-breaking within same Recommendation."""

    def test_tie_break_by_profit(self, ranker: DefaultOpportunityRanker) -> None:
        """When score equal, higher profit should come first."""
        opps = [
            _make_opportunity(
                listing_id="low_profit",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=10.0,
            ),
            _make_opportunity(
                listing_id="high_profit",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=65.0,
            ),
        ]

        result = ranker.rank(opps)

        assert result.ordered_opportunities[0].listing.listing_id == "high_profit"
        assert result.ordered_opportunities[1].listing.listing_id == "low_profit"

    def test_tie_break_by_confidence(self, ranker: DefaultOpportunityRanker) -> None:
        """When score and profit equal, higher confidence first."""
        opps = [
            _make_opportunity(
                listing_id="low_conf",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=20.0,
                confidence_score=0.50,
            ),
            _make_opportunity(
                listing_id="high_conf",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=20.0,
                confidence_score=0.95,
            ),
        ]

        result = ranker.rank(opps)

        assert result.ordered_opportunities[0].listing.listing_id == "high_conf"
        assert result.ordered_opportunities[1].listing.listing_id == "low_conf"

    def test_tie_break_by_roi(self, ranker: DefaultOpportunityRanker) -> None:
        """When score, profit, confidence equal, higher ROI first."""
        opps = [
            _make_opportunity(
                listing_id="low_roi",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=20.0,
                confidence_score=0.80,
                roi_percentage=30.0,
            ),
            _make_opportunity(
                listing_id="high_roi",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=20.0,
                confidence_score=0.80,
                roi_percentage=200.0,
            ),
        ]

        result = ranker.rank(opps)

        assert result.ordered_opportunities[0].listing.listing_id == "high_roi"
        assert result.ordered_opportunities[1].listing.listing_id == "low_roi"

    def test_tie_break_by_listing_id(self, ranker: DefaultOpportunityRanker) -> None:
        """When all numeric criteria equal, listing_id ascending."""
        opps = [
            _make_opportunity(
                listing_id="zzz_last",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=20.0,
                confidence_score=0.80,
                roi_percentage=50.0,
            ),
            _make_opportunity(
                listing_id="aaa_first",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=20.0,
                confidence_score=0.80,
                roi_percentage=50.0,
            ),
        ]

        result = ranker.rank(opps)

        assert result.ordered_opportunities[0].listing.listing_id == "aaa_first"
        assert result.ordered_opportunities[1].listing.listing_id == "zzz_last"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Test that ranking is always deterministic."""

    def test_identical_results_on_repeated_calls(self, ranker: DefaultOpportunityRanker) -> None:
        """Should produce identical results every time."""
        opps = [
            _make_opportunity(
                listing_id="a", recommendation=Recommendation.BUY, opportunity_score=70.0
            ),
            _make_opportunity(
                listing_id="b", recommendation=Recommendation.BUY, opportunity_score=90.0
            ),
            _make_opportunity(
                listing_id="c", recommendation=Recommendation.BUY, opportunity_score=80.0
            ),
        ]

        results = [ranker.rank(opps) for _ in range(5)]

        for r in results:
            ids = [o.listing.listing_id for o in r.ordered_opportunities]
            assert ids == ["b", "c", "a"]


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    """Test that input is never modified."""

    def test_original_list_not_modified(self, ranker: DefaultOpportunityRanker) -> None:
        """Should not modify the original list."""
        opps = [
            _make_opportunity(
                listing_id="c", recommendation=Recommendation.BUY, opportunity_score=30.0
            ),
            _make_opportunity(
                listing_id="a", recommendation=Recommendation.BUY, opportunity_score=90.0
            ),
            _make_opportunity(
                listing_id="b", recommendation=Recommendation.BUY, opportunity_score=50.0
            ),
        ]
        original_order = [o.listing.listing_id for o in opps]

        ranker.rank(opps)

        assert [o.listing.listing_id for o in opps] == original_order

    def test_original_opportunities_not_modified(self, ranker: DefaultOpportunityRanker) -> None:
        """Should not modify any opportunity object."""
        opp = _make_opportunity(
            listing_id="test",
            opportunity_score=75.0,
            estimated_profit=25.0,
        )
        original_score = opp.opportunity_score
        original_profit = opp.estimated_profit

        ranker.rank([opp])

        assert opp.opportunity_score == original_score
        assert opp.estimated_profit == original_profit

    def test_result_is_new_list(self, ranker: DefaultOpportunityRanker) -> None:
        """Should return a new list, not the original."""
        opps = [_make_opportunity(listing_id="a")]
        result = ranker.rank(opps)

        assert result.ordered_opportunities is not opps


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


class TestLimit:
    """Test limit parameter behavior."""

    def test_limit_none_returns_all_eligible(self, ranker: DefaultOpportunityRanker) -> None:
        """None limit should return all eligible."""
        opps = [
            _make_opportunity(
                listing_id=str(i),
                recommendation=Recommendation.BUY,
                opportunity_score=100.0 - i,
            )
            for i in range(10)
        ]
        result = ranker.rank(opps, limit=None)

        assert result.total_input == 10
        assert result.total_eligible == 10
        assert result.total_returned == 10

    def test_limit_zero_returns_empty(self, ranker: DefaultOpportunityRanker) -> None:
        """Limit 0 should return empty list."""
        opps = [
            _make_opportunity(
                listing_id=str(i),
                recommendation=Recommendation.BUY,
                opportunity_score=100.0 - i,
            )
            for i in range(5)
        ]
        result = ranker.rank(opps, limit=0)

        assert result.total_input == 5
        assert result.total_eligible == 5
        assert result.total_returned == 0
        assert len(result.ordered_opportunities) == 0
        assert result.buy_count == 5
        assert result.best_score == 0.0
        assert result.average_score == 0.0

    def test_limit_less_than_eligible(self, ranker: DefaultOpportunityRanker) -> None:
        """Limit < eligible should return only top N."""
        opps = [
            _make_opportunity(
                listing_id=str(i),
                recommendation=Recommendation.BUY,
                opportunity_score=100.0 - i,
            )
            for i in range(10)
        ]
        result = ranker.rank(opps, limit=3)

        assert result.total_eligible == 10
        assert result.total_returned == 3
        assert len(result.ordered_opportunities) == 3
        assert result.ordered_opportunities[0].opportunity_score == 100.0
        assert result.ordered_opportunities[2].opportunity_score == 98.0

    def test_limit_greater_than_eligible(self, ranker: DefaultOpportunityRanker) -> None:
        """Limit > eligible should return all eligible."""
        opps = [
            _make_opportunity(
                listing_id=str(i),
                recommendation=Recommendation.BUY,
                opportunity_score=100.0 - i,
            )
            for i in range(3)
        ]
        result = ranker.rank(opps, limit=100)

        assert result.total_eligible == 3
        assert result.total_returned == 3

    def test_limit_negative_raises(self, ranker: DefaultOpportunityRanker) -> None:
        """Negative limit should raise InvalidRankingLimitError."""
        opps = [_make_opportunity(listing_id="a")]

        with pytest.raises(InvalidRankingLimitError) as exc:
            ranker.rank(opps, limit=-1)

        assert exc.value.limit == -1
        assert "limit" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


class TestCounts:
    """Test BUY/MAYBE/SKIP counting over input."""

    def test_counts_over_all_input(self, ranker: DefaultOpportunityRanker) -> None:
        """Counts should be over ALL input, not just returned."""
        opps = [
            _make_opportunity(
                listing_id="b1", recommendation=Recommendation.BUY, opportunity_score=90.0
            ),
            _make_opportunity(
                listing_id="b2", recommendation=Recommendation.BUY, opportunity_score=80.0
            ),
            _make_opportunity(
                listing_id="s1", recommendation=Recommendation.SKIP, opportunity_score=30.0
            ),
            _make_opportunity(
                listing_id="s2", recommendation=Recommendation.SKIP, opportunity_score=20.0
            ),
            _make_opportunity(
                listing_id="m1", recommendation=Recommendation.MAYBE, opportunity_score=50.0
            ),
        ]

        result = ranker.rank(opps, limit=2)  # include_skip=False

        # Only 2 returned (BUYs), but counts are over all 5
        assert result.total_input == 5
        assert result.total_eligible == 3  # 2 BUY + 1 MAYBE
        assert result.total_excluded == 2  # 2 SKIPs filtered out
        assert result.total_returned == 2
        assert result.buy_count == 2
        assert result.maybe_count == 1
        assert result.skip_count == 2

    def test_buy_count(self, ranker: DefaultOpportunityRanker) -> None:
        """Should count BUY correctly."""
        opps = [
            _make_opportunity(
                listing_id="b1", recommendation=Recommendation.BUY, opportunity_score=80.0
            ),
            _make_opportunity(
                listing_id="b2", recommendation=Recommendation.BUY, opportunity_score=70.0
            ),
            _make_opportunity(
                listing_id="s1", recommendation=Recommendation.SKIP, opportunity_score=30.0
            ),
        ]

        result = ranker.rank(opps, include_skip=True)

        assert result.buy_count == 2
        assert result.maybe_count == 0
        assert result.skip_count == 1


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


class TestScores:
    """Test best_score and average_score over returned opportunities."""

    def test_best_score_over_returned(self, ranker: DefaultOpportunityRanker) -> None:
        """best_score should be max over returned, not input."""
        opps = [
            _make_opportunity(
                listing_id="buy_a",
                recommendation=Recommendation.BUY,
                opportunity_score=92.4,
            ),
            _make_opportunity(
                listing_id="skip_high",
                recommendation=Recommendation.SKIP,
                opportunity_score=99.0,  # Higher but excluded
            ),
            _make_opportunity(
                listing_id="buy_b",
                recommendation=Recommendation.BUY,
                opportunity_score=61.35,
            ),
        ]

        result = ranker.rank(opps)  # include_skip=False

        # best_score should be 92.4 (over BUYs only), not 99.0 (SKIP excluded)
        assert result.best_score == 92.4
        assert result.average_score == round((92.4 + 61.35) / 2, 2)

    def test_empty_scores_are_zero(self, ranker: DefaultOpportunityRanker) -> None:
        """Empty result should have 0.0 not None."""
        result = ranker.rank([])

        assert result.best_score == 0.0
        assert result.average_score == 0.0


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------


class TestExplain:
    """Test explain() method."""

    def test_explain_contains_key_info(self, ranker: DefaultOpportunityRanker) -> None:
        """Should contain new fields: total_input, total_eligible, total_excluded."""
        opps = [
            _make_opportunity(
                listing_id="b1",
                title="GTA V PS4",
                recommendation=Recommendation.BUY,
                opportunity_score=92.4,
                estimated_profit=25.0,
            ),
            _make_opportunity(
                listing_id="s1",
                title="Overpriced Game",
                recommendation=Recommendation.SKIP,
                opportunity_score=30.0,
                estimated_profit=-5.0,
            ),
        ]

        result = ranker.rank(opps)
        text = result.explain(top_n=2)

        assert "OPPORTUNITY RANKING" in text
        assert "OPPORTUNITY_SCORE" in text
        assert "Total Input: 2" in text
        assert "Total Eligible: 1" in text
        assert "Total Excluded: 1" in text
        assert "Total Returned: 1" in text
        assert "BUY: 1" in text
        assert "SKIP: 1" in text
        assert "1. GTA V PS4" in text
        assert "Score: 92.40" in text
        assert "Profit: EUR 25.00" in text
        assert "Recommendation: BUY" in text

    def test_explain_empty_with_na(self, ranker: DefaultOpportunityRanker) -> None:
        """Empty result should show N/A for scores."""
        result = ranker.rank([])
        text = result.explain()

        assert "Total Input: 0" in text
        assert "Best Score: N/A" in text
        assert "Average Score: N/A" in text

    def test_explain_deterministic(self, ranker: DefaultOpportunityRanker) -> None:
        """Should produce identical output on repeated calls."""
        opps = [
            _make_opportunity(
                listing_id="a",
                title="Game A",
                recommendation=Recommendation.BUY,
                opportunity_score=80.0,
                estimated_profit=15.0,
            ),
        ]

        result = ranker.rank(opps)
        text1 = result.explain()
        text2 = result.explain()

        assert text1 == text2


# ---------------------------------------------------------------------------
# RankingResult field coherence
# ---------------------------------------------------------------------------


class TestRankingResultCoherence:
    """Test that RankingResult fields are internally consistent."""

    def test_field_coherence(self, ranker: DefaultOpportunityRanker) -> None:
        """total_input = total_eligible + total_excluded."""
        opps = [
            _make_opportunity(
                listing_id="b1", recommendation=Recommendation.BUY, opportunity_score=80.0
            ),
            _make_opportunity(
                listing_id="s1", recommendation=Recommendation.SKIP, opportunity_score=30.0
            ),
            _make_opportunity(
                listing_id="s2", recommendation=Recommendation.SKIP, opportunity_score=20.0
            ),
        ]

        result = ranker.rank(opps)  # include_skip=False

        assert result.total_input == 3
        assert result.total_eligible == 1
        assert result.total_excluded == 2
        assert result.total_input == result.total_eligible + result.total_excluded
        assert result.total_returned <= result.total_eligible
        assert result.buy_count + result.maybe_count + result.skip_count == result.total_input

    def test_counts_sum_to_input(self, ranker: DefaultOpportunityRanker) -> None:
        """buy_count + maybe_count + skip_count == total_input."""
        opps = [
            _make_opportunity(
                listing_id="b1", recommendation=Recommendation.BUY, opportunity_score=90.0
            ),
            _make_opportunity(
                listing_id="m1", recommendation=Recommendation.MAYBE, opportunity_score=70.0
            ),
            _make_opportunity(
                listing_id="s1", recommendation=Recommendation.SKIP, opportunity_score=30.0
            ),
            _make_opportunity(
                listing_id="b2", recommendation=Recommendation.BUY, opportunity_score=85.0
            ),
        ]

        result = ranker.rank(opps, include_skip=True)

        assert result.buy_count + result.maybe_count + result.skip_count == result.total_input
        assert result.buy_count == 2
        assert result.maybe_count == 1
        assert result.skip_count == 1


# ---------------------------------------------------------------------------
# Strategy validation
# ---------------------------------------------------------------------------


class TestStrategyValidation:
    """Test strategy validation."""

    def test_valid_strategy_accepted(self) -> None:
        """OPPORTUNITY_SCORE should be accepted."""
        ranker = DefaultOpportunityRanker(RankingStrategy.OPPORTUNITY_SCORE)
        assert ranker.strategy == RankingStrategy.OPPORTUNITY_SCORE


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    """Test domain exceptions."""

    def test_invalid_ranking_limit_error(self) -> None:
        """Should create proper error with limit value."""
        error = InvalidRankingLimitError(-5)
        assert error.limit == -5
        assert "-5" in str(error)

    def test_unsupported_ranking_strategy_error(self) -> None:
        """Should create proper error with strategy name."""
        error = UnsupportedRankingStrategyError("absolute_profit")
        assert error.strategy == "absolute_profit"
        assert "absolute_profit" in str(error)
