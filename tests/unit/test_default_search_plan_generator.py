"""Tests for deterministic canonical search-plan generation."""

import inspect
from dataclasses import FrozenInstanceError

import pytest

from application.interfaces.candidate_search import SearchQuery
from application.interfaces.search_orchestrator import SearchPlan
from application.interfaces.search_plan_generator import (
    GameSearchTarget,
    SearchPlanGenerationError,
    SearchPlanGenerationRequest,
    SearchPlanGenerationStrategy,
    SearchPlanLimitExceededError,
    UnknownGameSearchTargetError,
)
from application.use_cases.default_search_plan_generator import (
    DefaultSearchPlanGenerator,
)
from domain.entities.detected_game import Platform
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.interfaces.game_catalog import IGameCatalog


def _entry(
    canonical_name: str = "Grand Theft Auto V",
    platform: Platform = Platform.PS4,
    aliases: tuple[str, ...] = ("GTA V", "GTA 5"),
) -> GameCatalogEntry:
    return GameCatalogEntry(canonical_name, platform, aliases)


class FakeGameCatalog(IGameCatalog):
    def __init__(self, entries: object) -> None:
        self.entries = entries
        self.calls = 0

    def list_games(self) -> tuple[GameCatalogEntry, ...]:
        self.calls += 1
        return self.entries  # type: ignore[return-value]


def _generator(
    entries: object = (_entry(),),
) -> tuple[DefaultSearchPlanGenerator, FakeGameCatalog]:
    catalog = FakeGameCatalog(entries)
    return DefaultSearchPlanGenerator(catalog), catalog


def _request(
    *,
    targets: object = (GameSearchTarget("Grand Theft Auto V", Platform.PS4),),
    latitude: object = 40.4168,
    longitude: object = -3.7038,
    max_results: object = 20,
    max_queries: object = 10,
    strategy: object = SearchPlanGenerationStrategy.CANONICAL_ONLY,
) -> SearchPlanGenerationRequest:
    return SearchPlanGenerationRequest(
        targets=targets,  # type: ignore[arg-type]
        latitude=latitude,  # type: ignore[arg-type]
        longitude=longitude,  # type: ignore[arg-type]
        max_results=max_results,  # type: ignore[arg-type]
        max_queries=max_queries,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
    )


def test_generator_requires_game_catalog_dependency() -> None:
    catalog = FakeGameCatalog((_entry(),))

    generator = DefaultSearchPlanGenerator(catalog)

    assert generator.game_catalog is catalog
    with pytest.raises(TypeError, match="game_catalog"):
        DefaultSearchPlanGenerator(object())  # type: ignore[arg-type]


def test_generator_has_only_synchronous_generate_as_public_operation() -> None:
    generator, _ = _generator()

    assert not inspect.iscoroutinefunction(generator.generate)
    assert {
        name
        for name, member in inspect.getmembers(
            DefaultSearchPlanGenerator,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    } == {"generate"}


def test_catalog_is_read_once_per_generation() -> None:
    generator, catalog = _generator()

    generator.generate(_request())

    assert catalog.calls == 1


def test_generate_rejects_invalid_request_without_reading_catalog() -> None:
    generator, catalog = _generator()

    with pytest.raises(TypeError, match="request"):
        generator.generate(object())  # type: ignore[arg-type]

    assert catalog.calls == 0


@pytest.mark.parametrize("catalog_value", [[], {}, None, "invalid", object()])
def test_non_tuple_catalog_result_is_rejected(catalog_value: object) -> None:
    generator, catalog = _generator(catalog_value)

    with pytest.raises(SearchPlanGenerationError, match="tuple"):
        generator.generate(_request())

    assert catalog.calls == 1


def test_non_catalog_entry_is_rejected_before_partial_generation() -> None:
    generator, _ = _generator((_entry("Before"), object(), _entry("After")))

    with pytest.raises(SearchPlanGenerationError, match="index 1"):
        generator.generate(
            _request(
                targets=[
                    GameSearchTarget("Before", Platform.PS4),
                    GameSearchTarget("After", Platform.PS4),
                ]
            )
        )


def test_empty_catalog_with_empty_targets_returns_empty_plan() -> None:
    generator, catalog = _generator(())

    result = generator.generate(_request(targets=[]))

    assert result.plan is not None
    assert result.plan.queries == ()
    assert result.targets_received == 0
    assert result.queries_generated == 0
    assert result.duplicate_queries_removed == 0
    assert catalog.calls == 1


def test_empty_catalog_with_target_raises_unknown_target_error() -> None:
    generator, _ = _generator(())

    with pytest.raises(
        UnknownGameSearchTargetError,
        match="Grand Theft Auto V.*PS4",
    ):
        generator.generate(_request())


@pytest.mark.parametrize(
    "duplicate_name",
    [
        "Grand Theft Auto V",
        "grand theft auto v",
        "  GRAND   THEFT AUTO V  ",
    ],
)
def test_duplicate_catalog_identity_is_rejected(duplicate_name: str) -> None:
    generator, _ = _generator((_entry(), _entry(duplicate_name)))

    with pytest.raises(SearchPlanGenerationError, match="duplicate identity"):
        generator.generate(_request())


def test_same_catalog_name_on_different_platforms_is_allowed() -> None:
    generator, _ = _generator(
        (
            _entry("Grand Theft Auto V", Platform.PS4),
            _entry("Grand Theft Auto V", Platform.PS5),
        )
    )

    result = generator.generate(
        _request(
            targets=[
                GameSearchTarget("Grand Theft Auto V", Platform.PS4),
                GameSearchTarget("Grand Theft Auto V", Platform.PS5),
            ]
        )
    )

    assert [query.keywords for query in result.plan.queries] == [
        "Grand Theft Auto V PS4",
        "Grand Theft Auto V PS5",
    ]


def test_catalog_entries_are_not_modified() -> None:
    entries = (_entry("  Grand   Theft Auto V  "),)
    original_entry = entries[0]
    generator, _ = _generator(entries)

    generator.generate(_request())

    assert entries == (original_entry,)
    assert entries[0] is original_entry
    assert entries[0].detection_aliases == ("GTA V", "GTA 5")


def test_each_generation_reads_catalog_and_has_no_residual_state() -> None:
    first_entry = _entry("Grand Theft Auto V")
    second_entry = _entry("Red Dead Redemption 2")
    catalog = FakeGameCatalog((first_entry,))
    generator = DefaultSearchPlanGenerator(catalog)

    first_result = generator.generate(_request())
    catalog.entries = (second_entry,)
    second_result = generator.generate(
        _request(
            targets=[
                GameSearchTarget("Red Dead Redemption 2", Platform.PS4),
            ]
        )
    )

    assert catalog.calls == 2
    assert first_result.plan.queries[0].keywords == "Grand Theft Auto V PS4"
    assert second_result.plan.queries[0].keywords == "Red Dead Redemption 2 PS4"


@pytest.mark.parametrize(
    "target",
    [
        GameSearchTarget("grand theft auto v", Platform.PS4),
        GameSearchTarget("  Grand   Theft Auto V  ", Platform.PS4),
    ],
)
def test_target_identity_allows_case_and_space_differences(
    target: GameSearchTarget,
) -> None:
    generator, _ = _generator((_entry("Grand Theft Auto V", Platform.PS4),))

    result = generator.generate(_request(targets=[target]))

    assert result.plan.queries[0].keywords == "Grand Theft Auto V PS4"


def test_target_platform_mismatch_is_unknown() -> None:
    generator, _ = _generator((_entry("Grand Theft Auto V", Platform.PS4),))

    with pytest.raises(UnknownGameSearchTargetError, match="PS5"):
        generator.generate(
            _request(
                targets=[
                    GameSearchTarget("Grand Theft Auto V", Platform.PS5),
                ]
            )
        )


@pytest.mark.parametrize(
    "target_name",
    ["GTA V", "GTA 5", "grand theft auto"],
)
def test_aliases_and_fuzzy_names_do_not_resolve(
    target_name: str,
) -> None:
    generator, _ = _generator((_entry(),))

    with pytest.raises(UnknownGameSearchTargetError):
        generator.generate(
            _request(
                targets=[GameSearchTarget(target_name, Platform.PS4)],
            )
        )


@pytest.mark.parametrize(
    ("catalog_name", "target_name"),
    [
        ("Ragnarök", "Ragnarok"),
        ("Game: One", "Game One"),
        ("Game II", "Game 2"),
    ],
)
def test_identity_does_not_transform_accents_punctuation_or_numbers(
    catalog_name: str,
    target_name: str,
) -> None:
    generator, _ = _generator((_entry(catalog_name),))

    with pytest.raises(UnknownGameSearchTargetError):
        generator.generate(
            _request(
                targets=[GameSearchTarget(target_name, Platform.PS4)],
            )
        )


def test_all_targets_are_resolved_before_any_plan_is_returned() -> None:
    generator, _ = _generator(
        (
            _entry("Grand Theft Auto V"),
            _entry("Red Dead Redemption 2"),
        )
    )

    with pytest.raises(UnknownGameSearchTargetError):
        generator.generate(
            _request(
                targets=[
                    GameSearchTarget("Grand Theft Auto V", Platform.PS4),
                    GameSearchTarget("Missing Game", Platform.PS4),
                ]
            )
        )


def test_one_target_generates_canonical_query_from_catalog_entry() -> None:
    generator, _ = _generator((_entry("  Grand   Theft Auto V  "),))

    result = generator.generate(_request())

    assert result.plan.queries == (
        SearchQuery("Grand Theft Auto V PS4", 40.4168, -3.7038, 20),
    )


def test_generation_preserves_readable_catalog_case_punctuation_accents_and_numbers() -> None:
    entry = _entry("Pokémon:   Stadium II", Platform.SWITCH)
    generator, _ = _generator((entry,))

    result = generator.generate(
        _request(
            targets=[
                GameSearchTarget("pokémon: stadium ii", Platform.SWITCH),
            ]
        )
    )

    assert result.plan.queries[0].keywords == "Pokémon: Stadium II Nintendo Switch"


def test_generation_preserves_request_location_and_max_results() -> None:
    generator, _ = _generator()

    result = generator.generate(
        _request(latitude=90, longitude=-180, max_results=321)
    )
    query = result.plan.queries[0]

    assert (query.latitude, query.longitude, query.max_results) == (90, -180, 321)


def test_generation_does_not_modify_request_or_targets() -> None:
    target = GameSearchTarget("  Grand   Theft Auto V  ", Platform.PS4)
    request = _request(targets=[target])

    generator, _ = _generator()
    generator.generate(request)

    assert request.targets == (target,)
    assert request.targets[0] is target
    with pytest.raises(FrozenInstanceError):
        request.targets = ()  # type: ignore[misc]


def test_external_target_list_is_not_aliased_by_generation() -> None:
    target = GameSearchTarget("Grand Theft Auto V", Platform.PS4)
    external_targets = [target]
    request = _request(targets=external_targets)
    external_targets.clear()
    generator, _ = _generator()

    result = generator.generate(request)

    assert request.targets == (target,)
    assert result.queries_generated == 1


def test_duplicate_target_generates_one_query_and_correct_counters() -> None:
    target = GameSearchTarget("Grand Theft Auto V", Platform.PS4)
    generator, _ = _generator()

    result = generator.generate(_request(targets=[target, target, target]))

    assert result.targets_received == 3
    assert result.queries_generated == 1
    assert result.duplicate_queries_removed == 2
    assert len(result.plan.queries) == 1


def test_duplicates_by_case_and_spaces_preserve_first_query() -> None:
    generator, _ = _generator((_entry("Grand Theft Auto V"),))

    result = generator.generate(
        _request(
            targets=[
                GameSearchTarget("  GRAND   THEFT AUTO V ", Platform.PS4),
                GameSearchTarget("Grand Theft Auto V", Platform.PS4),
            ]
        )
    )

    assert result.plan.queries == (
        SearchQuery("Grand Theft Auto V PS4", 40.4168, -3.7038, 20),
    )
    assert result.duplicate_queries_removed == 1


def test_unique_query_order_follows_target_order() -> None:
    entries = (
        _entry("Grand Theft Auto V"),
        _entry("Red Dead Redemption 2"),
        _entry("FIFA 24"),
    )
    generator, _ = _generator(entries)

    result = generator.generate(
        _request(
            targets=[
                GameSearchTarget("FIFA 24", Platform.PS4),
                GameSearchTarget("Grand Theft Auto V", Platform.PS4),
                GameSearchTarget("Red Dead Redemption 2", Platform.PS4),
            ]
        )
    )

    assert [query.keywords for query in result.plan.queries] == [
        "FIFA 24 PS4",
        "Grand Theft Auto V PS4",
        "Red Dead Redemption 2 PS4",
    ]


def test_query_key_includes_coordinates_and_max_results() -> None:
    generator, _ = _generator()
    first = SearchQuery("GTA V PS4", 40.4168, -3.7038, 20)
    different_location = SearchQuery("GTA V PS4", 41.0, -3.7038, 20)
    different_limit = SearchQuery("GTA V PS4", 40.4168, -3.7038, 21)

    assert generator._query_key(first) != generator._query_key(different_location)
    assert generator._query_key(first) != generator._query_key(different_limit)


def test_query_key_normalizes_only_case_and_spaces() -> None:
    generator, _ = _generator()
    first = SearchQuery("GTA   V PS4", 40.4168, -3.7038, 20)
    equivalent = SearchQuery("  gta v ps4  ", 40.4168, -3.7038, 20)

    assert generator._query_key(first) == generator._query_key(equivalent)


def test_search_plan_and_queries_are_tuples() -> None:
    generator, _ = _generator()

    result = generator.generate(_request())

    assert isinstance(result.plan, SearchPlan)
    assert isinstance(result.plan.queries, tuple)


def test_empty_targets_are_within_any_positive_limit() -> None:
    generator, _ = _generator(())

    result = generator.generate(_request(targets=[], max_queries=1))

    assert result.plan.queries == ()


def test_exact_max_queries_limit_is_accepted() -> None:
    generator, _ = _generator(
        (
            _entry("Grand Theft Auto V"),
            _entry("Red Dead Redemption 2"),
        )
    )

    result = generator.generate(
        _request(
            targets=[
                GameSearchTarget("Grand Theft Auto V", Platform.PS4),
                GameSearchTarget("Red Dead Redemption 2", Platform.PS4),
            ],
            max_queries=2,
        )
    )

    assert result.queries_generated == 2


def test_limit_is_applied_after_deduplication() -> None:
    target = GameSearchTarget("Grand Theft Auto V", Platform.PS4)
    generator, _ = _generator()

    result = generator.generate(
        _request(targets=[target, target, target], max_queries=1)
    )

    assert result.queries_generated == 1
    assert result.duplicate_queries_removed == 2


def test_exceeding_limit_raises_without_truncating_or_partial_result() -> None:
    generator, _ = _generator(
        (
            _entry("Grand Theft Auto V"),
            _entry("Red Dead Redemption 2"),
        )
    )

    with pytest.raises(
        SearchPlanLimitExceededError,
        match="limit=1.*unique_queries=2",
    ) as error:
        generator.generate(
            _request(
                targets=[
                    GameSearchTarget("Grand Theft Auto V", Platform.PS4),
                    GameSearchTarget("Red Dead Redemption 2", Platform.PS4),
                ],
                max_queries=1,
            )
        )

    assert not hasattr(error.value, "plan")
    assert not hasattr(error.value, "queries")


def test_generation_is_independent_of_previous_limit() -> None:
    generator, catalog = _generator(
        (
            _entry("Grand Theft Auto V"),
            _entry("Red Dead Redemption 2"),
        )
    )

    with pytest.raises(SearchPlanLimitExceededError):
        generator.generate(
            _request(
                targets=[
                    GameSearchTarget("Grand Theft Auto V", Platform.PS4),
                    GameSearchTarget("Red Dead Redemption 2", Platform.PS4),
                ],
                max_queries=1,
            )
        )

    result = generator.generate(
        _request(
            targets=[
                GameSearchTarget("Grand Theft Auto V", Platform.PS4),
            ],
            max_queries=1,
        )
    )

    assert result.queries_generated == 1
    assert catalog.calls == 2


def test_only_canonical_strategy_is_supported() -> None:
    generator, _ = _generator()

    result = generator.generate(
        _request(strategy=SearchPlanGenerationStrategy.CANONICAL_ONLY)
    )

    assert result.plan.queries[0].keywords == "Grand Theft Auto V PS4"


def test_unsupported_strategy_is_rejected_without_fallback() -> None:
    generator, catalog = _generator()
    request = _request()
    object.__setattr__(request, "strategy", object())

    with pytest.raises(SearchPlanGenerationError, match="strategy"):
        generator.generate(request)

    assert catalog.calls == 0


def test_generation_is_deterministic_without_timestamps_or_orchestration() -> None:
    generator, _ = _generator()
    request = _request()

    first = generator.generate(request)
    second = generator.generate(request)

    assert first == second
    assert not hasattr(first, "created_at")
    assert not hasattr(first, "processing_time")


def test_two_generators_with_same_catalog_are_equivalent() -> None:
    entries = (_entry(),)
    first_generator, _ = _generator(entries)
    second_generator, _ = _generator(entries)

    assert first_generator.generate(_request()) == second_generator.generate(
        _request()
    )
