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
from domain.entities.detected_game import DetectedGame
from domain.interfaces.candidate_eligibility_policy import (
    ICandidateEligibilityPolicy,
)

_EXPLICIT_HARDWARE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bconsola\b",
        r"\bvideoconsola\b",
        r"\bconsole\b",
    )
)

_PLATFORM_PRODUCT = (
    r"(?:ps4|playstation 4|ps5|playstation 5|xbox one|xbox series"
    r"(?: x| s)?|nintendo switch)"
)
_HARDWARE_TITLE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern)
    for pattern in (
        rf"\b{_PLATFORM_PRODUCT}\s+slim\b",
        rf"\b{_PLATFORM_PRODUCT}\s+pro\s+(?:(?:con\s+)?(?:mando|mandos|juegos|accesorios)|pack|bundle)\b",
        rf"\b{_PLATFORM_PRODUCT}\s+(?:(?:pro|slim)\s+)?(?:negra|negro|blanca|blanco)\b",
        rf"\b{_PLATFORM_PRODUCT}\s+(?:(?:pro|slim)\s+)?(?:500 ?gb|1 ?tb|2 ?tb)\b",
        rf"\b{_PLATFORM_PRODUCT}\s+(?:con\s+)?(?:\d+\s+)?juegos\b",
        rf"\bpack\s+(?:de\s+)?{_PLATFORM_PRODUCT}(?:\s+con)?\s+juegos\b",
    )
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

_PLATFORM_FAMILY_PATTERNS: Final[tuple[tuple[re.Pattern[str], ...], ...]] = (
    tuple(re.compile(pattern) for pattern in (r"\bps4\b", r"\bplaystation 4\b", r"\bplay 4\b")),
    tuple(re.compile(pattern) for pattern in (r"\bps5\b", r"\bplaystation 5\b", r"\bplay 5\b")),
    tuple(re.compile(pattern) for pattern in (r"\bxbox one\b", r"\bxboxone\b", r"\bxb1\b")),
    tuple(
        re.compile(pattern)
        for pattern in (
            r"\bxbox series\b",
            r"\bxbox series x\b",
            r"\bxbox series s\b",
            r"\bxboxseries\b",
            r"\bseries x\b",
            r"\bseries s\b",
        )
    ),
    tuple(
        re.compile(pattern)
        for pattern in (
            r"\bnintendo switch\b",
            r"\bswitch oled\b",
            r"\bswitch lite\b",
            r"\bswitch\b",
        )
    ),
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


class RuleBasedCandidateEligibilityPolicy(ICandidateEligibilityPolicy):
    """Classify candidates using conservative, deterministic text rules."""

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
        if self._is_multiplatform(normalized_text):
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
        if len(games) == 1:
            return CandidateClassification(
                CandidateDisposition.ELIGIBLE_INDIVIDUAL,
                CandidateClassificationReason.ELIGIBLE_SINGLE_GAME,
                games,
            )
        return CandidateClassification(
            CandidateDisposition.ELIGIBLE_LOT,
            CandidateClassificationReason.ELIGIBLE_MULTI_GAME_LOT,
            games,
        )

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

    @staticmethod
    def _is_hardware(title: str, text: str) -> bool:
        return any(pattern.search(text) for pattern in _EXPLICIT_HARDWARE_PATTERNS) or any(
            pattern.search(title) for pattern in _HARDWARE_TITLE_PATTERNS
        )

    @staticmethod
    def _has_included_accessory(title: str, text: str) -> bool:
        positive_text = text
        for pattern in _ACCESSORY_NEGATION_PATTERNS:
            positive_text = pattern.sub(" ", positive_text)
        return (
            _ACCESSORY_PATTERN.search(positive_text) is not None
            or _CENTERED_CABLE_PATTERN.search(title) is not None
        )

    @staticmethod
    def _is_multiplatform(text: str) -> bool:
        families = sum(
            any(pattern.search(text) for pattern in family)
            for family in _PLATFORM_FAMILY_PATTERNS
        )
        return families > 1

    @staticmethod
    def _has_unsupported_variant(text: str) -> bool:
        positive_text = text
        for pattern in _ADDITIONAL_CONTENT_NEGATION_PATTERNS:
            positive_text = pattern.sub(" ", positive_text)
        return any(
            pattern.search(positive_text) for pattern in _UNSUPPORTED_VARIANT_PATTERNS
        )


__all__ = ("RuleBasedCandidateEligibilityPolicy",)
