"""Pure text rendering for one operational search execution."""

import re
from decimal import Decimal

from application.interfaces.candidate_search import CandidateItemFailure
from application.interfaces.lot_opportunity_scanner import (
    GameValuationFailure,
    LotScanResult,
)
from application.interfaces.opportunity_scanner import FailureInfo
from application.interfaces.search_orchestrator import (
    CandidateItemFailureRecord,
    CandidateRoutingFailure,
    CandidateRoutingRecord,
    SearchOrchestrationResult,
    SearchQueryFailure,
)
from application.interfaces.search_plan_generator import SearchPlanGenerationResult
from domain.entities.game_valuation import GameValuation
from domain.interfaces.arbitrage_opportunity_detector import (
    ArbitrageOpportunity,
    Recommendation,
)

_SENSITIVE_MARKERS = (
    "authorization",
    "bearer ",
    "cookie",
    "header",
    "access_token",
    "refresh_token",
    "token",
    "traceback",
)

__all__ = ("render_terminal_report",)


def _one_line(value: str) -> str:
    printable = "".join(character if character.isprintable() else " " for character in value)
    return " ".join(printable.split()) or "N/A"


def _safe_error_message(value: str | None) -> str:
    if value is None:
        return "N/A"
    sanitized = _one_line(value)
    if any(marker in sanitized.casefold() for marker in _SENSITIVE_MARKERS):
        return "[redacted sensitive detail]"
    return re.sub(r"0x[0-9a-fA-F]+", "[redacted address]", sanitized)


def _safe_url(value: str) -> str:
    return _one_line(value.partition("?")[0].partition("#")[0])


def _money(value: Decimal, currency: str) -> str:
    return f"{value:.2f} {_one_line(currency)}"


def _percentage(value: Decimal) -> str:
    return f"{value:.2f}%"


def _render_generation(
    lines: list[str],
    generation: SearchPlanGenerationResult,
) -> None:
    lines.extend(
        (
            "SEARCH PLAN GENERATION",
            f"Targets received: {generation.targets_received}",
            f"Queries generated: {generation.queries_generated}",
            f"Duplicate queries removed: {generation.duplicate_queries_removed}",
            "Queries:",
        )
    )
    if not generation.plan.queries:
        lines.append("No queries.")
        return
    for position, query in enumerate(generation.plan.queries, 1):
        lines.extend(
            (
                f"{position}. {_one_line(query.keywords)}",
                f"   Location: {query.latitude}, {query.longitude}",
                f"   Max results: {query.max_results}",
            )
        )


def _render_execution(
    lines: list[str],
    execution: SearchOrchestrationResult,
) -> None:
    lines.extend(
        (
            "SEARCH EXECUTION",
            f"Total queries: {execution.total_queries}",
            f"Executed queries: {execution.executed_queries}",
            f"Duplicate queries: {execution.duplicate_queries}",
            f"Total items received: {execution.total_items_received}",
            f"Duplicate candidates: {execution.duplicate_candidates}",
            f"Unique candidates: {execution.unique_candidates}",
            f"Individual candidates: {execution.individual_candidates}",
            f"Lot candidates: {execution.lot_candidates}",
            f"Undetected candidates: {execution.undetected_candidates}",
            f"Ignored candidates: {len(execution.ignored_candidates)}",
            f"Ambiguous candidates: {len(execution.ambiguous_candidates)}",
            f"Processing time: {execution.processing_time:.6f} seconds",
        )
    )


def _render_individual_opportunity(
    lines: list[str],
    opportunity: ArbitrageOpportunity,
    position: int,
) -> None:
    listing = opportunity.listing
    lines.extend(
        (
            f"{position}. {_one_line(opportunity.game.canonical_name)} - "
            f"{opportunity.game.platform.value}",
            f"   Listing ID: {_one_line(listing.listing_id)}",
            f"   Title: {_one_line(listing.title)}",
            f"   URL: {_safe_url(listing.url)}",
            f"   Purchase price: {_money(opportunity.listing_price, opportunity.currency)}",
            f"   Market value: {_money(opportunity.market_price, opportunity.currency)}",
            f"   Net profit: {_money(opportunity.net_profit, opportunity.currency)}",
            f"   Net margin: {_percentage(opportunity.net_profit_margin_percentage)}",
            f"   Net ROI: {_percentage(opportunity.net_roi_percentage)}",
            f"   Confidence: {opportunity.confidence_score:.2f}",
            f"   Recommendation: {opportunity.recommendation.value.upper()}",
            f"   Reason code: {opportunity.reason.value}",
            f"   Opportunity score: {opportunity.opportunity_score:.2f}",
        )
    )


def _render_individuals(
    lines: list[str],
    execution: SearchOrchestrationResult,
) -> list[ArbitrageOpportunity]:
    lines.append("INDIVIDUAL OPPORTUNITIES")
    opportunities = (
        execution.individual_result.opportunities
        if execution.individual_result is not None
        else []
    )
    if not opportunities:
        lines.append("No individual opportunities.")
        return []
    for position, opportunity in enumerate(opportunities, 1):
        _render_individual_opportunity(lines, opportunity, position)
    return list(opportunities)


def _render_game_valuation(lines: list[str], valuation: GameValuation) -> None:
    lines.append(
        "   - "
        f"{_one_line(valuation.game.canonical_name)} / "
        f"{valuation.game.platform.value}: "
        f"{_money(valuation.estimated_market_value, valuation.currency)}, "
        f"confidence {valuation.confidence_score:.2f}, "
        f"observations {valuation.observations_used}, "
        f"outliers removed {valuation.observations_removed}"
    )


def _render_lot_result(
    lines: list[str],
    result: LotScanResult,
    position: int,
) -> None:
    listing = result.listing
    lines.extend(
        (
            f"{position}. {_one_line(listing.title)}",
            f"   Listing ID: {_one_line(listing.listing_id)}",
            f"   URL: {_safe_url(listing.url)}",
            f"   Lot price: {_money(listing.price, listing.currency)}",
            f"   Detected games: {result.total_detected_games}",
            f"   Valued games: {result.successfully_valued_games}",
            f"   Valuation failures: {result.failed_games}",
            f"   Complete valuation: {'Yes' if result.is_complete else 'No'}",
        )
    )
    if result.detected_games:
        lines.append("   Detected game identities:")
        for game in result.detected_games:
            lines.append(
                f"   - {_one_line(game.canonical_name)} / {game.platform.value}"
            )
    lines.append("   Game valuations:")
    if result.game_valuations:
        for valuation in result.game_valuations:
            _render_game_valuation(lines, valuation)
    else:
        lines.append("   No games valued.")

    opportunity = result.opportunity
    if opportunity is None:
        lines.append("   Opportunity status: No lot opportunity produced.")
        return
    lines.extend(
        (
            "   Opportunity status: Produced",
            f"   Total market value: "
            f"{_money(opportunity.reference_market_value, opportunity.currency)}",
            f"   Net profit: {_money(opportunity.net_profit, opportunity.currency)}",
            f"   Net margin: {_percentage(opportunity.net_profit_margin_percentage)}",
            f"   Net ROI: {_percentage(opportunity.net_roi_percentage)}",
            f"   Aggregate confidence: {opportunity.aggregate_confidence_score:.2f}",
            f"   Recommendation: {opportunity.recommendation.value.upper()}",
            f"   Reason code: {opportunity.reason.value}",
            f"   Opportunity score: {opportunity.opportunity_score:.2f}",
        )
    )


def _render_lots(
    lines: list[str],
    execution: SearchOrchestrationResult,
) -> list[LotScanResult]:
    lines.append("LOT OPPORTUNITIES")
    if not execution.lot_results:
        lines.append("No lot results.")
        return []
    for position, result in enumerate(execution.lot_results, 1):
        _render_lot_result(lines, result, position)
    return list(execution.lot_results)


def _render_candidate_records(
    lines: list[str],
    heading: str,
    empty_message: str,
    records: tuple[CandidateRoutingRecord, ...],
) -> None:
    lines.append(heading)
    if not records:
        lines.append(empty_message)
        return
    for position, record in enumerate(records, 1):
        lines.extend(
            (
                f"{position}. {_one_line(record.listing_title)}",
                f"   Listing ID: {_one_line(record.listing_id)}",
                f"   Reason: {record.reason.value}",
            )
        )


def _append_verbose_error(
    lines: list[str],
    error_type: str | None,
    error_message: str | None,
) -> None:
    if error_type is not None:
        lines.append(f"  Error type: {_one_line(error_type)}")
    if error_message is not None:
        lines.append(f"  Error message: {_safe_error_message(error_message)}")


def _render_query_failure(
    lines: list[str],
    failure: SearchQueryFailure,
    verbose: bool,
) -> None:
    lines.append(
        f"- Query index {failure.query_index} "
        f"({_one_line(failure.query.keywords)}): {_one_line(failure.reason)}"
    )
    if verbose:
        _append_verbose_error(lines, failure.error_type, failure.error_message)


def _render_item_failure(
    lines: list[str],
    record: CandidateItemFailureRecord,
    verbose: bool,
) -> None:
    failure: CandidateItemFailure = record.failure
    listing_id = _one_line(failure.listing_id) if failure.listing_id else "N/A"
    lines.append(
        f"- Query index {record.query_index}, item {failure.item_index}, "
        f"listing {listing_id}: {failure.kind.value} - {_one_line(failure.reason)}"
    )
    if verbose:
        _append_verbose_error(lines, None, failure.error_message)


def _render_routing_failure(
    lines: list[str],
    failure: CandidateRoutingFailure,
    verbose: bool,
) -> None:
    listing_id = _one_line(failure.listing_id) if failure.listing_id else "N/A"
    lines.append(
        f"- Listing {listing_id}: {failure.kind.value} - {_one_line(failure.reason)}"
    )
    if verbose:
        _append_verbose_error(lines, failure.error_type, failure.error_message)


def _render_scan_failure(
    lines: list[str],
    failure: FailureInfo,
    verbose: bool,
) -> None:
    lines.append(
        f"- Listing {_one_line(failure.listing_id)}: "
        f"{failure.stage.value} - {_one_line(failure.reason)}"
    )
    if verbose:
        _append_verbose_error(lines, None, failure.error_message)


def _render_lot_failure(
    lines: list[str],
    lot_listing_id: str,
    failure: GameValuationFailure,
    verbose: bool,
) -> None:
    game = (
        f"{_one_line(failure.game.canonical_name)} / {failure.game.platform.value}"
        if failure.game is not None
        else "N/A"
    )
    lines.append(
        f"- Lot {_one_line(lot_listing_id)}, game {game}: "
        f"{failure.stage.value} - {_one_line(failure.reason)}"
    )
    if verbose:
        _append_verbose_error(lines, None, failure.error_message)


def _render_failures(
    lines: list[str],
    execution: SearchOrchestrationResult,
    verbose: bool,
) -> int:
    query_failures = execution.query_failures
    item_failures = execution.item_failures
    routing_failures = execution.routing_failures
    individual_failures = (
        execution.individual_result.failures
        if execution.individual_result is not None
        else []
    )
    lot_failure_count = sum(
        len(result.failures) + (1 if result.analysis_failure is not None else 0)
        for result in execution.lot_results
    )
    total = (
        len(query_failures)
        + len(item_failures)
        + len(routing_failures)
        + len(individual_failures)
        + lot_failure_count
    )

    lines.extend(
        (
            "FAILURES",
            f"Query failures: {len(query_failures)}",
        )
    )
    for query_failure in query_failures:
        _render_query_failure(lines, query_failure, verbose)
    lines.append(f"Item failures: {len(item_failures)}")
    for item_failure_record in item_failures:
        _render_item_failure(lines, item_failure_record, verbose)
    lines.append(f"Routing failures: {len(routing_failures)}")
    for routing_failure in routing_failures:
        _render_routing_failure(lines, routing_failure, verbose)
    lines.append(f"Individual scanner failures: {len(individual_failures)}")
    for scan_failure in individual_failures:
        _render_scan_failure(lines, scan_failure, verbose)
    lines.append(f"Lot failures: {lot_failure_count}")
    for result in execution.lot_results:
        for lot_failure in result.failures:
            _render_lot_failure(
                lines,
                result.listing.listing_id,
                lot_failure,
                verbose,
            )
        if result.analysis_failure is not None:
            _render_scan_failure(lines, result.analysis_failure, verbose)
    if total == 0:
        lines.append("No failures.")
    return total


def _recommendation_counts(
    recommendations: list[Recommendation],
) -> tuple[int, int, int]:
    return (
        recommendations.count(Recommendation.BUY),
        recommendations.count(Recommendation.MAYBE),
        recommendations.count(Recommendation.SKIP),
    )


def _render_summary(
    lines: list[str],
    generation: SearchPlanGenerationResult,
    execution: SearchOrchestrationResult,
    individual_opportunities: list[ArbitrageOpportunity],
    lot_results: list[LotScanResult],
    total_failures: int,
) -> None:
    individual_counts = _recommendation_counts(
        [opportunity.recommendation for opportunity in individual_opportunities]
    )
    lot_counts = _recommendation_counts(
        [
            result.opportunity.recommendation
            for result in lot_results
            if result.opportunity is not None
        ]
    )
    lines.extend(
        (
            "SUMMARY",
            f"Queries generated: {generation.queries_generated}",
            f"Queries executed: {execution.executed_queries}",
            f"Unique candidates: {execution.unique_candidates}",
            f"Individual opportunities: {len(individual_opportunities)}",
            f"Lot results: {len(lot_results)}",
            f"Ignored candidates: {len(execution.ignored_candidates)}",
            f"Ambiguous candidates: {len(execution.ambiguous_candidates)}",
            f"Structured failures: {total_failures}",
            "Individual recommendations: "
            f"BUY={individual_counts[0]}, MAYBE={individual_counts[1]}, "
            f"SKIP={individual_counts[2]}",
            "Lot recommendations: "
            f"BUY={lot_counts[0]}, MAYBE={lot_counts[1]}, SKIP={lot_counts[2]}",
        )
    )


def render_terminal_report(
    generation: SearchPlanGenerationResult,
    execution: SearchOrchestrationResult,
    *,
    verbose: bool = False,
) -> str:
    """Return a deterministic terminal report without I/O or recalculation."""
    if not isinstance(generation, SearchPlanGenerationResult):
        raise TypeError("generation must be SearchPlanGenerationResult")
    if not isinstance(execution, SearchOrchestrationResult):
        raise TypeError("execution must be SearchOrchestrationResult")
    if type(verbose) is not bool:
        raise TypeError("verbose must be bool")

    lines: list[str] = []
    _render_generation(lines, generation)
    lines.append("")
    _render_execution(lines, execution)
    lines.append("")
    individual_opportunities = _render_individuals(lines, execution)
    lines.append("")
    lot_results = _render_lots(lines, execution)
    lines.append("")
    _render_candidate_records(
        lines,
        "IGNORED CANDIDATES",
        "No ignored candidates.",
        execution.ignored_candidates,
    )
    lines.append("")
    _render_candidate_records(
        lines,
        "AMBIGUOUS CANDIDATES",
        "No ambiguous candidates.",
        execution.ambiguous_candidates,
    )
    lines.append("")
    total_failures = _render_failures(lines, execution, verbose)
    lines.append("")
    _render_summary(
        lines,
        generation,
        execution,
        individual_opportunities,
        lot_results,
        total_failures,
    )
    return "\n".join(line.rstrip() for line in lines) + "\n"
