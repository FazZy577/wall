"""Opportunity ranker interface (port).

Defines the contract for ranking arbitrage opportunities.
This module is standalone — it is NOT integrated into the scanner yet.
Integration will happen in a future phase.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidRankingLimitError(Exception):
    """Raised when the limit parameter is negative."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Ranking limit must be >= 0, got {limit}")


class UnsupportedRankingStrategyError(Exception):
    """Raised when a ranking strategy is not yet implemented."""

    def __init__(self, strategy: str) -> None:
        self.strategy = strategy
        super().__init__(
            f"Ranking strategy '{strategy}' is not supported. "
            f"Only 'opportunity_score' is currently implemented."
        )


# ---------------------------------------------------------------------------
# RankingStrategy
# ---------------------------------------------------------------------------


class RankingStrategy(StrEnum):
    """Strategy for ranking arbitrage opportunities.

    Only OPPORTUNITY_SCORE is implemented. Future strategies:
        ABSOLUTE_PROFIT — sort by net_profit descending
        ROI — sort by net_roi_percentage descending
        MARKET_DISCOUNT — sort by acquisition_discount_to_reference_market_percentage descending
        CONFIDENCE — sort by confidence_score descending
        HYBRID — weighted combination of multiple factors
    """

    OPPORTUNITY_SCORE = "opportunity_score"


# ---------------------------------------------------------------------------
# RankingResult
# ---------------------------------------------------------------------------


@dataclass
class RankingResult:
    """Result of ranking a list of arbitrage opportunities.

    Provides the ordered list, summary statistics, and explainability.
    All counts (BUY/MAYBE/SKIP) are computed over ALL input opportunities.

    Attributes:
        ordered_opportunities: Sorted opportunities (post-filter, post-limit)
        strategy: Ranking strategy used
        total_input: Total opportunities received
        total_eligible: Opportunities after filtering SKIP (when include_skip=False)
        total_returned: Opportunities returned after applying limit
        total_excluded: SKIP opportunities excluded by filtering
        buy_count: BUY recommendations in all input
        maybe_count: MAYBE recommendations in all input
        skip_count: SKIP recommendations in all input
        best_score: Highest opportunity_score in ordered_opportunities (0.0 if empty)
        average_score: Mean opportunity_score in ordered_opportunities (0.0 if empty)
        include_skip: Whether SKIP opportunities were included
        created_at: Timestamp when ranking was computed
    """

    ordered_opportunities: list[ArbitrageOpportunity]
    strategy: RankingStrategy
    total_input: int
    total_eligible: int
    total_returned: int
    total_excluded: int
    buy_count: int
    maybe_count: int
    skip_count: int
    best_score: float
    average_score: float
    include_skip: bool
    created_at: datetime

    def explain(self, top_n: int = 10) -> str:
        """Generate deterministic human-readable ranking summary.

        Args:
            top_n: Number of top opportunities to show (default 10)

        Returns:
            Multi-line string with ranking summary and top opportunities
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("OPPORTUNITY RANKING")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"Strategy: {self.strategy.upper()}")
        lines.append("")
        lines.append(f"Total Input: {self.total_input}")
        lines.append(f"Total Eligible: {self.total_eligible}")
        lines.append(f"Total Excluded: {self.total_excluded}")
        lines.append(f"Total Returned: {self.total_returned}")
        lines.append("")
        lines.append("Recommendations:")
        lines.append(f"BUY: {self.buy_count}")
        lines.append(f"MAYBE: {self.maybe_count}")
        lines.append(f"SKIP: {self.skip_count}")
        lines.append("")
        lines.append(
            f"Best Score: {self.best_score:.2f}"
            if self.total_returned > 0
            else "Best Score: N/A"
        )
        lines.append(
            f"Average Score: {self.average_score:.2f}"
            if self.total_returned > 0
            else "Average Score: N/A"
        )

        if self.ordered_opportunities:
            lines.append("")
            lines.append("## TOP OPPORTUNITIES")
            lines.append("")

            for i, opp in enumerate(self.ordered_opportunities[:top_n], 1):
                lines.append(f"{i}. {opp.listing.title}")
                lines.append(f"   Score: {opp.opportunity_score:.2f}")
                lines.append(f"   Profit: EUR {opp.net_profit:.2f}")
                lines.append(f"   Recommendation: {opp.recommendation.upper()}")
                lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class IOpportunityRanker(ABC):
    """Interface for opportunity ranking implementations.

    Ranks arbitrage opportunities by a configurable strategy.
    The ranker contains NO business logic — it only orders and summarizes.
    """

    @abstractmethod
    def rank(
        self,
        opportunities: Sequence[ArbitrageOpportunity],
        limit: int | None = None,
        include_skip: bool = False,
    ) -> RankingResult:
        """Rank opportunities by the configured strategy.

        Default behavior (include_skip=False):
        - Includes BUY and MAYBE only
        - Excludes SKIP from the actionable ranking
        - SKIP opportunities are still counted in summary statistics

        When include_skip=True:
        - Includes BUY, MAYBE, and SKIP
        - SKIP appears after BUY and MAYBE in the ranking

        Primary sort: Recommendation (BUY > MAYBE > SKIP).
        Secondary sort: opportunity_score descending.
        Tie-breakers: net_profit, confidence_score, net_roi_percentage,
        listing_id ascending.

        Args:
            opportunities: Opportunities to rank (not modified)
            limit: Maximum number to return (None = all, 0 = empty, <0 = error)
            include_skip: Whether to include SKIP recommendations (default False)

        Returns:
            RankingResult with ordered opportunities and summary statistics

        Raises:
            InvalidRankingLimitError: If limit is negative
        """
        pass
