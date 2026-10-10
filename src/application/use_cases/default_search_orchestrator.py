"""Sequential and deterministic search orchestration use case."""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from application.interfaces.candidate_search import (
    CandidateSearchResult,
    ICandidateSearch,
    QueryScan,
    SearchQuery,
)
from application.interfaces.catalog_discovery_recorder import (
    ICatalogDiscoveryRecorder,
    NullCatalogDiscoveryRecorder,
)
from application.interfaces.detected_candidate import DetectedCandidate
from application.interfaces.game_metadata import IUnknownGameResolver, MetadataDeferred
from application.interfaces.listing_observation_recorder import (
    IdentificationStatus,
    IListingObservationRecorder,
    ListingObservation,
    NullListingObservationRecorder,
)
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
    CandidateRoutingRecord,
    ISearchOrchestrator,
    SearchOrchestrationResult,
    SearchPlan,
    SearchQueryFailure,
)
from domain.entities.candidate_classification import (
    CandidateClassification,
    CandidateClassificationReason,
    CandidateDisposition,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame
from domain.entities.search_coverage import (
    MarketplaceCategory,
    MarketplaceSearchFailure,
    SearchCoverage,
    SearchStopReason,
)
from domain.interfaces.candidate_eligibility_policy import (
    ICandidateEligibilityPolicy,
)
from domain.interfaces.game_detector import IGameDetector, ListingText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SearchQueryKey:
    normalized_keywords: str
    latitude: float
    longitude: float
    max_results: int
    category: MarketplaceCategory | None


class DefaultSearchOrchestrator(ISearchOrchestrator):
    """Coordinate candidate search, detection, and existing scanner use cases."""

    def __init__(
        self,
        candidate_search: ICandidateSearch,
        game_detector: IGameDetector,
        candidate_eligibility_policy: ICandidateEligibilityPolicy,
        opportunity_scanner: IOpportunityScanner,
        lot_opportunity_scanner: ILotOpportunityScanner,
        catalog_discovery_recorder: ICatalogDiscoveryRecorder | None = None,
        observation_recorder: IListingObservationRecorder | None = None,
        unknown_game_resolver: IUnknownGameResolver | None = None,
    ) -> None:
        self.unknown_game_resolver = unknown_game_resolver
        self.candidate_search = candidate_search
        self.observation_recorder = (
            observation_recorder if observation_recorder is not None
            else NullListingObservationRecorder()
        )
        self.game_detector = game_detector
        self.candidate_eligibility_policy = candidate_eligibility_policy
        self.opportunity_scanner = opportunity_scanner
        self.lot_opportunity_scanner = lot_opportunity_scanner
        self.catalog_discovery_recorder = (
            NullCatalogDiscoveryRecorder()
            if catalog_discovery_recorder is None
            else catalog_discovery_recorder
        )

    async def execute(self, plan: SearchPlan) -> SearchOrchestrationResult:
        """Execute one plan sequentially with execution-local state."""
        if not isinstance(plan, SearchPlan):
            raise TypeError("plan must be SearchPlan")

        start_time = time.perf_counter()
        run_id = uuid.uuid4().hex
        query_scans: list[QueryScan] = []
        routing_failures: list[CandidateRoutingFailure] = []
        if self.unknown_game_resolver is not None:
            try:
                maintenance_failures = await self.unknown_game_resolver.begin_run()
                routing_failures.extend(CandidateRoutingFailure(
                    listing_id=listing_id, kind=CandidateRoutingFailureKind.METADATA_RESOLUTION_ERROR,
                    reason="Scheduled metadata refresh failed; stored observations remain pending",
                    error_type="MetadataMaintenanceError", error_message="Metadata refresh unavailable",
                ) for listing_id in maintenance_failures)
            except Exception as error:
                routing_failures.append(CandidateRoutingFailure(
                    listing_id=None, kind=CandidateRoutingFailureKind.METADATA_MAINTENANCE_ERROR,
                    reason="Metadata maintenance failed; current candidate processing continues",
                    error_type=type(error).__name__, error_message="Metadata schedule unavailable",
                ))
        logger.info("Starting search plan with %d queries", len(plan.queries))

        unique_queries, duplicate_queries = self._deduplicate_queries(plan)
        candidates_received: list[CandidateListing] = []
        source_queries: dict[str, str] = {}
        query_failures: list[SearchQueryFailure] = []
        item_failures: list[CandidateItemFailureRecord] = []
        total_items_received = 0

        for query_index, query in unique_queries:
            query_started_at = datetime.now(UTC)
            logger.info("Executing candidate query at index %d", query_index)
            try:
                search_result = await self.candidate_search.search_candidates(query)
            except Exception as error:
                coverage = (
                    error.coverage if isinstance(error, MarketplaceSearchFailure)
                    else SearchCoverage(stop_reason=SearchStopReason.ERROR)
                )
                await self._record_query_scan(
                    QueryScan(run_id, query_index, query, coverage, query_started_at,
                              datetime.now(UTC), type(error).__name__),
                    query_scans, routing_failures,
                )
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
                await self._record_query_scan(
                    QueryScan(run_id, query_index, query, SearchCoverage(stop_reason=SearchStopReason.ERROR),
                              query_started_at, datetime.now(UTC), "TypeError"),
                    query_scans, routing_failures,
                )
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
                await self._record_query_scan(
                    QueryScan(run_id, query_index, query, SearchCoverage(stop_reason=SearchStopReason.ERROR),
                              query_started_at, datetime.now(UTC), "ValueError"),
                    query_scans, routing_failures,
                )
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
            await self._record_query_scan(
                QueryScan(run_id, query_index, query, search_result.coverage,
                          query_started_at, datetime.now(UTC)),
                query_scans, routing_failures,
            )
            candidates_received.extend(search_result.candidates)
            for candidate in search_result.candidates:
                source_queries.setdefault(candidate.listing_id, query.keywords)
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
        ignored_candidates: list[CandidateRoutingRecord] = []
        ambiguous_candidates: list[CandidateRoutingRecord] = []
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
                await self._record_observation(
                    listing, (), None, source_queries[listing.listing_id], routing_failures, error
                )
                logger.warning(
                    "Game detection failed for candidate: type=%s",
                    type(error).__name__,
                )
                continue

            try:
                classification = self.candidate_eligibility_policy.classify(
                    listing,
                    detected_candidate.detected_games,
                )
                if not isinstance(classification, CandidateClassification):
                    raise TypeError(
                        "candidate eligibility policy returned an invalid classification"
                    )
            except Exception as error:
                routing_failures.append(
                    self._routing_failure(
                        listing_id=listing.listing_id,
                        kind=CandidateRoutingFailureKind.CANDIDATE_CLASSIFICATION_ERROR,
                        reason="Candidate classification failed",
                        error=error,
                    )
                )
                undetected_candidates += 1
                await self._record_observation(
                    listing, detected_candidate.detected_games, None,
                    source_queries[listing.listing_id], routing_failures, error
                )
                logger.warning(
                    "Candidate classification failed: type=%s",
                    type(error).__name__,
                )
                continue

            partial_local_identity = (
                self.unknown_game_resolver is not None
                and classification.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL
                and self.unknown_game_resolver.needs_resolution(listing, detected_candidate.detected_games)
            )
            if partial_local_identity:
                # A known title can be only the prefix of a newly released sequel.
                # Provider failure must never restore that unconfirmed shorter identity.
                classification = CandidateClassification(
                    CandidateDisposition.AMBIGUOUS,
                    CandidateClassificationReason.UNCONFIRMED_IDENTITY, (),
                )
            if self.unknown_game_resolver is not None and (
                classification.reason is CandidateClassificationReason.NO_INCLUDED_GAME
                or classification.disposition is CandidateDisposition.AMBIGUOUS
            ):
                try:
                    if await self.unknown_game_resolver.resolve(listing):
                        refreshed = tuple(self.game_detector.detect_games(ListingText(listing.title, listing.description)))
                        classification = self.candidate_eligibility_policy.classify(listing, refreshed)
                        detected_candidate = DetectedCandidate(listing=listing, detected_games=refreshed)
                except Exception as error:
                    routing_failures.append(CandidateRoutingFailure(
                        listing_id=listing.listing_id,
                        kind=CandidateRoutingFailureKind.METADATA_RESOLUTION_ERROR,
                        reason="External identity resolution failed; candidate remains pending",
                        error_type=type(error).__name__,
                        error_message=("Metadata query deferred by request budget or active request"
                                       if isinstance(error, MetadataDeferred)
                                       else "Metadata provider or local registry unavailable"),
                    ))

            await self._record_observation(
                listing, detected_candidate.detected_games, classification,
                source_queries[listing.listing_id], routing_failures
            )

            if (
                classification.disposition is CandidateDisposition.IGNORED
                and classification.reason
                is CandidateClassificationReason.NO_INCLUDED_GAME
            ):
                await self._record_unrecognized_candidate(listing)

            if classification.disposition is CandidateDisposition.IGNORED:
                ignored_candidates.append(
                    CandidateRoutingRecord(
                        listing_id=listing.listing_id,
                        listing_title=listing.title,
                        disposition=classification.disposition,
                        reason=classification.reason,
                    )
                )
            elif classification.disposition is CandidateDisposition.AMBIGUOUS:
                ambiguous_candidates.append(
                    CandidateRoutingRecord(
                        listing_id=listing.listing_id,
                        listing_title=listing.title,
                        disposition=classification.disposition,
                        reason=classification.reason,
                    )
                )
            elif classification.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL:
                individual_candidates.append(
                    DetectedCandidate(
                        listing=listing,
                        detected_games=classification.included_games,
                        quantities=classification.quantities,
                    )
                )
            elif classification.disposition is CandidateDisposition.ELIGIBLE_LOT:
                lot_candidates.append(
                    DetectedCandidate(
                        listing=listing,
                        detected_games=classification.included_games,
                        quantities=classification.quantities,
                    )
                )
            else:
                raise AssertionError("unsupported candidate disposition")

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
            ignored_candidates=tuple(ignored_candidates),
            ambiguous_candidates=tuple(ambiguous_candidates),
            query_scans=tuple(query_scans),
        )

    async def _record_query_scan(
        self, scan: QueryScan, records: list[QueryScan], failures: list[CandidateRoutingFailure]
    ) -> None:
        records.append(scan)
        try:
            await self.observation_recorder.record_query_scan(scan)
        except Exception as error:
            failures.append(self._routing_failure(
                listing_id=None, kind=CandidateRoutingFailureKind.SCAN_STORAGE_ERROR,
                reason="Search coverage could not be persisted", error=error,
            ))

    async def _record_observation(
        self,
        listing: CandidateListing,
        detected_games: tuple[DetectedGame, ...],
        classification: CandidateClassification | None,
        source_query: str,
        failures: list[CandidateRoutingFailure],
        error: Exception | None = None,
    ) -> None:
        status: IdentificationStatus = "error"
        if classification is not None:
            if classification.reason is CandidateClassificationReason.NO_INCLUDED_GAME:
                status = "unknown"
            elif classification.disposition is CandidateDisposition.AMBIGUOUS:
                status = "ambiguous"
            elif classification.disposition is CandidateDisposition.IGNORED:
                status = "ignored"
            else:
                status = "resolved"
        try:
            await self.observation_recorder.record_observation(ListingObservation(
                listing_id=listing.listing_id, title=listing.title,
                description=listing.description, price=listing.price, currency=listing.currency,
                observed_at=datetime.now(UTC), status=status,
                detected_games=detected_games, classification=classification,
                error_type=type(error).__name__ if error else None, source_query=source_query,
            ))
        except Exception as storage_error:
            failures.append(self._routing_failure(
                listing_id=listing.listing_id,
                kind=CandidateRoutingFailureKind.OBSERVATION_STORAGE_ERROR,
                reason="Listing observation could not be persisted",
                error=storage_error,
            ))
            logger.warning("Listing observation storage failed: type=%s", type(storage_error).__name__)

    async def _record_unrecognized_candidate(self, listing: CandidateListing) -> None:
        try:
            await self.catalog_discovery_recorder.record_unrecognized_candidate(
                listing_id=listing.listing_id,
                original_title=listing.title,
                observed_at=datetime.now(UTC),
            )
        except Exception as error:
            logger.warning(
                "Catalog discovery recorder failed: type=%s",
                type(error).__name__,
            )

    @staticmethod
    def _query_key(query: SearchQuery) -> _SearchQueryKey:
        normalized_keywords = " ".join(query.keywords.strip().casefold().split())
        return _SearchQueryKey(
            normalized_keywords,
            query.latitude,
            query.longitude,
            query.max_results,
            query.category,
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
