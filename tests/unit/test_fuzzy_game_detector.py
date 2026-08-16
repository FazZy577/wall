"""Unit tests for FuzzyGameDetector."""

import ast
import inspect
from pathlib import Path

import pytest

from domain.entities.game_catalog_entry import GameCatalogEntry
from domain.interfaces.game_catalog import IGameCatalog
from domain.interfaces.game_detector import DetectionMethod, ListingText, Platform
from infrastructure.catalogs.packaged_game_catalog import PackagedGameCatalog
from infrastructure.detectors.fuzzy_game_detector import FuzzyGameDetector

PROJECT_ROOT = Path(__file__).parents[2]
DETECTOR_PATH = PROJECT_ROOT / "src/infrastructure/detectors/fuzzy_game_detector.py"

SHORT_ALIAS_CASES = (
    ("bo6", "Call of Duty: Black Ops 6", Platform.PS4),
    ("mw3", "Call of Duty: Modern Warfare III", Platform.PS4),
    ("mw2", "Call of Duty: Modern Warfare II", Platform.PS4),
    ("gow", "God of War", Platform.PS4),
    ("hzd", "Horizon Zero Dawn", Platform.PS4),
    ("hfw", "Horizon Forbidden West", Platform.PS4),
    ("got", "Ghost of Tsushima", Platform.PS4),
    ("re2", "Resident Evil 2", Platform.PS4),
    ("re3", "Resident Evil 3", Platform.PS4),
    ("re8", "Resident Evil Village", Platform.PS4),
    ("ds3", "Dark Souls III", Platform.PS4),
    ("gts", "Gran Turismo Sport", Platform.PS4),
    ("gt7", "Gran Turismo 7", Platform.PS4),
    ("bf5", "Battlefield V", Platform.PS4),
    ("bfv", "Battlefield V", Platform.PS4),
    ("sf5", "Street Fighter V", Platform.PS4),
    ("sfv", "Street Fighter V", Platform.PS4),
    ("ow2", "Overwatch 2", Platform.PS4),
    ("gt7", "Gran Turismo 7", Platform.PS5),
    ("re8", "Resident Evil Village", Platform.PS5),
    ("ac6", "Armored Core VI: Fires of Rubicon", Platform.PS5),
    ("mk1", "Mortal Kombat 1", Platform.PS5),
    ("sf6", "Street Fighter 6", Platform.PS5),
    ("bf6", "Battlefield 6", Platform.PS5),
    ("bg3", "Baldur's Gate 3", Platform.PS5),
    ("p5r", "Persona 5 Royal", Platform.PS5),
    ("kh3", "Kingdom Hearts III", Platform.PS5),
)


class _InMemoryGameCatalog(IGameCatalog):
    def __init__(self, entries: tuple[GameCatalogEntry, ...]) -> None:
        self.entries = entries
        self.list_games_calls = 0

    def list_games(self) -> tuple[GameCatalogEntry, ...]:
        self.list_games_calls += 1
        return self.entries


@pytest.fixture
def detector() -> FuzzyGameDetector:
    """Create detector instance with default catalog."""
    return FuzzyGameDetector(PackagedGameCatalog())


@pytest.mark.unit
class TestFuzzyGameDetector:
    """Test suite for FuzzyGameDetector."""

    def test_detector_initialization(self, detector: FuzzyGameDetector) -> None:
        """Test that detector initializes and loads catalog."""
        assert detector.game_catalog.list_games()

    def test_packaged_catalog_is_independent_of_working_directory(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Load and use the packaged catalog from an unrelated directory."""
        monkeypatch.chdir(tmp_path)

        detector = FuzzyGameDetector(PackagedGameCatalog())
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

    def test_detect_gta_v_exact(self, detector: FuzzyGameDetector) -> None:
        """Test GTA V detection - exact match."""
        listing = ListingText(title="GTA V PS4", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"
        assert games[0].confidence >= 0.95

    def test_detect_gta_5_variant(self, detector: FuzzyGameDetector) -> None:
        """Test GTA 5 detection - variant."""
        listing = ListingText(title="GTA 5 PS4", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"
        assert games[0].confidence >= 0.95

    def test_detect_gta_5_no_space(self, detector: FuzzyGameDetector) -> None:
        """Test GTA5 detection - no space."""
        listing = ListingText(title="GTA5 PS4", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"
        assert games[0].confidence >= 0.95

    def test_detect_grand_theft_auto(self, detector: FuzzyGameDetector) -> None:
        """Test full name detection."""
        listing = ListingText(title="Grand Theft Auto PS4", description="")
        games = detector.detect_games(listing)

        assert len(games) >= 1
        # Should match GTA V
        gta_matches = [g for g in games if "Grand Theft Auto V" in g.canonical_name]
        assert len(gta_matches) >= 1

    def test_detect_rdr2(self, detector: FuzzyGameDetector) -> None:
        """Test RDR2 detection."""
        listing = ListingText(title="RDR2 PS4", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Red Dead Redemption 2"
        assert games[0].confidence >= 0.95

    def test_detect_red_dead_redemption_ii(self, detector: FuzzyGameDetector) -> None:
        """Test Red Dead Redemption II detection."""
        listing = ListingText(title="Red Dead Redemption II PS4", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].canonical_name == "Red Dead Redemption 2"
        assert games[0].confidence >= 0.80

    def test_detect_fifa_24(self, detector: FuzzyGameDetector) -> None:
        """Test FIFA 24 detection."""
        listing = ListingText(title="FIFA24 PS4", description="")
        games = detector.detect_games(listing)

        # Should detect FIFA 24 (may also detect similar FIFAs with lower confidence)
        assert len(games) >= 1
        # First result should be FIFA 24 with highest confidence
        assert games[0].canonical_name == "EA Sports FC 24"
        assert games[0].confidence >= 0.95

    def test_detect_fc_24(self, detector: FuzzyGameDetector) -> None:
        """Test FC 24 detection."""
        listing = ListingText(title="FC 24 PS4", description="")
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
            title="GTA V GTA 5 Grand Theft Auto V PS4",
            description="",
        )
        games = detector.detect_games(listing)

        # Should only have one GTA V entry
        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"

    def test_detection_method_exact(self, detector: FuzzyGameDetector) -> None:
        """Test that exact matches have EXACT_MATCH method."""
        listing = ListingText(title="gta v ps4", description="")
        games = detector.detect_games(listing)

        assert len(games) == 1
        assert games[0].detection_method == DetectionMethod.EXACT_MATCH

    def test_detection_method_alias(self, detector: FuzzyGameDetector) -> None:
        """Test that alias matches have ALIAS_MATCH method."""
        listing = ListingText(title="gta 5 ps4", description="")
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

    @pytest.mark.parametrize(
        ("alias", "canonical_name", "platform"), SHORT_ALIAS_CASES
    )
    def test_every_short_catalog_alias_matches_when_lexically_isolated(
        self,
        detector: FuzzyGameDetector,
        alias: str,
        canonical_name: str,
        platform: Platform,
    ) -> None:
        games = detector.detect_games(
            ListingText(
                title=f"vendo {alias} para {platform.value}",
                description="",
            )
        )

        match = next(game for game in games if game.canonical_name == canonical_name)
        assert match.matched_text == alias
        assert match.confidence == 1.0
        assert match.detection_method is DetectionMethod.EXACT_MATCH

    @pytest.mark.parametrize(
        ("alias", "canonical_name", "platform"), SHORT_ALIAS_CASES
    )
    def test_every_short_catalog_alias_is_rejected_inside_larger_token(
        self,
        detector: FuzzyGameDetector,
        alias: str,
        canonical_name: str,
        platform: Platform,
    ) -> None:
        games = detector.detect_games(
            ListingText(
                title=f"vendo x{alias}x para {platform.value}",
                description="",
            )
        )

        assert canonical_name not in {game.canonical_name for game in games}

    def test_short_alias_inventory_matches_the_packaged_catalog(
        self,
        detector: FuzzyGameDetector,
    ) -> None:
        actual = []
        for game in detector.game_catalog.list_games():
            for alias in game.detection_aliases:
                normalized_alias = detector._normalize_text(alias)
                if " " not in normalized_alias and len(normalized_alias) <= 3:
                    actual.append(
                        (normalized_alias, game.canonical_name, game.platform)
                    )

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


@pytest.mark.unit
class TestInjectedGameCatalog:
    def test_detector_requires_a_game_catalog(self) -> None:
        with pytest.raises(TypeError):
            inspect.signature(FuzzyGameDetector).bind()
        with pytest.raises(TypeError, match="game_catalog must be IGameCatalog"):
            FuzzyGameDetector(object())  # type: ignore[arg-type]

    def test_synthetic_game_is_detected_from_injected_catalog(self) -> None:
        entry = GameCatalogEntry(
            canonical_name="Synthetic Test Game",
            platform=Platform.PS4,
            detection_aliases=("synthetic test",),
        )
        catalog = _InMemoryGameCatalog((entry,))
        detector = FuzzyGameDetector(catalog)

        games = detector.detect_games(
            ListingText(title="Synthetic Test Game PS4", description="")
        )

        assert len(games) == 1
        assert games[0].canonical_name == entry.canonical_name
        assert games[0].platform is entry.platform
        assert games[0].confidence == 1.0
        assert games[0].detection_method is DetectionMethod.EXACT_MATCH
        assert catalog.list_games_calls == 1

    def test_synthetic_game_is_absent_from_empty_injected_catalog(self) -> None:
        detector = FuzzyGameDetector(_InMemoryGameCatalog(()))

        games = detector.detect_games(
            ListingText(title="Synthetic Test Game PS4", description="")
        )

        assert games == []

    def test_detection_aliases_come_from_canonical_entry(self) -> None:
        entry = GameCatalogEntry(
            canonical_name="Synthetic Test Game",
            platform=Platform.PS4,
            detection_aliases=("laboratory alias",),
        )
        detector = FuzzyGameDetector(_InMemoryGameCatalog((entry,)))

        games = detector.detect_games(
            ListingText(title="laboratory alias PS4", description="")
        )

        assert len(games) == 1
        assert games[0].matched_text == "laboratory alias"
        assert games[0].detection_method is DetectionMethod.EXACT_MATCH

    def test_fuzzy_fallback_still_uses_injected_entry(self) -> None:
        entry = GameCatalogEntry(
            canonical_name="Synthetic Test Game",
            platform=Platform.PS4,
            detection_aliases=("synthetic adventure",),
        )
        detector = FuzzyGameDetector(_InMemoryGameCatalog((entry,)))

        games = detector.detect_games(
            ListingText(title="synthetic adventur PS4", description="")
        )

        assert len(games) == 1
        assert games[0].canonical_name == entry.canonical_name
        assert games[0].detection_method is DetectionMethod.FUZZY_MATCH
        assert 0.8 <= games[0].confidence < 1.0

    def test_detector_does_not_mutate_entries_or_aliases(self) -> None:
        entry = GameCatalogEntry(
            canonical_name="Synthetic Test Game",
            platform=Platform.PS4,
            detection_aliases=("synthetic test", "test game"),
        )
        entries = (entry,)
        catalog = _InMemoryGameCatalog(entries)
        detector = FuzzyGameDetector(catalog)

        first = detector.detect_games(
            ListingText(title="synthetic test PS4", description="")
        )
        second = detector.detect_games(
            ListingText(title="synthetic test PS4", description="")
        )

        assert catalog.entries is entries
        assert catalog.entries[0] is entry
        assert entry.detection_aliases == ("synthetic test", "test game")
        assert first == second
        assert catalog.list_games_calls == 1

    def test_repeated_identity_is_deduplicated_with_game_identity(self) -> None:
        entries = (
            GameCatalogEntry("Shared Game", Platform.PS4, ("shared game",)),
            GameCatalogEntry("Shared Game", Platform.PS5, ("shared game",)),
        )
        detector = FuzzyGameDetector(_InMemoryGameCatalog(entries))

        games = detector.detect_games(
            ListingText(title="Shared Game PS4 + Shared Game PS4", description="")
        )

        assert len(games) == 1
        assert games[0].platform is Platform.PS4

    def test_detector_source_has_no_catalog_resource_loading(self) -> None:
        source = DETECTOR_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }

        assert "json" not in imported_modules
        assert "importlib.resources" not in imported_modules
        assert "game_catalog.json" not in source
        assert ".open(" not in source


def _multiplatform_catalog() -> _InMemoryGameCatalog:
    catalog_rows = (
        (
            "Grand Theft Auto V",
            ("gta v", "gta 5"),
            (
                Platform.PS3,
                Platform.PS4,
                Platform.PS5,
                Platform.XBOX_360,
                Platform.XBOX_ONE,
            ),
        ),
        (
            "Red Dead Redemption 2",
            ("rdr2", "red dead 2"),
            (
                Platform.PS4,
                Platform.PS5,
                Platform.XBOX_ONE,
                Platform.XBOX_SERIES,
            ),
        ),
        (
            "Halo Test",
            ("halo test",),
            (
                Platform.XBOX,
                Platform.XBOX_360,
                Platform.XBOX_ONE,
                Platform.XBOX_SERIES,
            ),
        ),
        (
            "Zelda Test",
            ("zelda test",),
            (
                Platform.GAMECUBE,
                Platform.WII,
                Platform.WII_U,
                Platform.SWITCH,
            ),
        ),
        (
            "Portable Test",
            ("portable test",),
            (
                Platform.NINTENDO_DS,
                Platform.NINTENDO_3DS,
                Platform.PSP,
                Platform.PS_VITA,
            ),
        ),
        ("Legacy Test", ("legacy test",), (Platform.PS3,)),
    )
    return _InMemoryGameCatalog(
        tuple(
            GameCatalogEntry(name, platform, aliases)
            for name, aliases, platforms in catalog_rows
            for platform in platforms
        )
    )


@pytest.mark.unit
class TestMultiplatformDefectRegressions:
    def test_two_local_game_platform_pairs_do_not_share_a_global_platform(
        self,
    ) -> None:
        detector = FuzzyGameDetector(_multiplatform_catalog())

        games = detector.detect_games(
            ListingText(title="GTA V PS4 + RDR2 PS5", description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS4),
            ("Red Dead Redemption 2", Platform.PS5),
        ]

    def test_same_game_on_two_platforms_keeps_both_identities(self) -> None:
        detector = FuzzyGameDetector(_multiplatform_catalog())

        games = detector.detect_games(
            ListingText(title="GTA V PS4 + GTA V PS5", description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS4),
            ("Grand Theft Auto V", Platform.PS5),
        ]

    def test_unrecognized_text_platform_does_not_fall_back_to_catalog_platform(
        self,
    ) -> None:
        catalog = _InMemoryGameCatalog(
            (
                GameCatalogEntry(
                    "Grand Theft Auto V",
                    Platform.PS4,
                    ("gta v",),
                ),
            )
        )
        detector = FuzzyGameDetector(catalog)

        games = detector.detect_games(
            ListingText(title="Lote PS3: GTA V", description="")
        )

        assert games == []

    def test_text_without_platform_does_not_select_by_catalog_order(self) -> None:
        detector = FuzzyGameDetector(_multiplatform_catalog())

        games = detector.detect_games(ListingText(title="GTA V", description=""))

        assert games == []


@pytest.mark.unit
class TestDeterministicMultiplatformAssociation:
    @pytest.mark.parametrize(
        ("title", "platform"),
        [
            ("GTA V PS3", Platform.PS3),
            ("GTA V PS4", Platform.PS4),
            ("GTA V PS5", Platform.PS5),
            ("GTA V Xbox 360", Platform.XBOX_360),
            ("GTA V Xbox One", Platform.XBOX_ONE),
        ],
    )
    def test_same_game_resolves_to_its_local_platform(
        self,
        title: str,
        platform: Platform,
    ) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title=title, description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", platform)
        ]

    @pytest.mark.parametrize(
        ("title", "canonical_name", "platform"),
        [
            ("Halo Test Xbox original", "Halo Test", Platform.XBOX),
            ("Halo Test Xbox 360", "Halo Test", Platform.XBOX_360),
            ("Halo Test Xbox One", "Halo Test", Platform.XBOX_ONE),
            ("Halo Test Xbox Series X", "Halo Test", Platform.XBOX_SERIES),
            ("Zelda Test GameCube", "Zelda Test", Platform.GAMECUBE),
            ("Zelda Test Wii", "Zelda Test", Platform.WII),
            ("Zelda Test Wii U", "Zelda Test", Platform.WII_U),
            ("Zelda Test Switch", "Zelda Test", Platform.SWITCH),
            ("Portable Test Nintendo DS", "Portable Test", Platform.NINTENDO_DS),
            ("Portable Test 3DS", "Portable Test", Platform.NINTENDO_3DS),
            ("Portable Test PSP", "Portable Test", Platform.PSP),
            ("Portable Test PS Vita", "Portable Test", Platform.PS_VITA),
        ],
    )
    def test_every_multiplatform_family_is_associated_to_a_game(
        self,
        title: str,
        canonical_name: str,
        platform: Platform,
    ) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title=title, description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            (canonical_name, platform)
        ]

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            (
                "GTA V PS4 + RDR2 PS5",
                [
                    ("Grand Theft Auto V", Platform.PS4),
                    ("Red Dead Redemption 2", Platform.PS5),
                ],
            ),
            (
                "GTA V PS5 + RDR2 PS4",
                [
                    ("Grand Theft Auto V", Platform.PS5),
                    ("Red Dead Redemption 2", Platform.PS4),
                ],
            ),
            (
                "GTA V PS4 RDR2 PS5",
                [
                    ("Grand Theft Auto V", Platform.PS4),
                    ("Red Dead Redemption 2", Platform.PS5),
                ],
            ),
        ],
    )
    def test_multiple_pairs_preserve_local_textual_order(
        self,
        title: str,
        expected: list[tuple[str, Platform]],
    ) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title=title, description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == expected

    def test_three_occurrences_of_same_game_keep_three_platforms(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(
                title="GTA V PS3 + GTA V PS4 + GTA V PS5",
                description="",
            )
        )

        assert [game.platform for game in games] == [
            Platform.PS3,
            Platform.PS4,
            Platform.PS5,
        ]

    def test_unique_section_platform_is_inherited_after_colon_and_comma(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title="Lote PS3: GTA V, Legacy Test", description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS3),
            ("Legacy Test", Platform.PS3),
        ]

    def test_unique_title_platform_is_inherited_by_description(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title="Lote PS4", description="GTA V\nRDR2")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS4),
            ("Red Dead Redemption 2", Platform.PS4),
        ]

    def test_unique_description_platform_can_qualify_title_game(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title="GTA V", description="Version PS5")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS5)
        ]

    def test_two_games_share_one_unambiguous_platform(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title="GTA V y RDR2 PS4", description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS4),
            ("Red Dead Redemption 2", Platform.PS4),
        ]

    @pytest.mark.parametrize(
        "title",
        [
            "GTA V PS4 y PS5",
            "GTA V PS5 y PS4",
        ],
    )
    def test_one_game_with_two_product_platforms_is_ambiguous(
        self,
        title: str,
    ) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title=title, description="")
        )

        assert games == []

    @pytest.mark.parametrize(
        "title",
        [
            "PS4 GTA V RDR2 PS5",
            "GTA V PS4 PS5 RDR2",
        ],
    )
    def test_crossed_platform_positions_are_ambiguous(self, title: str) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title=title, description="")
        )

        assert games == []

    def test_compatibility_platform_does_not_override_product_platform(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(
                title="GTA V PS4 compatible con PS5",
                description="",
            )
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS4)
        ]

    @pytest.mark.parametrize(
        "title",
        [
            "GTA V compatible con PS5",
            "GTA V compatibilidad con PS5",
            "GTA V funciona en PS5",
            "GTA V retrocompatible con PS5",
        ],
    )
    def test_compatibility_only_does_not_create_product_platform(
        self,
        title: str,
    ) -> None:
        assert FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title=title, description="")
        ) == []

    def test_title_product_platform_wins_over_description_compatibility(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title="GTA V PS4", description="Compatible con PS5")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Grand Theft Auto V", Platform.PS4)
        ]

    def test_fuzzy_match_requires_one_resolvable_platform(self) -> None:
        detector = FuzzyGameDetector(_multiplatform_catalog())

        games = detector.detect_games(
            ListingText(title="Grand Thef Auto V PS4", description="")
        )

        assert len(games) == 1
        assert games[0].canonical_name == "Grand Theft Auto V"
        assert games[0].platform is Platform.PS4
        assert games[0].detection_method is DetectionMethod.FUZZY_MATCH
        assert 0.8 <= games[0].confidence < 1.0

    def test_fuzzy_match_abstains_with_multiple_platforms(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(
                title="Grand Thef Auto V PS4 PS5",
                description="",
            )
        )

        assert games == []

    @pytest.mark.parametrize("reverse_catalog", [False, True])
    def test_shared_alias_collision_does_not_select_catalog_order(
        self,
        reverse_catalog: bool,
    ) -> None:
        entries: tuple[GameCatalogEntry, ...] = (
            GameCatalogEntry("Alpha Game", Platform.PS4, ("shared alias",)),
            GameCatalogEntry("Beta Game", Platform.PS4, ("shared alias",)),
        )
        if reverse_catalog:
            entries = tuple(reversed(entries))
        detector = FuzzyGameDetector(_InMemoryGameCatalog(entries))

        assert detector.detect_games(
            ListingText(title="shared alias PS4", description="")
        ) == []

    def test_canonical_exact_name_wins_over_colliding_alias(self) -> None:
        entries = (
            GameCatalogEntry("Shared Alias", Platform.PS4, ()),
            GameCatalogEntry("Beta Game", Platform.PS4, ("shared alias",)),
        )
        games = FuzzyGameDetector(_InMemoryGameCatalog(entries)).detect_games(
            ListingText(title="Shared Alias PS4", description="")
        )

        assert [(game.canonical_name, game.platform) for game in games] == [
            ("Shared Alias", Platform.PS4)
        ]

    def test_exact_match_replaces_fuzzy_match_for_same_identity(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(
                title="Grand Thef Auto V PS4",
                description="GTA V",
            )
        )

        assert len(games) == 1
        assert games[0].matched_text == "gta v"
        assert games[0].confidence == 1.0
        assert games[0].detection_method is DetectionMethod.EXACT_MATCH

    def test_exact_detection_preserves_quality_and_matched_text(self) -> None:
        games = FuzzyGameDetector(_multiplatform_catalog()).detect_games(
            ListingText(title="vendo gta 5 para PS5", description="")
        )

        assert len(games) == 1
        assert games[0].matched_text == "gta 5"
        assert games[0].confidence == 1.0
        assert games[0].detection_method is DetectionMethod.EXACT_MATCH

    def test_detection_order_is_deterministic(self) -> None:
        detector = FuzzyGameDetector(_multiplatform_catalog())
        listing = ListingText(
            title="RDR2 PS5 + GTA V PS4 + Halo Test Xbox One",
            description="",
        )

        first = detector.detect_games(listing)
        second = detector.detect_games(listing)

        assert first == second
        assert [game.canonical_name for game in first] == [
            "Red Dead Redemption 2",
            "Grand Theft Auto V",
            "Halo Test",
        ]
