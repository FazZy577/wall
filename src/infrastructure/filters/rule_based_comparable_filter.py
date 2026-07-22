"""Rule-based comparable filter implementation.

Uses deterministic keyword matching and pattern detection to filter out
listings that cannot be used as valid comparables for price estimation.
"""

import re
import unicodedata

from domain.entities.detected_game import DetectedGame
from domain.interfaces.comparable_filter import ComparableFilterInput, IComparableFilter


class RuleBasedComparableFilter(IComparableFilter):
    """Filters listings using deterministic rules.

    Rejects listings that contain:
    - Consoles (without clear game references)
    - Controllers/accessories
    - Empty boxes
    - Accounts
    - Multi-game bundles
    - Wrong game versions
    """

    # Keywords for detecting consoles
    CONSOLE_KEYWORDS = [
        r"\bps4\b",
        r"\bps5\b",
        r"\bplaystation 4\b",
        r"\bplaystation 5\b",
        r"\bxbox one\b",
        r"\bxbox series\b",
        r"\bnintendo switch\b",
        r"\bswitch\b",
        r"\bconsola\b",
        r"\bconsole\b",
    ]

    # Keywords for detecting controllers
    CONTROLLER_KEYWORDS = [
        r"\bdualshock\b",
        r"\bdualsense\b",
        r"\bcontroller\b",
        r"\bmando\b",
        r"\bjoystick\b",
        r"\bcontrol\b",
    ]

    # Keywords for detecting accessories
    ACCESSORY_KEYWORDS = [
        r"\bfunda\b",
        r"\bcase\b",
        r"\bcarcasa\b",
        r"\bcable\b",
        r"\bhdmi\b",
        r"\bsoporte\b",
        r"\bdock\b",
        r"\bgrip\b",
        r"\bprotector\b",
        r"\bauriculares\b",
        r"\bheadset\b",
        r"\bcargador\b",
        r"\bcharger\b",
    ]

    # Keywords for detecting accounts
    ACCOUNT_KEYWORDS = [
        r"\bcuenta\b",
        r"\baccount\b",
        r"\bpsn\b",
        r"\bxbox live\b",
        r"\bdigital\b",
        r"\bcodigo\b",
        r"\bcode\b",
    ]

    # Keywords for detecting empty boxes
    EMPTY_BOX_INDICATORS = [
        r"\bsin disco\b",
        r"\bsolo caja\b",
        r"\bempty box\b",
        r"\bno disco\b",
        r"\bno game\b",
        r"\bwithout disc\b",
        r"\bsenza disco\b",
    ]

    # Keywords that appear in empty box listings
    BOX_KEYWORDS = [
        r"\bcaja\b",
        r"\bbox\b",
        r"\bsteelbook\b",
        r"\bestuche\b",
    ]

    # Keywords for detecting bundles/lots
    BUNDLE_KEYWORDS = [
        r"\blote\b",
        r"\bpack\b",
        r"\bcoleccion\b",
        r"\bcolección\b",
        r"\bbundle\b",
        r"\bvarios juegos\b",
        r"\bmultiple games\b",
    ]

    def __init__(self) -> None:
        """Initialize the rule-based filter."""
        pass

    def is_valid_comparable(
        self,
        target_game: DetectedGame,
        listing: ComparableFilterInput,
    ) -> bool:
        """Determine if a listing is valid as a comparable.

        Args:
            target_game: The game we want to price
            listing: The listing to evaluate

        Returns:
            True if listing can be used as comparable, False otherwise
        """
        # Normalize text for matching
        normalized_text = self._normalize_text(f"{listing.title} {listing.description}")

        # Rule 1: Reject consoles (without clear game context)
        if self._is_console_only(normalized_text):
            return False

        # Rule 2: Reject controllers
        if self._contains_keywords(normalized_text, self.CONTROLLER_KEYWORDS):
            return False

        # Rule 3: Reject accessories
        if self._contains_keywords(normalized_text, self.ACCESSORY_KEYWORDS):
            return False

        # Rule 4: Reject accounts
        if self._contains_keywords(normalized_text, self.ACCOUNT_KEYWORDS):
            return False

        # Rule 5: Reject empty boxes
        if self._is_empty_box(normalized_text):
            return False

        # Rule 6: Reject bundles/lots
        if self._contains_keywords(normalized_text, self.BUNDLE_KEYWORDS):
            return False

        # Rule 7: Verify game match
        return self._is_correct_game(target_game, listing)

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

    def _contains_keywords(self, text: str, keywords: list[str]) -> bool:
        """Check if text contains any of the keywords.

        Args:
            text: Normalized text to search
            keywords: List of regex patterns

        Returns:
            True if any keyword is found
        """
        return any(re.search(pattern, text) for pattern in keywords)

    def _is_console_only(self, text: str) -> bool:
        """Check if listing is console-only (no clear game reference).

        Args:
            text: Normalized text

        Returns:
            True if appears to be console-only
        """
        # Check if console keywords are present
        has_console = self._contains_keywords(text, self.CONSOLE_KEYWORDS)

        if not has_console:
            return False

        # Check for game-related words
        game_indicators = [
            r"\bjuego\b",
            r"\bjuegos\b",
            r"\bgame\b",
            r"\bgames\b",
            r"\bvideojuego\b",
            r"\bvideojuegos\b",
            r"\btitulo\b",
            r"\btitulos\b",
        ]

        has_game_words = self._contains_keywords(text, game_indicators)

        # Check for common game title keywords that indicate a specific game
        game_title_indicators = [
            r"\bgta\b",
            r"\bgta5\b",
            r"\bgtav\b",
            r"\bgrand theft\b",
            r"\bfifa\b",
            r"\bcod\b",
            r"\bcall of duty\b",
            r"\bred dead\b",
            r"\brdr2\b",
            r"\bassassin\b",
            r"\buncharted\b",
            r"\bhorizon\b",
            r"\bgod of war\b",
            r"\bspider.?man\b",
            r"\bminecraft\b",
            r"\bfortnite\b",
        ]

        has_game_title = self._contains_keywords(text, game_title_indicators)

        # If console keywords but no game words or titles, likely console-only
        # Be strict: only reject if clearly console-focused
        if not has_game_words and not has_game_title:
            # Very short listings are almost always console-only
            word_count = len(text.split())
            if word_count <= 6:
                return True

            # Longer listings without game words are also console-only
            # unless they contain specific game titles (checked elsewhere)
            if word_count <= 15:
                return True

        return False

    def _is_empty_box(self, text: str) -> bool:
        """Check if listing is for an empty box.

        Args:
            text: Normalized text

        Returns:
            True if appears to be empty box
        """
        # Check for box keywords
        has_box = self._contains_keywords(text, self.BOX_KEYWORDS)

        if not has_box:
            return False

        # Check for empty box indicators
        has_empty_indicator = self._contains_keywords(text, self.EMPTY_BOX_INDICATORS)

        return has_empty_indicator

    def _is_correct_game(
        self, target_game: DetectedGame, listing: ComparableFilterInput
    ) -> bool:
        """Verify that the listing matches the target game.

        Checks for common mismatches like:
        - GTA V vs GTA Trilogy
        - FIFA 23 vs FIFA 20

        Args:
            target_game: The game we're pricing
            listing: The listing to check

        Returns:
            True if listing matches target game
        """
        normalized_listing = self._normalize_text(f"{listing.title} {listing.description}")
        normalized_target = self._normalize_text(target_game.canonical_name)

        # Handle empty listings
        if not normalized_listing or not normalized_target:
            return False

        # Check for obviously different games

        # Case 1: Different numbered versions (FIFA 23 vs FIFA 20)
        # Only check for year-like numbers (18-99) to avoid false positives with PS5/PS4
        version_numbers = re.findall(r"\b([1-9]\d)\b", normalized_target)
        if version_numbers:
            for version in version_numbers:
                # Find other year-like numbers in listing
                listing_numbers = re.findall(r"\b([1-9]\d)\b", normalized_listing)
                for listing_num in listing_numbers:
                    # If we find a different year/version number, reject
                    # But only if it's clearly a version number (not 45, 60, etc.)
                    if listing_num != version and int(listing_num) >= 17 and int(listing_num) <= 99:
                        # Exception: Don't reject if the numbers are very different
                        # (e.g., 23 vs 5 is likely FIFA 23 vs PS5, not different FIFAs)
                        num_diff = abs(int(listing_num) - int(version))
                        if num_diff < 10:  # Close numbers are likely different versions
                            return False

        # Case 2: Trilogy vs single game
        if "trilogy" in normalized_target or "trilogia" in normalized_target:
            # Target is trilogy, listing must mention trilogy
            if "trilogy" not in normalized_listing and "trilogia" not in normalized_listing:
                return False
        else:
            # Target is NOT trilogy, reject if listing mentions trilogy
            if "trilogy" in normalized_listing or "trilogia" in normalized_listing:
                return False

        # Case 3: Different editions that are separate games
        # Example: "Black Ops 6" vs "Black Ops 3"
        target_edition_match = re.search(
            r"\b(black ops|modern warfare|world war)\s+(\d+|ii|iii|iv|v|vi)\b",
            normalized_target
        )
        if target_edition_match:
            edition_base = target_edition_match.group(1)
            edition_num = target_edition_match.group(2)

            # Convert roman numerals to numbers for comparison
            roman_map = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}
            target_num_normalized = roman_map.get(edition_num.lower(), edition_num)

            # Look for same base game with different number in listing
            listing_edition_matches = re.finditer(
                rf"\b{re.escape(edition_base)}\s+(\d+|ii|iii|iv|v|vi)\b",
                normalized_listing
            )

            found_exact_match = False
            for listing_match in listing_edition_matches:
                listing_num = listing_match.group(1)
                listing_num_normalized = roman_map.get(listing_num.lower(), listing_num)

                if listing_num_normalized == target_num_normalized:
                    found_exact_match = True
                elif listing_num_normalized != target_num_normalized and not found_exact_match:
                    # Different numbered edition found before the exact match
                    return False

        # Case 4: Check if target game name substantially appears
        # This handles variants like "GTA5" vs "GTA V" vs "Grand Theft Auto V"
        return self._game_name_appears(normalized_target, normalized_listing)

    def _game_name_appears(self, target_normalized: str, listing_normalized: str) -> bool:
        """Check if target game name substantially appears in listing.

        Args:
            target_normalized: Normalized target game name
            listing_normalized: Normalized listing text

        Returns:
            True if significant portion of game name appears
        """
        # Split target into words, remove very common words
        stopwords = {"de", "the", "of", "a", "an", "and", "edition", "edicion", "auto"}
        target_words = [w for w in target_normalized.split() if w not in stopwords and len(w) > 1]

        if not target_words:
            return True  # Empty target always matches

        # Special case: handle common game abbreviations
        # GTA, COD, FIFA, etc. are often written without spaces or with numbers
        if "grand" in target_words and "theft" in target_words and "gta" in listing_normalized:
            # Grand Theft Auto -> check for "gta"
            return True

        if "call" in target_words and "duty" in target_words and "cod" in listing_normalized:
            # Call of Duty -> check for "cod"
            return True

        # Count how many target words appear in listing
        matches = 0
        for word in target_words:
            if word in listing_normalized:
                matches += 1
            elif (
                len(word) <= 3
                and (word == "v" or word == "5")
                and (
                    re.search(r"\b(v|5)\b", listing_normalized)
                    or re.search(r"gta(v|5)", listing_normalized)
                )
            ):
                # For short words (v, 5), check for variations
                matches += 1

        # If at least 40% of significant words match, consider it a match
        # Very lenient to handle abbreviations and variations
        threshold = 0.4
        return matches >= max(1, len(target_words) * threshold)
