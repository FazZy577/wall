"""Dependency-direction guards for application scanner use cases."""

import ast
import importlib
import inspect
from pathlib import Path
from typing import get_args, get_type_hints
from unittest.mock import AsyncMock, Mock

from application.interfaces.candidate_search import ICandidateSearch
from application.interfaces.detected_candidate import DetectedCandidate
from application.interfaces.lot_opportunity_scanner import ILotOpportunityScanner
from application.interfaces.opportunity_scanner import IOpportunityScanner, RankingResult
from application.interfaces.search_orchestrator import (
    CandidateItemFailureRecord,
    CandidateRoutingFailure,
    CandidateRoutingFailureKind,
    ISearchOrchestrator,
    SearchOrchestrationResult,
    SearchPlan,
    SearchQueryFailure,
)
from application.use_cases.default_lot_opportunity_scanner import (
    DefaultLotOpportunityScanner,
)
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from application.use_cases.default_search_orchestrator import (
    DefaultSearchOrchestrator,
)
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.entities.resale_economics import EconomicBreakdown, ResaleEconomicPolicy
from domain.interfaces.arbitrage_opportunity_detector import IArbitrageOpportunityDetector
from domain.interfaces.game_catalog import IGameCatalog
from domain.interfaces.game_detector import IGameDetector
from domain.interfaces.lot_opportunity_analyzer import ILotOpportunityAnalyzer
from domain.interfaces.market_price_estimator import IMarketPriceEstimator
from domain.interfaces.opportunity_ranker import IOpportunityRanker, RankingStrategy
from domain.interfaces.outlier_removal import IOutlierRemoval
from domain.interfaces.price_collector import IPriceCollector
from domain.interfaces.price_dataset_builder import IPriceDatasetBuilder
from domain.interfaces.price_statistics import IPriceStatistics
from infrastructure.analyzers.default_lot_opportunity_analyzer import (
    DefaultLotOpportunityAnalyzer,
)
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)
from infrastructure.marketplaces.wallapop.adapter import (
    WallapopCandidateSearchAdapter,
)

SRC_ROOT = Path(__file__).parents[2] / "src"


def test_comparable_deduplication_has_one_infrastructure_boundary() -> None:
    """Comparable identity policy belongs only to the dataset builder."""
    builder_path = (
        SRC_ROOT / "infrastructure" / "dataset_builders" / "default_price_dataset_builder.py"
    )
    builder_source = builder_path.read_text(encoding="utf-8")

    assert "seen_identities" in builder_source
    assert "listing.detected_game.platform" in builder_source
    assert "listing.listing_id" in builder_source

    other_policy_locations = []
    policy_free_roots = (
        SRC_ROOT / "application",
        SRC_ROOT / "infrastructure" / "statistics",
        SRC_ROOT / "infrastructure" / "estimators",
        SRC_ROOT / "infrastructure" / "outliers",
    )
    for root in policy_free_roots:
        if not root.exists():
            continue
        for source_file in root.rglob("*.py"):
            if "seen_identities" in source_file.read_text(encoding="utf-8"):
                other_policy_locations.append(source_file)
    assert other_policy_locations == []


def test_listing_id_validation_stays_in_domain_and_external_normalization_at_edge() -> None:
    candidate_source = (
        SRC_ROOT / "domain/entities/candidate_listing.py"
    ).read_text(encoding="utf-8")
    comparable_source = (
        SRC_ROOT / "domain/entities/comparable_listing.py"
    ).read_text(encoding="utf-8")
    observation_source = (
        SRC_ROOT / "domain/interfaces/price_dataset_builder.py"
    ).read_text(encoding="utf-8")
    validator_source = (SRC_ROOT / "domain/listing_id.py").read_text(encoding="utf-8")
    builder_source = (
        SRC_ROOT
        / "infrastructure/dataset_builders/default_price_dataset_builder.py"
    ).read_text(encoding="utf-8")
    application_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SRC_ROOT / "application").rglob("*.py")
    )

    assert "validate_listing_id(self.listing_id)" in candidate_source
    assert "validate_listing_id(self.listing_id)" in comparable_source
    assert "validate_listing_id(self.listing_id)" in observation_source
    assert ".strip()" not in builder_source
    assert "listing_id.strip" not in application_source
    assert "casefold" not in validator_source
    assert "lstrip" not in validator_source
    assert not any(
        isinstance(node, ast.ClassDef) and node.name == "ListingId"
        for path in (SRC_ROOT / "domain").rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
    )


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


def test_candidate_search_contract_and_wallapop_adapter_respect_layers() -> None:
    contract_path = SRC_ROOT / "application/interfaces/candidate_search.py"
    contract_source = contract_path.read_text(encoding="utf-8")

    assert ICandidateSearch.__module__ == "application.interfaces.candidate_search"
    assert WallapopCandidateSearchAdapter.__module__ == (
        "infrastructure.marketplaces.wallapop.adapter"
    )
    assert "infrastructure" not in contract_source
    assert "wallapop" not in contract_source.casefold()


def test_search_orchestrator_contract_and_implementation_stay_in_application() -> None:
    contract_path = SRC_ROOT / "application/interfaces/search_orchestrator.py"
    contract_source = contract_path.read_text(encoding="utf-8")
    implementation_path = (
        SRC_ROOT / "application/use_cases/default_search_orchestrator.py"
    )
    implementation_source = implementation_path.read_text(encoding="utf-8")

    assert ISearchOrchestrator.__module__ == (
        "application.interfaces.search_orchestrator"
    )
    assert SearchPlan.__module__ == "application.interfaces.search_orchestrator"
    assert SearchOrchestrationResult.__module__ == (
        "application.interfaces.search_orchestrator"
    )
    assert "infrastructure" not in contract_source
    assert "wallapop" not in contract_source.casefold()
    assert DefaultSearchOrchestrator.__module__ == (
        "application.use_cases.default_search_orchestrator"
    )
    assert issubclass(DefaultSearchOrchestrator, ISearchOrchestrator)
    assert "infrastructure" not in implementation_source
    assert "wallapop" not in implementation_source.casefold()
    assert "playwright" not in implementation_source.casefold()
    assert "asyncio.run" not in implementation_source
    assert "ranker" not in implementation_source.casefold()


def test_search_orchestrator_injects_only_application_and_domain_ports() -> None:
    parameters = inspect.signature(DefaultSearchOrchestrator).parameters
    hints = get_type_hints(DefaultSearchOrchestrator.__init__)

    assert list(parameters) == [
        "candidate_search",
        "game_detector",
        "opportunity_scanner",
        "lot_opportunity_scanner",
    ]
    assert hints["candidate_search"] is ICandidateSearch
    assert hints["game_detector"] is IGameDetector
    assert hints["opportunity_scanner"] is IOpportunityScanner
    assert hints["lot_opportunity_scanner"] is ILotOpportunityScanner
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in parameters.values()
    )


def test_default_search_orchestrator_has_one_application_definition() -> None:
    definitions = [
        source_file.relative_to(SRC_ROOT)
        for source_file in SRC_ROOT.rglob("*.py")
        for node in ast.walk(
            ast.parse(source_file.read_text(encoding="utf-8"))
        )
        if isinstance(node, ast.ClassDef)
        and node.name == "DefaultSearchOrchestrator"
    ]

    assert definitions == [
        Path("application/use_cases/default_search_orchestrator.py")
    ]


def test_search_orchestrator_contract_symbols_have_one_definition_and_reuse_existing_models() -> None:
    expected = {
        "SearchPlan",
        "SearchQueryFailure",
        "CandidateItemFailureRecord",
        "CandidateRoutingFailure",
        "CandidateRoutingFailureKind",
        "SearchOrchestrationResult",
        "ISearchOrchestrator",
    }
    definitions: dict[str, list[Path]] = {name: [] for name in expected}

    for source_file in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(source_file.relative_to(SRC_ROOT))

    canonical = Path("application/interfaces/search_orchestrator.py")
    assert definitions == {name: [canonical] for name in expected}
    assert CandidateItemFailureRecord.__module__ == (
        "application.interfaces.search_orchestrator"
    )
    assert CandidateRoutingFailure.__module__ == (
        "application.interfaces.search_orchestrator"
    )
    assert CandidateRoutingFailureKind.__module__ == (
        "application.interfaces.search_orchestrator"
    )
    assert SearchQueryFailure.__module__ == (
        "application.interfaces.search_orchestrator"
    )


def test_domain_does_not_import_application_or_infrastructure() -> None:
    forbidden_roots = ("application", "infrastructure", "src.application", "src.infrastructure")
    forbidden = [
        (path, module)
        for path, module in _imports_beneath(SRC_ROOT / "domain")
        if any(module == root or module.startswith(f"{root}.") for root in forbidden_roots)
    ]

    assert forbidden == []


def test_game_catalog_boundary_respects_layers_without_generator_or_detector_migration() -> None:
    entry_path = SRC_ROOT / "domain/entities/game_catalog_entry.py"
    port_path = SRC_ROOT / "domain/interfaces/game_catalog.py"
    domain_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (entry_path, port_path)
    )
    application_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SRC_ROOT / "application").rglob("*.py")
    )
    detector_source = (
        SRC_ROOT / "infrastructure/detectors/fuzzy_game_detector.py"
    ).read_text(encoding="utf-8")

    assert GameCatalogEntry.__module__ == "domain.entities.game_catalog_entry"
    assert IGameCatalog.__module__ == "domain.interfaces.game_catalog"
    assert PackagedGameCatalog.__module__ == (
        "infrastructure.catalogs.packaged_game_catalog"
    )
    assert issubclass(PackagedGameCatalog, IGameCatalog)
    assert "infrastructure" not in domain_source
    assert "import json" not in domain_source
    assert "importlib.resources" not in domain_source
    assert "IGameCatalog" not in application_source
    assert "SearchPlanGenerator" not in application_source
    assert "PackagedGameCatalog" not in detector_source
    assert "IGameCatalog" not in detector_source


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
        "DetectedCandidate": Path("application/interfaces/detected_candidate.py"),
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
    assert DetectedCandidate.__module__ == "application.interfaces.detected_candidate"


def test_scanner_interfaces_share_one_detected_candidate_contract() -> None:
    single_hints = get_type_hints(IOpportunityScanner.scan_detected_listing)
    batch_hints = get_type_hints(IOpportunityScanner.scan_detected_multiple)
    lot_hints = get_type_hints(ILotOpportunityScanner.scan_detected_lot)

    assert single_hints["candidate"] is DetectedCandidate
    assert get_args(batch_hints["candidates"]) == (DetectedCandidate,)
    assert lot_hints["candidate"] is DetectedCandidate


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
        "application.interfaces.detected_candidate",
        "application.interfaces.search_orchestrator",
        "application.interfaces.opportunity_scanner",
        "application.interfaces.lot_opportunity_scanner",
        "application.use_cases.default_opportunity_scanner",
        "application.use_cases.default_lot_opportunity_scanner",
        "application.use_cases.default_search_orchestrator",
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
    assert inspect.iscoroutinefunction(IOpportunityScanner.scan_detected_listing)
    assert inspect.iscoroutinefunction(IOpportunityScanner.scan_detected_multiple)
    assert inspect.iscoroutinefunction(DefaultOpportunityScanner.scan_listing)
    assert inspect.iscoroutinefunction(DefaultOpportunityScanner.scan_multiple)
    assert inspect.iscoroutinefunction(DefaultOpportunityScanner.scan_detected_listing)
    assert inspect.iscoroutinefunction(DefaultOpportunityScanner.scan_detected_multiple)
    assert inspect.iscoroutinefunction(ILotOpportunityScanner.scan_lot)
    assert inspect.iscoroutinefunction(ILotOpportunityScanner.scan_detected_lot)
    assert inspect.iscoroutinefunction(DefaultLotOpportunityScanner.scan_lot)
    assert inspect.iscoroutinefunction(DefaultLotOpportunityScanner.scan_detected_lot)
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


def test_ranking_contract_has_one_canonical_definition_and_strategy() -> None:
    symbols = {"RankingStrategy", "IOpportunityRanker"}
    definitions: dict[str, list[Path]] = {symbol: [] for symbol in symbols}
    for source_file in SRC_ROOT.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(source_file.relative_to(SRC_ROOT))

    expected = [Path("domain/interfaces/opportunity_ranker.py")]
    assert definitions == dict.fromkeys(symbols, expected)
    assert list(RankingStrategy) == [RankingStrategy.OPPORTUNITY_SCORE]


def test_scanner_requires_ranker_port_and_application_does_not_sort() -> None:
    parameter = inspect.signature(DefaultOpportunityScanner).parameters[
        "opportunity_ranker"
    ]
    assert parameter.annotation is IOpportunityRanker
    assert parameter.default is inspect.Parameter.empty

    interface_tree = ast.parse(
        (SRC_ROOT / "application/interfaces/opportunity_scanner.py").read_text(
            encoding="utf-8"
        )
    )
    ranking_result = next(
        node
        for node in interface_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RankingResult"
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sorted"
        for node in ast.walk(ranking_result)
    )
    assert not hasattr(RankingResult, "from_opportunities")
    ranking_result_source = ast.unparse(ranking_result)
    assert ".sort(" not in ranking_result_source
    assert "_RECOMMENDATION_PRIORITY" not in ranking_result_source
    assert "fallback" not in ranking_result_source.casefold()


def test_default_ranker_owns_the_only_productive_opportunity_ordering() -> None:
    mapping_files: list[Path] = []
    opportunity_sort_files: list[Path] = []
    for source_file in SRC_ROOT.rglob("*.py"):
        source = source_file.read_text(encoding="utf-8")
        relative = source_file.relative_to(SRC_ROOT)
        if "_RECOMMENDATION_PRIORITY" in source:
            mapping_files.append(relative)
        if "sorted(" in source and "-opportunity.opportunity_score" in source:
            opportunity_sort_files.append(relative)

    ranker_path = Path("infrastructure/rankers/default_opportunity_ranker.py")
    assert mapping_files == [ranker_path]
    assert opportunity_sort_files == [ranker_path]
    assert "DefaultOpportunityRanker" not in (
        SRC_ROOT / "application/use_cases/default_opportunity_scanner.py"
    ).read_text(encoding="utf-8")
