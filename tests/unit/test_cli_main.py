"""Unit tests for the operational CLI parser and scan command."""

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import presentation.cli.main as cli_main
from application.interfaces.candidate_search import SearchQuery
from application.interfaces.search_orchestrator import (
    CandidateRoutingFailure,
    CandidateRoutingFailureKind,
    CandidateRoutingRecord,
    SearchOrchestrationResult,
    SearchPlan,
    SearchQueryFailure,
)
from application.interfaces.search_plan_generator import (
    SearchPlanGenerationResult,
    SearchPlanLimitExceededError,
    UnknownGameSearchTargetError,
)
from domain.entities.candidate_classification import (
    CandidateClassificationReason,
    CandidateDisposition,
)
from domain.entities.detected_game import Platform
from infrastructure.marketplaces.wallapop.playwright_client import (
    WallapopPlaywrightError,
)
from presentation.cli.config import (
    AppConfig,
    CurrencyEconomicsConfig,
    EconomicsConfig,
    LocationConfig,
    OutputConfig,
    SafetyConfig,
    SearchConfig,
    SearchTargetConfig,
    WallapopConfig,
)
from presentation.cli.config_loader import AppConfigLoadError
from presentation.cli.json_report import JsonReportWriteError

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


def _config(*, output: OutputConfig | None = None) -> AppConfig:
    return AppConfig(
        wallapop=WallapopConfig(),
        location=LocationConfig(latitude=40.0, longitude=-3.0),
        search=SearchConfig(
            max_queries=4,
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
            individual_min_net_profit_margin_percent="10",
            individual_min_confidence_score=0.5,
            currencies=(
                CurrencyEconomicsConfig(
                    currency="EUR",
                    quick_sale_discount_per_item="1",
                    fixed_selling_cost_per_item="1",
                    acquisition_overhead="1",
                    individual_min_net_profit="3",
                    lot_min_net_profit="5",
                ),
            ),
        ),
        output=output or OutputConfig(),
        safety=SafetyConfig(max_targets=4),
    )


def _execution(
    *,
    query_failures: tuple[SearchQueryFailure, ...] = (),
    total_queries: int = 1,
    executed_queries: int = 1,
) -> SearchOrchestrationResult:
    return SearchOrchestrationResult(
        individual_result=None,
        lot_results=(),
        query_failures=query_failures,
        item_failures=(),
        routing_failures=(),
        total_queries=total_queries,
        executed_queries=executed_queries,
        duplicate_queries=total_queries - executed_queries,
        total_items_received=0,
        valid_candidates_received=0,
        duplicate_candidates=0,
        unique_candidates=0,
        individual_candidates=0,
        lot_candidates=0,
        undetected_candidates=0,
        processing_time=0.1,
        created_at=_NOW,
    )


def _routing_record(
    listing_id: str,
    disposition: CandidateDisposition,
) -> CandidateRoutingRecord:
    reason = (
        CandidateClassificationReason.UNSUPPORTED_HARDWARE
        if disposition is CandidateDisposition.IGNORED
        else CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM
    )
    return CandidateRoutingRecord(
        listing_id=listing_id,
        listing_title=f"Candidate {listing_id}",
        disposition=disposition,
        reason=reason,
    )


def _classified_execution(
    ignored: tuple[CandidateRoutingRecord, ...],
    ambiguous: tuple[CandidateRoutingRecord, ...],
    *,
    technical_failure: bool,
) -> SearchOrchestrationResult:
    routing_failures = (
        (
            CandidateRoutingFailure(
                listing_id="technical-failure",
                kind=CandidateRoutingFailureKind.GAME_DETECTION_ERROR,
                reason="Game detection failed",
                error_type="RuntimeError",
                error_message="controlled failure",
            ),
        )
        if technical_failure
        else ()
    )
    undetected_candidates = int(technical_failure)
    unique_candidates = len(ignored) + len(ambiguous) + undetected_candidates
    return replace(
        _execution(),
        routing_failures=routing_failures,
        total_items_received=unique_candidates,
        valid_candidates_received=unique_candidates,
        unique_candidates=unique_candidates,
        undetected_candidates=undetected_candidates,
        ignored_candidates=ignored,
        ambiguous_candidates=ambiguous,
    )


class _Generator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self.request: object | None = None

    def generate(self, request: object) -> SearchPlanGenerationResult:
        self.calls += 1
        self.request = request
        if self.error is not None:
            raise self.error
        plan = SearchPlan((SearchQuery("Grand Theft Auto V PS4", 40.0, -3.0, 10),))
        return SearchPlanGenerationResult(plan, 1, 1, 0)


class _Orchestrator:
    def __init__(
        self,
        result: SearchOrchestrationResult,
        error: BaseException | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def execute(self, plan: SearchPlan) -> SearchOrchestrationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _patch_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: AppConfig | None = None,
    generator: _Generator | None = None,
    orchestrator: _Orchestrator | None = None,
) -> tuple[_Generator, _Orchestrator, dict[str, bool]]:
    configured = config or _config()
    fake_generator = generator or _Generator()
    fake_orchestrator = orchestrator or _Orchestrator(_execution())
    lifecycle = {"opened": False, "closed": False}

    def load(path: Path) -> AppConfig:
        return configured

    @asynccontextmanager
    async def open_runtime(runtime_config: AppConfig) -> Any:
        lifecycle["opened"] = True
        try:
            yield SimpleNamespace(
                plan_generator=fake_generator,
                search_orchestrator=fake_orchestrator,
            )
        finally:
            lifecycle["closed"] = True

    monkeypatch.setattr(cli_main, "load_app_config", load)
    monkeypatch.setattr(cli_main, "open_operational_runtime", open_runtime)
    return fake_generator, fake_orchestrator, lifecycle


@pytest.mark.unit
@pytest.mark.parametrize("arguments", [[], ["scan"], ["scan", "--config", "x.toml"], ["other"]])
def test_parser_keeps_argparse_code_two_for_invalid_arguments(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        cli_main.main(arguments)
    assert error.value.code == 2


@pytest.mark.unit
def test_help_and_version_use_standard_argparse_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as help_error:
        cli_main.main(["--help"])
    assert help_error.value.code == 0
    assert "scan" in capsys.readouterr().out

    with pytest.raises(SystemExit) as version_error:
        cli_main.main(["--version"])
    assert version_error.value.code == 0
    assert "wallapop-arbitrage" in capsys.readouterr().out


@pytest.mark.unit
def test_version_falls_back_when_distribution_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def missing(distribution_name: str) -> str:
        raise cli_main.PackageNotFoundError(distribution_name)

    monkeypatch.setattr(cli_main, "version", missing)

    with pytest.raises(SystemExit) as error:
        cli_main.main(["--version"])

    assert error.value.code == 0
    assert "development" in capsys.readouterr().out


@pytest.mark.unit
def test_main_parses_scan_verbose_and_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def run(coroutine: Any) -> int:
        frame = coroutine.cr_frame
        captured.update(frame.f_locals)
        coroutine.close()
        return 17

    monkeypatch.setattr(cli_main.asyncio, "run", run)
    result = cli_main.main(
        ["scan", "--config", "config.toml", "--confirm-live", "--verbose"]
    )

    assert result == 17
    assert captured["config_path"] == Path("config.toml")
    assert captured["confirm_live"] is True
    assert captured["verbose"] is True


@pytest.mark.unit
def test_public_contracts_and_type_validation() -> None:
    assert inspect.iscoroutinefunction(cli_main.run_scan)
    assert not inspect.iscoroutinefunction(cli_main.main)

    async def validate() -> None:
        with pytest.raises(TypeError):
            await cli_main.run_scan("config.toml", confirm_live=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            await cli_main.run_scan(Path("config.toml"), confirm_live=1)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            await cli_main.run_scan(
                Path("config.toml"),
                confirm_live=True,
                verbose=1,  # type: ignore[arg-type]
            )

    asyncio.run(validate())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_confirmation_never_loads_config_or_runtime(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_main,
        "load_app_config",
        lambda path: pytest.fail("configuration must not be loaded"),
    )
    monkeypatch.setattr(
        cli_main,
        "open_operational_runtime",
        lambda config: pytest.fail("runtime must not be opened"),
    )

    result = await cli_main.run_scan(Path("config.toml"), confirm_live=False)

    assert result == 2
    assert "confirm-live" in capsys.readouterr().err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_config_error_returns_three_and_loader_is_called_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[Path] = []

    def fail(path: Path) -> AppConfig:
        calls.append(path)
        raise AppConfigLoadError("invalid configuration")

    monkeypatch.setattr(cli_main, "load_app_config", fail)
    monkeypatch.setattr(
        cli_main,
        "preflight_json_report_destination",
        lambda *args, **kwargs: pytest.fail("preflight must not run"),
    )
    monkeypatch.setattr(
        cli_main,
        "open_operational_runtime",
        lambda config: pytest.fail("runtime must not be opened"),
    )

    result = await cli_main.run_scan(Path("bad.toml"), confirm_live=True)

    assert result == 3
    assert calls == [Path("bad.toml")]
    assert "Configuration error" in capsys.readouterr().err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_preserves_targets_duplicates_and_search_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    duplicate_target = config.search.targets[0]
    config = config.model_copy(
        update={
            "search": SearchConfig(
                strategy=config.search.strategy,
                max_queries=4,
                max_results_per_query=9,
                targets=(duplicate_target, duplicate_target),
            )
        }
    )
    generator, orchestrator, lifecycle = _patch_run(monkeypatch, config=config)

    result = await cli_main.run_scan(Path("config.toml"), confirm_live=True)

    request = generator.request
    assert result == 0
    assert generator.calls == 1
    assert orchestrator.calls == 1
    assert [target.canonical_name for target in request.targets] == [  # type: ignore[union-attr]
        "Grand Theft Auto V",
        "Grand Theft Auto V",
    ]
    assert [target.platform for target in request.targets] == [  # type: ignore[union-attr]
        Platform.PS4,
        Platform.PS4,
    ]
    assert request.latitude == 40.0  # type: ignore[union-attr]
    assert request.longitude == -3.0  # type: ignore[union-attr]
    assert request.max_results == 9  # type: ignore[union-attr]
    assert request.max_queries == 4  # type: ignore[union-attr]
    assert request.strategy is config.search.strategy  # type: ignore[union-attr]
    assert lifecycle == {"opened": True, "closed": True}


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("generation_error", "expected_code"),
    [
        (UnknownGameSearchTargetError("missing"), 4),
        (SearchPlanLimitExceededError("too many"), 5),
    ],
)
async def test_generation_errors_close_runtime_without_orchestration(
    monkeypatch: pytest.MonkeyPatch,
    generation_error: Exception,
    expected_code: int,
) -> None:
    generator = _Generator(generation_error)
    orchestrator = _Orchestrator(_execution())
    _, _, lifecycle = _patch_run(
        monkeypatch,
        generator=generator,
        orchestrator=orchestrator,
    )

    result = await cli_main.run_scan(Path("config.toml"), confirm_live=True)

    assert result == expected_code
    assert orchestrator.calls == 0
    assert lifecycle["closed"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_partial_and_total_marketplace_results_have_distinct_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _execution()
    _, _, _ = _patch_run(
        monkeypatch,
        orchestrator=_Orchestrator(empty),
    )
    assert await cli_main.run_scan(Path("config.toml"), confirm_live=True) == 0

    query = SearchQuery("Grand Theft Auto V PS4", 40.0, -3.0, 10)
    failure = SearchQueryFailure(query, 0, "failed", "TimeoutError", "timeout")
    partial = _execution(
        query_failures=(failure,),
        total_queries=2,
        executed_queries=2,
    )
    _, _, _ = _patch_run(
        monkeypatch,
        orchestrator=_Orchestrator(partial),
    )
    assert await cli_main.run_scan(Path("config.toml"), confirm_live=True) == 1

    total = _execution(query_failures=(failure,))
    _, _, _ = _patch_run(
        monkeypatch,
        orchestrator=_Orchestrator(total),
    )
    assert await cli_main.run_scan(Path("config.toml"), confirm_live=True) == 6


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ignored_count", "ambiguous_count", "technical_failure", "expected_code"),
    [
        (1, 0, False, 0),
        (0, 1, False, 0),
        (2, 2, False, 0),
        (1, 0, True, 1),
        (0, 1, True, 1),
    ],
)
async def test_expected_classifications_do_not_change_failure_exit_semantics(
    monkeypatch: pytest.MonkeyPatch,
    ignored_count: int,
    ambiguous_count: int,
    technical_failure: bool,
    expected_code: int,
) -> None:
    ignored = tuple(
        _routing_record(f"ignored-{index}", CandidateDisposition.IGNORED)
        for index in range(ignored_count)
    )
    ambiguous = tuple(
        _routing_record(f"ambiguous-{index}", CandidateDisposition.AMBIGUOUS)
        for index in range(ambiguous_count)
    )
    execution = _classified_execution(
        ignored,
        ambiguous,
        technical_failure=technical_failure,
    )
    _patch_run(monkeypatch, orchestrator=_Orchestrator(execution))

    code = await cli_main.run_scan(Path("config.toml"), confirm_live=True)

    assert code == expected_code


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination_kind",
    ["missing_parent", "existing_target", "directory_target"],
)
async def test_json_preflight_failure_prevents_runtime_and_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    destination_kind: str,
) -> None:
    overwrite = False
    if destination_kind == "missing_parent":
        destination = tmp_path / "missing" / "report.json"
    elif destination_kind == "existing_target":
        destination = tmp_path / "existing.json"
        destination.write_text("existing", encoding="utf-8")
    else:
        destination = tmp_path / "report-directory"
        destination.mkdir()
        overwrite = True
    config = _config(
        output=OutputConfig(
            terminal=True,
            json_path=destination,
            overwrite=overwrite,
        )
    )
    generator, orchestrator, lifecycle = _patch_run(monkeypatch, config=config)

    code = await cli_main.run_scan(Path("config.toml"), confirm_live=True)

    assert code == 7
    assert generator.calls == 0
    assert orchestrator.calls == 0
    assert lifecycle == {"opened": False, "closed": False}
    assert "JSON report error" in capsys.readouterr().err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_outputs_run_once_after_runtime_closes_and_preserve_overwrite(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config = _config(
        output=OutputConfig(
            terminal=True,
            json_path=tmp_path / "report.json",
            overwrite=True,
        )
    )
    _, _, lifecycle = _patch_run(monkeypatch, config=config)
    calls: list[str] = []

    def render(generation: object, execution: object, *, verbose: bool) -> str:
        assert lifecycle["closed"] is True
        calls.append(f"terminal:{verbose}")
        return "REPORT\n"

    def build(generation: object, execution: object) -> dict[str, object]:
        assert lifecycle["closed"] is True
        calls.append("build")
        return {"schema_version": 2}

    def write(report: object, path: Path, *, overwrite: bool) -> None:
        assert lifecycle["closed"] is True
        assert path == tmp_path / "report.json"
        assert overwrite is True
        calls.append("write")

    monkeypatch.setattr(cli_main, "render_terminal_report", render)
    monkeypatch.setattr(cli_main, "build_json_report", build)
    monkeypatch.setattr(cli_main, "write_json_report", write)

    result = await cli_main.run_scan(
        Path("config.toml"),
        confirm_live=True,
        verbose=True,
    )

    assert result == 0
    assert calls == ["terminal:True", "build", "write"]
    assert capsys.readouterr().out == "REPORT\n"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_json_preflight_runs_before_runtime_scan_and_final_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "report.json"
    config = _config(
        output=OutputConfig(
            terminal=False,
            json_path=destination,
            overwrite=False,
        )
    )
    generator, orchestrator, _ = _patch_run(monkeypatch, config=config)
    events: list[str] = []
    original_load = cli_main.load_app_config
    original_open = cli_main.open_operational_runtime
    original_generate = generator.generate
    original_execute = orchestrator.execute

    def load(path: Path) -> AppConfig:
        events.append("load")
        return original_load(path)

    def preflight(path: Path, *, overwrite: bool) -> None:
        assert path == destination
        assert overwrite is False
        events.append("preflight")

    @asynccontextmanager
    async def open_runtime(runtime_config: AppConfig) -> Any:
        events.append("open_runtime")
        async with original_open(runtime_config) as runtime:
            yield runtime

    def generate(request: object) -> SearchPlanGenerationResult:
        events.append("generate")
        return original_generate(request)

    async def execute(plan: SearchPlan) -> SearchOrchestrationResult:
        events.append("scan")
        return await original_execute(plan)

    def build(generation: object, execution: object) -> dict[str, object]:
        events.append("build_json")
        return {"schema_version": 2}

    def write(report: object, path: Path, *, overwrite: bool) -> None:
        events.append("write_json")

    monkeypatch.setattr(cli_main, "load_app_config", load)
    monkeypatch.setattr(cli_main, "preflight_json_report_destination", preflight)
    monkeypatch.setattr(cli_main, "open_operational_runtime", open_runtime)
    monkeypatch.setattr(generator, "generate", generate)
    monkeypatch.setattr(orchestrator, "execute", execute)
    monkeypatch.setattr(cli_main, "build_json_report", build)
    monkeypatch.setattr(cli_main, "write_json_report", write)

    code = await cli_main.run_scan(Path("config.toml"), confirm_live=True)

    assert code == 0
    assert events == [
        "load",
        "preflight",
        "open_runtime",
        "generate",
        "scan",
        "build_json",
        "write_json",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_outputs_are_not_called(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(
        output=OutputConfig(
            terminal=False,
            json_path=Path("report.json"),
            overwrite=False,
        )
    )
    _patch_run(monkeypatch, config=config)
    monkeypatch.setattr(
        cli_main,
        "render_terminal_report",
        lambda *args, **kwargs: pytest.fail("terminal renderer must not run"),
    )
    json_calls: list[str] = []
    monkeypatch.setattr(
        cli_main,
        "build_json_report",
        lambda generation, execution: json_calls.append("build") or {},
    )
    monkeypatch.setattr(
        cli_main,
        "write_json_report",
        lambda report, path, overwrite: json_calls.append("write"),
    )

    result = await cli_main.run_scan(Path("config.toml"), confirm_live=True)

    assert result == 0
    assert json_calls == ["build", "write"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_json_output_is_not_built_when_path_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_run(monkeypatch, config=_config(output=OutputConfig(terminal=True)))
    monkeypatch.setattr(cli_main, "render_terminal_report", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        cli_main,
        "preflight_json_report_destination",
        lambda *args, **kwargs: pytest.fail("preflight must not run"),
    )
    monkeypatch.setattr(
        cli_main,
        "build_json_report",
        lambda *args: pytest.fail("JSON report must not be built"),
    )
    monkeypatch.setattr(
        cli_main,
        "write_json_report",
        lambda *args, **kwargs: pytest.fail("JSON report must not be written"),
    )

    assert await cli_main.run_scan(Path("config.toml"), confirm_live=True) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_json_error_returns_seven_after_runtime_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(
        output=OutputConfig(
            terminal=False,
            json_path=tmp_path / "report.json",
            overwrite=False,
        )
    )
    _, orchestrator, lifecycle = _patch_run(monkeypatch, config=config)
    monkeypatch.setattr(cli_main, "build_json_report", lambda generation, execution: {})

    def fail(report: object, path: Path, *, overwrite: bool) -> None:
        assert lifecycle["closed"] is True
        raise JsonReportWriteError("cannot write")

    monkeypatch.setattr(cli_main, "write_json_report", fail)

    result = await cli_main.run_scan(Path("config.toml"), confirm_live=True)

    assert result == 7
    assert orchestrator.calls == 1
    assert lifecycle == {"opened": True, "closed": True}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancellation_marketplace_and_internal_errors_have_stable_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, _, lifecycle = _patch_run(
        monkeypatch,
        orchestrator=_Orchestrator(_execution(), asyncio.CancelledError()),
    )
    assert await cli_main.run_scan(Path("config.toml"), confirm_live=True) == 130
    assert lifecycle["closed"] is True

    @asynccontextmanager
    async def marketplace_failure(config: AppConfig) -> Any:
        raise WallapopPlaywrightError("unavailable")
        yield

    monkeypatch.setattr(cli_main, "open_operational_runtime", marketplace_failure)
    assert await cli_main.run_scan(Path("config.toml"), confirm_live=True) == 6

    _patch_run(monkeypatch, generator=_Generator(RuntimeError("bug")))
    assert await cli_main.run_scan(Path("config.toml"), confirm_live=True) == 70
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.unit
def test_main_maps_keyboard_interrupt_and_configures_logging(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configurations: list[dict[str, object]] = []

    def configure(**kwargs: object) -> None:
        configurations.append(dict(kwargs))

    def interrupt(coroutine: Any) -> int:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main.logging, "basicConfig", configure)
    monkeypatch.setattr(cli_main.asyncio, "run", interrupt)

    result = cli_main.main(
        ["scan", "--config", "config.toml", "--confirm-live", "--verbose"]
    )

    assert result == 130
    assert configurations[0]["level"] == logging.INFO
    assert configurations[0]["force"] is True
    assert "cancelled" in capsys.readouterr().err.casefold()


@pytest.mark.unit
def test_main_uses_warning_logging_by_default_without_accumulating_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configurations: list[dict[str, object]] = []

    def configure(**kwargs: object) -> None:
        configurations.append(dict(kwargs))

    def run(coroutine: Any) -> int:
        coroutine.close()
        return 0

    monkeypatch.setattr(cli_main.logging, "basicConfig", configure)
    monkeypatch.setattr(cli_main.asyncio, "run", run)

    arguments = ["scan", "--config", "config.toml", "--confirm-live"]
    assert cli_main.main(arguments) == 0
    assert cli_main.main(arguments) == 0
    assert [configuration["level"] for configuration in configurations] == [
        logging.WARNING,
        logging.WARNING,
    ]
    assert all(configuration["force"] is True for configuration in configurations)
