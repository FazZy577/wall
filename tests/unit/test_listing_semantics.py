"""Nominal, typed, and canonical boundaries for listing/game models."""

import ast
from decimal import Decimal
from pathlib import Path
from typing import get_type_hints
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.lot_opportunity_scanner import ILotOpportunityScanner
from application.interfaces.opportunity_scanner import IOpportunityScanner
from application.use_cases.default_opportunity_scanner import DefaultOpportunityScanner
from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.entities.detected_game import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from domain.entities.game_valuation import GameValuation
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    IArbitrageOpportunityDetector,
)
from domain.interfaces.comparable_filter import ComparableFilterInput, IComparableFilter
from domain.interfaces.game_detector import DetectedGame as PortDetectedGame
from domain.interfaces.game_detector import DetectionMethod as PortDetectionMethod
from domain.interfaces.game_detector import IGameDetector, ListingText
from domain.interfaces.game_detector import Platform as PortPlatform
from domain.interfaces.price_collector import (
    ComparableListing as PortComparableListing,
)
from domain.interfaces.price_collector import IPriceCollector
from domain.interfaces.price_dataset_builder import InvalidComparableListingError
from infrastructure.dataset_builders.default_price_dataset_builder import (
    DefaultPriceDatasetBuilder,
)
from infrastructure.rankers.default_opportunity_ranker import DefaultOpportunityRanker


def _game(platform: Platform = Platform.PS4) -> DetectedGame:
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="GTA V",
        platform=platform,
        confidence=1.0,
        detection_method=DetectionMethod.ALIAS_MATCH,
    )


def _candidate(identifier: str = "candidate") -> CandidateListing:
    return CandidateListing(
        listing_id=identifier,
        title="Lote PS3 PS4 PS5",
        description="GTA V y otros juegos",
        price=Decimal("30.0"),
        currency="EUR",
        url=f"https://example.test/{identifier}",
        raw_listing={"candidate": identifier},
    )


@pytest.mark.asyncio

async def test_candidate_and_comparable_are_nominally_unrelated() -> None:
    candidate = _candidate()
    comparable = ComparableListing(
        listing_id="comparable",
        title="GTA V PS4",
        description="",
        price=Decimal("15.0"),
        currency="EUR",
        detected_game=_game(),
        url="https://example.test/comparable",
    )

    assert type(candidate) is CandidateListing
    assert type(comparable) is ComparableListing
    assert not isinstance(candidate, ComparableListing)
    assert not isinstance(comparable, CandidateListing)
    assert not issubclass(CandidateListing, ComparableListing)
    assert not issubclass(ComparableListing, CandidateListing)


@pytest.mark.asyncio

async def test_legacy_comparable_import_reexports_canonical_class() -> None:
    assert PortComparableListing is ComparableListing


@pytest.mark.asyncio

async def test_detector_port_reexports_canonical_detection_models() -> None:
    assert PortDetectedGame is DetectedGame
    assert PortPlatform is Platform
    assert PortDetectionMethod is DetectionMethod


@pytest.mark.asyncio

async def test_comparable_filter_input_is_a_distinct_explicit_payload() -> None:
    filter_hints = get_type_hints(IComparableFilter.is_valid_comparable)

    assert filter_hints["listing"] is ComparableFilterInput
    assert ComparableFilterInput is not CandidateListing
    assert ComparableFilterInput is not ComparableListing
    assert not issubclass(ComparableFilterInput, CandidateListing)
    assert not issubclass(ComparableFilterInput, ComparableListing)


@pytest.mark.asyncio

async def test_candidate_has_no_single_platform_requirement() -> None:
    candidate = _candidate()
    detected_games = [_game(Platform.PS4), _game(Platform.PS5)]

    assert not hasattr(candidate, "platform")
    assert [game.platform for game in detected_games] == [Platform.PS4, Platform.PS5]


@pytest.mark.asyncio

async def test_dataset_builder_rejects_candidate_as_market_observation() -> None:
    with pytest.raises(
        InvalidComparableListingError,
        match="CandidateListing cannot be used as a market comparable",
    ):
        DefaultPriceDatasetBuilder().build([_candidate()], "EUR")


@pytest.mark.asyncio

async def test_candidate_is_rejected_even_when_mixed_with_valid_comparables() -> None:
    comparable = ComparableListing(
        listing_id="comparable",
        title="GTA V PS4",
        description="",
        price=Decimal("15.0"),
        currency="EUR",
        detected_game=_game(),
        url="https://example.test/comparable",
    )

    with pytest.raises(InvalidComparableListingError):
        DefaultPriceDatasetBuilder().build([comparable, _candidate()], "EUR")


@pytest.mark.asyncio

async def test_public_type_hints_enforce_listing_boundaries() -> None:
    scanner_single = get_type_hints(IOpportunityScanner.scan_listing)
    scanner_multiple = get_type_hints(IOpportunityScanner.scan_multiple)
    detector = get_type_hints(IArbitrageOpportunityDetector.detect)
    opportunity = get_type_hints(ArbitrageOpportunity)
    collector = get_type_hints(IPriceCollector.collect_comparables)

    assert scanner_single["listing"] is CandidateListing
    assert scanner_multiple["listings"] == list[CandidateListing]
    assert detector["listing"] is CandidateListing
    assert opportunity["listing"] is CandidateListing
    assert collector["return"] == list[ComparableListing]


@pytest.mark.asyncio

async def test_detection_and_lot_contracts_share_canonical_game_types() -> None:
    candidate_hints = get_type_hints(CandidateListing)
    detector_hints = get_type_hints(IGameDetector.detect_games)
    lot_hints = get_type_hints(ILotOpportunityScanner.scan_lot)
    valuation_hints = get_type_hints(GameValuation)

    assert "detected_games" not in candidate_hints
    assert detector_hints["listing_text"] is ListingText
    assert detector_hints["return"] == list[DetectedGame]
    assert lot_hints["listing"] is CandidateListing
    assert valuation_hints["game"] is DetectedGame
    assert GameValuation is not DetectedGame
    assert ListingText is not CandidateListing
    assert _game().platform is Platform.PS4


@pytest.mark.asyncio

async def test_canonical_domain_symbols_have_single_class_definition() -> None:
    source_root = Path(__file__).parents[2] / "src"
    canonical_symbols = {
        "CandidateListing",
        "ComparableListing",
        "DetectedGame",
        "ListingText",
        "GameValuation",
        "GameIdentity",
        "Platform",
        "DetectionMethod",
        "ResaleEconomicPolicy",
        "EconomicBreakdown",
    }
    definitions: dict[str, list[Path]] = {name: [] for name in canonical_symbols}

    for source_file in source_root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(source_file.relative_to(source_root))

    assert definitions == {
        "CandidateListing": [Path("domain/entities/candidate_listing.py")],
        "ComparableListing": [Path("domain/entities/comparable_listing.py")],
        "DetectedGame": [Path("domain/entities/detected_game.py")],
        "ListingText": [Path("domain/interfaces/game_detector.py")],
        "GameValuation": [Path("domain/entities/game_valuation.py")],
        "GameIdentity": [Path("domain/entities/game_identity.py")],
        "Platform": [Path("domain/entities/detected_game.py")],
        "DetectionMethod": [Path("domain/entities/detected_game.py")],
        "ResaleEconomicPolicy": [Path("domain/entities/resale_economics.py")],
        "EconomicBreakdown": [Path("domain/entities/resale_economics.py")],
    }


@pytest.mark.asyncio

async def test_no_generic_listing_class_exists_in_source() -> None:
    source_root = Path(__file__).parents[2] / "src"
    definitions: list[Path] = []

    for source_file in source_root.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.ClassDef) and node.name == "Listing"
            for node in ast.walk(tree)
        ):
            definitions.append(source_file.relative_to(source_root))

    assert definitions == []


@pytest.mark.asyncio

async def test_scanner_detects_games_from_candidate_text_without_candidate_platform() -> None:
    game_detector = Mock()
    game_detector.detect_games.return_value = [_game()]
    scanner = DefaultOpportunityScanner(
        game_detector=game_detector,
        price_collector=Mock(),
        dataset_builder=Mock(),
        statistics=Mock(),
        outlier_removal=Mock(),
        market_estimator=Mock(),
        arbitrage_detector=Mock(),
        opportunity_ranker=DefaultOpportunityRanker(),
    )
    scanner.price_collector.collect_comparables = AsyncMock(return_value=[])
    scanner.dataset_builder.build.return_value = Mock(sample_size=0)
    candidate = _candidate()

    await scanner.scan_listing(candidate)

    text = game_detector.detect_games.call_args.args[0]
    assert text.title == candidate.title
    assert text.description == candidate.description
    assert not hasattr(candidate, "platform")


def test_candidate_listing_never_accepts_or_reads_detected_games() -> None:
    repository_root = Path(__file__).parents[2]
    violations: list[str] = []
    for folder in ("src", "tests", "examples"):
        for source_file in (repository_root / folder).rglob("*.py"):
            tree = ast.parse(source_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    function_name = getattr(node.func, "id", None)
                    if function_name == "CandidateListing" and any(
                        keyword.arg == "detected_games" for keyword in node.keywords
                    ):
                        violations.append(str(source_file.relative_to(repository_root)))
                if (
                    folder == "src"
                    and isinstance(node, ast.Attribute)
                    and node.attr == "detected_games"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "listing"
                ):
                    violations.append(str(source_file.relative_to(repository_root)))

    assert violations == []
