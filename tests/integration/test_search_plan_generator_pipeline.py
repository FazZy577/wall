"""Offline integration of search-plan generation and search orchestration."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from application.interfaces.search_plan_generator import (
    GameSearchTarget,
    SearchPlanGenerationRequest,
    SearchPlanLimitExceededError,
    UnknownGameSearchTargetError,
)
from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from application.use_cases.default_opportunity_scanner import (
    DefaultOpportunityScanner,
)
from application.use_cases.default_search_orchestrator import (
    DefaultSearchOrchestrator,
)
from application.use_cases.default_search_plan_generator import (
    DefaultSearchPlanGenerator,
)
from domain.entities.detected_game import Platform
from domain.entities.resale_economics import ResaleEconomicPolicy
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
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
_GTA_KEYWORDS = "Grand Theft Auto V PS4"
_RDR2_KEYWORDS = "Red Dead Redemption 2 PS4"


@dataclass(frozen=True)
class _MarketplaceCall:
    keywords: str
    latitude: float
    longitude: float
    max_results: int


class _FakeMarketplaceSearch(IMarketplaceSearch):
    """Return independent raw copies and record every sequential search."""

    def __init__(
        self,
        responses: Mapping[str, Sequence[dict[str, Any]]],
    ) -> None:
        self._responses = {
            self._normalize(keywords): tuple(deepcopy(list(items)))
            for keywords, items in responses.items()
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
        return deepcopy(list(self._responses.get(self._normalize(keywords), ())))

    @staticmethod
    def _normalize(keywords: str) -> str:
        return " ".join(keywords.strip().casefold().split())


@dataclass(frozen=True)
class _Pipeline:
    catalog: PackagedGameCatalog
    generator: DefaultSearchPlanGenerator
    orchestrator: DefaultSearchOrchestrator
    marketplace: _FakeMarketplaceSearch


def _raw_listing(
    listing_id: str,
    title: str,
    price: str,
    *,
    description: str = "Videojuego completo en buen estado",
) -> dict[str, Any]:
    return {
        "id": listing_id,
        "title": title,
        "description": description,
        "price": price,
        "currency": "EUR",
        "web_slug": listing_id,
    }


def _gta_candidate(listing_id: str = "candidate-gta") -> dict[str, Any]:
    return _raw_listing(
        listing_id,
        "GTA V PS4 juego individual",
        "5.00",
    )


def _rdr2_candidate(listing_id: str = "candidate-rdr2") -> dict[str, Any]:
    return _raw_listing(
        listing_id,
        "RDR2 PS4 juego individual",
        "8.00",
    )


def _comparables(
    prefix: str,
    title: str,
    prices: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        _raw_listing(f"{prefix}-{index}", title, price)
        for index, price in enumerate(prices * 4)
    ]


def _gta_comparables() -> list[dict[str, Any]]:
    return _comparables(
        "gta-comparable",
        "GTA V PS4 juego",
        ("18", "19", "20", "21", "22"),
    )


def _rdr2_comparables() -> list[dict[str, Any]]:
    return _comparables(
        "rdr2-comparable",
        "Red Dead Redemption 2 PS4 juego",
        ("24", "25", "26", "27", "28"),
    )


def _responses(
    *,
    gta_candidates: Sequence[dict[str, Any]] = (),
    rdr2_candidates: Sequence[dict[str, Any]] = (),
) -> dict[str, Sequence[dict[str, Any]]]:
    return {
        _GTA_KEYWORDS: gta_candidates,
        _RDR2_KEYWORDS: rdr2_candidates,
        "gta v": _gta_comparables(),
        "rdr2": _rdr2_comparables(),
    }


def _build_pipeline(
    responses: Mapping[str, Sequence[dict[str, Any]]],
) -> _Pipeline:
    catalog = PackagedGameCatalog()
    generator = DefaultSearchPlanGenerator(catalog)
    marketplace = _FakeMarketplaceSearch(responses)
    detector = FuzzyGameDetector(catalog)
    collector = WallapopPriceCollector(
        marketplace,
        detector,
        RuleBasedComparableFilter(),
    )
    dataset_builder = DefaultPriceDatasetBuilder()
    statistics = DefaultPriceStatistics()
    outlier_removal = DefaultOutlierRemoval()
    market_estimator = DefaultMarketPriceEstimator()
    economic_policy = ResaleEconomicPolicy.neutral()

    individual_scanner = DefaultOpportunityScanner(
        game_detector=detector,
        price_collector=collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        arbitrage_detector=DefaultArbitrageOpportunityDetector(economic_policy),
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    lot_scanner = DefaultLotOpportunityScanner(
        game_detector=detector,
        price_collector=collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        lot_analyzer=DefaultLotOpportunityAnalyzer(economic_policy),
    )
    orchestrator = DefaultSearchOrchestrator(
        candidate_search=WallapopCandidateSearchAdapter(marketplace),
        game_detector=detector,
        candidate_eligibility_policy=RuleBasedCandidateEligibilityPolicy(),
        opportunity_scanner=individual_scanner,
        lot_opportunity_scanner=lot_scanner,
    )
    return _Pipeline(catalog, generator, orchestrator, marketplace)


def _request(
    targets: Sequence[GameSearchTarget],
    *,
    max_queries: int = 10,
) -> SearchPlanGenerationRequest:
    return SearchPlanGenerationRequest(
        targets=targets,
        latitude=_LATITUDE,
        longitude=_LONGITUDE,
        max_results=_MAX_RESULTS,
        max_queries=max_queries,
    )


def _gta_target(name: str = "Grand Theft Auto V") -> GameSearchTarget:
    return GameSearchTarget(name, Platform.PS4)


def _rdr2_target() -> GameSearchTarget:
    return GameSearchTarget("Red Dead Redemption 2", Platform.PS4)


def _called_keywords(pipeline: _Pipeline) -> list[str]:
    return [call.keywords for call in pipeline.marketplace.calls]


@pytest.mark.asyncio
async def test_complete_pipeline_from_real_catalog_target() -> None:
    pipeline = _build_pipeline(_responses(gta_candidates=[_gta_candidate()]))

    generation = pipeline.generator.generate(_request([_gta_target()]))

    assert (
        generation.targets_received,
        generation.queries_generated,
        generation.duplicate_queries_removed,
    ) == (1, 1, 0)
    assert len(generation.plan.queries) == 1
    generated_query = generation.plan.queries[0]
    assert generated_query.keywords == _GTA_KEYWORDS
    assert (
        generated_query.latitude,
        generated_query.longitude,
        generated_query.max_results,
    ) == (_LATITUDE, _LONGITUDE, _MAX_RESULTS)

    execution = await pipeline.orchestrator.execute(generation.plan)

    assert execution.query_failures == ()
    assert execution.item_failures == ()
    assert execution.routing_failures == ()
    assert execution.individual_result is not None
    assert execution.individual_result.successful == 1
    assert execution.individual_result.failed == 0
    assert len(execution.individual_result.opportunities) == 1
    opportunity = execution.individual_result.opportunities[0]
    assert opportunity.listing.listing_id == "candidate-gta"
    assert opportunity.game.canonical_name == "Grand Theft Auto V"
    assert opportunity.game.platform is Platform.PS4
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
    assert execution.lot_results == ()
    assert (
        execution.total_queries,
        execution.executed_queries,
        execution.duplicate_queries,
        execution.total_items_received,
        execution.valid_candidates_received,
        execution.unique_candidates,
        execution.individual_candidates,
        execution.lot_candidates,
        execution.undetected_candidates,
    ) == (1, 1, 0, 1, 1, 1, 1, 0, 0)
    assert _called_keywords(pipeline) == [_GTA_KEYWORDS, "gta v"]
    assert pipeline.marketplace.calls[0].max_results == _MAX_RESULTS
    assert pipeline.marketplace.calls[1].max_results == 100


@pytest.mark.asyncio
async def test_multiple_real_targets_preserve_generation_and_execution_order() -> None:
    pipeline = _build_pipeline(
        _responses(
            gta_candidates=[_gta_candidate()],
            rdr2_candidates=[_rdr2_candidate()],
        )
    )

    generation = pipeline.generator.generate(
        _request([_gta_target(), _rdr2_target()])
    )

    assert [query.keywords for query in generation.plan.queries] == [
        _GTA_KEYWORDS,
        _RDR2_KEYWORDS,
    ]
    assert (
        generation.targets_received,
        generation.queries_generated,
        generation.duplicate_queries_removed,
    ) == (2, 2, 0)

    execution = await pipeline.orchestrator.execute(generation.plan)

    assert execution.query_failures == ()
    assert execution.routing_failures == ()
    assert execution.individual_result is not None
    assert execution.individual_result.successful == 2
    assert execution.individual_result.failed == 0
    assert len(execution.individual_result.opportunities) == 2
    assert (
        execution.total_queries,
        execution.executed_queries,
        execution.duplicate_queries,
        execution.total_items_received,
        execution.valid_candidates_received,
        execution.duplicate_candidates,
        execution.unique_candidates,
        execution.individual_candidates,
        execution.lot_candidates,
    ) == (2, 2, 0, 2, 2, 0, 2, 2, 0)
    assert _called_keywords(pipeline) == [
        _GTA_KEYWORDS,
        _RDR2_KEYWORDS,
        "gta v",
        "rdr2",
    ]


@pytest.mark.asyncio
async def test_generator_deduplication_remains_separate_from_orchestrator() -> None:
    pipeline = _build_pipeline(_responses(gta_candidates=[_gta_candidate()]))
    targets = [
        _gta_target("Grand Theft Auto V"),
        _gta_target("  grand   theft auto v  "),
        _gta_target("GRAND THEFT AUTO V"),
    ]

    generation = pipeline.generator.generate(_request(targets))

    assert (
        generation.targets_received,
        generation.queries_generated,
        generation.duplicate_queries_removed,
    ) == (3, 1, 2)
    assert generation.plan.queries[0].keywords == _GTA_KEYWORDS

    execution = await pipeline.orchestrator.execute(generation.plan)

    assert (
        execution.total_queries,
        execution.executed_queries,
        execution.duplicate_queries,
    ) == (1, 1, 0)
    assert execution.unique_candidates == 1
    assert _called_keywords(pipeline) == [_GTA_KEYWORDS, "gta v"]


@pytest.mark.asyncio
async def test_unknown_target_is_atomic_before_marketplace_execution() -> None:
    pipeline = _build_pipeline(_responses(gta_candidates=[_gta_candidate()]))

    with pytest.raises(UnknownGameSearchTargetError):
        pipeline.generator.generate(
            _request(
                [
                    _gta_target(),
                    GameSearchTarget("Unknown Game", Platform.PS4),
                ]
            )
        )

    assert pipeline.marketplace.calls == []


@pytest.mark.asyncio
async def test_query_limit_is_atomic_and_duplicates_fit_after_deduplication() -> None:
    pipeline = _build_pipeline(_responses(gta_candidates=[_gta_candidate()]))

    with pytest.raises(SearchPlanLimitExceededError):
        pipeline.generator.generate(
            _request([_gta_target(), _rdr2_target()], max_queries=1)
        )

    assert pipeline.marketplace.calls == []

    generation = pipeline.generator.generate(
        _request(
            [_gta_target(), _gta_target(" grand   theft auto v ")],
            max_queries=1,
        )
    )
    execution = await pipeline.orchestrator.execute(generation.plan)

    assert generation.queries_generated == 1
    assert generation.duplicate_queries_removed == 1
    assert execution.executed_queries == 1
    assert _called_keywords(pipeline) == [_GTA_KEYWORDS, "gta v"]


@pytest.mark.asyncio
async def test_empty_targets_produce_valid_empty_generation_and_execution() -> None:
    pipeline = _build_pipeline(_responses())

    generation = pipeline.generator.generate(_request([]))
    execution = await pipeline.orchestrator.execute(generation.plan)

    assert pipeline.catalog.list_games()
    assert generation.plan.queries == ()
    assert (
        generation.targets_received,
        generation.queries_generated,
        generation.duplicate_queries_removed,
    ) == (0, 0, 0)
    assert execution.individual_result is None
    assert execution.lot_results == ()
    assert execution.query_failures == ()
    assert execution.item_failures == ()
    assert execution.routing_failures == ()
    assert (
        execution.total_queries,
        execution.executed_queries,
        execution.duplicate_queries,
        execution.total_items_received,
        execution.valid_candidates_received,
        execution.duplicate_candidates,
        execution.unique_candidates,
        execution.individual_candidates,
        execution.lot_candidates,
        execution.undetected_candidates,
    ) == (0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    assert pipeline.marketplace.calls == []


@pytest.mark.asyncio
async def test_consecutive_runs_share_no_generation_or_orchestration_state() -> None:
    pipeline = _build_pipeline(_responses(gta_candidates=[_gta_candidate()]))
    request = _request([_gta_target()])

    first_generation = pipeline.generator.generate(request)
    first_execution = await pipeline.orchestrator.execute(first_generation.plan)
    first_calls = tuple(pipeline.marketplace.calls)

    second_generation = pipeline.generator.generate(request)
    second_execution = await pipeline.orchestrator.execute(second_generation.plan)
    second_calls = tuple(pipeline.marketplace.calls[len(first_calls) :])

    assert second_generation == first_generation
    assert first_calls == second_calls
    assert first_execution.total_queries == second_execution.total_queries == 1
    assert first_execution.unique_candidates == second_execution.unique_candidates == 1
    assert first_execution.duplicate_queries == second_execution.duplicate_queries == 0
    assert first_execution.duplicate_candidates == second_execution.duplicate_candidates == 0
    assert first_execution.individual_result is not None
    assert second_execution.individual_result is not None
    assert first_execution.individual_result.comparable_cache_misses == 1
    assert second_execution.individual_result.comparable_cache_misses == 1
    assert first_execution.individual_result.comparable_cache_hits == 0
    assert second_execution.individual_result.comparable_cache_hits == 0
