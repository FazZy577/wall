"""Offline integration tests for the operational scan command."""

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import presentation.cli.main as cli_main
from domain.interfaces.marketplace_search import IMarketplaceSearch
from presentation.cli.composition import build_operational_runtime
from presentation.cli.config import AppConfig

pytestmark = pytest.mark.integration

_GTA_QUERY = "Grand Theft Auto V PS4"
_RDR_QUERY = "Red Dead Redemption 2 PS4"


class _FakeMarketplaceSearch(IMarketplaceSearch):
    def __init__(
        self,
        responses: Mapping[str, Sequence[dict[str, Any]]] | None = None,
        failures: Sequence[str] = (),
    ) -> None:
        self._responses = {
            self._normalize(key): tuple(deepcopy(list(items)))
            for key, items in (responses or {}).items()
        }
        self._failures = {self._normalize(key) for key in failures}
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
        normalized = self._normalize(keywords)
        if normalized in self._failures:
            raise RuntimeError("offline marketplace failure")
        return deepcopy(list(self._responses.get(normalized, ())))[:max_results]

    @staticmethod
    def _normalize(keywords: str) -> str:
        return " ".join(keywords.strip().casefold().split())


def _raw(listing_id: str, title: str, price: str) -> dict[str, Any]:
    return {
        "id": listing_id,
        "title": title,
        "description": "offline game listing",
        "price": price,
        "currency": "EUR",
        "web_slug": listing_id,
        "raw_secret": "must-not-be-reported",
    }


def _comparables(prefix: str, title: str, prices: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        _raw(f"{prefix}-{index}", title, price)
        for index, price in enumerate(prices * 4)
    ]


def _write_config(
    path: Path,
    *,
    targets: tuple[tuple[str, str], ...] = (("Grand Theft Auto V", "PS4"),),
    max_queries: int = 4,
    json_path: str | None = None,
) -> None:
    target_sections = "\n".join(
        (
            "[[search.targets]]\n"
            f'canonical_name = "{name}"\n'
            f'platform = "{platform}"'
        )
        for name, platform in targets
    )
    json_setting = f'json_path = "{json_path}"\n' if json_path is not None else ""
    path.write_text(
        (
            "[wallapop]\n"
            "headless = true\n"
            "timeout_ms = 20000\n"
            "max_pages = 1\n"
            "request_delay = 0.0\n\n"
            "[location]\n"
            "latitude = 40.4168\n"
            "longitude = -3.7038\n\n"
            "[search]\n"
            'strategy = "canonical_only"\n'
            f"max_queries = {max_queries}\n"
            "max_results_per_query = 10\n\n"
            f"{target_sections}\n\n"
            "[economics]\n"
            'selling_fee_rate = "0.10"\n'
            'safety_buffer_rate = "0.05"\n'
            'individual_min_net_profit_margin_percent = "10.0"\n'
            "individual_min_confidence_score = 0.0\n\n"
            "[[economics.currencies]]\n"
            'currency = "EUR"\n'
            'quick_sale_discount_per_item = "1.50"\n'
            'fixed_selling_cost_per_item = "0.75"\n'
            'acquisition_overhead = "2.00"\n'
            'individual_min_net_profit = "3.00"\n'
            'lot_min_net_profit = "5.00"\n\n'
            "[output]\n"
            "terminal = true\n"
            f"{json_setting}"
            "overwrite = false\n\n"
            "[safety]\n"
            f"max_targets = {len(targets)}\n"
        ),
        encoding="utf-8",
    )


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    marketplace: _FakeMarketplaceSearch,
) -> dict[str, bool]:
    lifecycle = {"opened": False, "closed": False}

    @asynccontextmanager
    async def open_runtime(config: AppConfig) -> AsyncIterator[Any]:
        lifecycle["opened"] = True
        try:
            yield build_operational_runtime(config, marketplace)
        finally:
            lifecycle["closed"] = True

    monkeypatch.setattr(cli_main, "open_operational_runtime", open_runtime)
    return lifecycle


def _success_responses() -> dict[str, Sequence[dict[str, Any]]]:
    return {
        _GTA_QUERY: (
            _raw("cli-individual", "GTA V PS4 juego individual", "5.00"),
        ),
        "gta v": _comparables(
            "cli-gta",
            "GTA V PS4 juego",
            ("18", "19", "20", "21", "22"),
        ),
    }


@pytest.mark.asyncio
async def test_scan_command_runs_full_offline_pipeline_and_writes_both_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    _write_config(config_path, json_path="scan.json")
    marketplace = _FakeMarketplaceSearch(_success_responses())
    lifecycle = _patch_runtime(monkeypatch, marketplace)

    code = await cli_main.run_scan(config_path, confirm_live=True)

    captured = capsys.readouterr()
    report_path = tmp_path / "scan.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert code == 0
    assert lifecycle == {"opened": True, "closed": True}
    assert "SEARCH PLAN GENERATION" in captured.out
    assert "SEARCH EXECUTION" in captured.out
    assert report["schema_version"] == 1
    assert report["generation"]["queries"][0]["keywords"] == _GTA_QUERY
    assert report["individual_opportunities"][0]["currency"] == "EUR"
    assert isinstance(report["individual_opportunities"][0]["purchase_price"], str)
    assert _GTA_QUERY in marketplace.calls
    assert "gta v" in [call.casefold() for call in marketplace.calls]
    serialized = report_path.read_text(encoding="utf-8").casefold()
    assert "must-not-be-reported" not in serialized
    assert "traceback" not in serialized


@pytest.mark.asyncio
async def test_unknown_target_and_limit_errors_do_not_search_marketplace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace = _FakeMarketplaceSearch()
    lifecycle = _patch_runtime(monkeypatch, marketplace)
    unknown_path = tmp_path / "unknown.toml"
    _write_config(unknown_path, targets=(("Unknown Game", "PS4"),))

    assert await cli_main.run_scan(unknown_path, confirm_live=True) == 4
    assert lifecycle["closed"] is True
    assert marketplace.calls == []

    limit_path = tmp_path / "limit.toml"
    _write_config(
        limit_path,
        targets=(
            ("Grand Theft Auto V", "PS4"),
            ("Red Dead Redemption 2", "PS4"),
        ),
        max_queries=1,
    )
    lifecycle.update(opened=False, closed=False)

    assert await cli_main.run_scan(limit_path, confirm_live=True) == 5
    assert lifecycle["closed"] is True
    assert marketplace.calls == []


@pytest.mark.asyncio
async def test_partial_query_failure_and_valid_empty_search_are_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial_path = tmp_path / "partial.toml"
    _write_config(
        partial_path,
        targets=(
            ("Grand Theft Auto V", "PS4"),
            ("Red Dead Redemption 2", "PS4"),
        ),
    )
    partial_marketplace = _FakeMarketplaceSearch(failures=(_GTA_QUERY,))
    _patch_runtime(monkeypatch, partial_marketplace)

    assert await cli_main.run_scan(partial_path, confirm_live=True) == 1
    assert partial_marketplace.calls == [_GTA_QUERY, _RDR_QUERY]

    empty_path = tmp_path / "empty.toml"
    _write_config(empty_path)
    empty_marketplace = _FakeMarketplaceSearch()
    _patch_runtime(monkeypatch, empty_marketplace)

    assert await cli_main.run_scan(empty_path, confirm_live=True) == 0
    assert empty_marketplace.calls == [_GTA_QUERY]
