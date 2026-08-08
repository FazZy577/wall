"""Offline pipeline integration through the owned runtime context manager."""

from copy import deepcopy
from decimal import Decimal
from typing import Any, ClassVar

import pytest

from application.interfaces.search_plan_generator import (
    GameSearchTarget,
    SearchPlanGenerationRequest,
)
from domain.entities.detected_game import Platform
from domain.interfaces.marketplace_search import IMarketplaceSearch
from presentation.cli import composition
from presentation.cli.composition import open_operational_runtime
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
_COMPARABLE_QUERY = "gta v PS4"


class _OfflinePlaywrightClient(IMarketplaceSearch):
    instances: ClassVar[list["_OfflinePlaywrightClient"]] = []
    responses: ClassVar[dict[str, list[dict[str, Any]]]] = {}

    def __init__(
        self,
        *,
        timeout_ms: float,
        max_pages: int,
        request_delay: float,
        headless: bool,
        debug_response_dir: object,
    ) -> None:
        del timeout_ms, max_pages, request_delay, headless
        assert debug_response_dir is None
        self.is_open = False
        self.closed = False
        self.calls: list[str] = []
        type(self).instances.append(self)

    async def __aenter__(self) -> "_OfflinePlaywrightClient":
        self.is_open = True
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self.is_open = False
        self.closed = True

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        del latitude, longitude
        assert self.is_open
        self.calls.append(keywords)
        response = deepcopy(self.responses.get(self._normalize(keywords), []))
        return response[:max_results]

    @staticmethod
    def _normalize(keywords: str) -> str:
        return " ".join(keywords.strip().casefold().split())


def _raw_listing(listing_id: str, title: str, price: str) -> dict[str, Any]:
    return {
        "id": listing_id,
        "title": title,
        "description": "Videojuego completo en buen estado",
        "price": price,
        "currency": "EUR",
        "web_slug": listing_id,
    }


def _responses() -> dict[str, list[dict[str, Any]]]:
    comparables = [
        _raw_listing(
            f"lifecycle-comparable-{index}",
            "GTA V PS4 juego",
            price,
        )
        for index, price in enumerate(("18", "19", "20", "21", "22") * 4)
    ]
    return {
        _OfflinePlaywrightClient._normalize(_CANDIDATE_QUERY): [
            _raw_listing(
                "lifecycle-candidate-gta",
                "GTA V PS4 juego individual",
                "5.00",
            )
        ],
        _OfflinePlaywrightClient._normalize(_COMPARABLE_QUERY): comparables,
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


@pytest.mark.asyncio
async def test_open_runtime_executes_pipeline_and_closes_owned_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _OfflinePlaywrightClient.instances.clear()
    _OfflinePlaywrightClient.responses = _responses()
    monkeypatch.setattr(
        composition,
        "WallapopPlaywrightClient",
        _OfflinePlaywrightClient,
    )
    config = _config()

    async with open_operational_runtime(config) as runtime:
        client = _OfflinePlaywrightClient.instances[0]
        assert client.is_open
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

        assert client.calls == [_CANDIDATE_QUERY, _COMPARABLE_QUERY]
        assert result.individual_result is not None
        assert len(result.individual_result.opportunities) == 1
        opportunity = result.individual_result.opportunities[0]
        assert opportunity.listing.currency == "EUR"
        assert isinstance(opportunity.listing.price, Decimal)
        assert isinstance(opportunity.market_price, Decimal)
        assert opportunity.economic_breakdown.currency == "EUR"
        assert result.query_failures == ()
        assert result.routing_failures == ()
        assert not client.closed

    assert len(_OfflinePlaywrightClient.instances) == 1
    assert not client.is_open
    assert client.closed
