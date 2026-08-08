"""Fuzzy game detection with deterministic local platform association."""

import re
from dataclasses import dataclass
from typing import Final

from rapidfuzz import fuzz

from domain.entities.detected_game import DetectedGame, DetectionMethod, Platform
from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.entities.game_identity import GameIdentity
from domain.interfaces.game_catalog import IGameCatalog
from domain.interfaces.game_detector import IGameDetector, ListingText
from infrastructure.matching.platform_lexical_matcher import (
    PlatformLexicalMatcher,
    PlatformMention,
)

_SEGMENT_SEPARATOR: Final[re.Pattern[str]] = re.compile(
    r"(?:\r?\n|[+,;|•·]|\s+-\s+)"
)
_COMPATIBILITY_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"(?:compatible con|compatibilidad con|funciona en|retrocompatible con)\s*$"
)


@dataclass(frozen=True)
class _GameVariantPattern:
    normalized_text: str
    pattern: re.Pattern[str]
    is_canonical: bool


@dataclass(frozen=True)
class _ExactGameCandidate:
    entry_index: int
    entry: GameCatalogEntry
    matched_text: str
    start: int
    end: int
    is_canonical: bool


@dataclass(frozen=True)
class _ExactGameMention:
    start: int
    end: int
    candidates: tuple[_ExactGameCandidate, ...]


@dataclass(frozen=True)
class _TextSegment:
    text: str
    platforms: tuple[PlatformMention, ...]


class FuzzyGameDetector(IGameDetector):
    """Detect catalog games only when a concrete platform is resolvable."""

    EXACT_MATCH_THRESHOLD = 100.0
    ALIAS_MATCH_THRESHOLD = 95.0
    FUZZY_HIGH_THRESHOLD = 90.0
    FUZZY_MEDIUM_THRESHOLD = 80.0
    MIN_CONFIDENCE_THRESHOLD = FUZZY_MEDIUM_THRESHOLD

    def __init__(self, game_catalog: IGameCatalog) -> None:
        """Initialize from one immutable snapshot of the canonical catalog."""
        if not isinstance(game_catalog, IGameCatalog):
            raise TypeError("game_catalog must be IGameCatalog")
        self.game_catalog = game_catalog
        self._catalog_entries: tuple[GameCatalogEntry, ...] = game_catalog.list_games()
        self._platform_matcher = PlatformLexicalMatcher()
        self._game_variant_patterns = self._build_game_variant_patterns()

    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        """Detect games from title and description without inventing platforms."""
        title_segments = self._build_segments(listing_text.title)
        description_segments = self._build_segments(listing_text.description)
        section_platforms = (
            self._section_platforms(title_segments),
            self._section_platforms(description_segments),
        )

        detected_games: list[DetectedGame] = []
        for section_index, segments in enumerate(
            (title_segments, description_segments)
        ):
            inherited_platform = self._inherited_platform(
                section_platforms[section_index],
                section_platforms[1 - section_index],
            )
            for segment in segments:
                detected_games.extend(
                    self._detect_in_segment(segment, inherited_platform)
                )

        return self._deduplicate_and_sort(detected_games)

    def _build_segments(self, text: str) -> tuple[_TextSegment, ...]:
        segments: list[_TextSegment] = []
        for raw_segment in _SEGMENT_SEPARATOR.split(text):
            normalized = self._normalize_text(raw_segment)
            if not normalized:
                continue
            mentions = tuple(
                mention
                for mention in self._platform_matcher.find_mentions(normalized)
                if not self._is_compatibility_mention(normalized, mention)
            )
            segments.append(_TextSegment(normalized, mentions))
        return tuple(segments)

    def _detect_in_segment(
        self,
        segment: _TextSegment,
        inherited_platform: Platform | None,
    ) -> list[DetectedGame]:
        exact_mentions = self._find_exact_mentions(segment.text)
        exact_entry_indexes = {
            candidate.entry_index
            for mention in exact_mentions
            for candidate in mention.candidates
        }
        assignments = self._associate_exact_mentions(
            exact_mentions,
            segment.platforms,
            inherited_platform,
        )

        detected: list[DetectedGame] = []
        for mention, platform in assignments:
            candidate = self._resolve_exact_candidate(mention, platform)
            if candidate is None:
                continue
            detected.append(
                DetectedGame(
                    canonical_name=candidate.entry.canonical_name,
                    matched_text=candidate.matched_text,
                    platform=platform,
                    confidence=1.0,
                    detection_method=DetectionMethod.EXACT_MATCH,
                )
            )

        fuzzy_platform = self._single_segment_platform(
            segment.platforms,
            inherited_platform,
        )
        if fuzzy_platform is None:
            return detected

        for entry_index, entry in enumerate(self._catalog_entries):
            if entry_index in exact_entry_indexes or entry.platform is not fuzzy_platform:
                continue
            fuzzy_match = self._fuzzy_match(entry_index, entry, segment.text)
            if fuzzy_match is not None:
                detected.append(fuzzy_match)
        return detected

    def _find_exact_mentions(self, text: str) -> tuple[_ExactGameMention, ...]:
        grouped: dict[tuple[int, int], dict[int, _ExactGameCandidate]] = {}
        for entry_index, entry_patterns in enumerate(self._game_variant_patterns):
            entry = self._catalog_entries[entry_index]
            for variant in entry_patterns:
                for match in variant.pattern.finditer(text):
                    span = (match.start(), match.end())
                    candidate = _ExactGameCandidate(
                        entry_index=entry_index,
                        entry=entry,
                        matched_text=variant.normalized_text,
                        start=match.start(),
                        end=match.end(),
                        is_canonical=variant.is_canonical,
                    )
                    previous = grouped.setdefault(span, {}).get(entry_index)
                    if previous is None or (
                        candidate.is_canonical and not previous.is_canonical
                    ):
                        grouped[span][entry_index] = candidate

        mentions = [
            _ExactGameMention(
                start=start,
                end=end,
                candidates=tuple(
                    candidates[index] for index in sorted(candidates)
                ),
            )
            for (start, end), candidates in grouped.items()
        ]
        selected: list[_ExactGameMention] = []
        for mention in sorted(
            mentions,
            key=lambda item: (-(item.end - item.start), item.start, item.end),
        ):
            if any(self._mentions_overlap(mention, existing) for existing in selected):
                continue
            selected.append(mention)
        return tuple(sorted(selected, key=lambda item: (item.start, item.end)))

    def _associate_exact_mentions(
        self,
        mentions: tuple[_ExactGameMention, ...],
        platform_mentions: tuple[PlatformMention, ...],
        inherited_platform: Platform | None,
    ) -> tuple[tuple[_ExactGameMention, Platform], ...]:
        if not mentions:
            return ()
        distinct_platforms = {mention.platform for mention in platform_mentions}
        if len(distinct_platforms) == 1:
            platform = next(iter(distinct_platforms))
            return tuple((mention, platform) for mention in mentions)
        if not distinct_platforms:
            if inherited_platform is None:
                return ()
            return tuple((mention, inherited_platform) for mention in mentions)
        if len(mentions) != len(platform_mentions):
            return ()
        paired_platforms = self._pair_adjacent_platforms(
            mentions,
            platform_mentions,
        )
        if paired_platforms is None:
            return ()
        return tuple(
            (game_mention, platform)
            for game_mention, platform in zip(
                mentions,
                paired_platforms,
                strict=True,
            )
        )

    @staticmethod
    def _pair_adjacent_platforms(
        game_mentions: tuple[_ExactGameMention, ...],
        platform_mentions: tuple[PlatformMention, ...],
    ) -> tuple[Platform, ...] | None:
        pairings: list[tuple[Platform, ...]] = []

        postfix = tuple(
            tuple(
                mention.platform
                for mention in platform_mentions
                if mention.start >= game.end
                and (
                    index == len(game_mentions) - 1
                    or mention.end <= game_mentions[index + 1].start
                )
            )
            for index, game in enumerate(game_mentions)
        )
        if all(len(platforms) == 1 for platforms in postfix):
            pairings.append(tuple(platforms[0] for platforms in postfix))

        prefix = tuple(
            tuple(
                mention.platform
                for mention in platform_mentions
                if mention.end <= game.start
                and (
                    index == 0
                    or mention.start >= game_mentions[index - 1].end
                )
            )
            for index, game in enumerate(game_mentions)
        )
        if all(len(platforms) == 1 for platforms in prefix):
            pairings.append(tuple(platforms[0] for platforms in prefix))

        if not pairings or any(pairing != pairings[0] for pairing in pairings[1:]):
            return None
        return pairings[0]

    @staticmethod
    def _resolve_exact_candidate(
        mention: _ExactGameMention,
        platform: Platform,
    ) -> _ExactGameCandidate | None:
        compatible = tuple(
            candidate
            for candidate in mention.candidates
            if candidate.entry.platform is platform
        )
        names = {candidate.entry.identity.canonical_name for candidate in compatible}
        if len(names) == 1:
            return next(
                (
                    candidate
                    for candidate in compatible
                    if candidate.is_canonical
                ),
                compatible[0],
            )

        canonical_names = {
            candidate.entry.identity.canonical_name
            for candidate in compatible
            if candidate.is_canonical
        }
        if len(canonical_names) != 1:
            return None
        canonical_name = next(iter(canonical_names))
        return next(
            candidate
            for candidate in compatible
            if candidate.is_canonical
            and candidate.entry.identity.canonical_name == canonical_name
        )

    def _fuzzy_match(
        self,
        entry_index: int,
        entry: GameCatalogEntry,
        text: str,
    ) -> DetectedGame | None:
        best_score = 0.0
        best_match_text = ""
        for variant in self._game_variant_patterns[entry_index]:
            score = fuzz.token_set_ratio(variant.normalized_text, text)
            if score > best_score:
                best_score = score
                best_match_text = variant.normalized_text
        if best_score < self.MIN_CONFIDENCE_THRESHOLD:
            return None
        method = (
            DetectionMethod.ALIAS_MATCH
            if best_score >= self.ALIAS_MATCH_THRESHOLD
            else DetectionMethod.FUZZY_MATCH
        )
        return DetectedGame(
            canonical_name=entry.canonical_name,
            matched_text=best_match_text,
            platform=entry.platform,
            confidence=best_score / 100.0,
            detection_method=method,
        )

    def _build_game_variant_patterns(
        self,
    ) -> tuple[tuple[_GameVariantPattern, ...], ...]:
        catalog_patterns: list[tuple[_GameVariantPattern, ...]] = []
        for entry in self._catalog_entries:
            variants = (
                (self._normalize_text(entry.canonical_name), True),
                *(
                    (self._normalize_text(alias), False)
                    for alias in entry.detection_aliases
                ),
            )
            catalog_patterns.append(
                tuple(
                    _GameVariantPattern(
                        normalized_text=normalized,
                        pattern=re.compile(
                            rf"(?<!\w){re.escape(normalized)}(?!\w)"
                        ),
                        is_canonical=is_canonical,
                    )
                    for normalized, is_canonical in variants
                )
            )
        return tuple(catalog_patterns)

    @staticmethod
    def _section_platforms(
        segments: tuple[_TextSegment, ...],
    ) -> frozenset[Platform]:
        return frozenset(
            mention.platform
            for segment in segments
            for mention in segment.platforms
        )

    @staticmethod
    def _inherited_platform(
        current_platforms: frozenset[Platform],
        other_platforms: frozenset[Platform],
    ) -> Platform | None:
        if len(current_platforms) == 1:
            return next(iter(current_platforms))
        if not current_platforms and len(other_platforms) == 1:
            return next(iter(other_platforms))
        return None

    @staticmethod
    def _single_segment_platform(
        mentions: tuple[PlatformMention, ...],
        inherited_platform: Platform | None,
    ) -> Platform | None:
        platforms = {mention.platform for mention in mentions}
        if len(platforms) == 1:
            return next(iter(platforms))
        if not platforms:
            return inherited_platform
        return None

    @staticmethod
    def _is_compatibility_mention(
        text: str,
        mention: PlatformMention,
    ) -> bool:
        return _COMPATIBILITY_PREFIX.search(text[: mention.start]) is not None

    @staticmethod
    def _mentions_overlap(
        first: _ExactGameMention,
        second: _ExactGameMention,
    ) -> bool:
        return first.start < second.end and second.start < first.end

    @staticmethod
    def _deduplicate_and_sort(
        games: list[DetectedGame],
    ) -> list[DetectedGame]:
        by_identity: dict[GameIdentity, DetectedGame] = {}
        for game in games:
            identity = GameIdentity(game.canonical_name, game.platform)
            previous = by_identity.get(identity)
            if previous is None or FuzzyGameDetector._is_better(game, previous):
                by_identity[identity] = game
        result = list(by_identity.values())
        result.sort(key=lambda game: game.confidence, reverse=True)
        return result

    @staticmethod
    def _is_better(candidate: DetectedGame, previous: DetectedGame) -> bool:
        if candidate.confidence != previous.confidence:
            return candidate.confidence > previous.confidence
        priority = {
            DetectionMethod.FUZZY_MATCH: 0,
            DetectionMethod.ALIAS_MATCH: 1,
            DetectionMethod.EXACT_MATCH: 2,
        }
        return priority[candidate.detection_method] > priority[previous.detection_method]

    def _normalize_text(self, text: str) -> str:
        return self._platform_matcher.normalize_text(text)
