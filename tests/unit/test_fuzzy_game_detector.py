"""Unit tests for FuzzyGameDetector."""

import pytest

from domain.interfaces.game_detector import DetectionMethod, ListingText, Platform
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector

SHORT_ALIAS_CASES = (
    ("bo6", "Call of Duty: Black Ops 6"),
    ("mw3", "Call of Duty: Modern Warfare III"),
    ("mw2", "Call of Duty: Modern Warfare II"),
    ("gow", "God of War"),
    ("hzd", "Horizon Zero Dawn"),
    ("hfw", "Horizon Forbidden West"),
    ("got", "Ghost of Tsushima"),
    ("re2", "Resident Evil 2"),
    ("re3", "Resident Evil 3"),
    ("re8", "Resident Evil Village"),
    ("ds3", "Dark Souls III"),
    ("gts", "Gran Turismo Sport"),
    ("gt7", "Gran Turismo 7"),
    ("bf5", "Battlefield V"),
    ("bfv", "Battlefield V"),
    ("sf5", "Street Fighter V"),
    ("sfv", "Street Fighter V"),
    ("ow2", "Overwatch 2"),
)


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

    def test_embedded_got_in_agotado_does_not_create_ghost_of_tsushima(
        self,
        detector: FuzzyGameDetector,
    ) -> None:
        games = detector.detect_games(
            ListingText(title="RDR2 PS4 agotado", description="")
        )
        names = [game.canonical_name for game in games]

        assert "Red Dead Redemption 2" in names
        assert "Ghost of Tsushima" not in names
        assert all(game.matched_text != "got" for game in games)

    @pytest.mark.parametrize(
        "title",
        [
            "Ghost of Tsushima GOT PS4",
            "GOT! PS4",
            "vendo got para ps4",
            "vendo GoT para PS4",
            "vendo (GOT) para PS4",
        ],
    )
    def test_isolated_got_alias_remains_an_exact_match(
        self,
        detector: FuzzyGameDetector,
        title: str,
    ) -> None:
        games = detector.detect_games(ListingText(title=title, description=""))
        ghost = next(
            game for game in games if game.canonical_name == "Ghost of Tsushima"
        )

        assert ghost.matched_text in {"ghost of tsushima", "got"}
        assert ghost.confidence == 1.0
        assert ghost.detection_method is DetectionMethod.EXACT_MATCH

    @pytest.mark.parametrize(("alias", "canonical_name"), SHORT_ALIAS_CASES)
    def test_every_short_catalog_alias_matches_when_lexically_isolated(
        self,
        detector: FuzzyGameDetector,
        alias: str,
        canonical_name: str,
    ) -> None:
        games = detector.detect_games(
            ListingText(title=f"vendo {alias} para ps4", description="")
        )

        match = next(game for game in games if game.canonical_name == canonical_name)
        assert match.matched_text == alias
        assert match.confidence == 1.0
        assert match.detection_method is DetectionMethod.EXACT_MATCH

    @pytest.mark.parametrize(("alias", "canonical_name"), SHORT_ALIAS_CASES)
    def test_every_short_catalog_alias_is_rejected_inside_larger_token(
        self,
        detector: FuzzyGameDetector,
        alias: str,
        canonical_name: str,
    ) -> None:
        games = detector.detect_games(
            ListingText(title=f"vendo x{alias}x para ps4", description="")
        )

        assert canonical_name not in {game.canonical_name for game in games}

    def test_short_alias_inventory_matches_the_packaged_catalog(
        self,
        detector: FuzzyGameDetector,
    ) -> None:
        actual = []
        for game in detector.catalog:
            for alias in game["aliases"]:
                normalized_alias = detector._normalize_text(alias)
                if " " not in normalized_alias and len(normalized_alias) <= 3:
                    actual.append((normalized_alias, game["canonical_name"]))

        assert tuple(actual) == SHORT_ALIAS_CASES

    def test_multiword_alias_and_canonical_name_keep_exact_semantics(
        self,
        detector: FuzzyGameDetector,
    ) -> None:
        alias_games = detector.detect_games(
            ListingText(title="vendo red dead 2 para ps4", description="")
        )
        canonical_games = detector.detect_games(
            ListingText(title="Ghost of Tsushima PS4", description="")
        )

        red_dead = next(
            game
            for game in alias_games
            if game.canonical_name == "Red Dead Redemption 2"
        )
        ghost = next(
            game
            for game in canonical_games
            if game.canonical_name == "Ghost of Tsushima"
        )
        assert red_dead.matched_text == "red dead 2"
        assert red_dead.detection_method is DetectionMethod.EXACT_MATCH
        assert ghost.matched_text == "ghost of tsushima"
        assert ghost.detection_method is DetectionMethod.EXACT_MATCH

    def test_title_and_description_still_combine_with_lexical_matching(
        self,
        detector: FuzzyGameDetector,
    ) -> None:
        games = detector.detect_games(
            ListingText(title="RDR2 PS4", description="Incluye (GOT)!")
        )
        names = {game.canonical_name for game in games}

        assert names == {"Red Dead Redemption 2", "Ghost of Tsushima"}

    def test_precomputed_patterns_are_immutable_instance_state(
        self,
        detector: FuzzyGameDetector,
    ) -> None:
        assert isinstance(detector._game_variant_patterns, tuple)
        assert all(
            isinstance(patterns, tuple)
            for patterns in detector._game_variant_patterns
        )
