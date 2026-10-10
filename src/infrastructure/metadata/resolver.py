"""Conservative external confirmation; seller text is never learned as an alias."""

from application.interfaces.game_metadata import (
    IGameMetadataProvider,
    IMetadataResolutionStore,
    IMetadataSchedule,
    IUnknownGameResolver,
    MetadataDeferred,
    MetadataUnavailable,
)
from domain.entities.candidate_classification import CandidateDisposition
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod
from domain.entities.game_record import ReleaseIdentity
from domain.interfaces.candidate_eligibility_policy import ICandidateEligibilityPolicy
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.matching.platform_lexical_matcher import PlatformLexicalMatcher
from infrastructure.metadata.query import extract_metadata_query, unsupported_metadata_listing


class VerifiedMetadataResolver(IUnknownGameResolver):
    def __init__(self, provider: IGameMetadataProvider, store: IMetadataResolutionStore,
                 detector: FuzzyGameDetector, policy: ICandidateEligibilityPolicy,
                 schedule: IMetadataSchedule | None = None, maintenance_limit: int = 5) -> None:
        self.provider = provider
        self.store = store
        self.detector = detector
        self.policy = policy
        self.matcher = PlatformLexicalMatcher()
        self.schedule = schedule
        self.maintenance_limit = maintenance_limit

    async def begin_run(self) -> tuple[str, ...]:
        if self.schedule is None:
            return ()
        self.schedule.begin_run()
        failures: list[str] = []
        for listing in self.schedule.due_listings(self.maintenance_limit):
            try:
                await self.resolve(listing)
            except Exception:
                failures.append(listing.listing_id)
        return tuple(failures)

    def needs_resolution(self, listing: CandidateListing, games: tuple[DetectedGame, ...]) -> bool:
        extracted = extract_metadata_query(listing)
        if extracted is None or len(games) != 1:
            return False
        query, _ = extracted
        game = games[0]
        return query not in {
            self.matcher.normalize_text(game.canonical_name),
            self.matcher.normalize_text(game.matched_text),
        } or game.detection_method is DetectionMethod.FUZZY_MATCH

    async def resolve(self, listing: CandidateListing) -> bool:
        extracted = extract_metadata_query(listing)
        if extracted is None:
            return False
        query, platform = extracted
        if unsupported_metadata_listing(listing):
            self.store.record_resolution(listing, query, platform, "unsupported_listing", ())
            return False
        if self.schedule is not None:
            self.schedule.remember(listing, query, platform)
        try:
            candidates = await self.provider.search(query)
        except MetadataDeferred:
            self.store.record_resolution(listing, query, platform, "deferred", ())
            raise
        except MetadataUnavailable:
            self.store.record_resolution(listing, query, platform, "provider_error", ())
            raise
        matches = tuple(candidate for candidate in candidates if (
            platform in candidate.platforms
            and query in {self.matcher.normalize_text(name) for name in (candidate.name, *candidate.aliases)}
        ))
        # Even an incompatible exact hit creates ambiguity when another hit shares its name.
        status = "not_found" if not matches else "ambiguous"
        selected = None
        if len(matches) == 1:
            candidate = matches[0]
            if candidate.content_type in {"main game", "remake", "remaster", "port"} and not candidate.edition:
                hypothetical = DetectedGame(candidate.name, query, platform, 1.0, DetectionMethod.EXACT_MATCH,
                                            ReleaseIdentity("validation", "validation", platform))
                classification = self.policy.classify(listing, (hypothetical,))
                if classification.disposition is CandidateDisposition.ELIGIBLE_INDIVIDUAL:
                    selected = candidate
                    status = "confirmed"
                else:
                    status = "unsupported_listing"
            else:
                status = "unsupported_content"
        entry = self.store.record_resolution(listing, query, platform, status, candidates, selected)
        if self.schedule is not None:
            self.schedule.resolution_status(query, "ambiguous" if selected is not None and entry is None else status)
        if entry is None:
            return False
        self.detector.refresh()
        return True
