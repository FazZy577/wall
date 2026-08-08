"""Composition root and owned lifecycle for the operational pipeline."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from application.interfaces.search_orchestrator import ISearchOrchestrator
from application.interfaces.search_plan_generator import ISearchPlanGenerator
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
from domain.entities.resale_economics import (
    ResaleAbsoluteCosts,
    ResaleEconomicPolicy,
)
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
from infrastructure.marketplaces.wallapop.playwright_client import (
    WallapopPlaywrightClient,
)
from infrastructure.outliers.default_outlier_removal import DefaultOutlierRemoval
from infrastructure.rankers.default_opportunity_ranker import (
    DefaultOpportunityRanker,
)
from infrastructure.statistics.default_price_statistics import (
    DefaultPriceStatistics,
)
from presentation.cli.config import AppConfig


@dataclass(frozen=True)
class OperationalRuntime:
    """Immutable public entry points produced by one composition call."""

    plan_generator: ISearchPlanGenerator
    search_orchestrator: ISearchOrchestrator

    def __post_init__(self) -> None:
        if not isinstance(self.plan_generator, ISearchPlanGenerator):
            raise TypeError("plan_generator must implement ISearchPlanGenerator")
        if not isinstance(self.search_orchestrator, ISearchOrchestrator):
            raise TypeError("search_orchestrator must implement ISearchOrchestrator")


def build_operational_runtime(
    config: AppConfig,
    marketplace_search: IMarketplaceSearch,
) -> OperationalRuntime:
    """Build an independent runtime without owning the external dependency."""
    if not isinstance(config, AppConfig):
        raise TypeError("config must be AppConfig")
    if not isinstance(marketplace_search, IMarketplaceSearch):
        raise TypeError("marketplace_search must implement IMarketplaceSearch")

    catalog = PackagedGameCatalog()
    plan_generator = DefaultSearchPlanGenerator(catalog)
    game_detector = FuzzyGameDetector(catalog)
    comparable_filter = RuleBasedComparableFilter()
    price_collector = WallapopPriceCollector(
        marketplace_search=marketplace_search,
        game_detector=game_detector,
        comparable_filter=comparable_filter,
    )
    dataset_builder = DefaultPriceDatasetBuilder()
    statistics = DefaultPriceStatistics()
    outlier_removal = DefaultOutlierRemoval()
    market_estimator = DefaultMarketPriceEstimator()

    absolute_costs_by_currency = {
        currency.currency: ResaleAbsoluteCosts(
            quick_sale_discount_per_item=currency.quick_sale_discount_per_item,
            fixed_selling_cost_per_item=currency.fixed_selling_cost_per_item,
            acquisition_overhead=currency.acquisition_overhead,
        )
        for currency in config.economics.currencies
    }
    individual_min_net_profit_by_currency = {
        currency.currency: currency.individual_min_net_profit
        for currency in config.economics.currencies
    }
    lot_min_net_profit_by_currency = {
        currency.currency: currency.lot_min_net_profit
        for currency in config.economics.currencies
    }
    economic_policy = ResaleEconomicPolicy(
        absolute_costs_by_currency=absolute_costs_by_currency,
        selling_fee_rate=config.economics.selling_fee_rate,
        safety_buffer_rate=config.economics.safety_buffer_rate,
    )
    arbitrage_detector = DefaultArbitrageOpportunityDetector(
        economic_policy=economic_policy,
        min_net_profit_by_currency=individual_min_net_profit_by_currency,
        min_net_profit_margin_percent=(
            config.economics.individual_min_net_profit_margin_percent
        ),
        min_confidence_score=config.economics.individual_min_confidence_score,
    )
    lot_analyzer = DefaultLotOpportunityAnalyzer(
        economic_policy=economic_policy,
        min_net_profit_by_currency=lot_min_net_profit_by_currency,
    )
    opportunity_ranker = DefaultOpportunityRanker()

    opportunity_scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=price_collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        arbitrage_detector=arbitrage_detector,
        opportunity_ranker=opportunity_ranker,
        latitude=config.location.latitude,
        longitude=config.location.longitude,
    )
    lot_opportunity_scanner = DefaultLotOpportunityScanner(
        game_detector=game_detector,
        price_collector=price_collector,
        dataset_builder=dataset_builder,
        statistics=statistics,
        outlier_removal=outlier_removal,
        market_estimator=market_estimator,
        lot_analyzer=lot_analyzer,
        latitude=config.location.latitude,
        longitude=config.location.longitude,
    )
    candidate_search = WallapopCandidateSearchAdapter(marketplace_search)
    candidate_eligibility_policy = RuleBasedCandidateEligibilityPolicy()
    search_orchestrator = DefaultSearchOrchestrator(
        candidate_search=candidate_search,
        game_detector=game_detector,
        candidate_eligibility_policy=candidate_eligibility_policy,
        opportunity_scanner=opportunity_scanner,
        lot_opportunity_scanner=lot_opportunity_scanner,
    )

    return OperationalRuntime(
        plan_generator=plan_generator,
        search_orchestrator=search_orchestrator,
    )


@asynccontextmanager
async def open_operational_runtime(
    config: AppConfig,
) -> AsyncIterator[OperationalRuntime]:
    """Open one owned marketplace client and yield its composed runtime."""
    if not isinstance(config, AppConfig):
        raise TypeError("config must be AppConfig")

    async with WallapopPlaywrightClient(
        timeout_ms=config.wallapop.timeout_ms,
        max_pages=config.wallapop.max_pages,
        request_delay=config.wallapop.request_delay,
        headless=config.wallapop.headless,
        debug_response_dir=None,
    ) as client:
        yield build_operational_runtime(config, client)
