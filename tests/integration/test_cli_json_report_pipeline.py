"""Offline integration test for the operational JSON report boundary."""

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
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
from presentation.cli.json_report import (
    build_json_report,
    preflight_json_report_destination,
    write_json_report,
)

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
        "raw_secret": "must-not-be-reported",
    }


def _comparables(
    prefix: str,
    title: str,
    prices: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        _raw(f"{prefix}-{index}", title, price)
        for index, price in enumerate(prices * 4)
    ]


def _config() -> AppConfig:
    return AppConfig(
        wallapop=WallapopConfig(
            headless=True,
            timeout_ms=20_000,
            max_pages=1,
            request_delay=0.0,
        ),
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
                "json-hardware",
                "PS4 Negra + 3 Juegos + 1 mando",
                "40.00",
                description="Incluye Red Dead Redemption 2",
            ),
            _raw("json-platform", "GTA V PS4 y PS5", "10.00"),
            _raw("json-edition", "GTA V Premium Edition PS4", "10.00"),
            _raw("json-no-game", "Anuncio no relacionado", "5.00"),
            _raw("json-individual", "GTA V PS4 juego individual", "5.00"),
            _raw("json-lot", "Lote GTA V RDR2 PS4", "20.00"),
        ),
        "gta v ps4": _comparables(
            "json-gta",
            "GTA V PS4 juego",
            ("18", "19", "20", "21", "22"),
        ),
        "rdr2 ps4": _comparables(
            "json-rdr2",
            "RDR2 PS4 juego",
            ("24", "25", "26", "27", "28"),
        ),
    }


@pytest.mark.asyncio
async def test_json_report_pipeline_is_offline_and_serializable(tmp_path: Path) -> None:
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
    report = build_json_report(generation, execution)
    output = tmp_path / "operational-report.json"
    preflight_json_report_destination(output, overwrite=False)
    assert not output.exists()
    write_json_report(report, output, overwrite=False)
    loaded = json.loads(output.read_text(encoding="utf-8"))

    assert loaded["schema_version"] == 2
    assert loaded["generation"]["queries"]
    keywords = [query["keywords"] for query in loaded["generation"]["queries"]]
    assert "Grand Theft Auto V PS4" in keywords
    assert loaded["individual_opportunities"]
    assert loaded["lot_results"]
    assert [record["listing_id"] for record in loaded["ignored_candidates"]] == [
        "json-hardware",
        "json-no-game",
    ]
    assert [record["reason"] for record in loaded["ignored_candidates"]] == [
        "unsupported_hardware",
        "no_included_game",
    ]
    assert [
        record["listing_id"] for record in loaded["ambiguous_candidates"]
    ] == ["json-platform", "json-edition"]
    assert [record["reason"] for record in loaded["ambiguous_candidates"]] == [
        "ambiguous_multiplatform",
        "unsupported_edition",
    ]
    assert loaded["execution"]["candidates"]["ignored"] == 2
    assert loaded["execution"]["candidates"]["ambiguous"] == 2
    assert loaded["summary"]["ignored_candidates"] == 2
    assert loaded["summary"]["ambiguous_candidates"] == 2
    assert loaded["failures"]["routing"] == []
    assert loaded["summary"]["structured_failures"] == sum(
        len(failures) for failures in loaded["failures"].values()
    )
    assert execution.routing_failures == ()
    assert all(
        isinstance(opportunity["purchase_price"], str)
        for opportunity in loaded["individual_opportunities"]
    )
    assert all(
        opportunity["currency"] == "EUR"
        for opportunity in loaded["individual_opportunities"]
    )
    serialized = output.read_text(encoding="utf-8").casefold()
    assert "raw_secret" not in serialized
    assert "must-not-be-reported" not in serialized
    assert "traceback" not in serialized
    assert marketplace.calls
