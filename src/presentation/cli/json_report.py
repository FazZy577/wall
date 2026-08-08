"""Deterministic, safe JSON reporting for one operational execution."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias, cast

from application.interfaces.candidate_search import SearchQuery
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
from domain.entities.lot_opportunity import LotOpportunity
from domain.interfaces.arbitrage_opportunity_detector import ArbitrageOpportunity

_JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = _JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

__all__ = (
    "JsonValue",
    "JsonReportWriteError",
    "build_json_report",
    "write_json_report",
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


class JsonReportWriteError(OSError):
    """Raised when a JSON report cannot be serialized or written."""


def _one_line(value: str) -> str:
    printable = "".join(character if character.isprintable() else " " for character in value)
    return " ".join(printable.split())


def _safe_message(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = _one_line(value)
    if any(marker in sanitized.casefold() for marker in _SENSITIVE_MARKERS):
        return "[redacted sensitive detail]"
    return re.sub(r"0x[0-9a-fA-F]+", "[redacted address]", sanitized)


def _safe_url(value: str) -> str:
    return _one_line(value).partition("?")[0].partition("#")[0]


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("JSON report contains a non-finite number")
    return value


def _json_list(values: list[dict[str, JsonValue]]) -> list[JsonValue]:
    return [cast(JsonValue, value) for value in values]


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _query_mapping(query: SearchQuery) -> dict[str, JsonValue]:
    return {
        "keywords": query.keywords,
        "latitude": _finite(query.latitude),
        "longitude": _finite(query.longitude),
        "max_results": query.max_results,
    }


def _opportunity_mapping(opportunity: ArbitrageOpportunity) -> dict[str, JsonValue]:
    listing = opportunity.listing
    return {
        "listing_id": listing.listing_id,
        "title": _one_line(listing.title),
        "url": _safe_url(listing.url),
        "game": opportunity.game.canonical_name,
        "platform": opportunity.game.platform.value,
        "purchase_price": str(opportunity.listing_price),
        "estimated_market_value": str(opportunity.market_price),
        "net_profit": str(opportunity.net_profit),
        "margin": str(opportunity.net_profit_margin_percentage),
        "roi": str(opportunity.net_roi_percentage),
        "confidence": _finite(opportunity.confidence_score),
        "recommendation": opportunity.recommendation.value,
        "reason_code": opportunity.reason.value,
        "opportunity_score": _finite(opportunity.opportunity_score),
        "currency": opportunity.currency,
    }


def _valuation_mapping(valuation: GameValuation) -> dict[str, JsonValue]:
    return {
        "game": valuation.game.canonical_name,
        "platform": valuation.game.platform.value,
        "estimated_price": str(valuation.estimated_market_value),
        "confidence": _finite(valuation.confidence_score),
        "observations_used": valuation.observations_used,
        "outliers_removed": valuation.observations_removed,
        "currency": valuation.currency,
    }


def _lot_opportunity_mapping(opportunity: LotOpportunity) -> dict[str, JsonValue]:
    return {
        "estimated_value": str(opportunity.reference_market_value),
        "net_profit": str(opportunity.net_profit),
        "margin": str(opportunity.net_profit_margin_percentage),
        "roi": str(opportunity.net_roi_percentage),
        "confidence": _finite(opportunity.aggregate_confidence_score),
        "recommendation": opportunity.recommendation.value,
        "reason_code": opportunity.reason.value,
        "opportunity_score": _finite(opportunity.opportunity_score),
        "currency": opportunity.currency,
    }


def _lot_mapping(result: LotScanResult) -> dict[str, JsonValue]:
    listing = result.listing
    return {
        "listing_id": listing.listing_id,
        "title": _one_line(listing.title),
        "url": _safe_url(listing.url),
        "lot_price": str(listing.price),
        "detected_games": _json_list([
            {"game": game.canonical_name, "platform": game.platform.value}
            for game in result.detected_games
        ]),
        "valued_games": result.successfully_valued_games,
        "valuation_failures": result.failed_games,
        "is_complete": result.is_complete,
        "game_valuations": _json_list(
            [_valuation_mapping(item) for item in result.game_valuations]
        ),
        "opportunity": (
            _lot_opportunity_mapping(result.opportunity)
            if result.opportunity is not None
            else None
        ),
    }


def _query_failure_mapping(failure: SearchQueryFailure) -> dict[str, JsonValue]:
    return {
        "query": _query_mapping(failure.query),
        "query_index": failure.query_index,
        "reason": _one_line(failure.reason),
        "error_type": failure.error_type,
        "message": _safe_message(failure.error_message),
    }


def _item_failure_mapping(record: CandidateItemFailureRecord) -> dict[str, JsonValue]:
    failure = record.failure
    return {
        "query": _query_mapping(record.query),
        "query_index": record.query_index,
        "item_index": failure.item_index,
        "kind": failure.kind.value,
        "listing_id": failure.listing_id,
        "reason": _one_line(failure.reason),
        "message": _safe_message(failure.error_message),
    }


def _routing_failure_mapping(failure: CandidateRoutingFailure) -> dict[str, JsonValue]:
    return {
        "listing_id": failure.listing_id,
        "kind": failure.kind.value,
        "reason": _one_line(failure.reason),
        "error_type": failure.error_type,
        "message": _safe_message(failure.error_message),
    }


def _candidate_routing_mapping(
    record: CandidateRoutingRecord,
) -> dict[str, JsonValue]:
    return {
        "listing_id": record.listing_id,
        "listing_title": _one_line(record.listing_title),
        "disposition": record.disposition.value,
        "reason": record.reason.value,
    }


def _scan_failure_mapping(failure: FailureInfo) -> dict[str, JsonValue]:
    return {
        "listing_id": failure.listing_id,
        "stage": failure.stage.value,
        "reason": _one_line(failure.reason),
        "message": _safe_message(failure.error_message),
    }


def _lot_failure_mapping(
    lot_listing_id: str,
    failure: GameValuationFailure,
) -> dict[str, JsonValue]:
    game: dict[str, JsonValue] | None = None
    if failure.game is not None:
        game = {
            "game": failure.game.canonical_name,
            "platform": failure.game.platform.value,
        }
    return {
        "listing_id": failure.listing_id or lot_listing_id,
        "game": game,
        "stage": failure.stage.value,
        "reason": _one_line(failure.reason),
        "message": _safe_message(failure.error_message),
    }


def build_json_report(
    generation: SearchPlanGenerationResult,
    execution: SearchOrchestrationResult,
) -> dict[str, JsonValue]:
    """Build an explicit, deterministic JSON-safe report mapping."""
    if not isinstance(generation, SearchPlanGenerationResult):
        raise TypeError("generation must be SearchPlanGenerationResult")
    if not isinstance(execution, SearchOrchestrationResult):
        raise TypeError("execution must be SearchOrchestrationResult")

    individual_opportunities = (
        execution.individual_result.opportunities
        if execution.individual_result is not None
        else []
    )
    individual_failures = (
        execution.individual_result.failures
        if execution.individual_result is not None
        else []
    )
    lot_failures: list[dict[str, JsonValue]] = []
    for result in execution.lot_results:
        lot_failures.extend(
            _lot_failure_mapping(result.listing.listing_id, failure)
            for failure in result.failures
        )
        if result.analysis_failure is not None:
            lot_failures.append(_scan_failure_mapping(result.analysis_failure))

    individual_counts = {"buy": 0, "maybe": 0, "skip": 0}
    for opportunity in individual_opportunities:
        individual_counts[opportunity.recommendation.value] += 1
    lot_counts = {"buy": 0, "maybe": 0, "skip": 0}
    for result in execution.lot_results:
        if result.opportunity is not None:
            lot_counts[result.opportunity.recommendation.value] += 1

    structured_failure_count = (
        len(execution.query_failures)
        + len(execution.item_failures)
        + len(execution.routing_failures)
        + len(individual_failures)
        + len(lot_failures)
    )
    generation_queries = _json_list(
        [_query_mapping(query) for query in generation.plan.queries]
    )
    individual_json = _json_list(
        [_opportunity_mapping(opportunity) for opportunity in individual_opportunities]
    )
    lot_json = _json_list([_lot_mapping(result) for result in execution.lot_results])
    ignored_candidates_json = _json_list(
        [_candidate_routing_mapping(record) for record in execution.ignored_candidates]
    )
    ambiguous_candidates_json = _json_list(
        [
            _candidate_routing_mapping(record)
            for record in execution.ambiguous_candidates
        ]
    )
    query_failures_json = _json_list(
        [_query_failure_mapping(failure) for failure in execution.query_failures]
    )
    item_failures_json = _json_list(
        [_item_failure_mapping(record) for record in execution.item_failures]
    )
    routing_failures_json = _json_list(
        [_routing_failure_mapping(failure) for failure in execution.routing_failures]
    )
    individual_failures_json = _json_list(
        [_scan_failure_mapping(failure) for failure in individual_failures]
    )
    lot_failures_json = _json_list(lot_failures)
    return {
        "schema_version": 2,
        "generation": {
            "targets_received": generation.targets_received,
            "queries_generated": generation.queries_generated,
            "duplicate_queries_removed": generation.duplicate_queries_removed,
            "queries": generation_queries,
        },
        "execution": {
            "created_at": _timestamp(execution.created_at),
            "processing_time_seconds": _finite(execution.processing_time),
            "queries": {
                "total": execution.total_queries,
                "executed": execution.executed_queries,
                "duplicates": execution.duplicate_queries,
                "failed": len(execution.query_failures),
            },
            "candidates": {
                "received": execution.total_items_received,
                "duplicates": execution.duplicate_candidates,
                "unique": execution.unique_candidates,
                "individual": execution.individual_candidates,
                "lots": execution.lot_candidates,
                "undetected": execution.undetected_candidates,
                "ignored": len(execution.ignored_candidates),
                "ambiguous": len(execution.ambiguous_candidates),
            },
        },
        "individual_opportunities": individual_json,
        "lot_results": lot_json,
        "ignored_candidates": ignored_candidates_json,
        "ambiguous_candidates": ambiguous_candidates_json,
        "failures": {
            "queries": query_failures_json,
            "items": item_failures_json,
            "routing": routing_failures_json,
            "individual_pipeline": individual_failures_json,
            "lots": lot_failures_json,
        },
        "summary": {
            "queries_generated": generation.queries_generated,
            "queries_executed": execution.executed_queries,
            "unique_candidates": execution.unique_candidates,
            "individual_opportunities": len(individual_opportunities),
            "lot_results": len(execution.lot_results),
            "ignored_candidates": len(execution.ignored_candidates),
            "ambiguous_candidates": len(execution.ambiguous_candidates),
            "structured_failures": structured_failure_count,
            "recommendations": {
                "individual": cast(JsonValue, individual_counts),
                "lots": cast(JsonValue, lot_counts),
            },
        },
    }


def write_json_report(
    report: Mapping[str, JsonValue],
    path: Path,
    *,
    overwrite: bool,
) -> None:
    """Serialize and atomically write a JSON report beside its target."""
    if not isinstance(report, Mapping):
        raise TypeError("report must be a Mapping")
    if not isinstance(path, Path):
        raise TypeError("path must be pathlib.Path")
    if type(overwrite) is not bool:
        raise TypeError("overwrite must be bool")

    try:
        serialized = json.dumps(
            dict(report),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise JsonReportWriteError(
            f"Could not serialize JSON report for {path}"
        ) from error

    try:
        target_exists = path.exists()
    except OSError as error:
        raise JsonReportWriteError(f"Could not inspect JSON report target {path}") from error
    if target_exists and not overwrite:
        file_exists_error = FileExistsError(str(path))
        raise JsonReportWriteError(
            f"JSON report target already exists: {path}"
        ) from file_exists_error

    temporary_path: Path | None = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        replaced = True
    except (OSError, TypeError, ValueError) as error:
        raise JsonReportWriteError(f"Could not write JSON report to {path}") from error
    finally:
        if not replaced and temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
