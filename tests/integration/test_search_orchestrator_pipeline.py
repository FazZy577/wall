"""Offline integration tests for the complete search orchestration pipeline."""

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.search_orchestrator import SearchPlan
from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from application.use_cases.default_opportunity_scanner import (
    DefaultOpportunityScanner,
)
from application.use_cases.default_search_orchestrator import (
    DefaultSearchOrchestrator,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.arbitrage_opportunity_detector import ArbitrageOpportunity
from domain.interfaces.game_detector import IGameDetector, ListingText
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.collectors.wallapop_price_collector import (
    WallapopPriceCollector,
)
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.estimators.default_market_price_estimator import (
    DefaultMarketPriceEstimator,
)
from infrastructure.filters.rule_based_comparable_filter import (
    RuleBasedComparableFilter,
)
from infrastructure.marketplaces.wallapop.adapter import (
    WallapopCandidateSearchAdapter,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.rankers.default_opportunity_ranker import (
    DefaultOpportunityRanker,
)
from infrastructure.statistics.default_price_statistics import (
    DefaultPriceStatistics,
)

pytestmark = pytest.mark.integration

_LATITUDE = 40.4168
_LONGITUDE = -3.7038
_MAX_RESULTS = 10


@dataclass(frozen=True)
class _MarketplaceCall:
    keywords: str
    latitude: float
    longitude: float
    max_results: int


class _FakeMarketplaceSearch(IMarketplaceSearch):
    """Return copied raw responses and record deterministic async searches."""

    def __init__(
        self,
        responses: Mapping[str, Sequence[dict[str, Any]]],
        *,
        failing_keywords: Iterable[str] = (),
    ) -> None:
        self._responses = {
            self._normalize_keywords(keywords): tuple(deepcopy(list(items)))
            for keywords, items in responses.items()
        }
        self._failing_keywords = {
            self._normalize_keywords(keywords) for keywords in failing_keywords
        }
        self.calls: list[_MarketplaceCall] = []

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            _MarketplaceCall(
                keywords=keywords,
                latitude=latitude,
                longitude=longitude,
                max_results=max_results,
            )
        )
        normalized_keywords = self._normalize_keywords(keywords)
        if normalized_keywords in self._failing_keywords:
            raise RuntimeError("controlled marketplace failure")
        return deepcopy(list(self._responses.get(normalized_keywords, ())))

    @staticmethod
    def _normalize_keywords(keywords: str) -> str:
        return " ".join(keywords.strip().casefold().split())


class _RecordingGameDetector(IGameDetector):
    """Record candidate detections while delegating to the production detector."""

    def __init__(self, delegate: FuzzyGameDetector) -> None:
        self._delegate = delegate
        self.calls: list[ListingText] = []

    def detect_games(self, listing_text: ListingText):
        self.calls.append(listing_text)
        return self._delegate.detect_games(listing_text)


@dataclass(frozen=True)
class _Pipeline:
    orchestrator: DefaultSearchOrchestrator
    marketplace: _FakeMarketplaceSearch
    candidate_detector: _RecordingGameDetector


def _raw_listing(
    listing_id: str,
    title: str,
    price: str,
    *,
    description: str = "Videojuego completo en buen estado",
    marker: str | None = None,
) -> dict[str, Any]:
    raw_listing: dict[str, Any] = {
        "id": listing_id,
        "title": title,
        "description": description,
        "price": price,
        "currency": "EUR",
        "web_slug": listing_id,
    }
    if marker is not None:
        raw_listing["fixture_marker"] = marker
    return raw_listing


def _individual_candidate(
    listing_id: str = "candidate-individual",
    *,
    title: str = "GTA V PS4",
    marker: str = "individual-first",
) -> dict[str, Any]:
    return _raw_listing(
        listing_id,
        title,
        "5.00",
        description="Juego individual de PS4",
        marker=marker,
    )


def _lot_candidate(listing_id: str = "candidate-lot") -> dict[str, Any]:
    return _raw_listing(
        listing_id,
        "Lote GTA V y RDR2 PS4",
        "10.00",
        description="Dos videojuegos completos",
        marker="lot",
    )


def _gta_comparables() -> list[dict[str, Any]]:
    prices = ("18", "19", "20", "21", "22") * 4
    return [
        _raw_listing(
            f"gta-comparable-{index}",
            "GTA V PS4 juego",
            price,
        )
        for index, price in enumerate(prices)
    ]


def _rdr2_comparables() -> list[dict[str, Any]]:
    prices = ("24", "25", "26", "27", "28") * 4
    return [
        _raw_listing(
            f"rdr2-comparable-{index}",
            "Red Dead Redemption 2 PS4 juego",
            price,
        )
        for index, price in enumerate(prices)
    ]


def _responses_with_comparables(
    candidate_responses: Mapping[str, Sequence[dict[str, Any]]],
    *,
    gta_comparables: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Sequence[dict[str, Any]]]:
    responses: dict[str, Sequence[dict[str, Any]]] = {
        "gta v": _gta_comparables()
        if gta_comparables is None
        else gta_comparables,
        "rdr2": _rdr2_comparables(),
    }
    responses.update(candidate_responses)
    return responses


def _build_pipeline(
    responses: Mapping[str, Sequence[dict[str, Any]]],
    *,
    failing_keywords: Iterable[str] = (),
) -> _Pipeline:
    marketplace = _FakeMarketplaceSearch(
        responses,
        failing_keywords=failing_keywords,
    )
    candidate_detector = _RecordingGameDetector(FuzzyGameDetector())
    comparable_detector = FuzzyGameDetector()
    collector = WallapopPriceCollector(
        marketplace,
        comparable_detector,
        RuleBasedComparableFilter(),
    )
    dataset_builder = DefaultPriceDatasetBuilder()
    statistics = DefaultPriceStatistics()
    outlier_removal = DefaultOutlierRemoval()
    market_estimator = DefaultMarketPriceEstimator()
    economic_policy = ResaleEconomicPolicy.neutral()

    individual_scanner = DefaultOpportunityScanner(
        game_detector=candidate_detector,
        price_collector=collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        arbitrage_detector=DefaultArbitrageOpportunityDetector(economic_policy),
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    lot_scanner = DefaultLotOpportunityScanner(
        game_detector=candidate_detector,
        price_collector=collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        lot_analyzer=DefaultLotOpportunityAnalyzer(economic_policy),
    )
    orchestrator = DefaultSearchOrchestrator(
        candidate_search=WallapopCandidateSearchAdapter(marketplace),
        game_detector=candidate_detector,
        opportunity_scanner=individual_scanner,
        lot_opportunity_scanner=lot_scanner,
    )
    return _Pipeline(orchestrator, marketplace, candidate_detector)


def _query(keywords: str) -> SearchQuery:
    return SearchQuery(
        keywords=keywords,
        latitude=_LATITUDE,
        longitude=_LONGITUDE,
        max_results=_MAX_RESULTS,
    )


def _executed_keywords(pipeline: _Pipeline) -> list[str]:
    return [call.keywords for call in pipeline.marketplace.calls]


@pytest.mark.asyncio
async def test_complete_individual_pipeline_uses_all_productive_components() -> None:
    pipeline = _build_pipeline(
        _responses_with_comparables(
            {"individual candidates": [_individual_candidate()]}
        )
    )

    result = await pipeline.orchestrator.execute(
        SearchPlan((_query("individual candidates"),))
    )

    assert result.query_failures == ()
    assert result.item_failures == ()
    assert result.routing_failures == ()
    assert result.individual_result is not None
    assert result.individual_result.successful == 1
    assert result.individual_result.failed == 0
    assert len(result.individual_result.opportunities) == 1
    opportunity = result.individual_result.opportunities[0]
    assert isinstance(opportunity, ArbitrageOpportunity)
    assert type(opportunity.listing) is CandidateListing
    assert opportunity.listing.listing_id == "candidate-individual"
    assert opportunity.listing.raw_listing["fixture_marker"] == "individual-first"
    assert opportunity.game.canonical_name == "Grand Theft Auto V"
    assert opportunity.game.platform.value == "PS4"
    assert opportunity.market_price > Decimal("0")
    assert 0.0 <= opportunity.confidence_score <= 1.0
    assert all(
        isinstance(amount, Decimal)
        for amount in (
            opportunity.market_price,
            opportunity.listing_price,
            opportunity.net_profit,
            opportunity.expected_sale_revenue,
            opportunity.break_even_sale_revenue,
        )
    )
    assert opportunity.currency == "EUR"
    assert result.lot_results == ()
    assert (
        result.total_queries,
        result.executed_queries,
        result.duplicate_queries,
        result.total_items_received,
        result.valid_candidates_received,
        result.duplicate_candidates,
        result.unique_candidates,
        result.individual_candidates,
        result.lot_candidates,
        result.undetected_candidates,
    ) == (1, 1, 0, 1, 1, 0, 1, 1, 0, 0)
    assert _executed_keywords(pipeline) == ["individual candidates", "gta v"]
    assert pipeline.marketplace.calls[0].max_results == _MAX_RESULTS
    assert pipeline.marketplace.calls[1].max_results == 100


@pytest.mark.asyncio
async def test_complete_lot_pipeline_keeps_lot_results_separate() -> None:
    pipeline = _build_pipeline(
        _responses_with_comparables({"lot candidates": [_lot_candidate()]})
    )

    result = await pipeline.orchestrator.execute(
        SearchPlan((_query("lot candidates"),))
    )

    assert result.individual_result is None
    assert result.query_failures == ()
    assert result.routing_failures == ()
    assert len(result.lot_results) == 1
    lot_result = result.lot_results[0]
    assert lot_result.listing.listing_id == "candidate-lot"
    assert lot_result.total_detected_games == 2
    assert lot_result.successfully_valued_games == 2
    assert lot_result.failed_games == 0
    assert lot_result.is_complete is True
    assert lot_result.failures == []
    assert {
        valuation.game.canonical_name for valuation in lot_result.game_valuations
    } == {"Grand Theft Auto V", "Red Dead Redemption 2"}
    assert all(
        isinstance(valuation.estimated_market_value, Decimal)
        and valuation.currency == "EUR"
        for valuation in lot_result.game_valuations
    )
    assert lot_result.opportunity is not None
    assert all(
        isinstance(amount, Decimal)
        for amount in (
            lot_result.opportunity.lot_price,
            lot_result.opportunity.reference_market_value,
            lot_result.opportunity.net_profit,
        )
    )
    assert lot_result.opportunity.currency == "EUR"
    assert (
        result.individual_candidates,
        result.lot_candidates,
        result.undetected_candidates,
    ) == (0, 1, 0)
    assert _executed_keywords(pipeline) == ["lot candidates", "gta v", "rdr2"]
    assert len(pipeline.candidate_detector.calls) == 1


@pytest.mark.asyncio
async def test_mixed_pipeline_deduplicates_queries_and_candidates_stably() -> None:
    first_individual = _individual_candidate(
        title="GTA V PS4 primera aparición",
        marker="first-wins",
    )
    duplicate_individual = _individual_candidate(
        title="GTA V PS4 aparición duplicada",
        marker="duplicate-loses",
    )
    pipeline = _build_pipeline(
        _responses_with_comparables(
            {
                "mixed first": [first_individual, _lot_candidate()],
                "mixed second": [duplicate_individual],
            }
        )
    )

    result = await pipeline.orchestrator.execute(
        SearchPlan(
            (
                _query("mixed first"),
                _query("mixed second"),
                _query(" MIXED   FIRST "),
            )
        )
    )

    assert (
        result.total_queries,
        result.executed_queries,
        result.duplicate_queries,
    ) == (3, 2, 1)
    assert (
        result.total_items_received,
        result.valid_candidates_received,
        result.duplicate_candidates,
        result.unique_candidates,
    ) == (3, 3, 1, 2)
    assert (
        result.individual_candidates,
        result.lot_candidates,
        result.undetected_candidates,
    ) == (1, 1, 0)
    assert result.individual_result is not None
    assert len(result.individual_result.opportunities) == 1
    individual = result.individual_result.opportunities[0]
    assert individual.listing.raw_listing["fixture_marker"] == "first-wins"
    assert len(result.lot_results) == 1
    assert result.lot_results[0].listing.listing_id == "candidate-lot"
    assert [call.title for call in pipeline.candidate_detector.calls] == [
        "GTA V PS4 primera aparición",
        "Lote GTA V y RDR2 PS4",
    ]
    assert _executed_keywords(pipeline) == [
        "mixed first",
        "mixed second",
        "gta v",
        "gta v",
        "rdr2",
    ]


@pytest.mark.asyncio
async def test_query_failure_preserves_successful_productive_pipeline() -> None:
    pipeline = _build_pipeline(
        _responses_with_comparables(
            {"valid after failure": [_individual_candidate()]}
        ),
        failing_keywords={"technical failure"},
    )

    result = await pipeline.orchestrator.execute(
        SearchPlan(
            (
                _query("technical failure"),
                _query("valid after failure"),
            )
        )
    )

    assert len(result.query_failures) == 1
    failure = result.query_failures[0]
    assert failure.query.keywords == "technical failure"
    assert failure.query_index == 0
    assert failure.error_type == "RuntimeError"
    assert failure.error_message == "controlled marketplace failure"
    assert not any(
        isinstance(value, BaseException) for value in vars(failure).values()
    )
    assert result.individual_result is not None
    assert result.individual_result.successful == 1
    assert len(result.individual_result.opportunities) == 1
    assert (
        result.total_queries,
        result.executed_queries,
        result.duplicate_queries,
        result.total_items_received,
        result.valid_candidates_received,
        result.unique_candidates,
    ) == (2, 2, 0, 1, 1, 1)
    assert _executed_keywords(pipeline) == [
        "technical failure",
        "valid after failure",
        "gta v",
    ]


@pytest.mark.asyncio
async def test_genuinely_empty_search_is_a_valid_empty_result() -> None:
    pipeline = _build_pipeline(
        _responses_with_comparables({"empty candidates": []})
    )

    result = await pipeline.orchestrator.execute(
        SearchPlan((_query("empty candidates"),))
    )

    assert result.query_failures == ()
    assert result.item_failures == ()
    assert result.routing_failures == ()
    assert result.individual_result is None
    assert result.lot_results == ()
    assert (
        result.total_queries,
        result.executed_queries,
        result.duplicate_queries,
        result.total_items_received,
        result.valid_candidates_received,
        result.duplicate_candidates,
        result.unique_candidates,
        result.individual_candidates,
        result.lot_candidates,
        result.undetected_candidates,
    ) == (1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    assert pipeline.candidate_detector.calls == []
    assert _executed_keywords(pipeline) == ["empty candidates"]


@pytest.mark.asyncio
async def test_candidate_is_excluded_from_its_own_market_dataset() -> None:
    candidate_id = "candidate-self-exclusion"
    remaining_comparables = [
        _raw_listing(
            f"self-exclusion-comparable-{index}",
            "GTA V PS4 juego",
            price,
        )
        for index, price in enumerate(("12", "14", "16", "18"))
    ]
    candidate_as_comparable = _raw_listing(
        candidate_id,
        "GTA V PS4 juego",
        "5.00",
    )
    pipeline = _build_pipeline(
        _responses_with_comparables(
            {
                "self exclusion": [
                    _individual_candidate(
                        candidate_id,
                        marker="self-exclusion-candidate",
                    )
                ]
            },
            gta_comparables=[candidate_as_comparable, *remaining_comparables],
        )
    )

    result = await pipeline.orchestrator.execute(
        SearchPlan((_query("self exclusion"),))
    )

    assert result.individual_result is not None
    assert result.individual_result.successful == 1
    assert result.individual_result.failed == 0
    opportunity = result.individual_result.opportunities[0]
    assert opportunity.listing.listing_id == candidate_id
    assert opportunity.market_price == Decimal("15")
    assert opportunity.market_price != Decimal("14")
    assert _executed_keywords(pipeline) == ["self exclusion", "gta v"]


@pytest.mark.asyncio
async def test_consecutive_executions_share_no_candidate_or_cache_state() -> None:
    pipeline = _build_pipeline(
        _responses_with_comparables(
            {"repeat candidates": [_individual_candidate()]}
        )
    )
    plan = SearchPlan((_query("repeat candidates"),))

    first = await pipeline.orchestrator.execute(plan)
    second = await pipeline.orchestrator.execute(plan)

    assert first.individual_result is not None
    assert second.individual_result is not None
    assert first.individual_result.comparable_cache_misses == 1
    assert second.individual_result.comparable_cache_misses == 1
    assert first.individual_result.comparable_cache_hits == 0
    assert second.individual_result.comparable_cache_hits == 0
    first_listing = first.individual_result.opportunities[0].listing
    second_listing = second.individual_result.opportunities[0].listing
    assert first_listing is not second_listing
    assert first_listing.raw_listing is not second_listing.raw_listing
    assert len(pipeline.candidate_detector.calls) == 2
    assert _executed_keywords(pipeline) == [
        "repeat candidates",
        "gta v",
        "repeat candidates",
        "gta v",
    ]
