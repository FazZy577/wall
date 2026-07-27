"""Unit tests for the sequential DefaultSearchOrchestrator."""

import asyncio
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from application.interfaces.candidate_search import (
    CandidateItemFailure,
    CandidateItemFailureKind,
    CandidateSearchResult,
    ICandidateSearch,
    SearchQuery,
)
from application.interfaces.detected_candidate import DetectedCandidate
from application.interfaces.lot_opportunity_scanner import (
    ILotOpportunityScanner,
    LotScanResult,
)
from application.interfaces.opportunity_scanner import (
    IOpportunityScanner,
    ScanResult,
)
from application.interfaces.search_orchestrator import (
    CandidateRoutingFailureKind,
    SearchPlan,
)
from application.use_cases.default_search_orchestrator import (
    DefaultSearchOrchestrator,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.interfaces.game_detector import IGameDetector, ListingText


def _query(
    keywords: str = "GTA V",
    *,
    latitude: float = 40.4168,
    longitude: float = -3.7038,
    max_results: int = 20,
) -> SearchQuery:
    return SearchQuery(keywords, latitude, longitude, max_results)


def _candidate(
    identifier: str,
    *,
    title: str | None = None,
    raw_marker: str | None = None,
) -> CandidateListing:
    return CandidateListing(
        identifier,
        title or identifier,
        "",
        Decimal("10"),
        "EUR",
        f"https://example.test/{identifier}",
        raw_listing={"marker": raw_marker or identifier},
    )


def _game(name: str = "GTA V") -> DetectedGame:
    return DetectedGame(
        name,
        name,
        Platform.PS4,
        1.0,
        DetectionMethod.EXACT_MATCH,
    )


def _search_result(
    query: SearchQuery,
    candidates: tuple[CandidateListing, ...] = (),
    failures: tuple[CandidateItemFailure, ...] = (),
    total_items: int | None = None,
) -> CandidateSearchResult:
    return CandidateSearchResult(
        query,
        candidates,
        failures,
        len(candidates) + len(failures) if total_items is None else total_items,
    )


def _scan_result() -> ScanResult:
    return ScanResult(
        total_processed=1,
        successful=1,
        failed=0,
        opportunities=[],
        failures=[],
        processing_time=0.1,
        created_at=datetime.now(UTC),
    )


def _lot_result(listing: CandidateListing) -> LotScanResult:
    return LotScanResult(
        listing=listing,
        opportunity=None,
        game_valuations=[],
        failures=[],
        total_detected_games=2,
        successfully_valued_games=0,
        failed_games=2,
        is_complete=False,
        processing_time=0.1,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def orchestrator() -> tuple[DefaultSearchOrchestrator, dict[str, Mock]]:
    candidate_search = Mock(spec=ICandidateSearch)
    candidate_search.search_candidates = AsyncMock()
    game_detector = Mock(spec=IGameDetector)
    opportunity_scanner = Mock(spec=IOpportunityScanner)
    opportunity_scanner.scan_detected_multiple = AsyncMock(return_value=_scan_result())
    lot_scanner = Mock(spec=ILotOpportunityScanner)
    lot_scanner.scan_detected_lot = AsyncMock()
    dependencies = {
        "search": candidate_search,
        "detector": game_detector,
        "individual": opportunity_scanner,
        "lot": lot_scanner,
    }
    return (
        DefaultSearchOrchestrator(
            candidate_search,
            game_detector,
            opportunity_scanner,
            lot_scanner,
        ),
        dependencies,
    )


@pytest.mark.asyncio
async def test_empty_plan_calls_no_dependency(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator

    result = await service.execute(SearchPlan(()))

    dependencies["search"].search_candidates.assert_not_awaited()
    dependencies["detector"].detect_games.assert_not_called()
    dependencies["individual"].scan_detected_multiple.assert_not_awaited()
    dependencies["lot"].scan_detected_lot.assert_not_awaited()
    assert result.total_queries == result.executed_queries == 0
    assert result.individual_result is None
    assert result.lot_results == ()


@pytest.mark.asyncio
async def test_empty_query_result_is_success_not_failure(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    dependencies["search"].search_candidates.return_value = _search_result(query)

    result = await service.execute(SearchPlan((query,)))

    assert (result.total_queries, result.executed_queries) == (1, 1)
    assert result.query_failures == ()
    assert result.total_items_received == result.valid_candidates_received == 0


@pytest.mark.asyncio
async def test_queries_execute_sequentially_in_original_order(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    queries = (_query("first"), _query("second"), _query("third"))
    active = 0
    maximum_active = 0
    observed: list[SearchQuery] = []

    async def search(query: SearchQuery) -> CandidateSearchResult:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        observed.append(query)
        result = _search_result(query)
        active -= 1
        return result

    dependencies["search"].search_candidates.side_effect = search

    await service.execute(SearchPlan(queries))

    assert observed == list(queries)
    assert maximum_active == 1


@pytest.mark.asyncio
async def test_equivalent_queries_execute_once_and_first_instance_wins(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    first = _query("GTA   5 PS4")
    duplicates = (_query("gta 5 ps4"), _query("Gta 5 Ps4"))
    dependencies["search"].search_candidates.return_value = _search_result(first)

    result = await service.execute(SearchPlan((first, *duplicates)))

    dependencies["search"].search_candidates.assert_awaited_once_with(first)
    assert (result.total_queries, result.executed_queries, result.duplicate_queries) == (
        3,
        1,
        2,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second",
    [
        _query("GTA V", latitude=41.0),
        _query("GTA V", longitude=-4.0),
        _query("GTA V", max_results=50),
    ],
)
async def test_query_key_preserves_coordinates_and_max_results(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
    second: SearchQuery,
) -> None:
    service, dependencies = orchestrator
    first = _query("GTA V")
    dependencies["search"].search_candidates.side_effect = [
        _search_result(first),
        _search_result(second),
    ]

    result = await service.execute(SearchPlan((first, second)))

    assert dependencies["search"].search_candidates.await_count == 2
    assert (result.executed_queries, result.duplicate_queries) == (2, 0)


@pytest.mark.asyncio
async def test_failed_query_counts_as_executed_and_duplicate_is_not_retried(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    first = _query("GTA   V")
    duplicate = _query("gta v")
    dependencies["search"].search_candidates.side_effect = RuntimeError("down")

    result = await service.execute(SearchPlan((first, duplicate)))

    assert dependencies["search"].search_candidates.await_count == 1
    assert (result.executed_queries, result.duplicate_queries) == (1, 1)
    assert result.query_failures[0].query is first
    assert result.query_failures[0].query_index == 0


@pytest.mark.asyncio
async def test_query_deduplication_is_local_to_each_execute(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    dependencies["search"].search_candidates.return_value = _search_result(query)

    first = await service.execute(SearchPlan((query,)))
    second = await service.execute(SearchPlan((query,)))

    assert dependencies["search"].search_candidates.await_count == 2
    assert first.executed_queries == second.executed_queries == 1


@pytest.mark.asyncio
async def test_technical_query_failures_are_ordered_and_do_not_stop_searches(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    queries = (_query("first"), _query("second"), _query("third"))
    dependencies["search"].search_candidates.side_effect = [
        RuntimeError("first error"),
        ValueError("second error"),
        _search_result(queries[2]),
    ]

    result = await service.execute(SearchPlan(queries))

    assert [failure.query_index for failure in result.query_failures] == [0, 1]
    assert [failure.error_type for failure in result.query_failures] == [
        "RuntimeError",
        "ValueError",
    ]
    assert result.executed_queries == 3


@pytest.mark.asyncio
async def test_invalid_or_mismatched_search_result_rejects_whole_query(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    first = _query("first")
    second = _query("second")
    wrong_candidate = _candidate("wrong")
    dependencies["search"].search_candidates.side_effect = [
        object(),
        _search_result(first, (wrong_candidate,)),
    ]

    result = await service.execute(SearchPlan((first, second)))

    assert [failure.error_type for failure in result.query_failures] == [
        "TypeError",
        "ValueError",
    ]
    assert result.total_items_received == 0
    assert result.valid_candidates_received == 0
    dependencies["detector"].detect_games.assert_not_called()


@pytest.mark.asyncio
async def test_unprintable_query_exception_is_safe(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    class UnprintableError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("cannot stringify")

    service, dependencies = orchestrator
    dependencies["search"].search_candidates.side_effect = UnprintableError()

    result = await service.execute(SearchPlan((_query(),)))

    assert result.query_failures[0].error_type == "UnprintableError"
    assert result.query_failures[0].error_message is None


@pytest.mark.asyncio
async def test_query_cancellation_propagates(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    dependencies["search"].search_candidates.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.execute(SearchPlan((_query(),)))


@pytest.mark.asyncio
async def test_item_failures_keep_identity_query_context_and_order(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    first_query = _query("first")
    second_query = _query("second")
    first_failure = CandidateItemFailure(
        2,
        CandidateItemFailureKind.INVALID_RAW_ITEM,
        "invalid raw",
        None,
        None,
    )
    second_failure = CandidateItemFailure(
        0,
        CandidateItemFailureKind.INVALID_CANDIDATE,
        "invalid candidate",
        "listing",
        "invalid title",
    )
    dependencies["search"].search_candidates.side_effect = [
        _search_result(first_query, failures=(first_failure,)),
        _search_result(second_query, failures=(second_failure,)),
    ]

    result = await service.execute(SearchPlan((first_query, second_query)))

    assert [record.query_index for record in result.item_failures] == [0, 1]
    assert result.item_failures[0].query is first_query
    assert result.item_failures[0].failure is first_failure
    assert result.item_failures[1].failure is second_failure


@pytest.mark.asyncio
async def test_candidates_deduplicate_globally_first_wins_and_preserve_order(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    first_query = _query("first")
    second_query = _query("second")
    first_a = _candidate("A", raw_marker="first-A")
    duplicate_a = _candidate("A", raw_marker="duplicate-A")
    candidate_b = _candidate("B")
    candidate_c = _candidate("C")
    original_raw = dict(first_a.raw_listing)
    dependencies["search"].search_candidates.side_effect = [
        _search_result(first_query, (first_a, duplicate_a, candidate_b)),
        _search_result(second_query, (duplicate_a, candidate_c)),
    ]
    dependencies["detector"].detect_games.return_value = [_game()]

    result = await service.execute(SearchPlan((first_query, second_query)))

    detected = dependencies["individual"].scan_detected_multiple.await_args.args[0]
    assert [candidate.listing for candidate in detected] == [
        first_a,
        candidate_b,
        candidate_c,
    ]
    assert detected[0].listing is first_a
    assert first_a.raw_listing == original_raw
    assert (
        result.valid_candidates_received,
        result.duplicate_candidates,
        result.unique_candidates,
    ) == (5, 2, 3)


@pytest.mark.asyncio
async def test_candidate_state_is_local_to_each_execute(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    candidate = _candidate("A")
    dependencies["search"].search_candidates.return_value = _search_result(
        query, (candidate,)
    )
    dependencies["detector"].detect_games.return_value = [_game()]

    first = await service.execute(SearchPlan((query,)))
    second = await service.execute(SearchPlan((query,)))

    assert dependencies["detector"].detect_games.call_count == 2
    assert first.unique_candidates == second.unique_candidates == 1
    assert dependencies["individual"].scan_detected_multiple.await_count == 2


@pytest.mark.asyncio
async def test_detection_routes_zero_one_many_and_preserves_duplicate_games(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    zero = _candidate("zero")
    individual = _candidate("individual")
    lot = _candidate("lot")
    repeated_game = _game()
    dependencies["search"].search_candidates.return_value = _search_result(
        query, (zero, individual, lot)
    )
    dependencies["detector"].detect_games.side_effect = [
        [],
        [repeated_game],
        [repeated_game, repeated_game],
    ]
    lot_result = _lot_result(lot)
    dependencies["lot"].scan_detected_lot.return_value = lot_result

    result = await service.execute(SearchPlan((query,)))

    assert dependencies["detector"].detect_games.call_count == 3
    individual_batch = dependencies[
        "individual"
    ].scan_detected_multiple.await_args.args[0]
    lot_input = dependencies["lot"].scan_detected_lot.await_args.args[0]
    assert individual_batch[0].listing is individual
    assert lot_input.listing is lot
    assert lot_input.detected_games == (repeated_game, repeated_game)
    assert [failure.kind for failure in result.routing_failures] == [
        CandidateRoutingFailureKind.NO_GAME_DETECTED
    ]
    assert (
        result.individual_candidates,
        result.lot_candidates,
        result.undetected_candidates,
    ) == (1, 1, 1)


@pytest.mark.asyncio
async def test_detector_errors_are_isolated_ordered_and_safe(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    class UnprintableError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("cannot stringify")

    service, dependencies = orchestrator
    query = _query()
    candidates = tuple(_candidate(identifier) for identifier in ("A", "B", "C"))
    dependencies["search"].search_candidates.return_value = _search_result(
        query, candidates
    )
    dependencies["detector"].detect_games.side_effect = [
        RuntimeError("first"),
        UnprintableError(),
        [_game()],
    ]

    result = await service.execute(SearchPlan((query,)))

    assert [failure.listing_id for failure in result.routing_failures] == ["A", "B"]
    assert all(
        failure.kind is CandidateRoutingFailureKind.GAME_DETECTION_ERROR
        for failure in result.routing_failures
    )
    assert result.routing_failures[1].error_message is None
    assert result.undetected_candidates == 2
    dependencies["individual"].scan_detected_multiple.assert_awaited_once()


@pytest.mark.asyncio
async def test_detector_cancellation_propagates(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    dependencies["search"].search_candidates.return_value = _search_result(
        query, (_candidate("A"),)
    )
    dependencies["detector"].detect_games.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.execute(SearchPlan((query,)))


@pytest.mark.asyncio
async def test_individuals_use_one_detected_batch_and_preserve_result_identity(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    candidates = (_candidate("A"), _candidate("B"), _candidate("C"))
    dependencies["search"].search_candidates.return_value = _search_result(
        query, candidates
    )
    dependencies["detector"].detect_games.return_value = [_game()]
    scan_result = _scan_result()
    dependencies["individual"].scan_detected_multiple.return_value = scan_result

    result = await service.execute(SearchPlan((query,)))

    dependencies["individual"].scan_detected_multiple.assert_awaited_once()
    batch = dependencies["individual"].scan_detected_multiple.await_args.args[0]
    assert isinstance(batch, tuple)
    assert [item.listing for item in batch] == list(candidates)
    assert result.individual_result is scan_result
    dependencies["individual"].scan_listing.assert_not_called()
    dependencies["individual"].scan_multiple.assert_not_called()
    dependencies["individual"].scan_detected_listing.assert_not_called()


@pytest.mark.asyncio
async def test_no_individual_candidates_skips_individual_scanner(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    dependencies["search"].search_candidates.return_value = _search_result(
        query, (_candidate("none"),)
    )
    dependencies["detector"].detect_games.return_value = []

    result = await service.execute(SearchPlan((query,)))

    dependencies["individual"].scan_detected_multiple.assert_not_awaited()
    assert result.individual_result is None


@pytest.mark.asyncio
async def test_individual_batch_failure_is_single_and_lots_continue(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    individual = _candidate("individual")
    lot = _candidate("lot")
    dependencies["search"].search_candidates.return_value = _search_result(
        query, (individual, lot)
    )
    dependencies["detector"].detect_games.side_effect = [
        [_game()],
        [_game("GTA V"), _game("RDR2")],
    ]
    dependencies["individual"].scan_detected_multiple.side_effect = RuntimeError(
        "batch failed"
    )
    lot_result = _lot_result(lot)
    dependencies["lot"].scan_detected_lot.return_value = lot_result

    result = await service.execute(SearchPlan((query,)))

    assert result.individual_result is None
    assert result.lot_results == (lot_result,)
    assert result.individual_candidates == result.lot_candidates == 1
    assert len(result.routing_failures) == 1
    failure = result.routing_failures[0]
    assert failure.kind is CandidateRoutingFailureKind.INDIVIDUAL_SCANNER_ERROR
    assert failure.listing_id is None


@pytest.mark.asyncio
async def test_individual_scanner_cancellation_propagates(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    dependencies["search"].search_candidates.return_value = _search_result(
        query, (_candidate("A"),)
    )
    dependencies["detector"].detect_games.return_value = [_game()]
    dependencies[
        "individual"
    ].scan_detected_multiple.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.execute(SearchPlan((query,)))


@pytest.mark.asyncio
async def test_lots_are_sequential_ordered_and_failures_are_isolated(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    lots = tuple(_candidate(identifier) for identifier in ("A", "B", "C"))
    dependencies["search"].search_candidates.return_value = _search_result(query, lots)
    dependencies["detector"].detect_games.return_value = [
        _game("GTA V"),
        _game("RDR2"),
    ]
    first_result = _lot_result(lots[0])
    third_result = _lot_result(lots[2])
    active = 0
    maximum_active = 0
    observed: list[str] = []

    async def scan(candidate: DetectedCandidate) -> LotScanResult:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        observed.append(candidate.listing.listing_id)
        active -= 1
        if candidate.listing.listing_id == "B":
            raise RuntimeError("lot failed")
        return first_result if candidate.listing.listing_id == "A" else third_result

    dependencies["lot"].scan_detected_lot.side_effect = scan

    result = await service.execute(SearchPlan((query,)))

    assert observed == ["A", "B", "C"]
    assert maximum_active == 1
    assert result.lot_results == (first_result, third_result)
    assert result.lot_results[0] is first_result
    assert result.routing_failures[0].kind is (
        CandidateRoutingFailureKind.LOT_SCANNER_ERROR
    )
    assert result.routing_failures[0].listing_id == "B"
    dependencies["lot"].scan_lot.assert_not_called()


@pytest.mark.asyncio
async def test_lot_scanner_cancellation_propagates(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    dependencies["search"].search_candidates.return_value = _search_result(
        query, (_candidate("lot"),)
    )
    dependencies["detector"].detect_games.return_value = [_game(), _game("RDR2")]
    dependencies["lot"].scan_detected_lot.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.execute(SearchPlan((query,)))


@pytest.mark.asyncio
async def test_execution_order_is_search_detect_individual_then_lots(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    events: list[str] = []
    first_query = _query("first")
    second_query = _query("second")
    individual = _candidate("individual")
    lot = _candidate("lot")

    async def search(query: SearchQuery) -> CandidateSearchResult:
        events.append(f"search:{query.keywords}")
        candidate = individual if query is first_query else lot
        return _search_result(query, (candidate,))

    def detect(listing_text: ListingText) -> list[DetectedGame]:
        title = listing_text.title
        events.append(f"detect:{title}")
        return [_game()] if title == "individual" else [_game(), _game("RDR2")]

    async def scan_individual(
        candidates: tuple[DetectedCandidate, ...],
    ) -> ScanResult:
        events.append(f"individual:{candidates[0].listing.listing_id}")
        return _scan_result()

    async def scan_lot(candidate: DetectedCandidate) -> LotScanResult:
        events.append(f"lot:{candidate.listing.listing_id}")
        return _lot_result(candidate.listing)

    dependencies["search"].search_candidates.side_effect = search
    dependencies["detector"].detect_games.side_effect = detect
    dependencies["individual"].scan_detected_multiple.side_effect = scan_individual
    dependencies["lot"].scan_detected_lot.side_effect = scan_lot

    await service.execute(SearchPlan((first_query, second_query)))

    assert events == [
        "search:first",
        "search:second",
        "detect:individual",
        "detect:lot",
        "individual:individual",
        "lot:lot",
    ]


@pytest.mark.asyncio
async def test_mixed_result_counters_separation_timestamps_and_tuples(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    first_query = _query("first")
    duplicate_query = _query(" FIRST ")
    second_query = _query("second")
    individual = _candidate("individual")
    duplicate_individual = _candidate("individual", raw_marker="duplicate")
    lot = _candidate("lot")
    undetected = _candidate("undetected")
    item_failure = CandidateItemFailure(
        3,
        CandidateItemFailureKind.INVALID_RAW_ITEM,
        "invalid",
        None,
        None,
    )
    dependencies["search"].search_candidates.side_effect = [
        _search_result(
            first_query,
            (individual, duplicate_individual),
            (item_failure,),
            total_items=3,
        ),
        _search_result(second_query, (lot, undetected), total_items=2),
    ]
    dependencies["detector"].detect_games.side_effect = [
        [_game()],
        [_game(), _game("RDR2")],
        [],
    ]
    scan_result = _scan_result()
    lot_result = _lot_result(lot)
    dependencies["individual"].scan_detected_multiple.return_value = scan_result
    dependencies["lot"].scan_detected_lot.return_value = lot_result

    result = await service.execute(
        SearchPlan((first_query, duplicate_query, second_query))
    )

    assert (
        result.total_queries,
        result.executed_queries,
        result.duplicate_queries,
    ) == (3, 2, 1)
    assert (
        result.total_items_received,
        result.valid_candidates_received,
        result.duplicate_candidates,
        result.unique_candidates,
    ) == (5, 4, 1, 3)
    assert (
        result.individual_candidates,
        result.lot_candidates,
        result.undetected_candidates,
    ) == (1, 1, 1)
    assert result.individual_result is scan_result
    assert result.lot_results == (lot_result,)
    assert isinstance(result.lot_results, tuple)
    assert isinstance(result.query_failures, tuple)
    assert isinstance(result.item_failures, tuple)
    assert isinstance(result.routing_failures, tuple)
    assert result.processing_time >= 0
    assert result.created_at.tzinfo is UTC


@pytest.mark.asyncio
async def test_orchestrator_does_not_close_dependencies_or_expose_ranker(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, dependencies = orchestrator
    query = _query()
    dependencies["search"].search_candidates.return_value = _search_result(query)
    closers = []
    for dependency in dependencies.values():
        dependency.close = Mock()
        closers.append(dependency.close)

    await service.execute(SearchPlan((query,)))

    assert not hasattr(service, "opportunity_ranker")
    assert list(inspect.signature(DefaultSearchOrchestrator).parameters) == [
        "candidate_search",
        "game_detector",
        "opportunity_scanner",
        "lot_opportunity_scanner",
    ]
    assert all(closer.call_count == 0 for closer in closers)


@pytest.mark.asyncio
async def test_execute_rejects_non_plan(
    orchestrator: tuple[DefaultSearchOrchestrator, dict[str, Mock]],
) -> None:
    service, _ = orchestrator

    with pytest.raises(TypeError, match="SearchPlan"):
        await service.execute(object())  # type: ignore[arg-type]
