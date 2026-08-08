"""Offline integration of the production pipeline and terminal renderer."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
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
from presentation.cli.terminal_report import render_terminal_report

pytestmark = pytest.mark.integration

_CANDIDATE_QUERY = "Grand Theft Auto V PS4"


class _FakeMarketplaceSearch(IMarketplaceSearch):
    def __init__(self, responses: Mapping[str, Sequence[dict[str, Any]]]) -> None:
        self._responses = {
            self._normalize(key): tuple(deepcopy(list(items)))
            for key, items in responses.items()
        }
        self.calls: list[str] = []

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        del latitude, longitude
        self.calls.append(keywords)
        return deepcopy(
            list(self._responses.get(self._normalize(keywords), ()))
        )[:max_results]

    @staticmethod
    def _normalize(keywords: str) -> str:
        return " ".join(keywords.strip().casefold().split())


def _raw(
    listing_id: str,
    title: str,
    price: str,
    *,
    description: str = "offline game listing",
) -> dict[str, Any]:
    return {
        "id": listing_id,
        "title": title,
        "description": description,
        "price": price,
        "currency": "EUR",
        "web_slug": listing_id,
        "raw_secret": "must-not-be-rendered",
    }


def _comparables(prefix: str, title: str, prices: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        _raw(f"{prefix}-{index}", title, price)
        for index, price in enumerate(prices * 4)
    ]


def _config() -> AppConfig:
    return AppConfig(
        wallapop=WallapopConfig(headless=True, timeout_ms=20_000, max_pages=1, request_delay=0.0),
        location=LocationConfig(latitude=40.4168, longitude=-3.7038),
        search=SearchConfig(
            max_queries=2,
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
        safety=SafetyConfig(max_targets=2),
    )


def _responses() -> dict[str, Sequence[dict[str, Any]]]:
    return {
        _CANDIDATE_QUERY: (
            _raw(
                "renderer-hardware",
                "PS4 Negra + 3 Juegos + 1 mando",
                "40.00",
                description="Incluye Red Dead Redemption 2",
            ),
            _raw("renderer-platform", "GTA V PS4 y PS5", "10.00"),
            _raw(
                "renderer-edition",
                "GTA V Premium Edition PS4",
                "10.00",
            ),
            _raw("renderer-no-game", "Anuncio no relacionado", "5.00"),
            _raw("renderer-individual", "GTA V PS4 juego individual", "5.00"),
            _raw("renderer-lot", "Lote GTA V RDR2 PS4", "20.00"),
        ),
        "gta v": _comparables("renderer-gta", "GTA V PS4 juego", ("18", "19", "20", "21", "22")),
        "rdr2": _comparables("renderer-rdr2", "RDR2 PS4 juego", ("24", "25", "26", "27", "28")),
    }


@pytest.mark.asyncio
async def test_terminal_renderer_composes_with_full_offline_pipeline() -> None:
    config = _config()
    marketplace = _FakeMarketplaceSearch(_responses())
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
    execution = await runtime.search_orchestrator.execute(generation.plan)
    report = render_terminal_report(generation, execution)

    assert "SEARCH PLAN GENERATION" in report
    assert "SEARCH EXECUTION" in report
    assert "INDIVIDUAL OPPORTUNITIES" in report
    assert "LOT OPPORTUNITIES" in report
    assert "IGNORED CANDIDATES" in report
    assert "AMBIGUOUS CANDIDATES" in report
    assert "FAILURES" in report
    assert "SUMMARY" in report
    assert _CANDIDATE_QUERY in report
    assert "renderer-individual" in report
    assert "renderer-lot" in report
    assert "Ignored candidates: 2" in report
    assert "Ambiguous candidates: 2" in report
    assert "renderer-hardware" in report
    assert "unsupported_hardware" in report
    assert "renderer-no-game" in report
    assert "no_included_game" in report
    assert "renderer-platform" in report
    assert "ambiguous_multiplatform" in report
    assert "renderer-edition" in report
    assert "unsupported_edition" in report
    assert execution.routing_failures == ()
    assert [record.listing_id for record in execution.ignored_candidates] == [
        "renderer-hardware",
        "renderer-no-game",
    ]
    assert [record.listing_id for record in execution.ambiguous_candidates] == [
        "renderer-platform",
        "renderer-edition",
    ]
    assert "EUR" in report
    assert "must-not-be-rendered" not in report
    assert "traceback" not in report.casefold()
    assert marketplace.calls[0] == _CANDIDATE_QUERY
    assert "gta v" in [call.casefold() for call in marketplace.calls]
    assert "rdr2" in [call.casefold() for call in marketplace.calls]
