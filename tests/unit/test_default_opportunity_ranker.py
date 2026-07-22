"""Unit tests for the single canonical opportunity ranking path."""

import itertools
from datetime import datetime

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.resale_economics import EconomicBreakdown
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    ReasonCode,
    Recommendation,
)
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from domain.interfaces.opportunity_ranker import RankingStrategy
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker


def _make_game(name: str = "Test Game") -> DetectedGame:
    return DetectedGame(
        name, name.lower(), Platform.PS4, 1.0, DetectionMethod.EXACT_MATCH
    )


def _make_opportunity(
    *,
    listing_id: str = "test001",
    title: str = "Test Game PS4",
    opportunity_score: float = 70.0,
    net_profit: float = 20.0,
    confidence_score: float = 0.80,
    net_roi_percentage: float = 50.0,
    acquisition_discount_to_reference_market_percentage: float = 30.0,
    recommendation: Recommendation = Recommendation.BUY,
    reason: ReasonCode = ReasonCode.UNDERVALUED,
    market_price: float = 30.0,
    listing_price: float = 10.0,
) -> ArbitrageOpportunity:
    listing = CandidateListing(
        listing_id, title, "Good condition", listing_price, "EUR",
        f"https://wallapop.com/item/{listing_id}",
    )
    total_cost = net_profit / (net_roi_percentage / 100.0) if net_roi_percentage else listing_price
    acquisition_price = market_price * (
        1 - acquisition_discount_to_reference_market_percentage / 100.0
    )
    breakdown = EconomicBreakdown(
        reference_market_value=market_price,
        expected_item_sale_prices=(market_price,),
        expected_sale_revenue=market_price,
        quick_sale_discount_total=0.0,
        selling_fees=0.0,
        fixed_selling_costs=0.0,
        safety_buffer=0.0,
        acquisition_price=acquisition_price,
        acquisition_overhead=total_cost - acquisition_price,
        total_acquisition_cost=total_cost,
        net_expected_proceeds=net_profit + total_cost,
        net_profit=net_profit,
        break_even_sale_revenue=total_cost,
        item_count=1,
    )
    return ArbitrageOpportunity(
        listing=listing,
        game=_make_game(),
        market_price=market_price,
        listing_price=listing_price,
        confidence_score=confidence_score,
        confidence_level="high",  # type: ignore[arg-type]
        opportunity_score=opportunity_score,
        recommendation=recommendation,
        reason=reason,
        created_at=datetime.now(),
        economic_breakdown=breakdown,
    )


def _ids(opportunities: list[ArbitrageOpportunity]) -> list[str]:
    return [opportunity.listing.listing_id for opportunity in opportunities]


def test_only_real_strategy_is_exposed() -> None:
    assert list(RankingStrategy) == [RankingStrategy.OPPORTUNITY_SCORE]
    assert not hasattr(RankingStrategy, "ABSOLUTE_PROFIT")
    assert not hasattr(RankingStrategy, "ROI")
    assert not hasattr(RankingStrategy, "MARKET_DISCOUNT")
    assert not hasattr(RankingStrategy, "CUSTOM")
    with pytest.raises(ValueError):
        RankingStrategy("roi")
    with pytest.raises(ValueError):
        RankingStrategy("absolute_profit")


def test_ranker_groups_recommendations_then_orders_by_score() -> None:
    opportunities = [
        _make_opportunity(listing_id="skip-100", recommendation=Recommendation.SKIP, opportunity_score=100),
        _make_opportunity(listing_id="buy-20", recommendation=Recommendation.BUY, opportunity_score=20),
        _make_opportunity(listing_id="maybe-90", recommendation=Recommendation.MAYBE, opportunity_score=90),
        _make_opportunity(listing_id="buy-80", recommendation=Recommendation.BUY, opportunity_score=80),
    ]

    ranked = DefaultOpportunityRanker().rank(opportunities)

    assert _ids(ranked) == ["buy-80", "buy-20", "maybe-90", "skip-100"]


@pytest.mark.parametrize("recommendation", list(Recommendation))
def test_equal_keys_preserve_input_order(recommendation: Recommendation) -> None:
    first = _make_opportunity(listing_id="first", recommendation=recommendation, opportunity_score=50)
    second = _make_opportunity(listing_id="second", recommendation=recommendation, opportunity_score=50)

    assert DefaultOpportunityRanker().rank([first, second]) == [first, second]


def test_ranker_returns_all_items_and_does_not_mutate_input() -> None:
    opportunities = [
        _make_opportunity(listing_id="skip", recommendation=Recommendation.SKIP),
        _make_opportunity(listing_id="buy", recommendation=Recommendation.BUY),
    ]
    original = list(opportunities)

    ranked = DefaultOpportunityRanker().rank(opportunities)

    assert opportunities == original
    assert set(map(id, ranked)) == set(map(id, opportunities))


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        (Recommendation.BUY, Recommendation.MAYBE),
        (Recommendation.BUY, Recommendation.SKIP),
        (Recommendation.MAYBE, Recommendation.SKIP),
    ],
)
def test_recommendation_priority_is_an_absolute_barrier(
    higher: Recommendation, lower: Recommendation
) -> None:
    preferred = _make_opportunity(
        listing_id="preferred", recommendation=higher, opportunity_score=1
    )
    other = _make_opportunity(
        listing_id="other", recommendation=lower, opportunity_score=100
    )

    assert DefaultOpportunityRanker().rank([other, preferred]) == [preferred, other]


@pytest.mark.parametrize("recommendation", list(Recommendation))
def test_score_descends_within_each_recommendation(
    recommendation: Recommendation,
) -> None:
    low = _make_opportunity(
        listing_id="low", recommendation=recommendation, opportunity_score=10
    )
    high = _make_opportunity(
        listing_id="high", recommendation=recommendation, opportunity_score=90
    )
    middle = _make_opportunity(
        listing_id="middle", recommendation=recommendation, opportunity_score=50
    )

    assert _ids(DefaultOpportunityRanker().rank([low, high, middle])) == [
        "high",
        "middle",
        "low",
    ]


@pytest.mark.parametrize(
    "different_field",
    ["net_profit", "confidence_score", "net_roi_percentage", "listing_id", "listing_price"],
)
def test_equal_primary_keys_have_no_hidden_tie_breaker(different_field: str) -> None:
    first_values: dict[str, object] = {"listing_id": "z-first"}
    second_values: dict[str, object] = {"listing_id": "a-second"}
    if different_field != "listing_id":
        first_values[different_field] = 1.0
        second_values[different_field] = 99.0
    first = _make_opportunity(
        **first_values, recommendation=Recommendation.BUY, opportunity_score=50  # type: ignore[arg-type]
    )
    second = _make_opportunity(
        **second_values, recommendation=Recommendation.BUY, opportunity_score=50  # type: ignore[arg-type]
    )

    assert DefaultOpportunityRanker().rank([first, second]) == [first, second]


@pytest.mark.parametrize("permutation", list(itertools.permutations(range(4))))
def test_order_is_correct_for_every_four_item_input_permutation(
    permutation: tuple[int, ...],
) -> None:
    canonical = [
        _make_opportunity(listing_id="buy-high", recommendation=Recommendation.BUY, opportunity_score=90),
        _make_opportunity(listing_id="buy-low", recommendation=Recommendation.BUY, opportunity_score=10),
        _make_opportunity(listing_id="maybe", recommendation=Recommendation.MAYBE, opportunity_score=100),
        _make_opportunity(listing_id="skip", recommendation=Recommendation.SKIP, opportunity_score=100),
    ]

    ranked = DefaultOpportunityRanker().rank([canonical[index] for index in permutation])

    assert ranked == canonical


@pytest.mark.parametrize("size", [0, 1, 2])
def test_repeated_ranking_is_deterministic_for_small_inputs(size: int) -> None:
    opportunities = [
        _make_opportunity(listing_id=str(index), opportunity_score=float(index))
        for index in range(size)
    ]
    ranker = DefaultOpportunityRanker()

    assert ranker.rank(opportunities) == ranker.rank(opportunities)
