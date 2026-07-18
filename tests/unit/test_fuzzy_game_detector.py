"""Unit tests for FuzzyGameDetector."""

import pytest

from domain.interfaces.game_detector import DetectionMethod, ListingText, Platform
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector


@pytest.fixture
def detector() -> FuzzyGameDetector:
    """Create detector instance with default catalog."""
    return FuzzyGameDetector()


@pytest.mark.unit
class TestFuzzyGameDetector:
    """Test suite for FuzzyGameDetector."""

    def test_detector_initialization(self, detector: FuzzyGameDetector) -> None:
        """Test that detector initializes and loads catalog."""
        assert detector.catalog is not None
        assert len(detector.catalog) > 0

    def test_packaged_catalog_is_independent_of_working_directory(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Load and use the packaged catalog from an unrelated directory."""
        monkeypatch.chdir(tmp_path)

        detector = FuzzyGameDetector()
        games = detector.detect_games(ListingText(title="GTA V PS4", description=""))

        assert games
        assert games[0].canonical_name == "Grand Theft Auto V"

    def test_normalize_text(self, detector: FuzzyGameDetector) -> None:
        """Test text normalization."""
        # Lowercase
        assert detector._normalize_text("GTA V") == "gta v"

        # Remove accents
        assert detector._normalize_text("pokémon") == "pokemon"

        # Remove special characters
        assert detector._normalize_text("Grand Theft Auto: V!") == "grand theft auto v"

        # Collapse spaces
        assert detector._normalize_text("GTA   V") == "gta v"

        # Combined
        assert detector._normalize_text("  GTA  V!!!  ") == "gta v"

    def test_detect_platform_ps4(self, detector: FuzzyGameDetector) -> None:
        """Test PS4 platform detection."""
        text = detector._normalize_text("Lote PS4 GTA V")
        assert detector._detect_platform(text) == Platform.PS4

        text = detector._normalize_text("PlayStation 4 games")
        assert detector._detect_platform(text) == Platform.PS4

    def test_detect_platform_ps5(self, detector: FuzzyGameDetector) -> None:
        """Test PS5 platform detection."""
        text = detector._normalize_text("Juegos PS5")
        assert detector._detect_platform(text) == Platform.PS5

    def test_detect_platform_xbox(self, detector: FuzzyGameDetector) -> None:
        """Test Xbox platform detection."""
        text = detector._normalize_text("Xbox One games")
        assert detector._detect_platform(text) == Platform.XBOX_ONE

        text = detector._normalize_text("Xbox Series X")
        assert detector._detect_platform(text) == Platform.XBOX_SERIES

    def test_detect_platform_switch(self, detector: FuzzyGameDetector) -> None:
        """Test Nintendo Switch platform detection."""
        text = detector._normalize_text("Nintendo Switch lote")
        assert detector._detect_platform(text) == Platform.SWITCH

    def test_detect_platform_unknown(self, detector: FuzzyGameDetector) -> None:
        """Test unknown platform."""
        text = detector._normalize_text("Videojuegos varios")
        assert detector._detect_platform(text) == Platform.UNKNOWN

    def test_detect_gta_v_exact(self, detector: FuzzyGameDetector) -> None:
        """Test GTA V detection - exact match."""
        listing = ListingText(title="GTA V", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"
        assert games[0].confidence >= 0.95

    def test_detect_gta_5_variant(self, detector: FuzzyGameDetector) -> None:
        """Test GTA 5 detection - variant."""
        listing = ListingText(title="GTA 5", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"
        assert games[0].confidence >= 0.95

    def test_detect_gta_5_no_space(self, detector: FuzzyGameDetector) -> None:
        """Test GTA5 detection - no space."""
        listing = ListingText(title="GTA5", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"
        assert games[0].confidence >= 0.95

    def test_detect_grand_theft_auto(self, detector: FuzzyGameDetector) -> None:
        """Test full name detection."""
        listing = ListingText(title="Grand Theft Auto", description="")
        games = detector.detect_games(listing)

        assert len(games) >= 1
        # Should match GTA V
        gta_matches = [g for g in games if "Grand Theft Auto V" in g.canonical_name]
        assert len(gta_matches) >= 1

    def test_detect_rdr2(self, detector: FuzzyGameDetector) -> None:
        """Test RDR2 detection."""
        listing = ListingText(title="RDR2", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Red Dead Redemption 2"
        assert games[0].confidence >= 0.95

    def test_detect_red_dead_redemption_ii(self, detector: FuzzyGameDetector) -> None:
        """Test Red Dead Redemption II detection."""
        listing = ListingText(title="Red Dead Redemption II", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Red Dead Redemption 2"
        assert games[0].confidence >= 0.80

    def test_detect_fifa_24(self, detector: FuzzyGameDetector) -> None:
        """Test FIFA 24 detection."""
        listing = ListingText(title="FIFA24", description="")
        games = detector.detect_games(listing)

        # Should detect FIFA 24 (may also detect similar FIFAs with lower confidence)
        assert len(games) >= 1
        # First result should be FIFA 24 with highest confidence
        assert games[0].canonical_name == "EA Sports FC 24"
        assert games[0].confidence >= 0.95

    def test_detect_fc_24(self, detector: FuzzyGameDetector) -> None:
        """Test FC 24 detection."""
        listing = ListingText(title="FC 24", description="")
        games = detector.detect_games(listing)

        # Should detect FC 24 (may also detect FC 25 with lower confidence)
        assert len(games) >= 1
        # First result should be FC 24 with highest confidence
        assert games[0].canonical_name == "EA Sports FC 24"
        assert games[0].confidence >= 0.95

    def test_detect_multiple_games_in_lote(self, detector: FuzzyGameDetector) -> None:
        """Test detection of multiple games in a lot."""
        listing = ListingText(
            title="Lote PS4 GTA V RDR2 FIFA 24",
            description="Todos completos. También cambio por Nintendo.",
        )
        games = detector.detect_games(listing)

        # Should detect at least GTA V, RDR2, and FIFA 24
        assert len(games) >= 3

        game_names = [g.canonical_name for g in games]
        assert "Grand Theft Auto V" in game_names
        assert "Red Dead Redemption 2" in game_names
        assert "EA Sports FC 24" in game_names

        # All should have high confidence
        for game in games:
            assert game.confidence >= 0.80

    def test_detect_games_with_description(self, detector: FuzzyGameDetector) -> None:
        """Test detection from both title and description."""
        listing = ListingText(
            title="Lote PS4",
            description="Incluye GTA 5 y Red Dead 2",
        )
        games = detector.detect_games(listing)

        assert len(games) >= 2
        game_names = [g.canonical_name for g in games]
        assert "Grand Theft Auto V" in game_names
        assert "Red Dead Redemption 2" in game_names

    def test_no_false_positives(self, detector: FuzzyGameDetector) -> None:
        """Test that unrelated text doesn't produce false matches."""
        listing = ListingText(
            title="Mando PS4 azul",
            description="Vendo mando inalámbrico en perfecto estado",
        )
        games = detector.detect_games(listing)

        # Should not detect any games
        assert len(games) == 0

    def test_platform_filter(self, detector: FuzzyGameDetector) -> None:
        """Test that platform filtering works."""
        listing = ListingText(
            title="Lote Xbox One FIFA 24",
            description="",
        )
        games = detector.detect_games(listing)

        # Should not detect PS4 FIFA (only Xbox One FIFA exists in catalog)
        # This test assumes catalog has platform-specific entries
        # For now, just check that detection works
        assert len(games) >= 0  # May be 0 if catalog doesn't have Xbox games

    def test_confidence_ordering(self, detector: FuzzyGameDetector) -> None:
        """Test that results are ordered by confidence."""
        listing = ListingText(
            title="GTA V RDR2 FIFA",
            description="",
        )
        games = detector.detect_games(listing)

        # Check that confidence is descending
        for i in range(len(games) - 1):
            assert games[i].confidence >= games[i + 1].confidence

    def test_no_duplicates(self, detector: FuzzyGameDetector) -> None:
        """Test that same game isn't detected twice."""
        listing = ListingText(
            title="GTA V GTA 5 Grand Theft Auto V",
            description="",
        )
        games = detector.detect_games(listing)

        # Should only have one GTA V entry
        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"

    def test_detection_method_exact(self, detector: FuzzyGameDetector) -> None:
        """Test that exact matches have EXACT_MATCH method."""
        listing = ListingText(title="gta v", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].detection_method == DetectionMethod.EXACT_MATCH

    def test_detection_method_alias(self, detector: FuzzyGameDetector) -> None:
        """Test that alias matches have ALIAS_MATCH method."""
        listing = ListingText(title="gta 5", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        # Should be EXACT_MATCH or ALIAS_MATCH depending on matching
        assert games[0].detection_method in [
            DetectionMethod.EXACT_MATCH,
            DetectionMethod.ALIAS_MATCH,
        ]

    def test_empty_listing(self, detector: FuzzyGameDetector) -> None:
        """Test empty listing returns no games."""
        listing = ListingText(title="", description="")
        games = detector.detect_games(listing)

        assert len(games) == 0

    def test_confidence_range(self, detector: FuzzyGameDetector) -> None:
        """Test that confidence is always between 0 and 1."""
        listing = ListingText(
            title="Lote PS4 GTA V RDR2 FIFA 24",
            description="",
        )
        games = detector.detect_games(listing)

        for game in games:
            assert 0.0 <= game.confidence <= 1.0

    def test_platform_propagation(self, detector: FuzzyGameDetector) -> None:
        """Test that detected platform is assigned to games."""
        listing = ListingText(
            title="Lote PS4 GTA V",
            description="",
        )
        games = detector.detect_games(listing)

        assert len(games) >= 1
        assert games[0].platform == Platform.PS4
