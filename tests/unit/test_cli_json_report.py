"""Unit tests for the explicit JSON report boundary."""

import inspect
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from application.interfaces.candidate_search import (
    CandidateItemFailure,
    CandidateItemFailureKind,
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
    SearchQueryFailure,
)
from presentation.cli import json_report
from presentation.cli.json_report import (
    JsonReportWriteError,
    build_json_report,
    write_json_report,
)
from tests.unit.test_cli_terminal_report import _empty_report_data, _report_data


@pytest.mark.unit
def test_build_json_report_has_stable_schema_and_explicit_values() -> None:
    data = _report_data()
    report = build_json_report(data.generation, data.execution)

    assert report["schema_version"] == 1
    assert set(report) == {
        "schema_version",
        "generation",
        "execution",
        "individual_opportunities",
        "lot_results",
        "failures",
        "summary",
    }
    generation = report["generation"]
    assert isinstance(generation, dict)
    assert generation["targets_received"] == 3
    assert generation["queries_generated"] == 2
    assert generation["duplicate_queries_removed"] == 1
    assert generation["queries"][0]["keywords"] == "Grand Theft Auto V PS4"  # type: ignore[index]

    individual = report["individual_opportunities"][0]  # type: ignore[index]
    assert individual["purchase_price"] == "8.00"  # type: ignore[index]
    assert individual["estimated_market_value"] == "15.00"  # type: ignore[index]
    assert individual["net_profit"] == "0.725"  # type: ignore[index]
    assert individual["recommendation"] == "buy"  # type: ignore[index]
    assert individual["reason_code"] == "undervalued"  # type: ignore[index]
    assert individual["url"] == "https://example.test/listing-1"  # type: ignore[index]

    lot = report["lot_results"][0]  # type: ignore[index]
    assert lot["lot_price"] == "20.00"  # type: ignore[index]
    assert lot["valued_games"] == 2  # type: ignore[index]
    assert lot["opportunity"]["recommendation"] == "maybe"  # type: ignore[index]

    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False)
    assert "raw_listing" not in encoded
    assert "authorization" not in encoded.casefold()
    assert "secret-token" not in encoded
    assert "not rendered" not in encoded


@pytest.mark.unit
def test_empty_report_is_valid_json_and_build_is_deterministic_without_mutation() -> None:
    generation, execution = _empty_report_data()
    before = deepcopy(execution)

    first = build_json_report(generation, execution)
    second = build_json_report(generation, execution)

    assert first == second
    assert first["individual_opportunities"] == []
    assert first["lot_results"] == []
    assert first["failures"] == {
        "queries": [],
        "items": [],
        "routing": [],
        "individual_pipeline": [],
        "lots": [],
    }
    assert execution == before


@pytest.mark.unit
def test_build_validates_result_types() -> None:
    generation, execution = _empty_report_data()

    with pytest.raises(TypeError):
        build_json_report(object(), execution)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        build_json_report(generation, object())  # type: ignore[arg-type]

    assert not inspect.iscoroutinefunction(build_json_report)
    assert not inspect.iscoroutinefunction(write_json_report)


@pytest.mark.unit
def test_timestamps_preserve_awareness_policy() -> None:
    generation, execution = _empty_report_data()

    aware = build_json_report(generation, execution)
    naive = build_json_report(
        generation,
        replace(execution, created_at=datetime(2025, 1, 1, 12, 30)),
    )

    assert aware["execution"]["created_at"] == "2025-01-01T00:00:00Z"  # type: ignore[index]
    assert naive["execution"]["created_at"] == "2025-01-01T12:30:00"  # type: ignore[index]


@pytest.mark.unit
def test_failures_are_grouped_lot_without_opportunity_is_preserved_and_secrets_are_removed() -> None:
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
        game=data.execution.lot_results[0].detected_games[1],
        stage=LotPipelineStage.PRICE_COLLECTION,
        reason="no comparables",
        error_message="failure at 0xABCDEF",
        listing_id="lot-1",
    )
    failed_lot = LotScanResult(
        listing=data.execution.lot_results[0].listing,
        opportunity=None,
        game_valuations=[data.execution.lot_results[0].game_valuations[0]],
        failures=[lot_failure],
        total_detected_games=2,
        successfully_valued_games=1,
        failed_games=1,
        is_complete=False,
        processing_time=0.1,
        created_at=data.execution.created_at,
        detected_games=list(data.execution.lot_results[0].detected_games),
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
                error_message="cookie=session-secret",
            )
        ],
        processing_time=0.1,
        created_at=data.execution.created_at,
    )
    execution = replace(
        data.execution,
        individual_result=failed_scan,
        lot_results=(failed_lot,),
        query_failures=(
            SearchQueryFailure(
                query=query,
                query_index=0,
                reason="search failed",
                error_type="RuntimeError",
                error_message="Traceback authorization Bearer secret-token",
            ),
        ),
        item_failures=(
            CandidateItemFailureRecord(
                query=query,
                query_index=0,
                failure=item_failure,
            ),
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
    )

    report = build_json_report(data.generation, execution)
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False)
    failures = report["failures"]

    assert failures["queries"][0]["error_type"] == "RuntimeError"  # type: ignore[index]
    assert failures["items"][0]["listing_id"] == "bad-item"  # type: ignore[index]
    assert failures["routing"][0]["message"] is None  # type: ignore[index]
    assert failures["individual_pipeline"][0]["stage"] == "price_collection"  # type: ignore[index]
    assert failures["lots"][0]["message"] == "failure at [redacted address]"  # type: ignore[index]
    assert report["lot_results"][0]["opportunity"] is None  # type: ignore[index]
    assert report["lot_results"][0]["is_complete"] is False  # type: ignore[index]
    assert report["summary"]["structured_failures"] == 5  # type: ignore[index]
    for secret in (
        "secret-token",
        "session-secret",
        "traceback",
        "0xabcdef",
        "raw_listing",
    ):
        assert secret not in encoded.casefold()


@pytest.mark.unit
def test_write_json_report_is_utf8_atomic_and_respects_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = {"message": "Español", "value": "€"}
    target = tmp_path / "report.json"
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = json_report.os.replace

    def replace(source: str | bytes | Path, destination: str | bytes | Path) -> None:
        replace_calls.append((Path(source), Path(destination)))
        original_replace(source, destination)

    monkeypatch.setattr(json_report.os, "replace", replace)
    write_json_report(report, target, overwrite=False)

    assert target.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(target.read_text(encoding="utf-8")) == report
    assert len(replace_calls) == 1
    assert replace_calls[0][0].parent == tmp_path
    assert replace_calls[0][1] == target
    assert not list(tmp_path.glob(".*.tmp"))

    with pytest.raises(JsonReportWriteError) as error:
        write_json_report(report, target, overwrite=False)
    assert str(target) in str(error.value)
    assert isinstance(error.value.__cause__, FileExistsError)

    write_json_report({"message": "replaced"}, target, overwrite=True)
    assert json.loads(target.read_text(encoding="utf-8"))["message"] == "replaced"


@pytest.mark.unit
def test_write_json_report_rejects_bad_inputs_and_cleans_temp_on_replace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "report.json"
    with pytest.raises(TypeError):
        write_json_report([], target, overwrite=False)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        write_json_report({}, str(target), overwrite=False)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        write_json_report({}, target, overwrite=1)  # type: ignore[arg-type]

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(json_report.os, "replace", fail_replace)
    with pytest.raises(JsonReportWriteError) as error:
        write_json_report({"safe": True}, target, overwrite=True)
    assert isinstance(error.value.__cause__, OSError)
    assert not list(tmp_path.glob(".*.tmp"))
    assert not target.exists()

    missing_parent = tmp_path / "missing" / "report.json"
    with pytest.raises(JsonReportWriteError) as missing_parent_error:
        write_json_report({"safe": True}, missing_parent, overwrite=True)
    assert isinstance(missing_parent_error.value.__cause__, FileNotFoundError)
    assert not missing_parent.parent.exists()


@pytest.mark.unit
def test_write_json_report_wraps_serialization_errors_without_mutating_mapping(
    tmp_path: Path,
) -> None:
    report = {"bad": float("nan")}
    snapshot = dict(report)

    with pytest.raises(JsonReportWriteError) as error:
        write_json_report(report, tmp_path / "report.json", overwrite=True)

    assert isinstance(error.value.__cause__, ValueError)
    assert report == snapshot
