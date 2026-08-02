"""Architecture guards for the initial CLI configuration boundary."""

import ast
import inspect
import tomllib
from pathlib import Path

from presentation.cli import config_loader, json_report
from presentation.cli.composition import (
    OperationalRuntime,
    build_operational_runtime,
    open_operational_runtime,
)
from presentation.cli.config import AppConfig
from presentation.cli.config_loader import AppConfigLoadError, load_app_config
from presentation.cli.json_report import (
    JsonReportWriteError,
    build_json_report,
    write_json_report,
)
from presentation.cli.main import main, run_scan
from presentation.cli.terminal_report import render_terminal_report

PROJECT_ROOT = Path(__file__).parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
CONFIG_PATH = SRC_ROOT / "presentation/cli/config.py"


def _imports_beneath(root: Path) -> list[tuple[Path, str]]:
    imports: list[tuple[Path, str]] = []
    for source_file in root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((source_file, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((source_file, node.module))
    return imports


def _imports_from_file(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_presentation_config_is_canonical_outer_layer_model() -> None:
    source = CONFIG_PATH.read_text(encoding="utf-8")

    assert AppConfig.__module__ == "presentation.cli.config"
    assert "application.interfaces.search_plan_generator" in source
    assert "domain.entities.detected_game" in source


def test_inner_layers_do_not_import_presentation() -> None:
    forbidden = [
        (path.relative_to(SRC_ROOT), module)
        for layer in ("domain", "application", "infrastructure")
        for path, module in _imports_beneath(SRC_ROOT / layer)
        if module == "presentation"
        or module.startswith("presentation.")
        or module == "src.presentation"
        or module.startswith("src.presentation.")
    ]

    assert forbidden == []


def test_config_has_no_forbidden_operational_imports_or_execution() -> None:
    source = CONFIG_PATH.read_text(encoding="utf-8")
    imported_modules = _imports_from_file(CONFIG_PATH)

    assert not any(
        module == "infrastructure"
        or module.startswith("infrastructure.")
        or module == "src.infrastructure"
        or module.startswith("src.infrastructure.")
        for module in imported_modules
    )
    assert "playwright" not in source.casefold()
    assert "tomllib" not in imported_modules
    assert "argparse" not in imported_modules
    assert "pydantic_settings" not in imported_modules
    assert "asyncio" not in imported_modules
    assert "async def" not in source
    assert "await " not in source
    assert "open(" not in source
    assert "DefaultSearchPlanGenerator" not in source
    assert "DefaultSearchOrchestrator" not in source


def test_config_loader_stays_in_presentation_and_has_no_execution_dependencies() -> None:
    loader_path = SRC_ROOT / "presentation/cli/config_loader.py"
    source = loader_path.read_text(encoding="utf-8")
    imported_modules = _imports_from_file(loader_path)

    assert "presentation.cli.config" in imported_modules
    assert "tomllib" in imported_modules
    assert "infrastructure" not in source.casefold()
    assert "playwright" not in source.casefold()
    assert "argparse" not in imported_modules
    assert "asyncio" not in imported_modules
    assert "pydantic_settings" not in imported_modules
    assert "DefaultSearchPlanGenerator" not in source
    assert "DefaultSearchOrchestrator" not in source
    assert "async def" not in source
    assert "await " not in source
    assert AppConfigLoadError.__module__ == "presentation.cli.config_loader"
    assert load_app_config.__annotations__["path"] is Path
    assert load_app_config.__annotations__["return"] is AppConfig
    assert load_app_config.__module__ == "presentation.cli.config_loader"
    assert set(config_loader.__all__) == {"AppConfigLoadError", "load_app_config"}


def test_composition_root_wires_layers_and_owns_live_client_lifecycle() -> None:
    composition_path = SRC_ROOT / "presentation/cli/composition.py"
    source = composition_path.read_text(encoding="utf-8")
    imported_modules = _imports_from_file(composition_path)
    tree = ast.parse(source)
    mutable_globals = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.value, (ast.Dict, ast.List, ast.Set))
    ]

    assert OperationalRuntime.__module__ == "presentation.cli.composition"
    assert build_operational_runtime.__module__ == "presentation.cli.composition"
    assert open_operational_runtime.__module__ == "presentation.cli.composition"
    assert not inspect.iscoroutinefunction(build_operational_runtime)
    assert inspect.isasyncgenfunction(open_operational_runtime.__wrapped__)
    assert any(module.startswith("domain.") for module in imported_modules)
    assert any(module.startswith("application.") for module in imported_modules)
    assert any(module.startswith("infrastructure.") for module in imported_modules)
    assert (
        "infrastructure.marketplaces.wallapop.playwright_client"
        in imported_modules
    )
    assert "WallapopPlaywrightClient" in source
    assert "asynccontextmanager" in source
    assert "async with WallapopPlaywrightClient" in source
    assert "contextlib" in imported_modules
    assert "argparse" not in imported_modules
    assert "tomllib" not in imported_modules
    assert "asyncio" not in imported_modules
    assert "asyncio.run" not in source
    assert "create_task" not in source
    assert "TaskGroup" not in source
    assert "gather(" not in source
    assert "new_event_loop" not in source
    assert "run_until_complete" not in source
    assert "dependency_injector" not in source
    assert "injector" not in imported_modules
    assert mutable_globals == []


def test_terminal_report_is_a_pure_presentation_boundary() -> None:
    report_path = SRC_ROOT / "presentation/cli/terminal_report.py"
    source = report_path.read_text(encoding="utf-8")
    imported_modules = _imports_from_file(report_path)

    assert render_terminal_report.__module__ == "presentation.cli.terminal_report"
    assert "application." in " ".join(imported_modules)
    assert "domain." in " ".join(imported_modules)
    assert not any(
        module == "infrastructure"
        or module.startswith("infrastructure.")
        for module in imported_modules
    )
    assert "infrastructure" not in source.casefold()
    assert "playwright" not in source.casefold()
    assert "presentation.cli.composition" not in imported_modules
    assert "presentation.cli.config_loader" not in imported_modules
    assert "argparse" not in imported_modules
    assert "tomllib" not in imported_modules
    assert "json" not in imported_modules
    assert "asyncio" not in imported_modules
    assert "print(" not in source
    assert "logging" not in imported_modules
    assert "raw_listing" not in source
    assert "open(" not in source


def test_json_report_is_a_safe_presentation_boundary() -> None:
    report_path = SRC_ROOT / "presentation/cli/json_report.py"
    source = report_path.read_text(encoding="utf-8")
    imported_modules = _imports_from_file(report_path)

    assert json_report.__name__ == "presentation.cli.json_report"
    assert JsonReportWriteError.__module__ == "presentation.cli.json_report"
    assert build_json_report.__module__ == "presentation.cli.json_report"
    assert write_json_report.__module__ == "presentation.cli.json_report"
    assert set(json_report.__all__) == {
        "JsonValue",
        "JsonReportWriteError",
        "build_json_report",
        "write_json_report",
    }
    assert any(module.startswith("application.") for module in imported_modules)
    assert any(module.startswith("domain.") for module in imported_modules)
    assert not any(
        module == "infrastructure"
        or module.startswith("infrastructure.")
        or module == "src.infrastructure"
        or module.startswith("src.infrastructure.")
        for module in imported_modules
    )
    assert "playwright" not in source.casefold()
    assert "presentation.cli.composition" not in imported_modules
    assert "presentation.cli.config_loader" not in imported_modules
    assert "argparse" not in imported_modules
    assert "tomllib" not in imported_modules
    assert "print(" not in source
    assert "logging" not in imported_modules
    assert "asyncio" not in imported_modules
    assert "dataclasses.asdict" not in source
    assert "vars(" not in source
    assert "raw_listing" not in source


def test_cli_main_is_the_single_operational_asyncio_boundary() -> None:
    main_path = SRC_ROOT / "presentation/cli/main.py"
    source = main_path.read_text(encoding="utf-8")
    imported_modules = _imports_from_file(main_path)
    asyncio_run_locations = [
        path.relative_to(SRC_ROOT)
        for path in SRC_ROOT.rglob("*.py")
        if "asyncio.run(" in path.read_text(encoding="utf-8")
    ]

    assert main.__module__ == "presentation.cli.main"
    assert run_scan.__module__ == "presentation.cli.main"
    assert inspect.iscoroutinefunction(run_scan)
    assert not inspect.iscoroutinefunction(main)
    assert "argparse" in imported_modules
    assert "asyncio" in imported_modules
    assert "logging" in imported_modules
    assert "presentation.cli.config_loader" in imported_modules
    assert "presentation.cli.composition" in imported_modules
    assert "presentation.cli.terminal_report" in imported_modules
    assert "presentation.cli.json_report" in imported_modules
    assert any(module.startswith("application.") for module in imported_modules)
    assert "WallapopPlaywrightClient" not in source
    assert "DefaultOpportunityScanner" not in source
    assert "DefaultLotOpportunityScanner" not in source
    assert "DefaultSearchPlanGenerator" not in source
    assert "DefaultSearchOrchestrator" not in source
    assert "selling_fee" not in source
    assert "net_profit_margin_percentage" not in source
    assert "asyncio.run(" in source
    assert asyncio_run_locations == [Path("presentation/cli/main.py")]


def test_module_entry_point_only_delegates_to_main() -> None:
    module_path = SRC_ROOT / "presentation/cli/__main__.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = _imports_from_file(module_path)

    assert module_path.exists()
    assert imported_modules == {"presentation.cli.main"}
    assert "raise SystemExit(main())" in source
    assert "asyncio" not in imported_modules
    assert "asyncio.run" not in source
    assert "playwright" not in source.casefold()
    assert "argparse" not in imported_modules
    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in tree.body)


def test_only_operational_console_script_is_registered() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    assert pyproject["project"]["scripts"] == {
        "wallapop-arbitrage": "presentation.cli.main:main"
    }


def test_cli_does_not_introduce_persistence_or_scheduling() -> None:
    cli_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SRC_ROOT / "presentation/cli").glob("*.py")
    ).casefold()

    assert "sqlite" not in cli_source
    assert "scheduler" not in cli_source
    assert "apscheduler" not in cli_source
    assert "cron" not in cli_source
