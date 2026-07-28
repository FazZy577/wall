"""Contract tests for the future SearchPlanGenerator use case."""

import inspect
from dataclasses import FrozenInstanceError, fields
from enum import StrEnum

import pytest

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.search_orchestrator import SearchPlan
from application.interfaces.search_plan_generator import (
    GameSearchTarget,
    ISearchPlanGenerator,
    SearchPlanGenerationError,
    SearchPlanGenerationRequest,
    SearchPlanGenerationResult,
    SearchPlanGenerationStrategy,
    SearchPlanLimitExceededError,
    UnknownGameSearchTargetError,
)
from domain.entities.detected_game import Platform


def _target(
    canonical_name: str = "Grand Theft Auto V",
    platform: Platform = Platform.PS4,
) -> GameSearchTarget:
    return GameSearchTarget(canonical_name, platform)


def _request(
    *,
    targets: object = None,
    latitude: object = 40.4168,
    longitude: object = -3.7038,
    max_results: object = 20,
    max_queries: object = 10,
    strategy: object = SearchPlanGenerationStrategy.CANONICAL_ONLY,
) -> SearchPlanGenerationRequest:
    actual_targets = (_target(),) if targets is None else targets
    return SearchPlanGenerationRequest(
        targets=actual_targets,  # type: ignore[arg-type]
        latitude=latitude,  # type: ignore[arg-type]
        longitude=longitude,  # type: ignore[arg-type]
        max_results=max_results,  # type: ignore[arg-type]
        max_queries=max_queries,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
    )


def _query(keywords: str = "Grand Theft Auto V PS4") -> SearchQuery:
    return SearchQuery(keywords, 40.4168, -3.7038, 20)


def _result(
    *,
    plan: object = None,
    targets_received: object = 1,
    queries_generated: object = 1,
    duplicate_queries_removed: object = 0,
) -> SearchPlanGenerationResult:
    actual_plan = SearchPlan((_query(),)) if plan is None else plan
    return SearchPlanGenerationResult(
        plan=actual_plan,  # type: ignore[arg-type]
        targets_received=targets_received,  # type: ignore[arg-type]
        queries_generated=queries_generated,  # type: ignore[arg-type]
        duplicate_queries_removed=duplicate_queries_removed,  # type: ignore[arg-type]
    )


def test_game_search_target_is_valid_stripped_and_keeps_platform() -> None:
    target = GameSearchTarget("  Grand Theft Auto V  ", Platform.PS5)

    assert target.canonical_name == "Grand Theft Auto V"
    assert target.platform is Platform.PS5


def test_game_search_target_does_not_normalize_internal_content() -> None:
    target = GameSearchTarget("  Pokémon:   Stadium 2!  ", Platform.SWITCH)

    assert target.canonical_name == "Pokémon:   Stadium 2!"


@pytest.mark.parametrize("canonical_name", ["", " ", "\t\r\n"])
def test_game_search_target_rejects_empty_name(canonical_name: str) -> None:
    with pytest.raises(ValueError, match="canonical_name"):
        GameSearchTarget(canonical_name, Platform.PS4)


@pytest.mark.parametrize("canonical_name", [None, 1, True, object()])
def test_game_search_target_rejects_non_string_name(
    canonical_name: object,
) -> None:
    with pytest.raises(TypeError, match="canonical_name"):
        GameSearchTarget(canonical_name, Platform.PS4)  # type: ignore[arg-type]


@pytest.mark.parametrize("platform", ["PS4", None, 1, object()])
def test_game_search_target_rejects_non_platform(platform: object) -> None:
    with pytest.raises(TypeError, match="platform"):
        GameSearchTarget("GTA V", platform)  # type: ignore[arg-type]


def test_game_search_target_rejects_unknown_platform() -> None:
    with pytest.raises(ValueError, match="UNKNOWN"):
        GameSearchTarget("GTA V", Platform.UNKNOWN)


def test_game_search_target_is_frozen_and_has_only_target_fields() -> None:
    target = _target()

    assert [field.name for field in fields(target)] == [
        "canonical_name",
        "platform",
    ]
    for detected_field in ("confidence", "matched_text", "detection_method"):
        assert not hasattr(target, detected_field)
    with pytest.raises(FrozenInstanceError):
        target.canonical_name = "RDR2"  # type: ignore[misc]


def test_generation_strategy_has_exactly_one_public_value() -> None:
    assert list(SearchPlanGenerationStrategy) == [
        SearchPlanGenerationStrategy.CANONICAL_ONLY
    ]
    assert SearchPlanGenerationStrategy.CANONICAL_ONLY.value == "canonical_only"
    assert issubclass(SearchPlanGenerationStrategy, StrEnum)
    for future_member in ("CANONICAL_AND_ALIASES", "AI_GENERATED", "FUZZY"):
        assert not hasattr(SearchPlanGenerationStrategy, future_member)


def test_generation_request_accepts_targets_and_defaults_strategy() -> None:
    target = _target()
    request = _request(targets=(target,))

    assert request.targets == (target,)
    assert request.targets[0] is target
    assert request.strategy is SearchPlanGenerationStrategy.CANONICAL_ONLY


def test_generation_request_snapshots_list_without_copying_targets() -> None:
    first = _target("GTA V")
    second = _target("RDR2")
    supplied_targets = [first, second]

    request = _request(targets=supplied_targets)
    supplied_targets.clear()

    assert isinstance(request.targets, tuple)
    assert request.targets == (first, second)
    assert request.targets[0] is first
    assert request.targets[1] is second


def test_generation_request_preserves_order_and_duplicates() -> None:
    first = _target("GTA V")
    second = _target("RDR2")

    request = _request(targets=[first, second, first])

    assert request.targets == (first, second, first)
    assert request.targets[0] is request.targets[2]


def test_generation_request_accepts_empty_targets_and_still_validates_inputs() -> None:
    request = _request(targets=[])

    assert request.targets == ()
    with pytest.raises(ValueError, match="max_queries"):
        _request(targets=[], max_queries=0)


@pytest.mark.parametrize("targets", [[_target(), object()], "GTA V", b"GTA V", 1])
def test_generation_request_rejects_invalid_target_collection(
    targets: object,
) -> None:
    with pytest.raises(TypeError, match="targets"):
        _request(targets=targets)


def test_generation_request_is_frozen() -> None:
    request = _request()

    with pytest.raises(FrozenInstanceError):
        request.max_queries = 2  # type: ignore[misc]


@pytest.mark.parametrize("latitude", [-90, -45.5, 0, 45.5, 90])
def test_generation_request_accepts_valid_latitude(latitude: float) -> None:
    assert _request(latitude=latitude).latitude == latitude


@pytest.mark.parametrize("latitude", [-90.0001, 90.0001])
def test_generation_request_rejects_out_of_range_latitude(
    latitude: float,
) -> None:
    with pytest.raises(ValueError, match="latitude"):
        _request(latitude=latitude)


@pytest.mark.parametrize("latitude", [float("nan"), float("inf"), float("-inf")])
def test_generation_request_rejects_non_finite_latitude(latitude: float) -> None:
    with pytest.raises(ValueError, match="latitude"):
        _request(latitude=latitude)


@pytest.mark.parametrize("latitude", [True, False, "40", None])
def test_generation_request_rejects_invalid_latitude_type(
    latitude: object,
) -> None:
    with pytest.raises(TypeError, match="latitude"):
        _request(latitude=latitude)


@pytest.mark.parametrize("longitude", [-180, -90.5, 0, 90.5, 180])
def test_generation_request_accepts_valid_longitude(longitude: float) -> None:
    assert _request(longitude=longitude).longitude == longitude


@pytest.mark.parametrize("longitude", [-180.0001, 180.0001])
def test_generation_request_rejects_out_of_range_longitude(
    longitude: float,
) -> None:
    with pytest.raises(ValueError, match="longitude"):
        _request(longitude=longitude)


@pytest.mark.parametrize("longitude", [float("nan"), float("inf"), float("-inf")])
def test_generation_request_rejects_non_finite_longitude(
    longitude: float,
) -> None:
    with pytest.raises(ValueError, match="longitude"):
        _request(longitude=longitude)


@pytest.mark.parametrize("longitude", [True, False, "3", None])
def test_generation_request_rejects_invalid_longitude_type(
    longitude: object,
) -> None:
    with pytest.raises(TypeError, match="longitude"):
        _request(longitude=longitude)


@pytest.mark.parametrize("max_results", [1, 20, 10_000])
def test_generation_request_accepts_positive_max_results(
    max_results: int,
) -> None:
    assert _request(max_results=max_results).max_results == max_results


@pytest.mark.parametrize("max_results", [0, -1])
def test_generation_request_rejects_non_positive_max_results(
    max_results: int,
) -> None:
    with pytest.raises(ValueError, match="max_results"):
        _request(max_results=max_results)


@pytest.mark.parametrize("max_results", [True, False, 1.0, "1", None])
def test_generation_request_rejects_non_integer_max_results(
    max_results: object,
) -> None:
    with pytest.raises(TypeError, match="max_results"):
        _request(max_results=max_results)


@pytest.mark.parametrize("max_queries", [1, 20, 10_000])
def test_generation_request_accepts_positive_max_queries(max_queries: int) -> None:
    assert _request(max_queries=max_queries).max_queries == max_queries


@pytest.mark.parametrize("max_queries", [0, -1])
def test_generation_request_rejects_non_positive_max_queries(
    max_queries: int,
) -> None:
    with pytest.raises(ValueError, match="max_queries"):
        _request(max_queries=max_queries)


@pytest.mark.parametrize("max_queries", [True, False, 1.0, "1", None])
def test_generation_request_rejects_non_integer_max_queries(
    max_queries: object,
) -> None:
    with pytest.raises(TypeError, match="max_queries"):
        _request(max_queries=max_queries)


def test_generation_request_accepts_explicit_strategy_enum() -> None:
    request = _request(strategy=SearchPlanGenerationStrategy.CANONICAL_ONLY)

    assert request.strategy is SearchPlanGenerationStrategy.CANONICAL_ONLY


class _OtherStrategy(StrEnum):
    CANONICAL_ONLY = "canonical_only"


@pytest.mark.parametrize(
    "strategy",
    ["canonical_only", _OtherStrategy.CANONICAL_ONLY, None],
)
def test_generation_request_rejects_non_canonical_strategy(
    strategy: object,
) -> None:
    with pytest.raises(TypeError, match="strategy"):
        _request(strategy=strategy)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(-90, -180), (0, 0), (40.4168, -3.7038), (90, 180)],
)
def test_generation_request_matches_search_query_valid_coordinates(
    latitude: float,
    longitude: float,
) -> None:
    query = SearchQuery("GTA V", latitude, longitude, 20)
    request = _request(latitude=latitude, longitude=longitude)

    assert request.latitude == query.latitude
    assert request.longitude == query.longitude


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("latitude", -91),
        ("latitude", float("nan")),
        ("latitude", True),
        ("longitude", 181),
        ("longitude", float("inf")),
        ("longitude", False),
    ],
)
def test_generation_request_matches_search_query_invalid_coordinates(
    field_name: str,
    value: object,
) -> None:
    query_values: dict[str, object] = {
        "latitude": 40.4168,
        "longitude": -3.7038,
    }
    query_values[field_name] = value

    with pytest.raises((TypeError, ValueError)) as query_error:
        SearchQuery(
            "GTA V",
            query_values["latitude"],  # type: ignore[arg-type]
            query_values["longitude"],  # type: ignore[arg-type]
            20,
        )
    with pytest.raises(type(query_error.value)):
        _request(**{field_name: value})


@pytest.mark.parametrize("max_results", [1, 25])
def test_generation_request_matches_search_query_valid_max_results(
    max_results: int,
) -> None:
    query = SearchQuery("GTA V", 40.4168, -3.7038, max_results)
    request = _request(max_results=max_results)

    assert request.max_results == query.max_results


@pytest.mark.parametrize("max_results", [0, -1, True, 1.0])
def test_generation_request_matches_search_query_invalid_max_results(
    max_results: object,
) -> None:
    with pytest.raises((TypeError, ValueError)) as query_error:
        SearchQuery(
            "GTA V",
            40.4168,
            -3.7038,
            max_results,  # type: ignore[arg-type]
        )
    with pytest.raises(type(query_error.value)):
        _request(max_results=max_results)


def test_generation_contract_does_not_modify_search_query() -> None:
    query = SearchQuery("  GTA V  ", 40.4168, -3.7038, 20)

    _request()

    assert query.keywords == "GTA V"
    assert [field.name for field in fields(query)] == [
        "keywords",
        "latitude",
        "longitude",
        "max_results",
    ]


def test_generation_result_is_valid_and_keeps_plan_identity() -> None:
    plan = SearchPlan((_query(),))

    result = _result(plan=plan)

    assert result.plan is plan
    assert result.targets_received == 1
    assert result.queries_generated == 1
    assert result.duplicate_queries_removed == 0


def test_generation_result_accepts_empty_plan() -> None:
    plan = SearchPlan(())

    result = _result(
        plan=plan,
        targets_received=0,
        queries_generated=0,
        duplicate_queries_removed=0,
    )

    assert result.plan is plan


def test_generation_result_rejects_non_search_plan() -> None:
    with pytest.raises(TypeError, match="plan"):
        _result(plan=object())


@pytest.mark.parametrize(
    "counter_name",
    ["targets_received", "queries_generated", "duplicate_queries_removed"],
)
@pytest.mark.parametrize("value", [-1, -10])
def test_generation_result_rejects_negative_counters(
    counter_name: str,
    value: int,
) -> None:
    values = {
        "targets_received": 1,
        "queries_generated": 1,
        "duplicate_queries_removed": 0,
        counter_name: value,
    }
    with pytest.raises(ValueError, match=counter_name):
        _result(**values)


@pytest.mark.parametrize(
    "counter_name",
    ["targets_received", "queries_generated", "duplicate_queries_removed"],
)
@pytest.mark.parametrize("value", [True, False, 1.0, "1"])
def test_generation_result_rejects_non_integer_counters(
    counter_name: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "targets_received": 1,
        "queries_generated": 1,
        "duplicate_queries_removed": 0,
        counter_name: value,
    }
    with pytest.raises(TypeError, match=counter_name):
        _result(**values)


def test_generation_result_requires_query_count_to_match_plan() -> None:
    with pytest.raises(ValueError, match="queries_generated"):
        _result(queries_generated=0)


def test_generation_result_rejects_duplicate_count_above_targets() -> None:
    with pytest.raises(ValueError, match="duplicate_queries_removed"):
        _result(
            plan=SearchPlan(()),
            targets_received=1,
            queries_generated=0,
            duplicate_queries_removed=2,
        )


def test_generation_result_rejects_generated_and_duplicates_above_targets() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        _result(
            targets_received=1,
            queries_generated=1,
            duplicate_queries_removed=1,
        )


def test_generation_result_allows_targets_without_queries() -> None:
    result = _result(
        targets_received=3,
        queries_generated=1,
        duplicate_queries_removed=1,
    )

    assert result.queries_generated + result.duplicate_queries_removed == 2


def test_generation_result_is_frozen_and_has_only_generation_metrics() -> None:
    result = _result()

    assert [field.name for field in fields(result)] == [
        "plan",
        "targets_received",
        "queries_generated",
        "duplicate_queries_removed",
    ]
    for orchestration_field in (
        "created_at",
        "processing_time",
        "opportunities",
        "query_failures",
    ):
        assert not hasattr(result, orchestration_field)
    with pytest.raises(FrozenInstanceError):
        result.targets_received = 2  # type: ignore[misc]


def test_generation_errors_have_small_distinguishable_hierarchy() -> None:
    unknown = UnknownGameSearchTargetError("Unknown game target")
    limit = SearchPlanLimitExceededError("Search plan limit exceeded")

    assert isinstance(unknown, SearchPlanGenerationError)
    assert isinstance(limit, SearchPlanGenerationError)
    assert type(unknown) is not type(limit)
    assert str(unknown) == "Unknown game target"
    assert str(limit) == "Search plan limit exceeded"
    assert not hasattr(unknown, "plan")
    assert not hasattr(limit, "catalog")
    assert vars(unknown) == {}
    assert vars(limit) == {}


def test_search_plan_generator_interface_is_abstract_and_synchronous() -> None:
    with pytest.raises(TypeError):
        ISearchPlanGenerator()

    assert inspect.isabstract(ISearchPlanGenerator)
    assert not inspect.iscoroutinefunction(ISearchPlanGenerator.generate)


def test_synchronous_search_plan_generator_fake_implements_contract() -> None:
    expected = _result()

    class FakeSearchPlanGenerator(ISearchPlanGenerator):
        def generate(
            self,
            request: SearchPlanGenerationRequest,
        ) -> SearchPlanGenerationResult:
            assert isinstance(request, SearchPlanGenerationRequest)
            return expected

    generator = FakeSearchPlanGenerator()

    assert generator.generate(_request()) is expected
    assert not inspect.iscoroutinefunction(generator.generate)


def test_search_plan_generator_interface_has_no_extra_public_methods() -> None:
    public_methods = {
        name
        for name, member in inspect.getmembers(
            ISearchPlanGenerator,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }

    assert public_methods == {"generate"}
