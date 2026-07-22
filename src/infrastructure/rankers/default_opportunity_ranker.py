"""Default opportunity ranker implementation.

Ranks arbitrage opportunities by a configurable strategy.
Contains NO business logic — only ordering and summarization.
"""

import statistics as std_stats
from collections.abc import Sequence
from datetime import UTC, datetime

from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    Recommendation,
)
from domain.interfaces.opportunity_ranker import (
    InvalidRankingLimitError,
    IOpportunityRanker,
    RankingResult,
    RankingStrategy,
    UnsupportedRankingStrategyError,
)

# Recommendation sort order: BUY = 0, MAYBE = 1, SKIP = 2
_RECOMMENDATION_ORDER: dict[Recommendation, int] = {
    Recommendation.BUY: 0,
    Recommendation.MAYBE: 1,
    Recommendation.SKIP: 2,
}


class DefaultOpportunityRanker(IOpportunityRanker):
    """Default implementation that ranks opportunities.

    Ranks by Recommendation first (BUY > MAYBE > SKIP), then by
    opportunity_score descending with deterministic tie-breaking.
    The ranker itself contains NO business logic — it only sorts.
    """

    def __init__(
        self,
        strategy: RankingStrategy = RankingStrategy.OPPORTUNITY_SCORE,
    ) -> None:
        """Initialize ranker with the configured strategy.

        Args:
            strategy: Ranking strategy to use (default: OPPORTUNITY_SCORE).
                Only OPPORTUNITY_SCORE is currently implemented.
        """
        self._validate_strategy(strategy)
        self.strategy = strategy

    @staticmethod
    def _validate_strategy(strategy: RankingStrategy) -> None:
        """Raise if the strategy is not implemented.

        Args:
            strategy: Strategy to validate

        Raises:
            UnsupportedRankingStrategyError: If strategy is not implemented
        """
        if strategy != RankingStrategy.OPPORTUNITY_SCORE:
            raise UnsupportedRankingStrategyError(strategy.value)

    def _sort_key(self, opp: ArbitrageOpportunity) -> tuple[int, float, float, float, float, str]:
        """Compute the sort key for a single opportunity.

        Returns a tuple for deterministic multi-criteria sorting.

        Primary: Recommendation (BUY=0, MAYBE=1, SKIP=2).
        Secondary: opportunity_score (descending — negated).
        Tie-breakers (all descending except listing_id ascending):
          1. net_profit (negated)
          2. confidence_score (negated)
          3. net_roi_percentage (negated)
          4. listing_id (ascending — not negated)

        Args:
            opp: Opportunity to compute key for

        Returns:
            Tuple suitable for sorted() key
        """
        return (
            _RECOMMENDATION_ORDER[opp.recommendation],
            -opp.opportunity_score,
            -opp.net_profit,
            -opp.confidence_score,
            -opp.net_roi_percentage,
            opp.listing.listing_id,
        )

    def rank(
        self,
        opportunities: Sequence[ArbitrageOpportunity],
        limit: int | None = None,
        include_skip: bool = False,
    ) -> RankingResult:
        """Rank opportunities by the configured strategy.

        Does NOT modify the input list or any opportunity.

        Default behavior (include_skip=False):
        - Filters out SKIP opportunities
        - Sorts BUY and MAYBE by Recommendation then score
        - A SKIP never displaces a BUY or MAYBE

        When include_skip=True:
        - Includes all opportunities
        - SKIP sorts after BUY and MAYBE

        Args:
            opportunities: Opportunities to rank
            limit: Maximum number to return (None = all, 0 = empty, <0 = error)
            include_skip: Whether to include SKIP recommendations (default False)

        Returns:
            RankingResult with ordered opportunities and summary statistics

        Raises:
            InvalidRankingLimitError: If limit is negative
        """
        # Validate limit
        if limit is not None and limit < 0:
            raise InvalidRankingLimitError(limit)

        total_input = len(opportunities)

        # Compute counts over ALL input opportunities
        buy_count = sum(1 for o in opportunities if o.recommendation == Recommendation.BUY)
        maybe_count = sum(1 for o in opportunities if o.recommendation == Recommendation.MAYBE)
        skip_count = sum(1 for o in opportunities if o.recommendation == Recommendation.SKIP)

        # Filter SKIP if not included
        if include_skip:
            eligible = list(opportunities)
        else:
            eligible = [
                o for o in opportunities
                if o.recommendation != Recommendation.SKIP
            ]

        total_eligible = len(eligible)
        total_excluded = total_input - total_eligible

        # Sort (creates a new list — does not modify input)
        sorted_opps = sorted(eligible, key=self._sort_key)

        # Apply limit
        if limit is None:
            returned = sorted_opps
        elif limit == 0:
            returned = []
        else:
            returned = sorted_opps[:limit]

        total_returned = len(returned)

        # Compute score stats over ordered_opportunities (post-filter, post-limit)
        if total_returned > 0:
            scores = [o.opportunity_score for o in returned]
            best_score = round(max(scores), 2)
            average_score = round(std_stats.mean(scores), 2)
        else:
            best_score = 0.0
            average_score = 0.0

        return RankingResult(
            ordered_opportunities=returned,
            strategy=self.strategy,
            total_input=total_input,
            total_eligible=total_eligible,
            total_returned=total_returned,
            total_excluded=total_excluded,
            buy_count=buy_count,
            maybe_count=maybe_count,
            skip_count=skip_count,
            best_score=best_score,
            average_score=average_score,
            include_skip=include_skip,
            created_at=datetime.now(UTC),
        )
