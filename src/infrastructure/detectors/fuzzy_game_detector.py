"""Fuzzy matching game detector implementation.

This detector uses string similarity matching against a game catalog
to identify games in listing text.
"""

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    IGameDetector,
    ListingText,
    Platform,
)


class FuzzyGameDetector(IGameDetector):
    """Game detector using fuzzy string matching.

    Normalizes text, extracts platform, and matches against a catalog
    of known games using RapidFuzz for similarity scoring.
    """

    # Confidence thresholds
    EXACT_MATCH_THRESHOLD = 100.0
    ALIAS_MATCH_THRESHOLD = 95.0
    FUZZY_HIGH_THRESHOLD = 90.0
    FUZZY_MEDIUM_THRESHOLD = 80.0
    MIN_CONFIDENCE_THRESHOLD = FUZZY_MEDIUM_THRESHOLD

    # Platform detection patterns
    PLATFORM_PATTERNS = {
        Platform.PS4: [r"\bps4\b", r"\bplaystation 4\b", r"\bplay 4\b"],
        Platform.PS5: [r"\bps5\b", r"\bplaystation 5\b", r"\bplay 5\b"],
        Platform.XBOX_ONE: [r"\bxbox one\b", r"\bxboxone\b", r"\bxb1\b"],
        Platform.XBOX_SERIES: [
            r"\bxbox series\b",
            r"\bxbox series x\b",
            r"\bxbox series s\b",
            r"\bxsx\b",
            r"\bxss\b",
        ],
        Platform.SWITCH: [
            r"\bswitch\b",
            r"\bnintendo switch\b",
            r"\bns\b",
        ],
    }

    def __init__(self, catalog_path: Path | str | None = None) -> None:
        """Initialize detector with game catalog.

        Args:
            catalog_path: Path to game catalog JSON file.
                         Defaults to data/game_catalog.json
        """
        if catalog_path is None:
            # Default catalog path relative to project root
            catalog_path = Path(__file__).parent.parent.parent.parent / "data" / "game_catalog.json"

        self.catalog_path = Path(catalog_path)
        self.catalog = self._load_catalog()

    def _load_catalog(self) -> list[dict[str, Any]]:
        """Load game catalog from JSON file.

        Returns:
            List of game dictionaries

        Raises:
            FileNotFoundError: If catalog file doesn't exist
            json.JSONDecodeError: If catalog is invalid JSON
        """
        if not self.catalog_path.exists():
            raise FileNotFoundError(f"Game catalog not found: {self.catalog_path}")

        with open(self.catalog_path, encoding="utf-8") as f:
            catalog: list[dict[str, Any]] = json.load(f)
            return catalog

    def detect_games(self, listing_text: ListingText) -> list[DetectedGame]:
        """Detect games in listing text using fuzzy matching.

        Args:
            listing_text: Text content to analyze

        Returns:
            List of detected games sorted by confidence (highest first)
        """
        # Normalize text
        normalized_title = self._normalize_text(listing_text.title)
        normalized_description = self._normalize_text(listing_text.description)
        combined_text = f"{normalized_title} {normalized_description}".strip()

        # Extract platform
        detected_platform = self._detect_platform(combined_text)

        # Find game matches
        detected_games: list[DetectedGame] = []

        for game in self.catalog:
            # Only match games from detected platform (or all if unknown)
            game_platform = Platform(game["platform"])
            if detected_platform != Platform.UNKNOWN and game_platform != detected_platform:
                continue

            # Try to match this game
            match = self._match_game(
                combined_text,
                game["canonical_name"],
                game["aliases"],
                game_platform,
            )

            if match:
                detected_games.append(match)

        # Remove duplicates (same canonical name)
        seen_names: set[str] = set()
        unique_games: list[DetectedGame] = []
        for detected_game in detected_games:
            if detected_game.canonical_name not in seen_names:
                seen_names.add(detected_game.canonical_name)
                unique_games.append(detected_game)

        # Sort by confidence (highest first)
        unique_games.sort(key=lambda x: x.confidence, reverse=True)

        return unique_games

    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching.

        - Convert to lowercase
        - Remove accents
        - Remove special characters
        - Collapse multiple spaces

        Args:
            text: Text to normalize

        Returns:
            Normalized text
        """
        # Lowercase
        text = text.lower()

        # Remove accents
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))

        # Remove special characters (keep alphanumeric and spaces)
        text = re.sub(r"[^a-z0-9\s]", " ", text)

        # Collapse multiple spaces
        text = re.sub(r"\s+", " ", text)

        return text.strip()

    def _detect_platform(self, normalized_text: str) -> Platform:
        """Detect gaming platform from text.

        Args:
            normalized_text: Normalized text to search

        Returns:
            Detected platform or UNKNOWN
        """
        for platform, patterns in self.PLATFORM_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, normalized_text):
                    return platform

        return Platform.UNKNOWN

    def _match_game(
        self,
        text: str,
        canonical_name: str,
        aliases: list[str],
        platform: Platform,
    ) -> DetectedGame | None:
        """Try to match a game against text.

        Args:
            text: Normalized text to search in
            canonical_name: Game's canonical name
            aliases: List of known aliases
            platform: Game's platform

        Returns:
            DetectedGame if match found above threshold, None otherwise
        """
        best_score = 0.0
        best_match_text = ""
        best_method = DetectionMethod.FUZZY_MATCH

        # Normalize canonical name and aliases
        normalized_canonical = self._normalize_text(canonical_name)
        normalized_aliases = [self._normalize_text(alias) for alias in aliases]

        all_variants = [normalized_canonical] + normalized_aliases

        for variant in all_variants:
            # Check for exact substring match
            if variant in text:
                score = self.EXACT_MATCH_THRESHOLD
                match_text = variant
                method = DetectionMethod.EXACT_MATCH
                if score > best_score:
                    best_score = score
                    best_match_text = match_text
                    best_method = method
                continue

            # Fuzzy matching using token_set_ratio (handles word order)
            score = fuzz.token_set_ratio(variant, text)

            if score > best_score:
                best_score = score
                best_match_text = variant
                # Determine method based on score
                if score >= self.ALIAS_MATCH_THRESHOLD:
                    best_method = DetectionMethod.ALIAS_MATCH
                else:
                    best_method = DetectionMethod.FUZZY_MATCH

        # Check if score meets minimum threshold
        if best_score < self.MIN_CONFIDENCE_THRESHOLD:
            return None

        # Calculate confidence (0.0 - 1.0)
        confidence = best_score / 100.0

        return DetectedGame(
            canonical_name=canonical_name,
            matched_text=best_match_text,
            platform=platform,
            confidence=confidence,
            detection_method=best_method,
        )
