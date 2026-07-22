"""Deterministic lot opportunity scanner example.

Demonstrates the complete lot pipeline with fake dependencies:
PriceCollector -> DatasetBuilder -> Statistics -> OutlierRemoval ->
MarketPriceEstimator -> GameValuation -> LotOpportunityAnalyzer.

No Playwright. No Wallapop API calls.
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    IGameDetector,
    ListingText,
    Platform,
)
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    IMarketPriceEstimator,
    MarketPriceEstimate,
    ReasonCode,
)
from domain.interfaces.outlier_removal import (
    IOutlierRemoval,
    OutlierMethod,
    OutlierRemovalResult,
)
from domain.interfaces.price_collector import IPriceCollector
from domain.interfaces.price_dataset_builder import (
    IPriceDatasetBuilder,
    PriceDataset,
    PriceObservation,
)
from domain.interfaces.price_statistics import IPriceStatistics, PriceStatisticsResult
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)


class FakePriceCollector(IPriceCollector):
    """Returns deterministic comparable listings for each game."""

    def __init__(self, prices_by_game: dict[str, float]) -> None:
        self.prices_by_game = prices_by_game

    async def collect_comparables(
        self,
        game: DetectedGame,
        latitude: float,
        longitude: float,
        max_results: int | None = None,
    ) -> list[ComparableListing]:
        _ = latitude, longitude, max_results
        await asyncio.sleep(0)
        price = self.prices_by_game[game.canonical_name]
        return [
            ComparableListing(
                listing_id=f"comp-{game.canonical_name.lower().replace(' ', '-')}",
                title=f"{game.canonical_name} PS4",
                description="Comparable deterministic listing",
                price=price,
                currency="EUR",
                detected_game=game,
                url=f"https://example.com/{game.canonical_name.lower().replace(' ', '-')}",
            )
        ]


class FakePriceDatasetBuilder(IPriceDatasetBuilder):
    """Builds one observation per comparable listing."""

    def build(self, comparable_listings: list[object]) -> PriceDataset:
        comparables = [listing for listing in comparable_listings if isinstance(listing, ComparableListing)]
        observations = [
            PriceObservation(
                price=listing.price,
                currency=listing.currency,
                listing_id=listing.listing_id,
                title=listing.title,
                platform=listing.detected_game.platform,
                source="fake",
                raw_listing={"price": listing.price, "title": listing.title},
            )
            for listing in comparables
        ]
        return PriceDataset(
            observations=observations,
            game=comparables[0].detected_game,
            created_at=datetime.now(UTC),
            sample_size=len(observations),
        )


class FakePriceStatistics(IPriceStatistics):
    """Returns deterministic statistics for a single-price dataset."""

    def calculate(self, dataset: PriceDataset) -> PriceStatisticsResult:
        price = dataset.observations[0].price
        return PriceStatisticsResult(
            count=dataset.sample_size,
            min_price=price,
            max_price=price,
            mean_price=price,
            median_price=price,
            standard_deviation=0.0,
            variance=0.0,
            q1=price,
            q3=price,
            iqr=0.0,
            percentile_10=price,
            percentile_25=price,
            percentile_75=price,
            percentile_90=price,
        )


class FakeOutlierRemoval(IOutlierRemoval):
    """Keeps all observations."""

    def remove_outliers(
        self,
        dataset: PriceDataset,
        statistics: PriceStatisticsResult,
    ) -> OutlierRemovalResult:
        return OutlierRemovalResult(
            clean_dataset=dataset,
            removed_observations=[],
            removed_count=0,
            kept_count=dataset.sample_size,
            lower_bound=statistics.min_price,
            upper_bound=statistics.max_price,
            method=OutlierMethod.IQR,
        )


class FakeMarketPriceEstimator(IMarketPriceEstimator):
    """Uses the deterministic dataset median as market price."""

    def estimate(
        self,
        dataset: PriceDataset,
        statistics: PriceStatisticsResult,
        observations_removed: int,
    ) -> MarketPriceEstimate:
        return MarketPriceEstimate(
            estimated_price=statistics.median_price,
            currency=dataset.observations[0].currency,
            confidence_score=0.80,
            confidence_level=ConfidenceLevel.HIGH,
            strategy=EstimationStrategy.MEDIAN,
            reason_code=ReasonCode.NORMAL,
            sample_size=dataset.sample_size,
            observations_removed=observations_removed,
            outlier_percentage=0.0,
            minimum_price=statistics.min_price,
            maximum_price=statistics.max_price,
            standard_deviation=statistics.standard_deviation,
            iqr=statistics.iqr,
            coefficient_of_variation=0.0,
            game=dataset.game,
            created_at=datetime.now(UTC),
        )


def make_game(name: str) -> DetectedGame:
    """Create a deterministic detected game."""
    return DetectedGame(
        canonical_name=name,
        matched_text=name,
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


class FakeGameDetector(IGameDetector):
    """Return the games encoded by this deterministic example."""

    def detect_games(self, _listing_text: ListingText) -> list[DetectedGame]:
        return [make_game("GTA V"), make_game("RDR2"), make_game("Spider-Man")]


async def main() -> None:
    """Run the deterministic lot scanner example."""
    listing = CandidateListing(
        listing_id="lot-example-001",
        title="Lote PS4 GTA V RDR2 Spider-Man",
        description="GTA V, Red Dead Redemption 2 y Spider-Man para PS4",
        price=35.0,
        currency="EUR",
        url="https://example.com/lot-example-001",
    )

    scanner = DefaultLotOpportunityScanner(
        game_detector=FakeGameDetector(),
        price_collector=FakePriceCollector(
            {
                "GTA V": 15.0,
                "RDR2": 20.0,
                "Spider-Man": 18.0,
            }
        ),
        dataset_builder=FakePriceDatasetBuilder(),
        statistics=FakePriceStatistics(),
        outlier_removal=FakeOutlierRemoval(),
        market_estimator=FakeMarketPriceEstimator(),
        # Explicit example policy: 3 EUR below market for each valued game.
        lot_analyzer=DefaultLotOpportunityAnalyzer(
            ResaleEconomicPolicy(3.0, 0.0, 0.0, 0.0, 0.0)
        ),
    )

    result = await scanner.scan_lot(listing)
    opportunity = result.opportunity
    if opportunity is None:
        raise RuntimeError("Expected lot opportunity")

    margin = opportunity.estimated_profit / opportunity.total_market_value * 100
    roi = opportunity.estimated_profit / opportunity.lot_price * 100

    print(f"Total detected games: {result.total_detected_games}")
    print(f"Successfully valued: {result.successfully_valued_games}")
    print(f"Failed: {result.failed_games}")
    print(f"Complete: {result.is_complete}")
    print()
    print(f"Total market value: {listing.currency} {opportunity.total_market_value:.2f}")
    print(f"Lot price: {listing.currency} {opportunity.lot_price:.2f}")
    print(f"Estimated profit: {listing.currency} {opportunity.estimated_profit:.2f}")
    print(f"Margin: {margin:.2f}%")
    print(f"ROI: {roi:.2f}%")
    print(f"Aggregate confidence: {opportunity.aggregate_confidence_score:.2f}")
    print(f"Recommendation: {opportunity.recommendation.upper()}")
    print(f"Reason: {opportunity.reason.upper()}")


if __name__ == "__main__":
    asyncio.run(main())
