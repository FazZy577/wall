"""Offline integration of the operational CLI composition root."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from application.interfaces.search_plan_generator import (
    GameSearchTarget,
    SearchPlanGenerationRequest,
)
from domain.entities.detected_game import Platform
from domain.interfaces.marketplace_search import IMarketplaceSearch
from presentation.cli.composition import build_operational_runtime
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

pytestmark = pytest.mark.integration

_CANDIDATE_QUERY = "Grand Theft Auto V PS4"
_COMPARABLE_QUERY = "gta v"


@dataclass(frozen=True)
class _MarketplaceCall:
    keywords: str
    latitude: float
    longitude: float
    max_results: int


class _OfflineMarketplaceSearch(IMarketplaceSearch):
    def __init__(
        self,
        responses: Mapping[str, Sequence[dict[str, Any]]],
    ) -> None:
        self._responses = {
            self._normalize(keywords): tuple(deepcopy(list(items)))
            for keywords, items in responses.items()
        }
        self.calls: list[_MarketplaceCall] = []
        self.closed = False

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            _MarketplaceCall(keywords, latitude, longitude, max_results)
        )
        response = deepcopy(
            list(self._responses.get(self._normalize(keywords), ()))
        )
        return response[:max_results]

    async def close(self) -> None:
        self.closed = True

    @staticmethod
    def _normalize(keywords: str) -> str:
        return " ".join(keywords.strip().casefold().split())


def _raw_listing(
    listing_id: str,
    title: str,
    price: str,
) -> dict[str, Any]:
    return {
        "id": listing_id,
        "title": title,
        "description": "Videojuego completo en buen estado",
        "price": price,
        "currency": "EUR",
        "web_slug": listing_id,
    }


def _config() -> AppConfig:
    return AppConfig(
        wallapop=WallapopConfig(
            headless=True,
            timeout_ms=20_000,
            max_pages=2,
            request_delay=0.5,
        ),
        location=LocationConfig(latitude=40.4168, longitude=-3.7038),
        search=SearchConfig(
            max_queries=3,
            max_results_per_query=10,
            targets=(
                SearchTargetConfig(
                    canonical_name="Grand Theft Auto V",
                    platform=Platform.PS4,
                ),
            ),
        ),
        economics=EconomicsConfig(
            selling_fee_rate="0.10",
            safety_buffer_rate="0.05",
            individual_min_net_profit_margin_percent="10.0",
            individual_min_confidence_score=0.0,
            currencies=(
                CurrencyEconomicsConfig(
                    currency="EUR",
                    quick_sale_discount_per_item="1.50",
                    fixed_selling_cost_per_item="0.75",
                    acquisition_overhead="2.00",
                    individual_min_net_profit="3.00",
                    lot_min_net_profit="5.00",
                ),
            ),
        ),
        safety=SafetyConfig(max_targets=3),
    )


def _responses() -> dict[str, Sequence[dict[str, Any]]]:
    comparables = [
        _raw_listing(
            f"composition-comparable-{index}",
            "GTA V PS4 juego",
            price,
        )
        for index, price in enumerate(("18", "19", "20", "21", "22") * 4)
    ]
    return {
        _CANDIDATE_QUERY: (
            _raw_listing(
                "composition-candidate-gta",
                "GTA V PS4 juego individual",
                "5.00",
            ),
        ),
        _COMPARABLE_QUERY: comparables,
    }


@pytest.mark.asyncio
async def test_composed_runtime_executes_the_full_pipeline_offline() -> None:
    config = _config()
    marketplace = _OfflineMarketplaceSearch(_responses())
    runtime = build_operational_runtime(config, marketplace)
    request = SearchPlanGenerationRequest(
        targets=tuple(
            GameSearchTarget(target.canonical_name, target.platform)
            for target in config.search.targets
        ),
        latitude=config.location.latitude,
        longitude=config.location.longitude,
        max_results=config.search.max_results_per_query,
        max_queries=config.search.max_queries,
        strategy=config.search.strategy,
    )

    generation = runtime.plan_generator.generate(request)
    result = await runtime.search_orchestrator.execute(generation.plan)

    assert generation.queries_generated == 1
    assert generation.plan.queries[0].keywords == _CANDIDATE_QUERY
    assert [call.keywords.casefold() for call in marketplace.calls] == [
        _CANDIDATE_QUERY.casefold(),
        _COMPARABLE_QUERY,
    ]
    assert marketplace.calls[0].max_results == config.search.max_results_per_query
    assert marketplace.calls[1].max_results == 100
    assert result.individual_result is not None
    assert len(result.individual_result.opportunities) == 1
    opportunity = result.individual_result.opportunities[0]
    breakdown = opportunity.economic_breakdown
    assert opportunity.listing.currency == "EUR"
    assert isinstance(opportunity.listing.price, Decimal)
    assert isinstance(opportunity.market_price, Decimal)
    assert breakdown.currency == "EUR"
    assert breakdown.quick_sale_discount_total == Decimal("1.50")
    assert breakdown.fixed_selling_costs == Decimal("0.75")
    assert breakdown.acquisition_overhead == Decimal("2.00")
    assert breakdown.selling_fees == (
        breakdown.expected_sale_revenue * config.economics.selling_fee_rate
    )
    assert breakdown.safety_buffer == (
        breakdown.expected_sale_revenue * config.economics.safety_buffer_rate
    )
    assert result.query_failures == ()
    assert result.routing_failures == ()
    assert not marketplace.closed
