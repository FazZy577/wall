"""P1.9 recommendation-priority ranking regressions."""

import itertools

import pytest

from application.interfaces.opportunity_scanner import (
    RankingResult as ApplicationRankingResult,
)
from application.interfaces.opportunity_scanner import (
    RankingStrategy as ApplicationRankingStrategy,
)
from domain.interfaces.arbitrage_opportunity_detector import Recommendation
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from tests.unit.test_default_opportunity_ranker import _make_opportunity


def _ids(result: ApplicationRankingResult) -> list[str]:
    return [item.listing.listing_id for item in result.ordered_opportunities]


@pytest.mark.parametrize(
    ("first_recommendation", "first_score", "second_recommendation", "second_score"),
    [
        (Recommendation.BUY, 1.0, Recommendation.SKIP, 100.0),
        (Recommendation.BUY, 10.0, Recommendation.MAYBE, 99.0),
        (Recommendation.MAYBE, 5.0, Recommendation.SKIP, 100.0),
    ],
)
def test_higher_priority_recommendation_is_an_absolute_barrier(
    first_recommendation: Recommendation,
    first_score: float,
    second_recommendation: Recommendation,
    second_score: float,
) -> None:
    higher_priority = _make_opportunity(
        listing_id="higher-priority",
        recommendation=first_recommendation,
        opportunity_score=first_score,
    )
    lower_priority = _make_opportunity(
        listing_id="lower-priority",
        recommendation=second_recommendation,
        opportunity_score=second_score,
    )

    result = ApplicationRankingResult.from_opportunities(
        [lower_priority, higher_priority]
    )

    assert result.ordered_opportunities == [higher_priority, lower_priority]
    assert higher_priority.opportunity_score == first_score
    assert lower_priority.opportunity_score == second_score
    assert higher_priority.recommendation is first_recommendation
    assert lower_priority.recommendation is second_recommendation


def test_complete_mixed_scenario_groups_then_sorts_by_score() -> None:
    opportunities = [
        _make_opportunity(listing_id="buy-20", recommendation=Recommendation.BUY, opportunity_score=20),
        _make_opportunity(listing_id="skip-100", recommendation=Recommendation.SKIP, opportunity_score=100),
        _make_opportunity(listing_id="maybe-90", recommendation=Recommendation.MAYBE, opportunity_score=90),
        _make_opportunity(listing_id="buy-80", recommendation=Recommendation.BUY, opportunity_score=80),
        _make_opportunity(listing_id="skip-30", recommendation=Recommendation.SKIP, opportunity_score=30),
        _make_opportunity(listing_id="maybe-40", recommendation=Recommendation.MAYBE, opportunity_score=40),
    ]
    original = list(opportunities)

    result = ApplicationRankingResult.from_opportunities(opportunities)

    assert _ids(result) == [
        "buy-80", "buy-20", "maybe-90", "maybe-40", "skip-100", "skip-30"
    ]
    assert (result.buy_count, result.maybe_count, result.skip_count) == (2, 2, 2)
    assert opportunities == original
    assert len(result.ordered_opportunities) == 6


@pytest.mark.parametrize("recommendation", list(Recommendation))
def test_same_recommendation_preserves_historical_score_order(
    recommendation: Recommendation,
) -> None:
    opportunities = [
        _make_opportunity(listing_id="low", recommendation=recommendation, opportunity_score=10),
        _make_opportunity(listing_id="high", recommendation=recommendation, opportunity_score=90),
        _make_opportunity(listing_id="mid", recommendation=recommendation, opportunity_score=50),
    ]

    assert _ids(ApplicationRankingResult.from_opportunities(opportunities)) == [
        "high", "mid", "low"
    ]


def test_equal_metrics_keep_input_order_and_different_recommendations_do_not() -> None:
    first = _make_opportunity(listing_id="z", recommendation=Recommendation.BUY, opportunity_score=50)
    second = _make_opportunity(listing_id="a", recommendation=Recommendation.BUY, opportunity_score=50)
    maybe = _make_opportunity(listing_id="maybe", recommendation=Recommendation.MAYBE, opportunity_score=50)
    skip = _make_opportunity(listing_id="skip", recommendation=Recommendation.SKIP, opportunity_score=50)

    result = ApplicationRankingResult.from_opportunities([skip, first, maybe, second])

    assert result.ordered_opportunities == [first, second, maybe, skip]


@pytest.mark.parametrize(
    "strategy",
    [strategy for strategy in ApplicationRankingStrategy if strategy is not ApplicationRankingStrategy.OPPORTUNITY_SCORE],
)
def test_unimplemented_strategy_keeps_score_fallback_with_priority(
    strategy: ApplicationRankingStrategy,
    caplog: pytest.LogCaptureFixture,
) -> None:
    buy = _make_opportunity(listing_id="buy", recommendation=Recommendation.BUY, opportunity_score=1)
    skip = _make_opportunity(listing_id="skip", recommendation=Recommendation.SKIP, opportunity_score=100)

    result = ApplicationRankingResult.from_opportunities([skip, buy], strategy)

    assert result.ordered_opportunities == [buy, skip]
    assert "Falling back" in caplog.text


def test_priority_property_and_determinism_for_all_recommendation_permutations() -> None:
    priority = {Recommendation.BUY: 0, Recommendation.MAYBE: 1, Recommendation.SKIP: 2}
    for permutation in itertools.permutations(Recommendation):
        opportunities = [
            _make_opportunity(
                listing_id=f"{recommendation.value}-{index}",
                recommendation=recommendation,
                opportunity_score=float(index),
            )
            for index, recommendation in enumerate(permutation)
        ]
        first = ApplicationRankingResult.from_opportunities(opportunities)
        second = ApplicationRankingResult.from_opportunities(opportunities)
        priorities = [priority[item.recommendation] for item in first.ordered_opportunities]

        assert priorities == sorted(priorities)
        assert first.ordered_opportunities == second.ordered_opportunities


def test_standalone_ranker_uses_same_barrier_when_skip_is_included() -> None:
    buy = _make_opportunity(listing_id="buy", recommendation=Recommendation.BUY, opportunity_score=1)
    skip = _make_opportunity(listing_id="skip", recommendation=Recommendation.SKIP, opportunity_score=100)

    result = DefaultOpportunityRanker().rank([skip, buy], include_skip=True)

    assert result.ordered_opportunities == [buy, skip]
