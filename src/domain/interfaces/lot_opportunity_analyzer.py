"""Lot opportunity analyzer interface (port).

Defines the contract for analyzing lot arbitrage opportunities.
The analyzer decides BUY/MAYBE/SKIP and computes opportunity scores.
It does NOT search for comparables or estimate market prices.
"""

from abc import ABC, abstractmethod

from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity


class ILotOpportunityAnalyzer(ABC):
    """Interface for lot opportunity analysis implementations.

    Receives a candidate listing and its game valuations, then:
    - Computes aggregate metrics (reference_market_value, profit, margin, ROI)
    - Determines BUY/MAYBE/SKIP recommendation
    - Calculates opportunity_score (0-100)
    - Builds the LotOpportunity

    The analyzer contains NO knowledge of:
    - Wallapop or any marketplace
    - Price collection or comparable listings
    - Statistical calculations or outlier removal
    """

    @abstractmethod
    def analyze(
        self,
        listing: CandidateListing,
        game_valuations: list[GameValuation],
        total_detected_games: int,
    ) -> LotOpportunity:
        """Analyze a candidate listing with its game valuations.

        Args:
            listing: The candidate listing (lot) being evaluated
            game_valuations: Successfully obtained game valuations
            total_detected_games: Total games detected in the listing
                (may differ from len(game_valuations) if some failed)

        Returns:
            LotOpportunity with recommendation, reason, and score
        """
        pass
