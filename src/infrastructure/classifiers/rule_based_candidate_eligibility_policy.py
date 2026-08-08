"""Deterministic candidate eligibility policy."""

import re
import unicodedata
from collections.abc import Sequence
from typing import Final

from domain.entities.candidate_classification import (
    CandidateClassification,
    CandidateClassificationReason,
    CandidateDisposition,
)
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, Platform
from domain.entities.game_identity import GameIdentity
from domain.interfaces.candidate_eligibility_policy import (
    ICandidateEligibilityPolicy,
)
from infrastructure.matching.platform_lexical_matcher import (
    PlatformLexicalMatcher,
    PlatformMention,
)

_EXPLICIT_HARDWARE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bconsola\b",
        r"\bvideoconsola\b",
        r"\bconsole\b",
    )
)

_HARDWARE_UNIT_SIGNAL: Final[re.Pattern[str]] = re.compile(
    r"\b(?:500|512)\s*(?:gb|go)\b|\b(?:1|2|4)\s*tb\b|"
    r"\b(?:negra|negro|blanca|blanco)\b|"
    r"\b(?:con\s+)?(?:\d+\s+)?juegos\b"
)
_HARDWARE_VARIANT_SUPPORT: Final[re.Pattern[str]] = re.compile(
    r"\b(?:mando|mandos|juegos|accesorio|accesorios|cable|cables|pack|bundle|"
    r"500\s*(?:gb|go)|512\s*(?:gb|go)|(?:1|2|4)\s*tb|"
    r"negra|negro|blanca|blanco)\b"
)

_ACCESSORY_TERM = (
    r"(?:mando|mandos|controlador|controladores|controller|controllers|"
    r"dualshock(?: 4)?|joystick|joysticks|volante|volantes|camara|camaras|"
    r"headset|headsets|auricular|auriculares|accesorio|accesorios)"
)
_ACCESSORY_PATTERN: Final[re.Pattern[str]] = re.compile(rf"\b{_ACCESSORY_TERM}\b")
_ACCESSORY_NEGATION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        rf"\bsin\s+(?:(?:el|la|los|las|ningun|ninguna)\s+)?{_ACCESSORY_TERM}\b",
        rf"\bno\s+incluye(?:n)?\s+(?:(?:el|la|los|las|ningun|ninguna)\s+)?{_ACCESSORY_TERM}\b",
        rf"\b{_ACCESSORY_TERM}\s+no\s+incluid[oa]s?\b",
    )
)
_CENTERED_CABLE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:vendo\s+)?(?:cable|cables|cargador|cargadores|charger|chargers)\b"
    r"|\b(?:pack|lote)\s+(?:de\s+)?(?:cables|cargadores|chargers)\b"
)

_UNSUPPORTED_VARIANT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:premium|special|ultimate|deluxe|gold|complete|anniversary|limited) edition\b",
        r"\bedicion (?:premium|especial|ultimate|deluxe|gold|completa|aniversario|limitada)\b",
        r"\bcollector(?:s| s)? edition\b",
        r"\bedicion coleccionista\b",
        r"\bsteelbook\b",
        r"\bcaja metalica\b",
        r"\bedicion metalica\b",
        r"\bgoty\b",
        r"\bgame of the year\b",
        r"\b(?:incluye|incluido|incluida|con) (?:el )?dlcs?\b",
        r"\bdlcs\b",
        r"\bdlcs? incluid[oa]s?\b",
        r"\bseason pass\b",
        r"\bpase de temporada\b",
        r"\bcontenido descargable incluido\b",
        r"\bcodigos? sin usar\b",
        r"\b(?:incluye|con) extras\b",
        r"\bcontenido adicional\b",
        r"\b(?:incluye|con) (?:una )?expansion\b",
        r"\bexpansion incluid[ao]\b",
        r"\bsin (?:el )?(?:mapa|manual|caratula|disco)\b",
        r"\bsolo (?:el )?(?:disco|caja)\b",
        r"\bdisco suelto\b",
        r"\bcaja vacia\b",
        r"\bcaja y manual sin juego\b",
        r"\b(?:disc only|loose disc|box only|empty box)\b",
        r"\b(?:without|no) (?:disc|manual|map|cover)\b",
    )
)
_ADDITIONAL_CONTENT_NEGATION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:no incluye|sin) (?:el )?(?:dlcs?|season pass|pase de temporada|contenido adicional|contenido descargable|extras|expansion)\b",
        r"\b(?:dlcs?|season pass|pase de temporada|contenido adicional|contenido descargable|extras|expansion) no incluid[oa]s?\b",
    )
)

# Context is evaluated in short, independently normalised clauses.  These
# expressions deliberately cover only unambiguous marketplace wording; they
# are not intended to be a general natural-language parser.
_CLAUSE_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:\n|[.,;:/()|•·+]|\s+-\s+)"
)
_POSITIVE_LOT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\binclu(?:ye|yen|ido|ida|idos|idas)\b",
        r"\bcontiene\b",
        r"\bcon\s+los\s+juegos\b",
        r"\blote\b",
        r"\bpack\s+de\s+juegos\b",
        r"\bjuegos\s+incluidos\b",
        r"\bvendo\s+juntos\b",
        r"\bse\s+vende\s+todo\s+junto\b",
        r"\bambos\s+juegos\b",
        r"\blos\s+siguientes\s+juegos\b",
    )
)
_CONTEXT_PREFIX_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:busco|buscando|me\s+interesa)\s*$",
        r"\bcompatible\s+con\s*$",
        r"\b(?:tambien\s+vendo|vendo\s+por\s+separado|disponible\s+por\s+separado)\s*$",
        r"\b(?:no\s+incluye|no\s+viene\s+con)\s*$",
        r"\b(?:referencia\s+a|parecido\s+a)\s*$",
        r"\b(?:acepto\s+cambio\s+por|cambiaria\s+por|se\s+cambia\s+por|cambio\s+por)\s*$",
        r"\b(?:acepto|aceptaria)\s*$",
        r"\bcambio(?:\s+[a-z0-9]+){0,8}\s+por\s*$",
    )
)
_CONTEXT_SUFFIX_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:no\s+incluido|no\s+incluida|no\s+viene\s+con)$",
        r"\b(?:vendido\s+por\s+separado|disponible\s+por\s+separado|por\s+separado)$",
        r"\ba\s+cambio$",
    )
)
_CONTEXT_SCOPE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\b(?:busco|buscando|me\s+interesa|compatible\s+con|referencia\s+a|parecido\s+a)\b",
        r"\b(?:tambien\s+vendo|vendo\s+por\s+separado|disponible\s+por\s+separado|no\s+incluye|no\s+viene\s+con)\b",
        r"\b(?:cambio|cambiaria|se\s+cambia)(?:\s+[a-z0-9]+){0,8}\s+por\b",
    )
)


def _normalise_clauses(text: str) -> tuple[str, ...]:
    """Return independently normalised clauses without joining boundaries."""
    return tuple(
        clause
        for raw_clause in _CLAUSE_SEPARATOR_PATTERN.split(text)
        if (clause := RuleBasedCandidateEligibilityPolicy._normalize_text(raw_clause))
    )


def _is_contextual_occurrence(clause: str, start: int, end: int) -> bool:
    before = clause[:start].rstrip()
    after = clause[end:].strip()
    if any(pattern.search(before) for pattern in _CONTEXT_PREFIX_PATTERNS):
        return True
    if any(pattern.match(after) for pattern in _CONTEXT_SUFFIX_PATTERNS):
        return True
    for pattern in _CONTEXT_SCOPE_PATTERNS:
        marker = pattern.search(before)
        if marker is not None:
            tail = before[marker.end() :]
            if not any(positive.search(tail) for positive in _POSITIVE_LOT_PATTERNS):
                return True
    return False


class RuleBasedCandidateEligibilityPolicy(ICandidateEligibilityPolicy):
    """Classify candidates using conservative, deterministic text rules."""

    def __init__(self) -> None:
        self._platform_matcher = PlatformLexicalMatcher()

    def classify(
        self,
        listing: CandidateListing,
        detected_games: Sequence[DetectedGame],
    ) -> CandidateClassification:
        """Return an immutable routing classification for one candidate."""
        if not isinstance(listing, CandidateListing):
            raise TypeError("listing must be CandidateListing")
        if isinstance(detected_games, (str, bytes, bytearray)) or not isinstance(
            detected_games, Sequence
        ):
            raise TypeError("detected_games must be a non-string Sequence")

        games = tuple(detected_games)
        if any(not isinstance(game, DetectedGame) for game in games):
            raise TypeError("detected_games must contain only DetectedGame")

        normalized_title = self._normalize_text(listing.title)
        normalized_text = self._normalize_text(
            f"{listing.title} {listing.description}"
        )

        if self._is_hardware(normalized_title, normalized_text):
            return CandidateClassification(
                CandidateDisposition.IGNORED,
                CandidateClassificationReason.UNSUPPORTED_HARDWARE,
                (),
            )
        if self._has_included_accessory(normalized_title, normalized_text):
            return CandidateClassification(
                CandidateDisposition.IGNORED,
                CandidateClassificationReason.ACCESSORY_OR_CONTROLLER,
                (),
            )
        if games:
            self._validate_game_identities(games)
            included_games, has_unresolved, has_contextual = self._included_games(
                listing.title,
                listing.description,
                games,
            )
        else:
            included_games, has_unresolved, has_contextual = (), False, False
        if self._has_unresolved_multiplatform(
            listing.title,
            listing.description,
            included_games,
        ):
            return CandidateClassification(
                CandidateDisposition.AMBIGUOUS,
                CandidateClassificationReason.AMBIGUOUS_MULTIPLATFORM,
                (),
            )
        if self._has_unsupported_variant(normalized_text):
            return CandidateClassification(
                CandidateDisposition.AMBIGUOUS,
                CandidateClassificationReason.UNSUPPORTED_EDITION,
                (),
            )
        if not games:
            return CandidateClassification(
                CandidateDisposition.IGNORED,
                CandidateClassificationReason.NO_INCLUDED_GAME,
                (),
            )
        if not included_games:
            reason = CandidateClassificationReason.CONTEXTUAL_REFERENCE_ONLY
            disposition = (
                CandidateDisposition.IGNORED
                if has_contextual and not has_unresolved
                else CandidateDisposition.AMBIGUOUS
            )
            return CandidateClassification(disposition, reason, ())
        if len(included_games) == 1:
            return CandidateClassification(
                CandidateDisposition.ELIGIBLE_INDIVIDUAL,
                CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
                included_games,
            )
        return CandidateClassification(
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            included_games,
        )

    @staticmethod
    def _validate_game_identities(games: tuple[DetectedGame, ...]) -> None:
        identities: set[GameIdentity | tuple[str, Platform]] = set()
        for game in games:
            normalized_name = " ".join(
                game.canonical_name.strip().casefold().split()
            )
            identity: GameIdentity | tuple[str, Platform]
            if game.platform is Platform.UNKNOWN:
                identity = (normalized_name, game.platform)
            else:
                identity = GameIdentity(game.canonical_name, game.platform)
            if identity in identities:
                raise ValueError("detected_games contains duplicate game identity")
            identities.add(identity)

    def _included_games(
        self,
        title: str,
        description: str,
        games: tuple[DetectedGame, ...],
    ) -> tuple[tuple[DetectedGame, ...], bool, bool]:
        title_clauses = _normalise_clauses(title)
        description_clauses = _normalise_clauses(description)
        positive_lot = any(
            pattern.search(clause)
            for pattern in _POSITIVE_LOT_PATTERNS
            for clause in (*title_clauses, *description_clauses)
        )

        reliable_title: set[int] = set()
        reliable_description: set[int] = set()
        contextual_indices: set[int] = set()
        unresolved_indices: set[int] = set()

        for index, game in enumerate(games):
            title_occurrences = self._locate_game(game, title_clauses, "title")
            description_occurrences = self._locate_game(
                game,
                description_clauses,
                "description",
            )
            all_occurrences = (*title_occurrences, *description_occurrences)
            if not all_occurrences:
                # A fuzzy detector may not provide a literal span that can be
                # located safely.  Do not invent inclusion context for it.
                unresolved_indices.add(index)
                continue

            has_reliable = False
            for source, clause, start, end in all_occurrences:
                if self._is_contextual_game_occurrence(clause, start, end):
                    contextual_indices.add(index)
                else:
                    has_reliable = True
                    if source == "title":
                        reliable_title.add(index)
                    else:
                        reliable_description.add(index)
            if not has_reliable:
                contextual_indices.add(index)

        if reliable_title:
            included_indices = set(reliable_title)
            if positive_lot:
                included_indices.update(reliable_description)
        elif positive_lot or len(reliable_description) == 1:
            included_indices = set(reliable_description)
        else:
            included_indices = set()

        included = tuple(game for index, game in enumerate(games) if index in included_indices)
        return included, bool(unresolved_indices), bool(contextual_indices)

    def _is_contextual_game_occurrence(
        self,
        clause: str,
        start: int,
        end: int,
    ) -> bool:
        if _is_contextual_occurrence(clause, start, end):
            return True
        after = clause[end:].strip()
        mentions = self._platform_matcher.find_mentions(after)
        if not mentions or mentions[0].start != 0:
            return False
        suffix = after[mentions[0].end :].strip()
        return any(pattern.match(suffix) for pattern in _CONTEXT_SUFFIX_PATTERNS)

    @classmethod
    def _locate_game(
        cls,
        game: DetectedGame,
        clauses: tuple[str, ...],
        source: str,
    ) -> tuple[tuple[str, str, int, int], ...]:
        variants: list[str] = []
        for value in (game.matched_text, game.canonical_name):
            normalized = cls._normalize_text(value)
            if normalized and normalized not in variants:
                variants.append(normalized)
        occurrences: list[tuple[str, str, int, int]] = []
        for clause in clauses:
            for variant in variants:
                pattern = re.compile(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])")
                occurrences.extend(
                    (source, clause, match.start(), match.end())
                    for match in pattern.finditer(clause)
                )
        return tuple(occurrences)

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.casefold())
        without_accents = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        alphanumeric = re.sub(r"[^a-z0-9\s]", " ", without_accents)
        return " ".join(alphanumeric.split())

    def _is_hardware(self, title: str, text: str) -> bool:
        if any(pattern.search(text) for pattern in _EXPLICIT_HARDWARE_PATTERNS):
            return True
        mentions = self._platform_matcher.find_mentions(title)
        if not mentions:
            return False
        if _HARDWARE_UNIT_SIGNAL.search(title) is not None:
            return True
        return any(self._has_hardware_variant(title, mention) for mention in mentions)

    @staticmethod
    def _has_hardware_variant(title: str, mention: PlatformMention) -> bool:
        suffix = title[mention.end :].lstrip()
        if mention.platform in {
            Platform.PS2,
            Platform.PS3,
            Platform.PS4,
            Platform.PS5,
            Platform.XBOX_360,
        } and re.match(r"(?:super\s+)?slim\b", suffix):
            return True

        variant_present = False
        if mention.platform in {Platform.PS4, Platform.PS5}:
            variant_present = re.match(r"pro\b", suffix) is not None
        elif mention.platform is Platform.XBOX_ONE:
            variant_present = re.match(r"[sx]\b", suffix) is not None
        elif mention.platform is Platform.XBOX_SERIES:
            variant_present = (
                mention.matched_text.endswith((" x", " s"))
                or re.match(r"[sx]\b", suffix) is not None
            )
        elif mention.platform is Platform.SWITCH:
            variant_present = re.match(r"(?:lite|oled)\b", suffix) is not None

        return variant_present and _HARDWARE_VARIANT_SUPPORT.search(title) is not None

    @staticmethod
    def _has_included_accessory(title: str, text: str) -> bool:
        positive_text = text
        for pattern in _ACCESSORY_NEGATION_PATTERNS:
            positive_text = pattern.sub(" ", positive_text)
        return (
            _ACCESSORY_PATTERN.search(positive_text) is not None
            or _CENTERED_CABLE_PATTERN.search(title) is not None
        )

    def _has_unresolved_multiplatform(
        self,
        title: str,
        description: str,
        included_games: tuple[DetectedGame, ...],
    ) -> bool:
        clauses = (*_normalise_clauses(title), *_normalise_clauses(description))
        mentions_by_clause = tuple(
            (
                clause,
                tuple(
                    mention
                    for mention in self._platform_matcher.find_mentions(clause)
                    if not _is_contextual_occurrence(
                        clause,
                        mention.start,
                        mention.end,
                    )
                ),
            )
            for clause in clauses
        )
        product_platforms = {
            mention.platform
            for _, mentions in mentions_by_clause
            for mention in mentions
        }
        included_platforms = {
            game.platform
            for game in included_games
            if game.platform is not Platform.UNKNOWN
        }
        if len(included_games) > 1 and any(
            game.platform is Platform.UNKNOWN for game in included_games
        ):
            return True
        if len(product_platforms) <= 1 and len(included_platforms) <= 1:
            return False
        if not included_games:
            return True
        if any(game.platform is Platform.UNKNOWN for game in included_games):
            return True
        if any(
            not self._has_local_platform_evidence(game, mentions_by_clause)
            for game in included_games
        ):
            return True

        for clause, mentions in mentions_by_clause:
            if not mentions or not self._clause_contains_game(clause, included_games):
                continue
            if any(
                mention.platform not in included_platforms
                for mention in mentions
            ):
                return True
        return not self._repeated_games_are_distinguishable(
            clauses,
            included_games,
        )

    @classmethod
    def _has_local_platform_evidence(
        cls,
        game: DetectedGame,
        mentions_by_clause: tuple[
            tuple[str, tuple[PlatformMention, ...]], ...
        ],
    ) -> bool:
        for clause, mentions in mentions_by_clause:
            if not any(mention.platform is game.platform for mention in mentions):
                continue
            if cls._clause_contains_game(clause, (game,)):
                return True
        return False

    @classmethod
    def _clause_contains_game(
        cls,
        clause: str,
        games: tuple[DetectedGame, ...],
    ) -> bool:
        return any(cls._game_occurrences(game, clause) for game in games)

    @classmethod
    def _repeated_games_are_distinguishable(
        cls,
        clauses: tuple[str, ...],
        games: tuple[DetectedGame, ...],
    ) -> bool:
        games_by_name: dict[str, list[DetectedGame]] = {}
        for game in games:
            normalized_name = " ".join(
                game.canonical_name.strip().casefold().split()
            )
            games_by_name.setdefault(normalized_name, []).append(game)

        for repeated_games in games_by_name.values():
            if len(repeated_games) == 1:
                continue
            occurrences = {
                (clause_index, start, end)
                for clause_index, clause in enumerate(clauses)
                for start, end in cls._game_occurrences(
                    repeated_games[0],
                    clause,
                )
                if not _is_contextual_occurrence(clause, start, end)
            }
            if len(occurrences) < len(repeated_games):
                return False
        return True

    @classmethod
    def _game_occurrences(
        cls,
        game: DetectedGame,
        clause: str,
    ) -> tuple[tuple[int, int], ...]:
        variants: list[str] = []
        for value in (game.matched_text, game.canonical_name):
            normalized = cls._normalize_text(value)
            if normalized and normalized not in variants:
                variants.append(normalized)
        occurrences: set[tuple[int, int]] = set()
        for variant in variants:
            pattern = re.compile(
                rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])"
            )
            occurrences.update(
                (match.start(), match.end())
                for match in pattern.finditer(clause)
            )
        return tuple(sorted(occurrences))

    @staticmethod
    def _has_unsupported_variant(text: str) -> bool:
        positive_text = text
        for pattern in _ADDITIONAL_CONTENT_NEGATION_PATTERNS:
            positive_text = pattern.sub(" ", positive_text)
        return any(
            pattern.search(positive_text) for pattern in _UNSUPPORTED_VARIANT_PATTERNS
        )


__all__ = ("RuleBasedCandidateEligibilityPolicy",)
