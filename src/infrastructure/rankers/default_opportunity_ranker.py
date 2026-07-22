"""Canonical opportunity ranker implementation."""

from collections.abc import Sequence

from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    Recommendation,
)
from domain.interfaces.opportunity_ranker import IOpportunityRanker, RankingStrategy

_RECOMMENDATION_PRIORITY: dict[Recommendation, int] = {
    Recommendation.BUY: 0,
    Recommendation.MAYBE: 1,
    Recommendation.SKIP: 2,
}


class DefaultOpportunityRanker(IOpportunityRanker):
    """Rank every opportunity using the single supported strategy."""

    def rank(
        self,
        opportunities: Sequence[ArbitrageOpportunity],
        strategy: RankingStrategy = RankingStrategy.OPPORTUNITY_SCORE,
    ) -> list[ArbitrageOpportunity]:
        """Return a stable BUY/MAYBE/SKIP ranking without filtering."""
        del strategy
        return sorted(
            opportunities,
            key=lambda opportunity: (
                _RECOMMENDATION_PRIORITY[opportunity.recommendation],
                -opportunity.opportunity_score,
            ),
        )
