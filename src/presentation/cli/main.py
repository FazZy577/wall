"""Command-line entry point for one explicitly confirmed operational scan."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from application.interfaces.search_orchestrator import SearchOrchestrationResult
from application.interfaces.search_plan_generator import (
    GameSearchTarget,
    SearchPlanGenerationError,
    SearchPlanGenerationRequest,
    SearchPlanLimitExceededError,
    UnknownGameSearchTargetError,
)
from infrastructure.marketplaces.wallapop.playwright_client import (
    WallapopPlaywrightError,
)
from presentation.cli.composition import open_operational_runtime
from presentation.cli.config import AppConfig
from presentation.cli.config_loader import AppConfigLoadError, load_app_config
from presentation.cli.json_report import (
    JsonReportWriteError,
    build_json_report,
    preflight_json_report_destination,
    write_json_report,
)
from presentation.cli.terminal_report import render_terminal_report

__all__ = ("run_scan", "main")

_DISTRIBUTION_NAME = "wallapop-arbitrage"
_LOGGER = logging.getLogger(__name__)


def _distribution_version() -> str:
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "development"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=_DISTRIBUTION_NAME,
        description="Search for configured second-hand game opportunities.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_distribution_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser(
        "scan",
        help="Run one explicitly configured live marketplace scan.",
    )
    scan_parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to the TOML application configuration.",
    )
    scan_parser.add_argument(
        "--confirm-live",
        action="store_true",
        required=True,
        help="Confirm that this command may access the live marketplace.",
    )
    scan_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable informational logging and verbose failure rendering.",
    )
    return parser


def _request_from_config(config: AppConfig) -> SearchPlanGenerationRequest:
    return SearchPlanGenerationRequest(
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


def _has_structured_failures(execution: SearchOrchestrationResult) -> bool:
    individual_failures = (
        execution.individual_result.failures
        if execution.individual_result is not None
        else ()
    )
    return bool(
        execution.query_failures
        or execution.item_failures
        or execution.routing_failures
        or individual_failures
        or any(
            result.failures or result.analysis_failure is not None
            for result in execution.lot_results
        )
    )


def _execution_exit_code(execution: SearchOrchestrationResult) -> int:
    if not _has_structured_failures(execution):
        return 0

    successful_queries = execution.executed_queries - len(execution.query_failures)
    has_usable_result = bool(
        successful_queries > 0
        or execution.total_items_received > 0
        or execution.unique_candidates > 0
        or execution.individual_result is not None
        or execution.lot_results
    )
    all_queries_failed = bool(
        execution.executed_queries > 0
        and len(execution.query_failures) == execution.executed_queries
    )
    if all_queries_failed and not has_usable_result:
        return 6
    return 1


def _safe_error_text(error: BaseException, fallback: str) -> str:
    try:
        message = str(error)
    except Exception:
        return fallback
    normalized = " ".join(message.split())
    return normalized or fallback


def _write_stderr(message: str) -> None:
    sys.stderr.write(message.rstrip() + "\n")


def _unexpected_error(verbose: bool) -> int:
    _write_stderr("Internal error while running scan.")
    if verbose:
        _LOGGER.exception("Unexpected scan failure")
    return 70


async def run_scan(
    config_path: Path,
    *,
    confirm_live: bool,
    verbose: bool = False,
) -> int:
    """Run one configured scan and return its stable process exit code."""
    if not isinstance(config_path, Path):
        raise TypeError("config_path must be pathlib.Path")
    if type(confirm_live) is not bool:
        raise TypeError("confirm_live must be bool")
    if type(verbose) is not bool:
        raise TypeError("verbose must be bool")
    if not confirm_live:
        _write_stderr("Live scan requires explicit --confirm-live.")
        return 2

    try:
        config = load_app_config(config_path)
    except AppConfigLoadError as error:
        _write_stderr(
            f"Configuration error: {_safe_error_text(error, 'unable to load config')}"
        )
        return 3

    try:
        if config.output.json_path is not None:
            preflight_json_report_destination(
                config.output.json_path,
                overwrite=config.output.overwrite,
            )
        request = _request_from_config(config)
        async with open_operational_runtime(config) as runtime:
            generation = runtime.plan_generator.generate(request)
            execution = await runtime.search_orchestrator.execute(generation.plan)

        if config.output.terminal:
            terminal_report = render_terminal_report(
                generation,
                execution,
                verbose=verbose,
            )
            sys.stdout.write(terminal_report)

        if config.output.json_path is not None:
            json_report = build_json_report(generation, execution)
            write_json_report(
                json_report,
                config.output.json_path,
                overwrite=config.output.overwrite,
            )
        return _execution_exit_code(execution)
    except UnknownGameSearchTargetError as error:
        _write_stderr(
            f"Unknown game target: {_safe_error_text(error, 'target not found')}"
        )
        return 4
    except SearchPlanLimitExceededError as error:
        _write_stderr(
            f"Search plan limit exceeded: {_safe_error_text(error, 'plan too large')}"
        )
        return 5
    except JsonReportWriteError as error:
        _write_stderr(
            f"JSON report error: {_safe_error_text(error, 'unable to write report')}"
        )
        return 7
    except WallapopPlaywrightError as error:
        _write_stderr(
            f"Marketplace failure: {_safe_error_text(error, 'marketplace unavailable')}"
        )
        return 6
    except (asyncio.CancelledError, KeyboardInterrupt):
        _write_stderr("Scan cancelled.")
        return 130
    except SearchPlanGenerationError:
        return _unexpected_error(verbose)
    except Exception:
        return _unexpected_error(verbose)


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s | %(name)s | %(message)s",
        stream=sys.stderr,
        force=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and execute the selected command."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    verbose = bool(arguments.verbose)
    _configure_logging(verbose)

    try:
        return asyncio.run(
            run_scan(
                arguments.config,
                confirm_live=arguments.confirm_live,
                verbose=verbose,
            )
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        _write_stderr("Scan cancelled.")
        return 130
    except Exception:
        return _unexpected_error(verbose)
