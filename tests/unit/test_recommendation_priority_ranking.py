"""Ranking summary and recommendation-priority regressions."""

from application.interfaces.opportunity_scanner import RankingResult
from domain.interfaces.arbitrage_opportunity_detector import Recommendation
from domain.interfaces.opportunity_ranker import RankingStrategy
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker
from tests.unit.test_default_opportunity_ranker import _make_opportunity


def test_ranking_result_only_summarizes_supplied_order() -> None:
    skip = _make_opportunity(listing_id="skip", recommendation=Recommendation.SKIP, opportunity_score=90)
    buy = _make_opportunity(listing_id="buy", recommendation=Recommendation.BUY, opportunity_score=10)

    result = RankingResult.from_ranked_opportunities([skip, buy])

    assert result.ordered_opportunities == [skip, buy]
    assert result.strategy is RankingStrategy.OPPORTUNITY_SCORE
    assert result.total_opportunities == 2
    assert (result.buy_count, result.maybe_count, result.skip_count) == (1, 0, 1)
    assert (result.best_score, result.average_score) == (90, 50)


def test_canonical_ranker_enforces_recommendation_barrier() -> None:
    skip = _make_opportunity(listing_id="skip", recommendation=Recommendation.SKIP, opportunity_score=100)
    buy = _make_opportunity(listing_id="buy", recommendation=Recommendation.BUY, opportunity_score=1)

    ranked = DefaultOpportunityRanker().rank([skip, buy])
    result = RankingResult.from_ranked_opportunities(ranked)

    assert result.ordered_opportunities == [buy, skip]
