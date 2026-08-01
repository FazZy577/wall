"""Tests for the owned Wallapop runtime lifecycle."""

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any, ClassVar

import pytest

from application.use_cases.default_search_orchestrator import DefaultSearchOrchestrator
from application.use_cases.default_search_plan_generator import (
    DefaultSearchPlanGenerator,
)
from domain.entities.detected_game import Platform
from domain.interfaces.marketplace_search import IMarketplaceSearch
from presentation.cli import composition
from presentation.cli.composition import OperationalRuntime, open_operational_runtime
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


class _FakePlaywrightClient(IMarketplaceSearch):
    instances: ClassVar[list["_FakePlaywrightClient"]] = []
    enter_error: ClassVar[BaseException | None] = None

    def __init__(
        self,
        *,
        timeout_ms: float,
        max_pages: int,
        request_delay: float,
        headless: bool,
        debug_response_dir: object,
    ) -> None:
        self.constructor_arguments = {
            "timeout_ms": timeout_ms,
            "max_pages": max_pages,
            "request_delay": request_delay,
            "headless": headless,
            "debug_response_dir": debug_response_dir,
        }
        self.enter_count = 0
        self.exit_count = 0
        self.is_open = False
        self.closed = False
        self.exit_exception: tuple[object, object, object] | None = None
        self.search_calls = 0
        type(self).instances.append(self)

    async def __aenter__(self) -> "_FakePlaywrightClient":
        self.enter_count += 1
        if self.enter_error is not None:
            raise self.enter_error
        self.is_open = True
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.exit_count += 1
        self.exit_exception = (exc_type, exc_value, traceback)
        self.is_open = False
        self.closed = True

    async def search_listings(
        self,
        keywords: str,
        latitude: float,
        longitude: float,
        max_results: int,
    ) -> list[dict[str, Any]]:
        del keywords, latitude, longitude, max_results
        self.search_calls += 1
        return []


@pytest.fixture(autouse=True)
def _replace_playwright_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakePlaywrightClient.instances.clear()
    _FakePlaywrightClient.enter_error = None
    monkeypatch.setattr(
        composition,
        "WallapopPlaywrightClient",
        _FakePlaywrightClient,
    )


def _config() -> AppConfig:
    return AppConfig(
        wallapop=WallapopConfig(
            headless=True,
            timeout_ms=12_345,
            max_pages=2,
            request_delay=0.25,
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
            individual_min_net_profit_margin_percent="25.0",
            individual_min_confidence_score=0.5,
            currencies=(
                CurrencyEconomicsConfig(
                    currency="EUR",
                    quick_sale_discount_per_item="1.50",
                    fixed_selling_cost_per_item="0.75",
                    acquisition_overhead="2.00",
                    individual_min_net_profit="10.00",
                    lot_min_net_profit="15.00",
                ),
            ),
        ),
        safety=SafetyConfig(max_targets=3),
    )


def test_open_runtime_is_an_async_context_manager() -> None:
    manager = open_operational_runtime(_config())

    assert isinstance(manager, AbstractAsyncContextManager)
    assert inspect.isasyncgenfunction(open_operational_runtime.__wrapped__)
    assert open_operational_runtime.__annotations__["config"] is AppConfig
    assert open_operational_runtime.__annotations__["return"] == (
        AsyncIterator[OperationalRuntime]
    )


@pytest.mark.asyncio
async def test_valid_config_opens_one_client_and_yields_productive_runtime() -> None:
    config = _config()

    async with open_operational_runtime(config) as runtime:
        client = _FakePlaywrightClient.instances[0]
        assert isinstance(runtime, OperationalRuntime)
        assert isinstance(runtime.plan_generator, DefaultSearchPlanGenerator)
        assert isinstance(runtime.search_orchestrator, DefaultSearchOrchestrator)
        assert client.is_open
        assert not client.closed
        assert client.enter_count == 1
        assert client.exit_count == 0

    assert len(_FakePlaywrightClient.instances) == 1
    assert client.enter_count == 1
    assert client.exit_count == 1
    assert client.closed
    assert not client.is_open


@pytest.mark.asyncio
async def test_wallapop_config_maps_exactly_and_disables_debug_output() -> None:
    config = _config()

    async with open_operational_runtime(config):
        client = _FakePlaywrightClient.instances[0]

    assert client.constructor_arguments == {
        "timeout_ms": config.wallapop.timeout_ms,
        "max_pages": config.wallapop.max_pages,
        "request_delay": config.wallapop.request_delay,
        "headless": config.wallapop.headless,
        "debug_response_dir": None,
    }


@pytest.mark.parametrize("invalid", [None, object(), "config", 1, False])
@pytest.mark.asyncio
async def test_invalid_config_fails_before_constructing_client(
    invalid: object,
) -> None:
    with pytest.raises(TypeError, match="config must be AppConfig"):
        async with open_operational_runtime(invalid):  # type: ignore[arg-type]
            pytest.fail("invalid configuration must not yield")

    assert _FakePlaywrightClient.instances == []


@pytest.mark.asyncio
async def test_exact_entered_client_is_passed_to_runtime_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = composition.build_operational_runtime
    received_clients: list[IMarketplaceSearch] = []

    def recording_builder(
        config: AppConfig,
        marketplace_search: IMarketplaceSearch,
    ) -> OperationalRuntime:
        received_clients.append(marketplace_search)
        return original_builder(config, marketplace_search)

    monkeypatch.setattr(composition, "build_operational_runtime", recording_builder)

    async with open_operational_runtime(_config()):
        client = _FakePlaywrightClient.instances[0]

    assert received_clients == [client]


@pytest.mark.asyncio
async def test_caller_exception_reaches_exit_closes_and_propagates() -> None:
    error = RuntimeError("caller failed")

    with pytest.raises(RuntimeError, match="caller failed") as raised:
        async with open_operational_runtime(_config()):
            client = _FakePlaywrightClient.instances[0]
            raise error

    assert raised.value is error
    assert client.exit_count == 1
    assert client.exit_exception is not None
    assert client.exit_exception[0] is RuntimeError
    assert client.exit_exception[1] is error
    assert client.closed


@pytest.mark.asyncio
async def test_cancellation_reaches_exit_closes_and_propagates() -> None:
    cancellation = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError) as raised:
        async with open_operational_runtime(_config()):
            client = _FakePlaywrightClient.instances[0]
            raise cancellation

    assert raised.value is cancellation
    assert client.exit_count == 1
    assert client.exit_exception is not None
    assert client.exit_exception[0] is asyncio.CancelledError
    assert client.exit_exception[1] is cancellation
    assert client.closed


@pytest.mark.asyncio
async def test_client_construction_error_propagates_without_entering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_construction(**_arguments: object) -> _FakePlaywrightClient:
        raise RuntimeError("construction failed")

    monkeypatch.setattr(composition, "WallapopPlaywrightClient", fail_construction)

    with pytest.raises(RuntimeError, match="construction failed"):
        async with open_operational_runtime(_config()):
            pytest.fail("construction failure must not yield")

    assert _FakePlaywrightClient.instances == []


@pytest.mark.asyncio
async def test_enter_error_propagates_without_exit_or_double_close() -> None:
    enter_error = RuntimeError("enter failed")
    _FakePlaywrightClient.enter_error = enter_error

    with pytest.raises(RuntimeError, match="enter failed") as raised:
        async with open_operational_runtime(_config()):
            pytest.fail("enter failure must not yield")

    client = _FakePlaywrightClient.instances[0]
    assert raised.value is enter_error
    assert client.enter_count == 1
    assert client.exit_count == 0
    assert not client.closed


@pytest.mark.asyncio
async def test_two_openings_create_distinct_clients_without_shared_state() -> None:
    async with open_operational_runtime(_config()) as first_runtime:
        first_client = _FakePlaywrightClient.instances[0]
    async with open_operational_runtime(_config()) as second_runtime:
        second_client = _FakePlaywrightClient.instances[1]

    assert first_runtime is not second_runtime
    assert first_client is not second_client
    assert first_client.exit_count == 1
    assert second_client.exit_count == 1
    assert first_client.closed and second_client.closed
