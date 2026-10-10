"""Select comparable physical products using resolved identity and sale context."""

import re
from decimal import Decimal

from domain.entities.candidate_classification import CandidateDisposition
from domain.entities.candidate_listing import CandidateListing
from domain.entities.detected_game import DetectedGame, DetectionMethod
from domain.entities.game_identity import GameIdentity
from domain.interfaces.comparable_filter import ComparableFilterInput, IComparableFilter
from domain.interfaces.game_detector import IGameDetector, ListingText
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.classifiers.rule_based_candidate_eligibility_policy import (
    RuleBasedCandidateEligibilityPolicy,
)
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector
from infrastructure.matching.platform_lexical_matcher import PlatformLexicalMatcher

_NON_PHYSICAL = re.compile(
    r"\b(?:digital|descarga|download|cuenta|account|codigo|code|psn|xbox live)\b"
)
_BUNDLE = re.compile(r"\b(?:lote|pack|coleccion|bundle|varios juegos|multiple games)\b")
_OTHER_PRODUCT = re.compile(
    r"\b(?:funda|carcasa|cable|hdmi|soporte|dock|grip|protector|cargador|charger|dualsense)\b"
)
_CONTEXT = re.compile(r"\b(?:busco|cambio por|tambien vendo)\b")


class RuleBasedComparableFilter(IComparableFilter):
    """Require one standard physical copy of the exact target identity.

    The collector supplies its detection snapshot; standalone callers may inject
    a detector. The packaged catalog is only the default detection provider, not
    a second whitelist of game titles maintained by this filter. Unmodeled
    editions/formats are excluded until the product identity models them.
    """

    def __init__(self, game_detector: IGameDetector | None = None) -> None:
        self._game_detector = game_detector
        self._eligibility = RuleBasedCandidateEligibilityPolicy()

    def is_valid_comparable(
        self,
        target_game: DetectedGame,
        listing: ComparableFilterInput,
    ) -> bool:
        if not listing.title.strip():
            return False
        try:
            target_identity = GameIdentity.from_game(target_game)
        except (TypeError, ValueError):
            return False
        games = listing.detected_games
        if games is None:
            if self._game_detector is None:
                self._game_detector = FuzzyGameDetector(PackagedGameCatalog())
            games = tuple(
                self._game_detector.detect_games(ListingText(listing.title, listing.description))
            )
        if not games:
            return False
        if not any(
            mention.platform is target_game.platform
            for mention in PlatformLexicalMatcher().find_mentions(
                f"{listing.title} {listing.description}"
            )
        ):
            return False

        price = listing.price
        if price is None:
            # Standalone calls can omit price without turning an amount in the
            # text into a game version or an invented conflicting asking price.
            amounts = {
                Decimal(value.replace(",", "."))
                for value in re.findall(
                    r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?|EUR)(?!\w)",
                    f"{listing.title} {listing.description}",
                    re.I,
                )
            }
            if len(amounts) > 1:
                return False
            price = next(iter(amounts), Decimal("1"))
        if not price.is_finite() or price <= 0:
            return False
        candidate = CandidateListing(
            "comparable", listing.title, listing.description, price, listing.currency, ""
        )
        classification = self._eligibility.classify(candidate, games)
        if classification.disposition is not CandidateDisposition.ELIGIBLE_INDIVIDUAL:
            return False
        included = classification.included_games[0]
        if GameIdentity.from_game(included) != target_identity:
            return False
        if included.detection_method is DetectionMethod.FUZZY_MATCH:
            return False

        # Product words within a resolved title (e.g. Code Vein) are not format
        # evidence. Evaluate the remaining local text, including negations.
        names = {
            self._normalize_text(value)
            for value in (included.canonical_name, included.matched_text)
        } - {""}
        for section in (listing.title, listing.description):
            for raw_clause in re.split(r"[.;\n]", section):
                clause = self._normalize_text(raw_clause)
                for name in sorted(names, key=len, reverse=True):
                    clause = re.sub(rf"\b{re.escape(name)}\b", "", clause)
                clause = re.sub(
                    r"\b(?:no|sin) (?:es |incluye )?(?:digital|codigo|code|cuenta)\b", "", clause
                )
                if _CONTEXT.match(clause.strip()) and not re.search(
                    r"\b(?:pero|incluye|contiene)\b", clause
                ):
                    continue
                if any(
                    not self._eligibility._is_contextual_product(clause, match.start(), match.end())
                    for pattern in (_NON_PHYSICAL, _BUNDLE, _OTHER_PRODUCT)
                    for match in pattern.finditer(clause)
                ):
                    return False
        return True

    @staticmethod
    def _normalize_text(text: str) -> str:
        return PlatformLexicalMatcher.normalize_text(text)
