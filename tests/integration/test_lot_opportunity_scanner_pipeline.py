"""Offline integration coverage for the unified lot analysis flow."""

from unittest.mock import Mock

import pytest

from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.statistics.default_price_statistics import DefaultPriceStatistics


def _game(name: str) -> DetectedGame:
    return DetectedGame(
        canonical_name=name,
        matched_text=name,
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


class _Detector:
    def __init__(self, games: list[DetectedGame]) -> None:
        self.games = games

    def detect_games(self, listing_text: object) -> list[DetectedGame]:
        del listing_text
        return self.games


class _Collector:
    prices = {"GTA V": 15.0, "RDR2": 20.0, "FIFA 24": 10.0}

    def __init__(self, candidate_id: str) -> None:
        self.candidate_id = candidate_id
        self.calls: list[DetectedGame] = []

    async def collect_comparables(
        self,
        game: DetectedGame,
        latitude: float,
        longitude: float,
        max_results: int | None = None,
    ) -> list[ComparableListing]:
        del latitude, longitude, max_results
        self.calls.append(game)
        price = self.prices[game.canonical_name]
        identifiers = [self.candidate_id, *(f"{game.canonical_name}-{i}" for i in range(20))]
        return [
            ComparableListing(
                listing_id=identifier,
                title=game.canonical_name,
                description="",
                price=40.0 if identifier == self.candidate_id else price,
                currency="EUR",
                detected_game=game,
                url=f"https://example.test/{identifier}",
                raw_listing={"kind": "comparable"},
            )
            for identifier in identifiers
        ]


@pytest.mark.asyncio
async def test_real_offline_lot_pipeline_uses_one_candidate_and_three_valuations() -> None:
    games = [_game("GTA V"), _game("RDR2"), _game("FIFA 24")]
    candidate = CandidateListing(
        listing_id="lot-123",
        title="Lote GTA V, RDR2 y FIFA 24 para PS4",
        description="Tres juegos",
        price=40.0,
        currency="EUR",
        url="https://example.test/lot-123",
        raw_listing={"kind": "candidate"},
    )
    collector = _Collector(candidate.listing_id)
    builder = Mock(wraps=DefaultPriceDatasetBuilder())
    analyzer = Mock(wraps=DefaultLotOpportunityAnalyzer())
    scanner = DefaultLotOpportunityScanner(
        game_detector=_Detector(games),
        price_collector=collector,
        dataset_builder=builder,
        statistics=DefaultPriceStatistics(),
        outlier_removal=DefaultOutlierRemoval(),
        market_estimator=DefaultMarketPriceEstimator(),
        lot_analyzer=analyzer,
    )

    result = await scanner.scan_lot(candidate)

    assert result.total_detected_games == 3
    assert len(result.game_valuations) == 3
    assert result.opportunity is not None
    assert result.opportunity.total_market_value == 45.0
    assert result.opportunity.lot_price == 40.0
    assert len(collector.calls) == 3
    analyzer.analyze.assert_called_once()
    assert all(
        candidate.listing_id not in [item.listing_id for item in call.args[0]]
        for call in builder.build.call_args_list
    )
    assert candidate.raw_listing == {"kind": "candidate"}

