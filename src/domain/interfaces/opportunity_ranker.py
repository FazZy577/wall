"""Canonical port for ranking arbitrage opportunities."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import StrEnum

from domain.interfaces.arbitrage_opportunity_detector import ArbitrageOpportunity


class RankingStrategy(StrEnum):
    """Ranking strategies with a real production implementation."""

    OPPORTUNITY_SCORE = "opportunity_score"


class IOpportunityRanker(ABC):
    """Order all opportunities without filtering or mutation."""

    @abstractmethod
    def rank(
        self,
        opportunities: Sequence[ArbitrageOpportunity],
        strategy: RankingStrategy = RankingStrategy.OPPORTUNITY_SCORE,
    ) -> list[ArbitrageOpportunity]:
        """Return a new list ordered by recommendation and strategy."""
        pass
