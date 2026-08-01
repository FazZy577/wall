"""Architecture guards for the initial CLI configuration boundary."""

import ast
import inspect
from pathlib import Path

from presentation.cli import config_loader
from presentation.cli.composition import OperationalRuntime, build_operational_runtime
from presentation.cli.config import AppConfig
from presentation.cli.config_loader import AppConfigLoadError, load_app_config

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


def test_composition_root_wires_layers_without_owning_external_lifecycle() -> None:
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
    assert not inspect.iscoroutinefunction(build_operational_runtime)
    assert any(module.startswith("domain.") for module in imported_modules)
    assert any(module.startswith("application.") for module in imported_modules)
    assert any(module.startswith("infrastructure.") for module in imported_modules)
    assert "WallapopPlaywrightClient" not in source
    assert "playwright" not in source.casefold()
    assert "argparse" not in imported_modules
    assert "tomllib" not in imported_modules
    assert "asyncio" not in imported_modules
    assert "asyncio.run" not in source
    assert "async def" not in source
    assert "await " not in source
    assert "dependency_injector" not in source
    assert "injector" not in imported_modules
    assert mutable_globals == []


def test_future_cli_modules_do_not_exist_yet() -> None:
    forbidden_paths = [
        SRC_ROOT / "presentation/cli/main.py",
        SRC_ROOT / "presentation/cli/__main__.py",
        SRC_ROOT / "presentation/cli/terminal_report.py",
        SRC_ROOT / "presentation/cli/json_report.py",
    ]

    assert not any(path.exists() for path in forbidden_paths)


def test_no_console_script_is_registered_yet() -> None:
    pyproject_source = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "[project.scripts]" not in pyproject_source
