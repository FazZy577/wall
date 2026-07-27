"""Sequential and deterministic search orchestration use case."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from application.interfaces.candidate_search import (
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
    CandidateItemFailureRecord,
    CandidateRoutingFailure,
    CandidateRoutingFailureKind,
    ISearchOrchestrator,
    SearchOrchestrationResult,
    SearchPlan,
    SearchQueryFailure,
)
from domain.entities.candidate_listing import CandidateListing
from domain.interfaces.game_detector import IGameDetector, ListingText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SearchQueryKey:
    normalized_keywords: str
    latitude: float
    longitude: float
    max_results: int


class DefaultSearchOrchestrator(ISearchOrchestrator):
    """Coordinate candidate search, detection, and existing scanner use cases."""

    def __init__(
        self,
        candidate_search: ICandidateSearch,
        game_detector: IGameDetector,
        opportunity_scanner: IOpportunityScanner,
        lot_opportunity_scanner: ILotOpportunityScanner,
    ) -> None:
        self.candidate_search = candidate_search
        self.game_detector = game_detector
        self.opportunity_scanner = opportunity_scanner
        self.lot_opportunity_scanner = lot_opportunity_scanner

    async def execute(self, plan: SearchPlan) -> SearchOrchestrationResult:
        """Execute one plan sequentially with execution-local state."""
        if not isinstance(plan, SearchPlan):
            raise TypeError("plan must be SearchPlan")

        start_time = time.perf_counter()
        logger.info("Starting search plan with %d queries", len(plan.queries))

        unique_queries, duplicate_queries = self._deduplicate_queries(plan)
        candidates_received: list[CandidateListing] = []
        query_failures: list[SearchQueryFailure] = []
        item_failures: list[CandidateItemFailureRecord] = []
        total_items_received = 0

        for query_index, query in unique_queries:
            logger.info("Executing candidate query at index %d", query_index)
            try:
                search_result = await self.candidate_search.search_candidates(query)
            except Exception as error:
                query_failures.append(
                    self._query_failure(query, query_index, error)
                )
                logger.warning(
                    "Candidate query failed at index %d: type=%s",
                    query_index,
                    type(error).__name__,
                )
                continue

            if not isinstance(search_result, CandidateSearchResult):
                query_failures.append(
                    SearchQueryFailure(
                        query=query,
                        query_index=query_index,
                        reason="Candidate search failed",
                        error_type="TypeError",
                        error_message=(
                            "candidate search returned "
                            f"{type(search_result).__name__}, expected "
                            "CandidateSearchResult"
                        ),
                    )
                )
                logger.warning(
                    "Candidate query returned an invalid result at index %d: type=%s",
                    query_index,
                    type(search_result).__name__,
                )
                continue

            if search_result.query != query:
                query_failures.append(
                    SearchQueryFailure(
                        query=query,
                        query_index=query_index,
                        reason="Candidate search failed",
                        error_type="ValueError",
                        error_message="candidate search result query does not match",
                    )
                )
                logger.warning(
                    "Candidate query returned mismatched context at index %d",
                    query_index,
                )
                continue

            total_items_received += search_result.total_items_received
            candidates_received.extend(search_result.candidates)
            item_failures.extend(
                CandidateItemFailureRecord(
                    query=query,
                    query_index=query_index,
                    failure=failure,
                )
                for failure in search_result.failures
            )

        unique_candidates, duplicate_candidates = self._deduplicate_candidates(
            candidates_received
        )
        logger.info(
            "Candidate search produced %d unique candidates",
            len(unique_candidates),
        )

        individual_candidates: list[DetectedCandidate] = []
        lot_candidates: list[DetectedCandidate] = []
        routing_failures: list[CandidateRoutingFailure] = []
        undetected_candidates = 0

        for listing in unique_candidates:
            try:
                detected_games = self.game_detector.detect_games(
                    ListingText(
                        title=listing.title,
                        description=listing.description,
                    )
                )
                detected_candidate = DetectedCandidate(
                    listing=listing,
                    detected_games=tuple(detected_games),
                )
            except Exception as error:
                routing_failures.append(
                    self._routing_failure(
                        listing_id=listing.listing_id,
                        kind=CandidateRoutingFailureKind.GAME_DETECTION_ERROR,
                        reason="Game detection failed",
                        error=error,
                    )
                )
                undetected_candidates += 1
                logger.warning(
                    "Game detection failed for candidate: type=%s",
                    type(error).__name__,
                )
                continue

            if not detected_candidate.detected_games:
                routing_failures.append(
                    CandidateRoutingFailure(
                        listing_id=listing.listing_id,
                        kind=CandidateRoutingFailureKind.NO_GAME_DETECTED,
                        reason="No game detected",
                        error_type=None,
                        error_message=None,
                    )
                )
                undetected_candidates += 1
            elif len(detected_candidate.detected_games) == 1:
                individual_candidates.append(detected_candidate)
            else:
                lot_candidates.append(detected_candidate)

        individual_result = await self._scan_individual_candidates(
            individual_candidates,
            routing_failures,
        )
        lot_results = await self._scan_lot_candidates(
            lot_candidates,
            routing_failures,
        )

        processing_time = time.perf_counter() - start_time
        logger.info(
            "Search plan completed with %d unique candidates in %.3f seconds",
            len(unique_candidates),
            processing_time,
        )
        return SearchOrchestrationResult(
            individual_result=individual_result,
            lot_results=tuple(lot_results),
            query_failures=tuple(query_failures),
            item_failures=tuple(item_failures),
            routing_failures=tuple(routing_failures),
            total_queries=len(plan.queries),
            executed_queries=len(unique_queries),
            duplicate_queries=duplicate_queries,
            total_items_received=total_items_received,
            valid_candidates_received=len(candidates_received),
            duplicate_candidates=duplicate_candidates,
            unique_candidates=len(unique_candidates),
            individual_candidates=len(individual_candidates),
            lot_candidates=len(lot_candidates),
            undetected_candidates=undetected_candidates,
            processing_time=processing_time,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _query_key(query: SearchQuery) -> _SearchQueryKey:
        normalized_keywords = " ".join(query.keywords.strip().casefold().split())
        return _SearchQueryKey(
            normalized_keywords,
            query.latitude,
            query.longitude,
            query.max_results,
        )

    @classmethod
    def _deduplicate_queries(
        cls,
        plan: SearchPlan,
    ) -> tuple[list[tuple[int, SearchQuery]], int]:
        unique_queries: list[tuple[int, SearchQuery]] = []
        seen: set[_SearchQueryKey] = set()
        duplicate_queries = 0

        for query_index, query in enumerate(plan.queries):
            key = cls._query_key(query)
            if key in seen:
                duplicate_queries += 1
                logger.info("Skipping duplicate candidate query at index %d", query_index)
                continue
            seen.add(key)
            unique_queries.append((query_index, query))

        return unique_queries, duplicate_queries

    @staticmethod
    def _deduplicate_candidates(
        candidates: list[CandidateListing],
    ) -> tuple[list[CandidateListing], int]:
        unique_candidates: list[CandidateListing] = []
        seen_listing_ids: set[str] = set()
        duplicate_candidates = 0

        for candidate in candidates:
            if candidate.listing_id in seen_listing_ids:
                duplicate_candidates += 1
                continue
            seen_listing_ids.add(candidate.listing_id)
            unique_candidates.append(candidate)

        return unique_candidates, duplicate_candidates

    async def _scan_individual_candidates(
        self,
        candidates: list[DetectedCandidate],
        routing_failures: list[CandidateRoutingFailure],
    ) -> ScanResult | None:
        if not candidates:
            return None

        try:
            return await self.opportunity_scanner.scan_detected_multiple(
                tuple(candidates)
            )
        except Exception as error:
            routing_failures.append(
                self._routing_failure(
                    listing_id=None,
                    kind=CandidateRoutingFailureKind.INDIVIDUAL_SCANNER_ERROR,
                    reason="Individual scanner failed",
                    error=error,
                )
            )
            logger.warning(
                "Individual scanner batch failed: type=%s",
                type(error).__name__,
            )
            return None

    async def _scan_lot_candidates(
        self,
        candidates: list[DetectedCandidate],
        routing_failures: list[CandidateRoutingFailure],
    ) -> list[LotScanResult]:
        results: list[LotScanResult] = []
        for candidate in candidates:
            try:
                result = await self.lot_opportunity_scanner.scan_detected_lot(
                    candidate
                )
            except Exception as error:
                routing_failures.append(
                    self._routing_failure(
                        listing_id=candidate.listing.listing_id,
                        kind=CandidateRoutingFailureKind.LOT_SCANNER_ERROR,
                        reason="Lot scanner failed",
                        error=error,
                    )
                )
                logger.warning(
                    "Lot scanner failed for candidate: type=%s",
                    type(error).__name__,
                )
                continue
            results.append(result)
        return results

    @classmethod
    def _query_failure(
        cls,
        query: SearchQuery,
        query_index: int,
        error: Exception,
    ) -> SearchQueryFailure:
        return SearchQueryFailure(
            query=query,
            query_index=query_index,
            reason="Candidate search failed",
            error_type=type(error).__name__,
            error_message=cls._safe_error_message(error),
        )

    @classmethod
    def _routing_failure(
        cls,
        *,
        listing_id: str | None,
        kind: CandidateRoutingFailureKind,
        reason: str,
        error: Exception,
    ) -> CandidateRoutingFailure:
        return CandidateRoutingFailure(
            listing_id=listing_id,
            kind=kind,
            reason=reason,
            error_type=type(error).__name__,
            error_message=cls._safe_error_message(error),
        )

    @staticmethod
    def _safe_error_message(error: Exception) -> str | None:
        try:
            message = str(error)
        except Exception:
            return None
        return message or None
