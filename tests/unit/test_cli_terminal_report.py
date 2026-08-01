"""Tests for the deterministic and pure terminal renderer."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

import pytest

from application.interfaces.candidate_search import (
    CandidateItemFailure,
    CandidateItemFailureKind,
    SearchQuery,
)
from application.interfaces.lot_opportunity_scanner import (
    GameValuationFailure,
    LotPipelineStage,
    LotScanResult,
)
from application.interfaces.opportunity_scanner import (
    FailureInfo,
    PipelineStage,
    ScanResult,
)
from application.interfaces.search_orchestrator import (
    CandidateItemFailureRecord,
    CandidateRoutingFailure,
    CandidateRoutingFailureKind,
    SearchOrchestrationResult,
    SearchPlan,
    SearchQueryFailure,
)
from application.interfaces.search_plan_generator import SearchPlanGenerationResult
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.game_valuation import GameValuation
from domain.entities.lot_opportunity import LotOpportunity, LotReasonCode
from domain.entities.resale_economics import EconomicBreakdown
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    ReasonCode,
    Recommendation,
)
from domain.interfaces.market_price_estimator import (
    ConfidenceLevel,
    EstimationStrategy,
    MarketPriceEstimate,
)
from domain.interfaces.market_price_estimator import (
    ReasonCode as EstimateReasonCode,
)
from presentation.cli.terminal_report import render_terminal_report

_NOW = datetime(2025, 1, 1, tzinfo=UTC)


class _ReportData(NamedTuple):
    generation: SearchPlanGenerationResult
    execution: SearchOrchestrationResult
    opportunity: ArbitrageOpportunity
    lot_opportunity: LotOpportunity


def _game(name: str = "Grand Theft Auto V") -> DetectedGame:
    return DetectedGame(
        canonical_name=name,
        matched_text="GTA V",
        platform=Platform.PS4,
        confidence=0.98,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


def _listing(
    listing_id: str,
    title: str,
    price: str,
    *,
    url: str = "https://example.test/listing-1?tracking=secret-token",
) -> CandidateListing:
    return CandidateListing(
        listing_id=listing_id,
        title=title,
        description="not rendered",
        price=Decimal(price),
        currency="EUR",
        url=url,
        raw_listing={
            "authorization": "Bearer secret-token",
            "tracking_id": "raw-secret",
        },
    )


def _breakdown(
    *,
    reference: str,
    acquisition: str,
    item_count: int,
    net_profit: str,
) -> EconomicBreakdown:
    return EconomicBreakdown(
        reference_market_value=Decimal(reference),
        expected_item_sale_prices=tuple(
            Decimal("13.50") for _ in range(item_count)
        ),
        expected_sale_revenue=Decimal("13.50") * item_count,
        quick_sale_discount_total=Decimal("1.50") * item_count,
        selling_fees=Decimal("1.35") * item_count,
        fixed_selling_costs=Decimal("0.75") * item_count,
        safety_buffer=Decimal("0.675") * item_count,
        acquisition_price=Decimal(acquisition),
        acquisition_overhead=Decimal("2.00"),
        total_acquisition_cost=Decimal(acquisition) + Decimal("2.00"),
        net_expected_proceeds=Decimal("10.725") * item_count,
        net_profit=Decimal(net_profit),
        break_even_sale_revenue=Decimal("11.20"),
        item_count=item_count,
        currency="EUR",
    )


def _estimate(game: DetectedGame, price: str = "15.00") -> MarketPriceEstimate:
    return MarketPriceEstimate(
        estimated_price=Decimal(price),
        currency="EUR",
        confidence_score=0.72,
        confidence_level=ConfidenceLevel.MEDIUM,
        strategy=EstimationStrategy.MEDIAN,
        reason_code=EstimateReasonCode.NORMAL,
        sample_size=12,
        observations_removed=2,
        outlier_percentage=14.2857,
        minimum_price=Decimal("10.00"),
        maximum_price=Decimal("20.00"),
        standard_deviation=Decimal("2.00"),
        iqr=Decimal("3.00"),
        coefficient_of_variation=0.13,
        game=game,
        created_at=_NOW,
    )


def _opportunity(
    listing: CandidateListing,
    game: DetectedGame,
    *,
    recommendation: Recommendation = Recommendation.BUY,
) -> ArbitrageOpportunity:
    return ArbitrageOpportunity(
        listing=listing,
        game=game,
        market_price=Decimal("15.00"),
        listing_price=listing.price,
        confidence_score=0.72,
        confidence_level=ConfidenceLevel.MEDIUM,
        opportunity_score=78.4,
        recommendation=recommendation,
        reason=(
            ReasonCode.UNDERVALUED
            if recommendation is Recommendation.BUY
            else ReasonCode.FAIR_PRICE
        ),
        created_at=_NOW,
        economic_breakdown=_breakdown(
            reference="15.00",
            acquisition=str(listing.price),
            item_count=1,
            net_profit="0.725",
        ),
    )


def _valuation(game: DetectedGame, price: str = "15.00") -> GameValuation:
    estimate = _estimate(game, price)
    return GameValuation(
        game=game,
        market_price_estimate=estimate,
        estimated_market_value=estimate.estimated_price,
        confidence_score=estimate.confidence_score,
        observations_used=estimate.sample_size,
        observations_removed=estimate.observations_removed,
        created_at=_NOW,
    )


def _lot_opportunity(listing: CandidateListing, valuations: list[GameValuation]) -> LotOpportunity:
    breakdown = _breakdown(
        reference="30.00",
        acquisition=str(listing.price),
        item_count=2,
        net_profit="4.50",
    )
    return LotOpportunity.from_valuations(
        listing=listing,
        game_valuations=valuations,
        recommendation=Recommendation.MAYBE,
        reason=LotReasonCode.FAIR_VALUE_LOT,
        opportunity_score=61.2,
        economic_breakdown=breakdown,
    )


def _report_data() -> _ReportData:
    game = _game()
    candidate = _listing("candidate-1", "GTA V PS4", "8.00")
    individual = _opportunity(candidate, game)
    lot_listing = _listing(
        "lot-1",
        "Lote GTA V + RDR2",
        "20.00",
        url="https://example.test/lot-1",
    )
    second_game = _game("Red Dead Redemption 2")
    valuations = [_valuation(game), _valuation(second_game, "15.00")]
    lot_opportunity = _lot_opportunity(lot_listing, valuations)
    generation = SearchPlanGenerationResult(
        plan=SearchPlan(
            (
                SearchQuery("Grand Theft Auto V PS4", 40.4168, -3.7038, 10),
                SearchQuery("Red Dead Redemption 2 PS4", 40.4168, -3.7038, 10),
            )
        ),
        targets_received=3,
        queries_generated=2,
        duplicate_queries_removed=1,
    )
    lot_result = LotScanResult(
        listing=lot_listing,
        opportunity=lot_opportunity,
        game_valuations=valuations,
        failures=[],
        total_detected_games=2,
        successfully_valued_games=2,
        failed_games=0,
        is_complete=True,
        processing_time=0.2,
        created_at=_NOW,
        detected_games=[game, second_game],
    )
    scan_result = ScanResult(
        total_processed=1,
        successful=1,
        failed=0,
        opportunities=[individual],
        failures=[],
        processing_time=0.1,
        created_at=_NOW,
        comparable_cache_hits=0,
        comparable_cache_misses=1,
    )
    execution = SearchOrchestrationResult(
        individual_result=scan_result,
        lot_results=(lot_result,),
        query_failures=(),
        item_failures=(),
        routing_failures=(),
        total_queries=2,
        executed_queries=2,
        duplicate_queries=0,
        total_items_received=2,
        valid_candidates_received=2,
        duplicate_candidates=0,
        unique_candidates=2,
        individual_candidates=1,
        lot_candidates=1,
        undetected_candidates=0,
        processing_time=0.5,
        created_at=_NOW,
    )
    return _ReportData(generation, execution, individual, lot_opportunity)


def _empty_report_data() -> tuple[SearchPlanGenerationResult, SearchOrchestrationResult]:
    generation = SearchPlanGenerationResult(
        plan=SearchPlan(()),
        targets_received=0,
        queries_generated=0,
        duplicate_queries_removed=0,
    )
    execution = SearchOrchestrationResult(
        individual_result=None,
        lot_results=(),
        query_failures=(),
        item_failures=(),
        routing_failures=(),
        total_queries=0,
        executed_queries=0,
        duplicate_queries=0,
        total_items_received=0,
        valid_candidates_received=0,
        duplicate_candidates=0,
        unique_candidates=0,
        individual_candidates=0,
        lot_candidates=0,
        undetected_candidates=0,
        processing_time=0.0,
        created_at=_NOW,
    )
    return generation, execution


@pytest.mark.unit
def test_renderer_returns_stable_report_with_all_sections_and_fields() -> None:
    data = _report_data()
    report = render_terminal_report(data.generation, data.execution)

    headers = [
        "SEARCH PLAN GENERATION",
        "SEARCH EXECUTION",
        "INDIVIDUAL OPPORTUNITIES",
        "LOT OPPORTUNITIES",
        "FAILURES",
        "SUMMARY",
    ]
    assert all(header in report for header in headers)
    assert [report.index(header) for header in headers] == sorted(
        report.index(header) for header in headers
    )
    assert report.endswith("\n")
    assert "Targets received: 3" in report
    assert "Duplicate queries removed: 1" in report
    assert "Grand Theft Auto V PS4" in report
    assert "Total queries: 2" in report
    assert "candidate-1" in report
    assert "Purchase price: 8.00 EUR" in report
    assert "Market value: 15.00 EUR" in report
    assert "Net margin: 5.37%" in report
    assert "Net ROI: 7.25%" in report
    assert "Recommendation: BUY" in report
    assert "Opportunity score: 78.40" in report
    assert "Lote GTA V + RDR2" in report
    assert "Valued games: 2" in report
    assert "Aggregate confidence: 0.72" in report
    assert "Recommendation: MAYBE" in report
    assert "No failures." in report


@pytest.mark.unit
def test_renderer_preserves_order_does_not_mutate_and_is_deterministic() -> None:
    data = _report_data()
    before = (
        list(data.execution.individual_result.opportunities),
        list(data.execution.lot_results[0].game_valuations),
    )

    first = render_terminal_report(data.generation, data.execution)
    second = render_terminal_report(data.generation, data.execution)

    assert first == second
    assert first.index("candidate-1") < first.index("lot-1")
    assert before[0] == data.execution.individual_result.opportunities
    assert before[1] == data.execution.lot_results[0].game_valuations
    assert all(not line.endswith(" ") for line in first.splitlines())
    assert "\x1b" not in first


@pytest.mark.unit
def test_empty_results_keep_every_section_and_do_not_create_metrics() -> None:
    generation, execution = _empty_report_data()

    report = render_terminal_report(generation, execution)

    assert "No queries." in report
    assert "No individual opportunities." in report
    assert "No lot results." in report
    assert "No failures." in report
    assert "Structured failures: 0" in report
    assert "Total queries: 0" in report


@pytest.mark.unit
def test_verbose_failures_are_structured_and_sensitive_data_is_redacted() -> None:
    data = _report_data()
    query = data.generation.plan.queries[0]
    item_failure = CandidateItemFailure(
        item_index=2,
        kind=CandidateItemFailureKind.INVALID_CANDIDATE,
        reason="invalid candidate",
        listing_id="bad-item",
        error_message="authorization: Bearer secret-token",
    )
    lot_failure = GameValuationFailure(
        game=None,
        stage=LotPipelineStage.PRICE_COLLECTION,
        reason="no comparables",
        error_message="Traceback at 0xABCDEF",
        listing_id="lot-1",
    )
    failed_scan = ScanResult(
        total_processed=1,
        successful=0,
        failed=1,
        opportunities=[],
        failures=[
            FailureInfo(
                listing_id="candidate-failed",
                stage=PipelineStage.PRICE_COLLECTION,
                reason="collection failed",
                error_message="technical detail",
            )
        ],
        processing_time=0.1,
        created_at=_NOW,
    )
    failed_lot = LotScanResult(
        listing=data.lot_opportunity.listing,
        opportunity=None,
        game_valuations=[],
        failures=[lot_failure],
        total_detected_games=1,
        successfully_valued_games=0,
        failed_games=1,
        is_complete=False,
        processing_time=0.1,
        created_at=_NOW,
    )
    execution = SearchOrchestrationResult(
        individual_result=failed_scan,
        lot_results=(failed_lot,),
        query_failures=(
            SearchQueryFailure(
                query=query,
                query_index=0,
                reason="search failed",
                error_type="RuntimeError",
                error_message="traceback authorization Bearer secret-token",
            ),
        ),
        item_failures=(
            CandidateItemFailureRecord(query=query, query_index=0, failure=item_failure),
        ),
        routing_failures=(
            CandidateRoutingFailure(
                listing_id="candidate-failed",
                kind=CandidateRoutingFailureKind.NO_GAME_DETECTED,
                reason="no game",
                error_type=None,
                error_message=None,
            ),
        ),
        total_queries=1,
        executed_queries=1,
        duplicate_queries=0,
        total_items_received=1,
        valid_candidates_received=0,
        duplicate_candidates=0,
        unique_candidates=0,
        individual_candidates=0,
        lot_candidates=0,
        undetected_candidates=0,
        processing_time=0.2,
        created_at=_NOW,
    )

    compact = render_terminal_report(data.generation, execution)
    verbose = render_terminal_report(data.generation, execution, verbose=True)

    assert "Query failures: 1" in compact
    assert "Error type:" not in compact
    assert "Error type: RuntimeError" in verbose
    assert "[redacted sensitive detail]" in verbose
    assert "raw-secret" not in verbose
    assert "secret-token" not in verbose
    assert "Traceback" not in verbose
    assert "0xABCDEF" not in verbose
    assert "Structured failures: 5" in verbose


@pytest.mark.unit
@pytest.mark.parametrize(
    ("generation", "execution", "verbose"),
    [
        (object(), _empty_report_data()[1], False),
        (_empty_report_data()[0], object(), False),
        (_empty_report_data()[0], _empty_report_data()[1], 1),
        (_empty_report_data()[0], _empty_report_data()[1], "yes"),
    ],
)
def test_renderer_rejects_invalid_inputs(
    generation: object,
    execution: object,
    verbose: object,
) -> None:
    with pytest.raises(TypeError):
        render_terminal_report(generation, execution, verbose=verbose)  # type: ignore[arg-type]
