"""Dependency-direction guards for application scanner use cases."""

import ast
import importlib
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from application.interfaces.lot_opportunity_scanner import ILotOpportunityScanner
from application.interfaces.opportunity_scanner import IOpportunityScanner
from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.resale_economics import EconomicBreakdown, ResaleEconomicPolicy
from domain.interfaces.arbitrage_opportunity_detector import IArbitrageOpportunityDetector
from domain.interfaces.game_detector import IGameDetector
from domain.interfaces.lot_opportunity_analyzer import ILotOpportunityAnalyzer
from domain.interfaces.market_price_estimator import IMarketPriceEstimator
from domain.interfaces.outlier_removal import IOutlierRemoval
from domain.interfaces.price_collector import IPriceCollector
from domain.interfaces.price_dataset_builder import IPriceDatasetBuilder
from domain.interfaces.price_statistics import IPriceStatistics
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)

SRC_ROOT = Path(__file__).parents[2] / "src"


def test_economic_policy_is_canonical_and_required_by_economic_components() -> None:
    detector_parameter = inspect.signature(
        DefaultArbitrageOpportunityDetector
    ).parameters["economic_policy"]
    analyzer_parameter = inspect.signature(DefaultLotOpportunityAnalyzer).parameters[
        "economic_policy"
    ]

    assert ResaleEconomicPolicy.__module__ == "domain.entities.resale_economics"
    assert EconomicBreakdown.__module__ == "domain.entities.resale_economics"
    assert detector_parameter.default is inspect.Parameter.empty
    assert analyzer_parameter.default is inspect.Parameter.empty

    application_calls: list[Path] = []
    for source_file in (SRC_ROOT / "application").rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ResaleEconomicPolicy"
            for node in ast.walk(tree)
        ):
            application_calls.append(source_file)
    assert application_calls == []


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


def test_application_does_not_import_infrastructure() -> None:
    forbidden = [
        (path, module)
        for path, module in _imports_beneath(SRC_ROOT / "application")
        if module == "infrastructure"
        or module.startswith("infrastructure.")
        or module == "src.infrastructure"
        or module.startswith("src.infrastructure.")
    ]

    assert forbidden == []


def test_domain_does_not_import_application_or_infrastructure() -> None:
    forbidden_roots = ("application", "infrastructure", "src.application", "src.infrastructure")
    forbidden = [
        (path, module)
        for path, module in _imports_beneath(SRC_ROOT / "domain")
        if any(module == root or module.startswith(f"{root}.") for root in forbidden_roots)
    ]

    assert forbidden == []


def test_scanner_symbols_have_single_application_definition() -> None:
    expected = {
        "DefaultOpportunityScanner": Path(
            "application/use_cases/default_opportunity_scanner.py"
        ),
        "DefaultLotOpportunityScanner": Path(
            "application/use_cases/default_lot_opportunity_scanner.py"
        ),
        "IOpportunityScanner": Path("application/interfaces/opportunity_scanner.py"),
        "ILotOpportunityScanner": Path(
            "application/interfaces/lot_opportunity_scanner.py"
        ),
        "ScanResult": Path("application/interfaces/opportunity_scanner.py"),
        "FailureInfo": Path("application/interfaces/opportunity_scanner.py"),
        "PipelineStage": Path("application/interfaces/opportunity_scanner.py"),
        "LotScanResult": Path("application/interfaces/lot_opportunity_scanner.py"),
        "GameValuationFailure": Path(
            "application/interfaces/lot_opportunity_scanner.py"
        ),
        "LotPipelineStage": Path(
            "application/interfaces/lot_opportunity_scanner.py"
        ),
    }
    definitions: dict[str, list[Path]] = {name: [] for name in expected}

    for source_file in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(source_file.relative_to(SRC_ROOT))

    assert definitions == {name: [path] for name, path in expected.items()}


def test_scanner_modules_are_canonical_application_modules() -> None:
    assert DefaultOpportunityScanner.__module__ == (
        "application.use_cases.default_opportunity_scanner"
    )
    assert DefaultLotOpportunityScanner.__module__ == (
        "application.use_cases.default_lot_opportunity_scanner"
    )
    assert IOpportunityScanner.__module__ == "application.interfaces.opportunity_scanner"
    assert ILotOpportunityScanner.__module__ == (
        "application.interfaces.lot_opportunity_scanner"
    )


def test_old_scanner_modules_were_removed() -> None:
    old_paths = [
        SRC_ROOT / "domain/interfaces/opportunity_scanner.py",
        SRC_ROOT / "domain/interfaces/lot_opportunity_scanner.py",
        SRC_ROOT / "infrastructure/scanners/default_opportunity_scanner.py",
        SRC_ROOT / "infrastructure/scanners/default_lot_opportunity_scanner.py",
    ]

    assert not any(path.exists() for path in old_paths)


def test_canonical_modules_import_without_cycles() -> None:
    modules = [
        "application.interfaces.opportunity_scanner",
        "application.interfaces.lot_opportunity_scanner",
        "application.use_cases.default_opportunity_scanner",
        "application.use_cases.default_lot_opportunity_scanner",
        "domain.entities.candidate_listing",
        "domain.entities.comparable_listing",
        "infrastructure.collectors.wallapop_price_collector",
        "infrastructure.detectors.fuzzy_game_detector",
    ]

    assert all(importlib.import_module(module) for module in modules)


def test_scanner_and_collector_contracts_are_async_end_to_end() -> None:
    assert inspect.iscoroutinefunction(IPriceCollector.collect_comparables)
    assert inspect.iscoroutinefunction(IOpportunityScanner.scan_listing)
    assert inspect.iscoroutinefunction(IOpportunityScanner.scan_multiple)
    assert inspect.iscoroutinefunction(DefaultOpportunityScanner.scan_listing)
    assert inspect.iscoroutinefunction(DefaultOpportunityScanner.scan_multiple)
    assert inspect.iscoroutinefunction(ILotOpportunityScanner.scan_lot)
    assert inspect.iscoroutinefunction(DefaultLotOpportunityScanner.scan_lot)
    assert isinstance(AsyncMock(spec=IPriceCollector).collect_comparables, AsyncMock)

    synchronous_methods = [
        IGameDetector.detect_games,
        IPriceDatasetBuilder.build,
        IPriceStatistics.calculate,
        IOutlierRemoval.remove_outliers,
        IMarketPriceEstimator.estimate,
        IArbitrageOpportunityDetector.detect,
        ILotOpportunityAnalyzer.analyze,
    ]
    assert all(not inspect.iscoroutinefunction(method) for method in synchronous_methods)
    assert all(
        isinstance(getattr(Mock(spec=owner), method.__name__), Mock)
        for owner, method in [
            (IGameDetector, IGameDetector.detect_games),
            (IPriceDatasetBuilder, IPriceDatasetBuilder.build),
            (IPriceStatistics, IPriceStatistics.calculate),
            (IOutlierRemoval, IOutlierRemoval.remove_outliers),
            (IMarketPriceEstimator, IMarketPriceEstimator.estimate),
            (IArbitrageOpportunityDetector, IArbitrageOpportunityDetector.detect),
            (ILotOpportunityAnalyzer, ILotOpportunityAnalyzer.analyze),
        ]
    )


def test_application_has_no_manual_event_loop_bridge() -> None:
    forbidden = {
        "asyncio.run",
        "asyncio.Runner",
        "new_event_loop",
        "get_event_loop",
        "get_running_loop",
        "set_event_loop",
        "run_until_complete",
        "run_coroutine_threadsafe",
        "Thread",
        "ThreadPoolExecutor",
        "Awaitable",
        "iscoroutine",
        "isawaitable",
        "nest_asyncio",
        "_run_async",
        "run_sync",
        "scan_sync",
        "asyncio.gather",
        "create_task",
        "TaskGroup",
        "as_completed",
    }
    occurrences: list[tuple[Path, str]] = []

    for source_file in (SRC_ROOT / "application").rglob("*.py"):
        source = source_file.read_text(encoding="utf-8")
        occurrences.extend(
            (source_file.relative_to(SRC_ROOT), token)
            for token in forbidden
            if token in source
        )

    assert occurrences == []
