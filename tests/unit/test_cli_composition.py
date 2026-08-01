"""Tests for the synchronous operational CLI composition root."""

import ast
import inspect
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from application.interfaces.search_orchestrator import ISearchOrchestrator
from application.interfaces.search_plan_generator import ISearchPlanGenerator
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from application.use_cases.default_search_orchestrator import DefaultSearchOrchestrator
from application.use_cases.default_search_plan_generator import (
    DefaultSearchPlanGenerator,
)
from domain.entities.detected_game import Platform
from domain.interfaces.marketplace_search import IMarketplaceSearch
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.collectors.wallapop_price_collector import (
    WallapopPriceCollector,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)
from infrastructure.marketplaces.wallapop.adapter import (
    WallapopCandidateSearchAdapter,
)
from presentation.cli.composition import OperationalRuntime, build_operational_runtime
from presentation.cli.config import (
    AppConfig,
    CurrencyEconomicsConfig,
    EconomicsConfig,
    LocationConfig,
    SafetyConfig,
    SearchConfig,
    SearchTargetConfig,
    WallapopConfig,
)

PROJECT_ROOT = Path(__file__).parents[2]
COMPOSITION_PATH = PROJECT_ROOT / "src/presentation/cli/composition.py"


class _FakeMarketplaceSearch(IMarketplaceSearch):
    def __init__(self) -> None:
        self.calls = 0
        self.open_calls = 0
        self.close_calls = 0

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        del keywords, latitude, longitude, max_results
        self.calls += 1
        return []

    async def open(self) -> None:
        self.open_calls += 1

    async def close(self) -> None:
        self.close_calls += 1


def _currency(
    currency: str,
    *,
    quick_sale_discount: str,
    fixed_cost: str,
    overhead: str,
    individual_profit: str,
    lot_profit: str,
) -> CurrencyEconomicsConfig:
    return CurrencyEconomicsConfig(
        currency=currency,
        quick_sale_discount_per_item=quick_sale_discount,
        fixed_selling_cost_per_item=fixed_cost,
        acquisition_overhead=overhead,
        individual_min_net_profit=individual_profit,
        lot_min_net_profit=lot_profit,
    )


def _config(*, multiple_currencies: bool = False) -> AppConfig:
    currencies = [
        _currency(
            "EUR",
            quick_sale_discount="1.25",
            fixed_cost="0.75",
            overhead="2.50",
            individual_profit="8.25",
            lot_profit="14.50",
        )
    ]
    if multiple_currencies:
        currencies.append(
            _currency(
                "USD",
                quick_sale_discount="2.125",
                fixed_cost="1.375",
                overhead="3.625",
                individual_profit="9.875",
                lot_profit="16.125",
            )
        )
    return AppConfig(
        wallapop=WallapopConfig(
            headless=True,
            timeout_ms=12_345,
            max_pages=2,
            request_delay=0.25,
        ),
        location=LocationConfig(latitude=40.4168, longitude=-3.7038),
        search=SearchConfig(
            max_queries=5,
            max_results_per_query=12,
            targets=(
                SearchTargetConfig(
                    canonical_name="Grand Theft Auto V",
                    platform=Platform.PS4,
                ),
            ),
        ),
        economics=EconomicsConfig(
            selling_fee_rate="0.123",
            safety_buffer_rate="0.047",
            individual_min_net_profit_margin_percent="21.75",
            individual_min_confidence_score=0.64,
            currencies=tuple(currencies),
        ),
        safety=SafetyConfig(max_targets=5),
    )


def _concrete_runtime(
    config: AppConfig | None = None,
    marketplace: _FakeMarketplaceSearch | None = None,
) -> tuple[
    OperationalRuntime,
    DefaultSearchPlanGenerator,
    DefaultSearchOrchestrator,
    _FakeMarketplaceSearch,
]:
    actual_marketplace = marketplace or _FakeMarketplaceSearch()
    runtime = build_operational_runtime(config or _config(), actual_marketplace)
    return (
        runtime,
        cast(DefaultSearchPlanGenerator, runtime.plan_generator),
        cast(DefaultSearchOrchestrator, runtime.search_orchestrator),
        actual_marketplace,
    )


def test_build_returns_frozen_runtime_with_application_interfaces() -> None:
    runtime, _, _, _ = _concrete_runtime()

    assert isinstance(runtime.plan_generator, ISearchPlanGenerator)
    assert isinstance(runtime.search_orchestrator, ISearchOrchestrator)
    with pytest.raises(FrozenInstanceError):
        runtime.plan_generator = runtime.plan_generator


@pytest.mark.parametrize("invalid", [None, object(), "config", 1, False])
def test_build_rejects_invalid_config_type(invalid: object) -> None:
    with pytest.raises(TypeError, match="config must be AppConfig"):
        build_operational_runtime(invalid, _FakeMarketplaceSearch())  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", [None, object(), "marketplace", 1, False])
def test_build_rejects_invalid_marketplace_type(invalid: object) -> None:
    with pytest.raises(TypeError, match="marketplace_search"):
        build_operational_runtime(_config(), invalid)  # type: ignore[arg-type]


def test_build_is_synchronous_and_does_not_manage_marketplace_lifecycle() -> None:
    marketplace = _FakeMarketplaceSearch()

    runtime = build_operational_runtime(_config(), marketplace)

    assert isinstance(runtime, OperationalRuntime)
    assert not inspect.iscoroutinefunction(build_operational_runtime)
    assert marketplace.calls == 0
    assert marketplace.open_calls == 0
    assert marketplace.close_calls == 0


def test_every_build_creates_an_independent_graph_without_mutating_config() -> None:
    config = _config()
    marketplace = _FakeMarketplaceSearch()
    snapshot = config.model_dump(mode="python")

    first, first_generator, first_orchestrator, _ = _concrete_runtime(
        config, marketplace
    )
    second, second_generator, second_orchestrator, _ = _concrete_runtime(
        config, marketplace
    )

    assert first is not second
    assert first_generator is not second_generator
    assert first_orchestrator is not second_orchestrator
    assert first_orchestrator.opportunity_scanner is not (
        second_orchestrator.opportunity_scanner
    )
    assert config.model_dump(mode="python") == snapshot


def test_generator_uses_a_fresh_packaged_catalog() -> None:
    _, first_generator, _, _ = _concrete_runtime()
    _, second_generator, _, _ = _concrete_runtime()

    assert isinstance(first_generator.game_catalog, PackagedGameCatalog)
    assert first_generator.game_catalog is not second_generator.game_catalog
    assert len(first_generator.game_catalog.list_games()) == 50


def test_candidate_and_comparable_search_share_the_injected_marketplace() -> None:
    marketplace = _FakeMarketplaceSearch()
    _, _, orchestrator, _ = _concrete_runtime(marketplace=marketplace)
    candidate_search = cast(
        WallapopCandidateSearchAdapter, orchestrator.candidate_search
    )
    individual_scanner = cast(
        DefaultOpportunityScanner, orchestrator.opportunity_scanner
    )
    collector = cast(WallapopPriceCollector, individual_scanner.price_collector)

    assert candidate_search.marketplace_search is marketplace
    assert collector.marketplace_search is marketplace
    assert (
        orchestrator.lot_opportunity_scanner.price_collector
        is individual_scanner.price_collector
    )


def test_economic_configuration_is_translated_exactly_for_each_currency() -> None:
    config = _config(multiple_currencies=True)
    _, _, orchestrator, _ = _concrete_runtime(config)
    individual_scanner = cast(
        DefaultOpportunityScanner, orchestrator.opportunity_scanner
    )
    detector = cast(
        DefaultArbitrageOpportunityDetector,
        individual_scanner.arbitrage_detector,
    )
    lot_analyzer = cast(
        DefaultLotOpportunityAnalyzer,
        orchestrator.lot_opportunity_scanner.lot_analyzer,
    )
    policy = detector.economic_policy

    assert policy is lot_analyzer.economic_policy
    assert policy.selling_fee_rate is config.economics.selling_fee_rate
    assert policy.safety_buffer_rate is config.economics.safety_buffer_rate
    assert set(policy.absolute_costs_by_currency) == {"EUR", "USD"}
    for configured in config.economics.currencies:
        costs = policy.absolute_costs_by_currency[configured.currency]
        assert costs.quick_sale_discount_per_item is (
            configured.quick_sale_discount_per_item
        )
        assert costs.fixed_selling_cost_per_item is (
            configured.fixed_selling_cost_per_item
        )
        assert costs.acquisition_overhead is configured.acquisition_overhead
        assert detector.min_net_profit_by_currency[configured.currency] is (
            configured.individual_min_net_profit
        )
        assert lot_analyzer.min_net_profit_by_currency[configured.currency] is (
            configured.lot_min_net_profit
        )
    assert detector.min_net_profit_margin_percent is (
        config.economics.individual_min_net_profit_margin_percent
    )
    assert detector.min_confidence_score == (
        config.economics.individual_min_confidence_score
    )
    assert policy.absolute_costs_by_currency["USD"].acquisition_overhead == Decimal(
        "3.625"
    )


def test_scanners_receive_the_configured_location() -> None:
    config = _config()
    _, _, orchestrator, _ = _concrete_runtime(config)

    assert orchestrator.opportunity_scanner.latitude == config.location.latitude
    assert orchestrator.opportunity_scanner.longitude == config.location.longitude
    assert orchestrator.lot_opportunity_scanner.latitude == config.location.latitude
    assert orchestrator.lot_opportunity_scanner.longitude == config.location.longitude


def test_composition_has_no_neutral_policy_async_or_mutable_globals() -> None:
    source = COMPOSITION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    mutable_globals = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(
            node.value,
            (ast.Dict, ast.List, ast.Set),
        )
    ]

    assert "ResaleEconomicPolicy.neutral" not in source
    assert "async def" not in source
    assert "await " not in source
    assert "playwright" not in source.casefold()
    assert mutable_globals == []
