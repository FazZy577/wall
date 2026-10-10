"""B07 discovery through real planning, browser capture, routing and SQLite."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from application.interfaces.search_plan_generator import (
    SearchPlanGenerationRequest,
    SearchPlanGenerationStrategy,
)
from application.use_cases.default_search_plan_generator import DefaultSearchPlanGenerator
from domain.entities.detected_game import Platform
from domain.entities.search_coverage import MarketplaceCategory, SearchStopReason
from domain.interfaces.game_catalog import IGameCatalog
from presentation.cli.composition import build_operational_runtime
from presentation.cli.config_loader import load_app_config
from presentation.cli.json_report import build_json_report
from presentation.cli.main import _request_from_config
from presentation.cli.terminal_report import render_terminal_report
from tests.unit.test_wallapop_playwright_client import (
    PlaywrightHarness,
    make_listing,
    make_payload,
    make_response,
)

pytestmark = pytest.mark.integration
CATEGORY = MarketplaceCategory.CONSOLES_AND_VIDEO_GAMES


@pytest.mark.parametrize("platforms, expected", [
    ((), [""]), ((Platform.PS5,), ["PS5"]),
    ((Platform.PS4, Platform.PS5, Platform.PS4), ["PS4", "PS5"]),
])
def test_discovery_never_reads_game_catalog(platforms, expected):
    catalog = Mock(spec=IGameCatalog)
    catalog.list_games.side_effect = AssertionError("Discovery must not read game names")
    result = DefaultSearchPlanGenerator(catalog).generate(SearchPlanGenerationRequest(
        targets=(), latitude=40.4, longitude=-3.7, max_results=20, max_queries=5,
        strategy=SearchPlanGenerationStrategy.DISCOVERY, discovery_platforms=platforms,
    ))
    assert [query.keywords for query in result.plan.queries] == expected
    assert all(query.category is CATEGORY for query in result.plan.queries)
    catalog.list_games.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_keyword", ["", "PS5"])
async def test_discovery_url_uses_official_category_parameters(platform_keyword):
    harness = PlaywrightHarness([[make_response(payload=make_payload([]))]])
    async with harness.build_client() as client:
        batch = await client.search_with_scope(platform_keyword, 40.4, -3.7, 20, category=CATEGORY)
    params = parse_qs(urlsplit(harness.page.goto.call_args.args[0]).query, keep_blank_values=True)
    assert params == {
        "keywords": [platform_keyword], "category_id": ["24200"], "subcategory_ids": ["24203"],
        "latitude": ["40.4"], "longitude": ["-3.7"],
    }
    assert batch.coverage.pages_received == 1
    assert batch.coverage.stop_reason is SearchStopReason.EXHAUSTED


@pytest.mark.asyncio
@pytest.mark.parametrize("limit, pages, expected", [
    (1, 3, SearchStopReason.RESULT_LIMIT),
    (20, 1, SearchStopReason.PAGE_LIMIT),
    (20, 3, SearchStopReason.EXHAUSTED),
])
async def test_scan_reports_the_actual_stop_condition(limit, pages, expected):
    harness = PlaywrightHarness([
        [make_response(payload=make_payload([make_listing(1), make_listing(2)], next_page="opaque"))],
        [make_response(payload=make_payload([make_listing(3)]))],
    ])
    async with harness.build_client(max_pages=pages) as client:
        batch = await client.search_with_scope("PS5", 40.4, -3.7, limit, category=CATEGORY)
    assert batch.coverage.stop_reason is expected
    assert batch.coverage.pages_received == (2 if expected is SearchStopReason.EXHAUSTED else 1)
    assert batch.coverage.max_pages == pages
    assert batch.coverage.items_received == (3 if expected is SearchStopReason.EXHAUSTED else 2)


@pytest.mark.asyncio
async def test_absent_pagination_is_not_reported_as_complete():
    payload = {"data": {"section": {"items": []}}}
    harness = PlaywrightHarness([[make_response(payload=payload)]])
    async with harness.build_client() as client:
        batch = await client.search_with_scope("", 40.4, -3.7, 20, category=CATEGORY)
    assert batch.coverage.stop_reason is SearchStopReason.PAGINATION_UNKNOWN


@pytest.mark.asyncio
async def test_new_unknown_game_enters_discovery_and_survives_restart(tmp_path):
    example = Path(__file__).resolve().parents[2] / "config.discovery.example.toml"
    config_path = tmp_path / "config.toml"
    config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    config = load_app_config(config_path)
    assert not config.search.targets
    unknown = {
        "id": "tomorrow-release", "title": "Zyxqv Adventure IX PS5", "description": "Juego fisico completo",
        "price": {"amount": 20, "currency": "EUR"},
    }
    for _ in range(2):
        harness = PlaywrightHarness([[make_response(payload=make_payload([unknown]))]])
        async with harness.build_client() as client:
            runtime = build_operational_runtime(config, client)
            generation = runtime.plan_generator.generate(_request_from_config(config))
            result = await runtime.search_orchestrator.execute(generation.plan)
        assert len(result.ignored_candidates) == 1
        assert not result.query_failures
        assert not result.routing_failures
        report = build_json_report(generation, result)
        scan = report["execution"]["query_scans"][0]
        assert scan["pages_received"] == 1
        assert scan["stop_reason"] == "exhausted"
        assert scan["query"]["category"] == CATEGORY.value
        assert "stop=exhausted" in render_terminal_report(generation, result)
        json.dumps(report)  # Coverage contains no enums or opaque browser objects.
    with closing(sqlite3.connect(config.persistence.database_path)) as connection:
        assert connection.execute("SELECT listing_id, seen_count FROM listing_observations").fetchall() == [
            ("tomorrow-release", 2),
        ]
        assert connection.execute("SELECT status FROM listing_identifications").fetchall() == [("unknown",)]
        assert connection.execute("SELECT count(DISTINCT run_id) FROM query_scans").fetchone() == (2,)


@pytest.mark.asyncio
async def test_failed_second_page_keeps_coverage_and_does_not_claim_completion():
    from infrastructure.marketplaces.wallapop.playwright_client import WallapopSearchHTTPError

    harness = PlaywrightHarness([
        [make_response(payload=make_payload([make_listing(1)], next_page="opaque"))],
        [make_response(status=500)],
    ])
    async with harness.build_client() as client:
        with pytest.raises(WallapopSearchHTTPError) as caught:
            await client.search_with_scope("", 40.4, -3.7, 20, category=CATEGORY)
    assert caught.value.coverage.stop_reason is SearchStopReason.ERROR
    assert caught.value.coverage.pages_received == 1
    assert caught.value.coverage.items_received == 1


@pytest.mark.asyncio
async def test_unsupported_discovery_does_not_silently_search_without_category():
    from domain.interfaces.marketplace_search import IMarketplaceSearch

    class LegacySearch(IMarketplaceSearch):
        async def search_listings(self, *args, **kwargs):
            raise AssertionError("Must not drop the requested category")

    with pytest.raises(NotImplementedError):
        await LegacySearch().search_with_scope("PS5", 40.4, -3.7, 20, category=CATEGORY)


def test_discovery_respects_query_budget():
    from application.interfaces.search_plan_generator import SearchPlanLimitExceededError

    with pytest.raises(SearchPlanLimitExceededError):
        DefaultSearchPlanGenerator(Mock(spec=IGameCatalog)).generate(SearchPlanGenerationRequest(
            targets=(), latitude=40.4, longitude=-3.7, max_results=20, max_queries=1,
            strategy=SearchPlanGenerationStrategy.DISCOVERY,
            discovery_platforms=(Platform.PS4, Platform.PS5),
        ))


@pytest.mark.parametrize("extra", [
    {"targets": [{"canonical_name": "GTA V", "platform": "PS4"}]},
    {"discovery_platforms": ["UNKNOWN"]},
    {"discovery_platforms": ["not a platform"]},
    {"discovery_platforms": "PS5"},
])
def test_discovery_config_rejects_conflicting_or_invalid_filters(extra):
    from pydantic import ValidationError

    from presentation.cli.config import SearchConfig

    with pytest.raises(ValidationError):
        SearchConfig(strategy="discovery", max_queries=4, max_results_per_query=20, **extra)
