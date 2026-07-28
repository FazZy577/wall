"""Deterministic canonical search-plan generation use case."""

from dataclasses import dataclass

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
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.interfaces.game_catalog import IGameCatalog


@dataclass(frozen=True)
class _CatalogIdentity:
    canonical_name: str
    platform: Platform


@dataclass(frozen=True)
class _SearchQueryKey:
    normalized_keywords: str
    latitude: float
    longitude: float
    max_results: int


class DefaultSearchPlanGenerator(ISearchPlanGenerator):
    """Generate one deterministic plan using canonical catalog names only."""

    def __init__(self, game_catalog: IGameCatalog) -> None:
        if not isinstance(game_catalog, IGameCatalog):
            raise TypeError("game_catalog must be IGameCatalog")
        self.game_catalog = game_catalog

    def generate(
        self,
        request: SearchPlanGenerationRequest,
    ) -> SearchPlanGenerationResult:
        """Resolve every target and return an atomic canonical query plan."""
        if not isinstance(request, SearchPlanGenerationRequest):
            raise TypeError("request must be SearchPlanGenerationRequest")
        if request.strategy is not SearchPlanGenerationStrategy.CANONICAL_ONLY:
            raise SearchPlanGenerationError(
                f"Unsupported search plan generation strategy: {request.strategy!r}"
            )

        catalog_entries = self.game_catalog.list_games()
        catalog_index = self._build_catalog_index(catalog_entries)
        resolved_entries = [
            self._resolve_target(target, catalog_index)
            for target in request.targets
        ]

        unique_queries: list[SearchQuery] = []
        seen_queries: set[_SearchQueryKey] = set()
        for entry in resolved_entries:
            query = self._build_query(entry, request)
            query_key = self._query_key(query)
            if query_key in seen_queries:
                continue
            seen_queries.add(query_key)
            unique_queries.append(query)

        if len(unique_queries) > request.max_queries:
            raise SearchPlanLimitExceededError(
                "Search plan limit exceeded: "
                f"limit={request.max_queries}, "
                f"unique_queries={len(unique_queries)}"
            )

        plan = SearchPlan(tuple(unique_queries))
        return SearchPlanGenerationResult(
            plan=plan,
            targets_received=len(request.targets),
            queries_generated=len(unique_queries),
            duplicate_queries_removed=len(request.targets) - len(unique_queries),
        )

    @staticmethod
    def _build_catalog_index(
        catalog_entries: object,
    ) -> dict[_CatalogIdentity, GameCatalogEntry]:
        if not isinstance(catalog_entries, tuple):
            raise SearchPlanGenerationError(
                "game catalog must return tuple[GameCatalogEntry, ...]"
            )

        catalog_index: dict[_CatalogIdentity, GameCatalogEntry] = {}
        for index, entry in enumerate(catalog_entries):
            if not isinstance(entry, GameCatalogEntry):
                raise SearchPlanGenerationError(
                    f"game catalog entry at index {index} must be GameCatalogEntry"
                )
            identity = _CatalogIdentity(
                canonical_name=DefaultSearchPlanGenerator._normalize_name(
                    entry.canonical_name
                ),
                platform=entry.platform,
            )
            if identity in catalog_index:
                raise SearchPlanGenerationError(
                    "game catalog contains duplicate identity: "
                    f"{entry.canonical_name!r} / {entry.platform.value}"
                )
            catalog_index[identity] = entry
        return catalog_index

    @staticmethod
    def _resolve_target(
        target: GameSearchTarget,
        catalog_index: dict[_CatalogIdentity, GameCatalogEntry],
    ) -> GameCatalogEntry:
        identity = _CatalogIdentity(
            canonical_name=DefaultSearchPlanGenerator._normalize_name(
                target.canonical_name
            ),
            platform=target.platform,
        )
        try:
            return catalog_index[identity]
        except KeyError as error:
            raise UnknownGameSearchTargetError(
                "Unknown game search target: "
                f"{target.canonical_name!r} / {target.platform.value}"
            ) from error

    @staticmethod
    def _build_query(
        entry: GameCatalogEntry,
        request: SearchPlanGenerationRequest,
    ) -> SearchQuery:
        keywords = DefaultSearchPlanGenerator._normalize_spaces(
            f"{entry.canonical_name} {entry.platform.value}"
        )
        return SearchQuery(
            keywords=keywords,
            latitude=request.latitude,
            longitude=request.longitude,
            max_results=request.max_results,
        )

    @staticmethod
    def _query_key(query: SearchQuery) -> _SearchQueryKey:
        return _SearchQueryKey(
            normalized_keywords=DefaultSearchPlanGenerator._normalize_name(
                query.keywords
            ),
            latitude=query.latitude,
            longitude=query.longitude,
            max_results=query.max_results,
        )

    @staticmethod
    def _normalize_name(value: str) -> str:
        return DefaultSearchPlanGenerator._normalize_spaces(value).casefold()

    @staticmethod
    def _normalize_spaces(value: str) -> str:
        return " ".join(value.strip().split())
