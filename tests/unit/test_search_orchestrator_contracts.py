"""Contract tests for the future SearchOrchestrator use case."""

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime
from decimal import Decimal

import pytest

from application.interfaces.candidate_search import (
    CandidateItemFailure,
    CandidateItemFailureKind,
    SearchQuery,
)
from application.interfaces.lot_opportunity_scanner import LotScanResult
from application.interfaces.opportunity_scanner import ScanResult
from application.interfaces.search_orchestrator import (
    CandidateItemFailureRecord,
    CandidateRoutingFailure,
    CandidateRoutingFailureKind,
    CandidateRoutingRecord,
    ISearchOrchestrator,
    SearchOrchestrationResult,
    SearchPlan,
    SearchQueryFailure,
)
from domain.entities.candidate_classification import (
    CandidateClassificationReason,
    CandidateDisposition,
)
from domain.entities.candidate_listing import CandidateListing


def _query(keywords: str = "GTA V") -> SearchQuery:
    return SearchQuery(keywords, 40.4168, -3.7038, 20)


def _candidate(identifier: str = "candidate-1") -> CandidateListing:
    return CandidateListing(
        identifier,
        "GTA V PS4",
        "",
        Decimal("10"),
        "EUR",
        f"https://example.test/{identifier}",
    )


def _scan_result() -> ScanResult:
    return ScanResult(
        total_processed=1,
        successful=0,
        failed=1,
        opportunities=[],
        failures=[],
        processing_time=0.1,
        created_at=datetime.now(),
    )


def _lot_result() -> LotScanResult:
    return LotScanResult(
        listing=_candidate("lot-1"),
        opportunity=None,
        game_valuations=[],
        failures=[],
        total_detected_games=0,
        successfully_valued_games=0,
        failed_games=1,
        is_complete=False,
        processing_time=0.1,
        created_at=datetime.now(),
    )


def _item_failure() -> CandidateItemFailure:
    return CandidateItemFailure(
        item_index=2,
        kind=CandidateItemFailureKind.INVALID_CANDIDATE,
        reason="invalid candidate",
        listing_id="raw-2",
        error_message="title must not be empty",
    )


def _empty_result() -> SearchOrchestrationResult:
    return SearchOrchestrationResult(
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
        created_at=datetime.now(),
    )


def test_search_plan_accepts_empty_sequence_and_snapshots_order() -> None:
    queries = [_query("GTA V"), _query("GTA V"), _query("RDR2")]

    plan = SearchPlan(queries)  # type: ignore[arg-type]
    queries.clear()

    assert isinstance(plan.queries, tuple)
    assert [query.keywords for query in plan.queries] == ["GTA V", "GTA V", "RDR2"]


def test_search_plan_preserves_duplicates_and_is_frozen() -> None:
    query = _query()
    plan = SearchPlan((query, query))

    assert plan.queries == (query, query)
    assert plan.queries[0] is query
    with pytest.raises(FrozenInstanceError):
        plan.queries = ()  # type: ignore[misc]


def test_search_plan_rejects_non_search_query_elements() -> None:
    with pytest.raises(TypeError, match="SearchQuery"):
        SearchPlan((object(),))  # type: ignore[arg-type]


def test_search_query_failure_validates_safe_context() -> None:
    failure = SearchQueryFailure(
        query=_query(),
        query_index=0,
        reason="search failed",
        error_type="RuntimeError",
        error_message="marketplace unavailable",
    )

    assert failure.query is not None
    assert not hasattr(failure, "exception")
    assert not hasattr(failure, "traceback")


@pytest.mark.parametrize("index", [-1, True])
def test_search_query_failure_rejects_invalid_index(index: object) -> None:
    with pytest.raises((TypeError, ValueError), match="query_index"):
        SearchQueryFailure(_query(), index, "failed", "RuntimeError", None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reason", "error_type"),
    [("", "RuntimeError"), ("failed", "")],
)
def test_search_query_failure_rejects_empty_descriptions(
    reason: str,
    error_type: str,
) -> None:
    with pytest.raises(ValueError):
        SearchQueryFailure(_query(), 0, reason, error_type, None)


def test_candidate_item_failure_record_reuses_existing_failure() -> None:
    failure = _item_failure()
    record = CandidateItemFailureRecord(_query(), 3, failure)

    assert record.failure is failure
    assert record.query_index == 3


def test_candidate_item_failure_record_rejects_invalid_context() -> None:
    with pytest.raises(ValueError, match="query_index"):
        CandidateItemFailureRecord(_query(), -1, _item_failure())
    with pytest.raises(TypeError, match="CandidateItemFailure"):
        CandidateItemFailureRecord(_query(), 0, object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "listing_id"),
    [
        (CandidateRoutingFailureKind.NO_GAME_DETECTED, "candidate-1"),
        (CandidateRoutingFailureKind.GAME_DETECTION_ERROR, "candidate-1"),
        (CandidateRoutingFailureKind.CANDIDATE_CLASSIFICATION_ERROR, "candidate-1"),
        (CandidateRoutingFailureKind.LOT_SCANNER_ERROR, "candidate-1"),
        (CandidateRoutingFailureKind.INDIVIDUAL_SCANNER_ERROR, None),
    ],
)
def test_candidate_routing_failure_valid_kinds(
    kind: CandidateRoutingFailureKind,
    listing_id: str | None,
) -> None:
    failure = CandidateRoutingFailure(
        listing_id=listing_id,
        kind=kind,
        reason="routing failed",
        error_type=None,
        error_message=None,
    )

    assert failure.kind is kind
    assert failure.listing_id == listing_id


def test_individual_batch_failure_does_not_invent_listing_id() -> None:
    with pytest.raises(ValueError, match="listing_id"):
        CandidateRoutingFailure(
            "batch-id",
            CandidateRoutingFailureKind.INDIVIDUAL_SCANNER_ERROR,
            "batch failed",
            "RuntimeError",
            "scanner failed",
        )


@pytest.mark.parametrize(
    ("kind", "listing_id"),
    [
        (CandidateRoutingFailureKind.NO_GAME_DETECTED, None),
        (CandidateRoutingFailureKind.GAME_DETECTION_ERROR, None),
        (CandidateRoutingFailureKind.CANDIDATE_CLASSIFICATION_ERROR, None),
        (CandidateRoutingFailureKind.LOT_SCANNER_ERROR, None),
        (CandidateRoutingFailureKind.INDIVIDUAL_SCANNER_ERROR, "candidate-1"),
    ],
)
def test_candidate_routing_failure_requires_correct_listing_scope(
    kind: CandidateRoutingFailureKind,
    listing_id: str | None,
) -> None:
    with pytest.raises(ValueError, match="listing_id"):
        CandidateRoutingFailure(listing_id, kind, "failed", None, None)


def test_candidate_routing_failure_reuses_canonical_listing_id_validation() -> None:
    with pytest.raises(ValueError, match="listing_id"):
        CandidateRoutingFailure(
            " candidate-1 ",
            CandidateRoutingFailureKind.NO_GAME_DETECTED,
            "no game",
            None,
            None,
        )
    with pytest.raises(ValueError, match="reason"):
        CandidateRoutingFailure(
            "candidate-1",
            CandidateRoutingFailureKind.NO_GAME_DETECTED,
            "",
            None,
            None,
        )


def test_candidate_routing_failure_is_frozen() -> None:
    failure = CandidateRoutingFailure(
        "candidate-1",
        CandidateRoutingFailureKind.NO_GAME_DETECTED,
        "no game",
        None,
        None,
    )

    with pytest.raises(FrozenInstanceError):
        failure.reason = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("disposition", "reason"),
    [
        (
            CandidateDisposition.IGNORED,
            CandidateClassificationReason.UNSUPPORTED_HARDWARE,
        ),
        (
            CandidateDisposition.AMBIGUOUS,
            CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
        ),
    ],
)
def test_candidate_routing_record_accepts_expected_classifications(
    disposition: CandidateDisposition,
    reason: CandidateClassificationReason,
) -> None:
    record = CandidateRoutingRecord(
        "candidate-1",
        "Candidate title",
        disposition,
        reason,
    )

    assert record.listing_id == "candidate-1"
    assert record.listing_title == "Candidate title"
    assert record.disposition is disposition
    assert record.reason is reason
    with pytest.raises(FrozenInstanceError):
        record.listing_title = "Changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("listing_id", "listing_title"),
    [("", "Title"), ("candidate-1", "")],
)
def test_candidate_routing_record_rejects_empty_identity_context(
    listing_id: str,
    listing_title: str,
) -> None:
    with pytest.raises(ValueError):
        CandidateRoutingRecord(
            listing_id,
            listing_title,
            CandidateDisposition.IGNORED,
            CandidateClassificationReason.NO_INCLUDED_GAME,
        )


def test_candidate_routing_record_rejects_wrong_enum_types() -> None:
    with pytest.raises(TypeError, match="disposition"):
        CandidateRoutingRecord(
            "candidate-1",
            "Title",
            "ignored",  # type: ignore[arg-type]
            CandidateClassificationReason.NO_INCLUDED_GAME,
        )
    with pytest.raises(TypeError, match="reason"):
        CandidateRoutingRecord(
            "candidate-1",
            "Title",
            CandidateDisposition.IGNORED,
            "no included game",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("disposition", "reason"),
    [
        (
            CandidateDisposition.ELIGIBLE_INDIVIDUAL,
            CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
        ),
        (
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
        ),
        (
            CandidateDisposition.IGNORED,
            CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
        ),
        (
            CandidateDisposition.AMBIGUOUS,
            CandidateClassificationReason.NO_INCLUDED_GAME,
        ),
    ],
)
def test_candidate_routing_record_rejects_incompatible_semantics(
    disposition: CandidateDisposition,
    reason: CandidateClassificationReason,
) -> None:
    with pytest.raises(ValueError):
        CandidateRoutingRecord(
            "candidate-1",
            "Title",
            disposition,
            reason,
        )


def test_candidate_routing_record_contains_only_safe_scalar_context() -> None:
    field_names = {field.name for field in fields(CandidateRoutingRecord)}

    assert field_names == {
        "listing_id",
        "listing_title",
        "disposition",
        "reason",
    }
    assert not field_names.intersection(
        {
            "listing",
            "raw_listing",
            "description",
            "price",
            "detected_games",
            "included_games",
            "exception",
            "economic_breakdown",
        }
    )


def test_empty_search_orchestration_result_is_valid() -> None:
    result = _empty_result()

    assert result.individual_result is None
    assert result.lot_results == ()
    assert result.total_queries == 0
    assert result.unique_candidates == 0
    assert result.ignored_candidates == ()
    assert result.ambiguous_candidates == ()


def test_result_snapshots_collections_without_copying_existing_results() -> None:
    scan_result = _scan_result()
    lot_result = _lot_result()
    query_failure = SearchQueryFailure(_query(), 0, "failed", "RuntimeError", None)
    item_record = CandidateItemFailureRecord(_query(), 0, _item_failure())
    routing_failure = CandidateRoutingFailure(
        "candidate-1",
        CandidateRoutingFailureKind.NO_GAME_DETECTED,
        "no game",
        None,
        None,
    )
    lots = [lot_result]
    query_failures = [query_failure]
    item_failures = [item_record]
    routing_failures = [routing_failure]

    result = SearchOrchestrationResult(
        scan_result,
        lots,  # type: ignore[arg-type]
        query_failures,  # type: ignore[arg-type]
        item_failures,  # type: ignore[arg-type]
        routing_failures,  # type: ignore[arg-type]
        1,
        1,
        0,
        1,
        1,
        0,
        1,
        1,
        0,
        0,
        0.0,
        datetime.now(),
    )
    lots.clear()
    query_failures.clear()
    item_failures.clear()
    routing_failures.clear()

    assert isinstance(result.lot_results, tuple)
    assert isinstance(result.query_failures, tuple)
    assert isinstance(result.item_failures, tuple)
    assert isinstance(result.routing_failures, tuple)
    assert result.individual_result is scan_result
    assert result.lot_results[0] is lot_result
    assert result.query_failures[0] is query_failure
    assert result.item_failures[0] is item_record
    assert result.routing_failures[0] is routing_failure


@pytest.mark.parametrize(
    "field_name",
    [
        "total_queries",
        "executed_queries",
        "duplicate_queries",
        "total_items_received",
        "valid_candidates_received",
        "duplicate_candidates",
        "unique_candidates",
        "individual_candidates",
        "lot_candidates",
        "undetected_candidates",
    ],
)
def test_result_rejects_negative_counters(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        replace(_empty_result(), **{field_name: -1})


def test_result_rejects_inconsistent_query_counters() -> None:
    with pytest.raises(ValueError, match="total_queries"):
        replace(_empty_result(), total_queries=1)
    with pytest.raises(ValueError, match="total_queries"):
        replace(_empty_result(), executed_queries=1)


def test_result_rejects_inconsistent_candidate_counters() -> None:
    with pytest.raises(ValueError, match="duplicate_candidates"):
        replace(
            _empty_result(),
            valid_candidates_received=1,
            duplicate_candidates=2,
            unique_candidates=0,
        )
    with pytest.raises(ValueError, match="unique_candidates"):
        replace(
            _empty_result(),
            valid_candidates_received=2,
            duplicate_candidates=0,
            unique_candidates=1,
        )


def test_result_rejects_inconsistent_routing_counters() -> None:
    with pytest.raises(ValueError, match="individual_candidates"):
        replace(
            _empty_result(),
            valid_candidates_received=1,
            unique_candidates=1,
        )


def test_result_counts_expected_classifications_as_terminal_routes() -> None:
    ignored = CandidateRoutingRecord(
        "ignored",
        "Ignored candidate",
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.NO_INCLUDED_GAME,
    )
    ambiguous = CandidateRoutingRecord(
        "ambiguous",
        "Ambiguous candidate",
        CandidateDisposition.AMBIGUOUS,
        CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
    )

    result = replace(
        _empty_result(),
        valid_candidates_received=2,
        unique_candidates=2,
        ignored_candidates=[ignored],  # type: ignore[arg-type]
        ambiguous_candidates=[ambiguous],  # type: ignore[arg-type]
    )

    assert result.ignored_candidates == (ignored,)
    assert result.ambiguous_candidates == (ambiguous,)


def test_result_rejects_records_in_the_wrong_collection() -> None:
    ignored = CandidateRoutingRecord(
        "ignored",
        "Ignored candidate",
        CandidateDisposition.IGNORED,
        CandidateClassificationReason.NO_INCLUDED_GAME,
    )
    ambiguous = CandidateRoutingRecord(
        "ambiguous",
        "Ambiguous candidate",
        CandidateDisposition.AMBIGUOUS,
        CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
    )

    with pytest.raises(ValueError, match="ignored_candidates"):
        replace(_empty_result(), ignored_candidates=(ambiguous,))
    with pytest.raises(ValueError, match="ambiguous_candidates"):
        replace(_empty_result(), ambiguous_candidates=(ignored,))


@pytest.mark.parametrize("processing_time", [-1.0, float("nan"), float("inf")])
def test_result_rejects_invalid_processing_time(processing_time: float) -> None:
    with pytest.raises(ValueError, match="processing_time"):
        replace(_empty_result(), processing_time=processing_time)


def test_result_allows_none_individual_and_has_no_mixed_opportunity_list() -> None:
    result = _empty_result()
    field_names = {field.name for field in fields(SearchOrchestrationResult)}

    assert result.individual_result is None
    assert "opportunities" not in field_names
    assert "ranking" not in field_names


def test_search_orchestrator_interface_is_async_and_abstract() -> None:
    assert inspect.iscoroutinefunction(ISearchOrchestrator.execute)
    with pytest.raises(TypeError):
        ISearchOrchestrator()


@pytest.mark.asyncio
async def test_fake_search_orchestrator_can_return_existing_result() -> None:
    result = _empty_result()

    class FakeSearchOrchestrator(ISearchOrchestrator):
        async def execute(self, plan: SearchPlan) -> SearchOrchestrationResult:
            assert plan.queries == ()
            return result

    returned = await FakeSearchOrchestrator().execute(SearchPlan(()))

    assert returned is result
