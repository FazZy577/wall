"""B03: safe lot composition, copy quantities and total purchase price."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.detected_candidate import DetectedCandidate
from application.use_cases.default_lot_opportunity_scanner import DefaultLotOpportunityScanner
from domain.entities.candidate_classification import CandidateDisposition
from domain.entities.candidate_listing import CandidateListing
from domain.entities.game_valuation import GameValuation
from domain.entities.resale_economics import ResaleAbsoluteCosts, ResaleEconomicPolicy
from domain.entities.sale_terms import PriceBasis, assess_sale_terms
from domain.interfaces.game_detector import ListingText
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    MarketPriceEstimate,
    ReasonCode,
)
from infrastructure.analyzers.default_lot_opportunity_analyzer import DefaultLotOpportunityAnalyzer
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.detectors.default_arbitrage_opportunity_detector import (
    DefaultArbitrageOpportunityDetector,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def detector():
    return FuzzyGameDetector(PackagedGameCatalog())


def listing(title, description="", price="50"):
    return CandidateListing("b03", title, description, Decimal(price), "EUR", "")


def classify(detector, candidate):
    games = detector.detect_games(ListingText(candidate.title, candidate.description))
    return RuleBasedCandidateEligibilityPolicy().classify(candidate, games)


def estimate(game):
    return MarketPriceEstimate(
        Decimal("100"),
        "EUR",
        0.9,
        ConfidenceLevel.HIGH,
        EstimationStrategy.MEDIAN,
        ReasonCode.NORMAL,
        20,
        0,
        0.0,
        Decimal("100"),
        Decimal("100"),
        Decimal("0"),
        Decimal("0"),
        0.0,
        game,
        datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "description",
    [
        "50 € cada uno",
        "50 euros por unidad",
        "Precio a consultar",
        "Desde 50 €",
        "GTA V 50 €, RDR2 60 €",
        "Precio total 100 €",
        "Se venden por separado",
        "Incluye otro juego",
        "Incluye 3 juegos",
        "Varias copias disponibles",
    ],
)
def test_unresolved_terms_block_routing(detector, description):
    result = classify(detector, listing("Lote GTA V + RDR2 PS4", description))
    assert result.disposition is CandidateDisposition.AMBIGUOUS
    assert not result.included_games


def test_two_mentions_without_bundle_evidence_are_not_a_lot(detector):
    assert (
        classify(detector, listing("GTA V y RDR2 PS4")).disposition
        is CandidateDisposition.AMBIGUOUS
    )


@pytest.mark.parametrize(
    "title",
    [
        "Lote GTA V + Aventura desconocida PS4",
        "Lote GTA V y Aventura desconocida PS4",
    ],
)
def test_unidentified_item_does_not_disappear_from_lot(detector, title):
    assert classify(detector, listing(title)).disposition is CandidateDisposition.AMBIGUOUS


def test_wanted_game_does_not_increase_contents(detector):
    result = classify(detector, listing("GTA V PS4", "Busco otro juego: RDR2"))
    assert result.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL
    assert result.total_units == 1


@pytest.mark.parametrize(
    "title",
    [
        "Dos copias de GTA V PS4",
        "2 unidades de GTA V PS4",
    "Lote GTA V x2 PS4",
    "Lote GTA V PS4 x2",
        "Lote 2x GTA V PS4",
    ],
)
def test_two_copies_have_one_identity_and_two_units(detector, title):
    result = classify(detector, listing(title))
    assert result.disposition is CandidateDisposition.ELIGIBLE_LOT
    assert len(result.included_games) == 1
    assert result.quantities == (2,)
    assert result.total_units == 2


def test_repeated_title_is_not_quantity(detector):
    result = classify(detector, listing("GTA V PS4", "GTA V completo"))
    assert result.total_units == 1


def test_conflicting_copy_counts_are_unresolved(detector):
    result = classify(detector, listing("2 copias de GTA V PS4", "3 copias de GTA V"))
    assert result.disposition is CandidateDisposition.AMBIGUOUS


@pytest.mark.parametrize("quantity", ["0", "-2", "2.5", "101"])
def test_invalid_copy_counts_are_not_guessed(detector, quantity):
    result = classify(detector, listing(f"{quantity} copias de GTA V PS4"))
    assert result.disposition is CandidateDisposition.AMBIGUOUS


def test_unknown_included_game_in_description_blocks_buy(detector):
    result = classify(detector, listing("GTA V PS4", "Incluye Aventura desconocida"))
    assert result.disposition is CandidateDisposition.AMBIGUOUS


def test_total_unit_price_is_not_computed_from_unconfirmed_purchase(detector):
    candidate = listing("Dos copias de GTA V PS4", "50 € cada uno")
    games = tuple(detector.detect_games(ListingText(candidate.title, candidate.description)))
    terms = assess_sale_terms(candidate, games)
    assert terms.price_basis is PriceBasis.PER_UNIT
    assert not terms.resolved
    assert candidate.price == Decimal("50")


@pytest.mark.asyncio
async def test_scanner_values_identity_once_and_charges_costs_per_copy(detector):
    candidate = listing("Dos copias de GTA V PS4", "Precio total 50 €")
    game = classify(detector, candidate).included_games[0]
    policy = ResaleEconomicPolicy(
        {"EUR": ResaleAbsoluteCosts(Decimal("0"), Decimal("3"), Decimal("5"))},
        Decimal("0"),
        Decimal("0"),
    )
    scanner = DefaultLotOpportunityScanner(
        detector,
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        DefaultLotOpportunityAnalyzer(policy),
    )
    scanner._value_game = AsyncMock(
        return_value=(GameValuation.from_market_estimate(game, estimate(game)), None)
    )
    result = await scanner.scan_detected_lot(DetectedCandidate(candidate, (game,), (2,)))
    scanner._value_game.assert_awaited_once()
    assert result.total_detected_games == 1
    assert result.game_valuations[0].quantity == 2
    assert result.opportunity.total_units == 2
    assert result.opportunity.reference_market_value == Decimal("200")
    assert result.opportunity.economic_breakdown.fixed_selling_costs == Decimal("6")
    assert result.opportunity.net_profit == Decimal("139")


@pytest.mark.asyncio
async def test_direct_scanner_cannot_bypass_unit_price_guard(detector):
    collector = AsyncMock()
    scanner = DefaultLotOpportunityScanner(
        detector, collector, Mock(), Mock(), Mock(), Mock(), Mock()
    )
    result = await scanner.scan_lot(listing("Lote GTA V + RDR2 PS4", "50 € cada uno"))
    assert result.opportunity is None
    assert result.analysis_failure is not None
    collector.collect_comparables.assert_not_called()


def test_analyzers_cannot_issue_buy_for_unit_price(detector):
    candidate = listing("Dos copias de GTA V PS4", "50 € cada uno")
    game = detector.detect_games(ListingText(candidate.title, candidate.description))[0]
    valuation = replace(GameValuation.from_market_estimate(game, estimate(game)), quantity=2)
    policy = ResaleEconomicPolicy.neutral()
    with pytest.raises(ValueError, match="total purchase price"):
        DefaultLotOpportunityAnalyzer(policy).analyze(candidate, [valuation], 1)
    with pytest.raises(ValueError, match="total purchase price"):
        DefaultArbitrageOpportunityDetector(policy).detect(candidate, estimate(game))
