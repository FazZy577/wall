"""Unit tests for RuleBasedComparableFilter."""

import pytest

from domain.interfaces.comparable_filter import ComparableFilterInput
from domain.interfaces.game_detector import DetectedGame, DetectionMethod, Platform
from infrastructure.filters.rule_based_comparable_filter import RuleBasedComparableFilter


@pytest.fixture
def filter_instance() -> RuleBasedComparableFilter:
    """Create a filter instance for testing."""
    return RuleBasedComparableFilter()


@pytest.fixture
def gta_v_game() -> DetectedGame:
    """Sample GTA V game for testing."""
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


@pytest.fixture
def fifa_23_game() -> DetectedGame:
    """Sample FIFA 23 game for testing."""
    return DetectedGame(
        canonical_name="FIFA 23",
        matched_text="fifa 23",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


@pytest.fixture
def cod_bo6_game() -> DetectedGame:
    """Sample Call of Duty Black Ops 6 game for testing."""
    return DetectedGame(
        canonical_name="Call of Duty: Black Ops 6",
        matched_text="cod bo6",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


class TestValidComparables:
    """Test cases for valid comparable listings."""

    def test_simple_game_listing(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Simple game listing."""
        listing = ComparableFilterInput(
            title="GTA V PS4",
            description="Juego en buen estado",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_game_with_full_name(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Game with full canonical name."""
        listing = ComparableFilterInput(
            title="Grand Theft Auto V PS4",
            description="Estado perfecto",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_game_with_variant_spelling(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Game with variant spelling."""
        listing = ComparableFilterInput(
            title="GTA5 PlayStation 4",
            description="",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_game_with_accents(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Game listing with Spanish accents."""
        listing = ComparableFilterInput(
            title="GTA V Edición estándar",
            description="Juego usado en buen estado",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_fifa_23(
        self, filter_instance: RuleBasedComparableFilter, fifa_23_game: DetectedGame
    ) -> None:
        """Valid: FIFA 23 listing."""
        listing = ComparableFilterInput(
            title="FIFA 23 PS4",
            description="Juego de fútbol",
        )
        assert filter_instance.is_valid_comparable(fifa_23_game, listing) is True


class TestConsoleRejection:
    """Test cases for console-only listings (should be rejected)."""

    def test_console_only_short(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Console only, no games."""
        listing = ComparableFilterInput(
            title="PS4 (PlayStation 4) Negra",
            description="Consola en buen estado",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_console_with_accessories(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Console with accessories."""
        listing = ComparableFilterInput(
            title="PlayStation 4 Slim 1TB",
            description="Incluye mando y cable HDMI",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_xbox_console(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Xbox console."""
        listing = ComparableFilterInput(
            title="Xbox One 500GB",
            description="Console in good condition",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_nintendo_switch(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Nintendo Switch console."""
        listing = ComparableFilterInput(
            title="Nintendo Switch",
            description="Consola portátil",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False


class TestControllerRejection:
    """Test cases for controller listings (should be rejected)."""

    def test_dualshock_controller(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: DualShock controller."""
        listing = ComparableFilterInput(
            title="Mando DualShock 4 PS4",
            description="Mando original",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_dualsense_controller(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: DualSense controller."""
        listing = ComparableFilterInput(
            title="DualSense PS5 Blanco",
            description="Controller for PlayStation 5",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_generic_controller(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Generic controller mention."""
        listing = ComparableFilterInput(
            title="Controller PS4",
            description="Joystick inalámbrico",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_mando_spanish(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Spanish word for controller."""
        listing = ComparableFilterInput(
            title="Mando PS4 Blanco",
            description="En perfecto estado",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False


class TestAccessoryRejection:
    """Test cases for accessory listings (should be rejected)."""

    def test_case(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Case/funda."""
        listing = ComparableFilterInput(
            title="Funda PS4",
            description="Protector de silicona",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_hdmi_cable(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: HDMI cable."""
        listing = ComparableFilterInput(
            title="Cable HDMI PS4",
            description="2 metros",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_dock(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Dock/charging station."""
        listing = ComparableFilterInput(
            title="Dock de carga PS4",
            description="Para dos mandos",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_headset(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Headset."""
        listing = ComparableFilterInput(
            title="Auriculares PS4",
            description="Headset gaming",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False


class TestAccountRejection:
    """Test cases for account listings (should be rejected)."""

    def test_psn_account(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: PSN account."""
        listing = ComparableFilterInput(
            title="Cuenta PSN con juegos",
            description="Account with games",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_digital_code(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Digital code."""
        listing = ComparableFilterInput(
            title="GTA V Código Digital",
            description="Digital download code",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_xbox_live_account(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Xbox Live account."""
        listing = ComparableFilterInput(
            title="Xbox Live Account",
            description="Cuenta con suscripción",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False


class TestEmptyBoxRejection:
    """Test cases for empty box listings (should be rejected)."""

    def test_box_without_disc(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Box without disc."""
        listing = ComparableFilterInput(
            title="Caja GTA V sin disco",
            description="Solo la caja original",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_empty_steelbook(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Empty steelbook."""
        listing = ComparableFilterInput(
            title="Steelbook GTA V",
            description="Sin disco, solo caja metálica",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_box_only_english(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Box only (English)."""
        listing = ComparableFilterInput(
            title="GTA V Box",
            description="Empty box, no game",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_box_without_disc_italian(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Box without disc (Italian)."""
        listing = ComparableFilterInput(
            title="Caja FIFA 23",
            description="Senza disco",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False


class TestBundleRejection:
    """Test cases for bundle/lot listings (should be rejected)."""

    def test_lote_multiple_games(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Lote with multiple games."""
        listing = ComparableFilterInput(
            title="Lote GTA V + RDR2 + FIFA 23",
            description="3 juegos por el precio de 2",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_pack_games(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Pack of games."""
        listing = ComparableFilterInput(
            title="Pack juegos PS4",
            description="GTA V, God of War, Uncharted",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_coleccion(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Collection."""
        listing = ComparableFilterInput(
            title="Colección juegos Rockstar",
            description="GTA V y Red Dead Redemption 2",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_bundle_english(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Bundle (English)."""
        listing = ComparableFilterInput(
            title="Game Bundle PS4",
            description="Multiple games included",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False


class TestWrongGameRejection:
    """Test cases for wrong game versions (should be rejected)."""

    def test_gta_trilogy_vs_gta_v(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: GTA Trilogy when looking for GTA V."""
        listing = ComparableFilterInput(
            title="GTA Trilogy PS4",
            description="3 juegos clásicos",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_fifa_20_vs_fifa_23(
        self, filter_instance: RuleBasedComparableFilter, fifa_23_game: DetectedGame
    ) -> None:
        """Reject: FIFA 20 when looking for FIFA 23."""
        listing = ComparableFilterInput(
            title="FIFA 20 PS4",
            description="Juego de fútbol",
        )
        assert filter_instance.is_valid_comparable(fifa_23_game, listing) is False

    def test_fifa_18_vs_fifa_23(
        self, filter_instance: RuleBasedComparableFilter, fifa_23_game: DetectedGame
    ) -> None:
        """Reject: FIFA 18 when looking for FIFA 23."""
        listing = ComparableFilterInput(
            title="FIFA 18",
            description="Edición estándar",
        )
        assert filter_instance.is_valid_comparable(fifa_23_game, listing) is False

    def test_cod_bo3_vs_cod_bo6(
        self, filter_instance: RuleBasedComparableFilter, cod_bo6_game: DetectedGame
    ) -> None:
        """Reject: Black Ops 3 when looking for Black Ops 6."""
        listing = ComparableFilterInput(
            title="Call of Duty Black Ops 3 PS4",
            description="COD BO3",
        )
        assert filter_instance.is_valid_comparable(cod_bo6_game, listing) is False

    def test_cod_bo4_vs_cod_bo6(
        self, filter_instance: RuleBasedComparableFilter, cod_bo6_game: DetectedGame
    ) -> None:
        """Reject: Black Ops 4 when looking for Black Ops 6."""
        listing = ComparableFilterInput(
            title="COD Black Ops 4",
            description="",
        )
        assert filter_instance.is_valid_comparable(cod_bo6_game, listing) is False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_title_and_description(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Edge case: Empty strings."""
        listing = ComparableFilterInput(title="", description="")
        # Should reject due to no game match
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_very_short_listing(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Edge case: Very short listing."""
        listing = ComparableFilterInput(title="PS4", description="")
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_game_with_console_mention(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Game with console mention (but game is primary)."""
        listing = ComparableFilterInput(
            title="GTA V para PS4",
            description="Videojuego Grand Theft Auto V compatible con PlayStation 4",
        )
        # Should be valid because game is clearly mentioned
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_game_multiple_platforms(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Game compatible with multiple platforms."""
        listing = ComparableFilterInput(
            title="GTA V PS4/PS5",
            description="Compatible con ambas consolas",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_special_characters_in_title(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Title with special characters."""
        listing = ComparableFilterInput(
            title="🎮 GTA V - PS4 ⭐⭐⭐⭐⭐",
            description="Estado perfecto!!!",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_uppercase_listing(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: All uppercase listing."""
        listing = ComparableFilterInput(
            title="GTA V PS4",
            description="JUEGO EN PERFECTO ESTADO",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_mixed_languages(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Mixed Spanish and English."""
        listing = ComparableFilterInput(
            title="GTA V PS4 Game",
            description="Juego en good condition",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True


class TestNormalization:
    """Test text normalization functionality."""

    def test_normalize_accents(self, filter_instance: RuleBasedComparableFilter) -> None:
        """Test accent removal."""
        normalized = filter_instance._normalize_text("Edición Estándar")
        assert "ó" not in normalized
        assert "á" not in normalized
        assert "edicion" in normalized
        assert "estandar" in normalized

    def test_normalize_special_chars(
        self, filter_instance: RuleBasedComparableFilter
    ) -> None:
        """Test special character removal."""
        normalized = filter_instance._normalize_text("GTA-V (2013) ¡Nuevo!")
        assert "-" not in normalized
        assert "(" not in normalized
        assert "¡" not in normalized
        assert "gta" in normalized
        assert "v" in normalized
        assert "2013" in normalized

    def test_normalize_multiple_spaces(
        self, filter_instance: RuleBasedComparableFilter
    ) -> None:
        """Test multiple space collapse."""
        normalized = filter_instance._normalize_text("GTA    V     PS4")
        assert "    " not in normalized
        assert normalized == "gta v ps4"


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_steelbook_with_game(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Steelbook is not modeled as the standard game."""
        listing = ComparableFilterInput(
            title="GTA V Steelbook Edition PS4",
            description="Incluye el juego completo en disco",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_special_edition(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Reject: Premium edition is not modeled as the standard game."""
        listing = ComparableFilterInput(
            title="GTA V Premium Edition PS4",
            description="Incluye contenido adicional",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is False

    def test_used_game(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Used game listing."""
        listing = ComparableFilterInput(
            title="GTA V PS4 Usado",
            description="Buen estado, disco funciona perfectamente",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True

    def test_sealed_new_game(
        self, filter_instance: RuleBasedComparableFilter, gta_v_game: DetectedGame
    ) -> None:
        """Valid: Sealed new game."""
        listing = ComparableFilterInput(
            title="GTA V PS4 Nuevo Precintado",
            description="Sin abrir, sellado de fábrica",
        )
        assert filter_instance.is_valid_comparable(gta_v_game, listing) is True


@pytest.mark.parametrize(
    "title",
    [
        "GTA V Premium Edition PS4",
        "GTA V Edición Premium PS4",
        "GTA V Special Edition PS4",
        "GTA V Edición Especial PS4",
        "GTA V Ultimate Edition PS4",
        "GTA V Deluxe Edition PS4",
        "GTA V Collector's Edition PS4",
        "GTA V Collector’s Edition PS4",
        "GTA V Collector Edition PS4",
        "GTA V Edición Coleccionista PS4",
        "GTA V Gold Edition PS4",
        "GTA V Complete Edition PS4",
        "GTA V Anniversary Edition PS4",
        "GTA V Limited Edition PS4",
        "GTA V Edición Limitada PS4",
        "GTA V Steelbook PS4 con disco",
        "GTA V caja metálica PS4",
        "GTA V edición metálica PS4",
        "GTA V GOTY PS4",
        "GTA V Game of the Year PS4",
        "GTA V PS4 incluye DLC",
        "GTA V PS4 con DLC",
        "GTA V PS4 DLCs",
        "GTA V PS4 season pass",
        "GTA V PS4 pase de temporada",
        "GTA V PS4 contenido descargable incluido",
        "GTA V PS4 códigos sin usar",
        "GTA V PS4 con extras",
        "GTA V PS4 contenido adicional",
        "GTA V PS4 expansión incluida",
        "GTA V PS4 sin mapa",
        "GTA V PS4 sin manual",
        "GTA V PS4 sin carátula",
        "GTA V PS4 solo disco",
        "GTA V PS4 disco suelto",
        "GTA V PS4 solo caja",
        "GTA V PS4 caja vacía",
        "GTA V PS4 sin disco",
        "GTA V PS4 caja y manual sin juego",
    ],
)
def test_unmodeled_editions_content_and_incomplete_copies_are_rejected(
    filter_instance: RuleBasedComparableFilter,
    gta_v_game: DetectedGame,
    title: str,
) -> None:
    listing = ComparableFilterInput(title=title, description="")

    assert filter_instance.is_valid_comparable(gta_v_game, listing) is False


@pytest.mark.parametrize(
    "title",
    [
        "GTA V PS4",
        "GTA V PS4 Edición estándar",
        "GTA V PS4 Standard Edition",
        "GTA V PS4 juego completo",
        "GTA V PS4 con caja",
        "GTA V PS4 buen estado",
        "GTA V PS4 usado como nuevo",
        "GTA V PS4 Premium condition",
        "GTA V PS4 especial para regalo",
        "GTA V PS4 última unidad",
        "GTA V PS4 deluxe estado",
        "GTA V PS4 no incluye DLC",
        "GTA V PS4 sin contenido adicional",
        "GTA V PS4 DLC no incluido",
        "GTA V PS4 DLC disponible por separado",
    ],
)
def test_standard_and_contextually_similar_listings_remain_comparable(
    filter_instance: RuleBasedComparableFilter,
    gta_v_game: DetectedGame,
    title: str,
) -> None:
    listing = ComparableFilterInput(title=title, description="")

    assert filter_instance.is_valid_comparable(gta_v_game, listing) is True
