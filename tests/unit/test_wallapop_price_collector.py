"""Unit tests for WallapopPriceCollector.

Tests the orchestration of WallapopClient → GameDetector → ComparableFilter
using mocks (no real API calls).
"""

from unittest.mock import AsyncMock, Mock

import pytest

from domain.entities.candidate_listing import CandidateListing
from domain.entities.comparable_listing import ComparableListing
from domain.interfaces.game_detector import (
    DetectedGame,
    DetectionMethod,
    Platform,
)
from infrastructure.collectors.wallapop_price_collector import WallapopPriceCollector


@pytest.fixture
def mock_wallapop_client() -> Mock:
    """Create a mock marketplace search implementation."""
    client = Mock()
    client.search_listings = AsyncMock()
    return client


@pytest.fixture
def mock_game_detector() -> Mock:
    """Create mock GameDetector."""
    detector = Mock()
    detector.detect_games = Mock()
    return detector


@pytest.fixture
def mock_comparable_filter() -> Mock:
    """Create mock ComparableFilter."""
    filter_mock = Mock()
    filter_mock.is_valid_comparable = Mock()
    return filter_mock


@pytest.fixture
def target_game() -> DetectedGame:
    """Create target game for testing."""
    return DetectedGame(
        canonical_name="Grand Theft Auto V",
        matched_text="gta v",
        platform=Platform.PS4,
        confidence=1.0,
        detection_method=DetectionMethod.EXACT_MATCH,
    )


@pytest.fixture
def price_collector(
    mock_wallapop_client: Mock,
    mock_game_detector: Mock,
    mock_comparable_filter: Mock,
) -> WallapopPriceCollector:
    """Create WallapopPriceCollector with mocks."""
    return WallapopPriceCollector(
        marketplace_search=mock_wallapop_client,
        game_detector=mock_game_detector,
        comparable_filter=mock_comparable_filter,
    )


class TestSearchQueryGeneration:
    """Test search query generation from game."""

    def test_gta_v_canonical_name(self, price_collector: WallapopPriceCollector) -> None:
        """Should convert 'Grand Theft Auto V' to 'GTA V'."""
        game = DetectedGame(
            canonical_name="Grand Theft Auto V",
            matched_text="grand theft auto v ps4",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        query = price_collector._generate_search_query(game)
        assert query == "GTA V"

    def test_gta_5_with_number(self, price_collector: WallapopPriceCollector) -> None:
        """Should convert 'Grand Theft Auto 5' to 'GTA 5'."""
        game = DetectedGame(
            canonical_name="Grand Theft Auto 5",
            matched_text="grand theft auto 5",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        query = price_collector._generate_search_query(game)
        assert query == "GTA 5"

    def test_short_matched_text(self, price_collector: WallapopPriceCollector) -> None:
        """Should use short matched_text directly."""
        game = DetectedGame(
            canonical_name="Grand Theft Auto V",
            matched_text="gta v",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        query = price_collector._generate_search_query(game)
        assert query == "gta v"

    def test_call_of_duty(self, price_collector: WallapopPriceCollector) -> None:
        """Should convert 'Call of Duty: Black Ops 6' to 'COD black ops 6'."""
        game = DetectedGame(
            canonical_name="Call of Duty: Black Ops 6",
            matched_text="call of duty black ops 6",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        query = price_collector._generate_search_query(game)
        assert query == "COD black ops 6"

    def test_fifa_with_year(self, price_collector: WallapopPriceCollector) -> None:
        """Should convert 'FIFA 23' to 'FIFA 23'."""
        game = DetectedGame(
            canonical_name="FIFA 23",
            matched_text="fifa 23",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        query = price_collector._generate_search_query(game)
        assert query == "fifa 23"

    def test_ea_sports_fc(self, price_collector: WallapopPriceCollector) -> None:
        """Should convert 'EA Sports FC 24' to 'FC 24'."""
        game = DetectedGame(
            canonical_name="EA Sports FC 24",
            matched_text="ea sports fc 24",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        query = price_collector._generate_search_query(game)
        assert query == "FC 24"

    def test_red_dead_redemption(self, price_collector: WallapopPriceCollector) -> None:
        """Should use canonical name + platform for uncommon games."""
        game = DetectedGame(
            canonical_name="Red Dead Redemption 2",
            matched_text="red dead redemption 2",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        query = price_collector._generate_search_query(game)
        assert query == "Red Dead Redemption 2 PS4"


class TestListingProcessing:
    """Test individual listing processing."""

    def test_valid_comparable(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should return ComparableListing for valid comparable."""
        raw_listing = {
            "id": 123456,
            "title": "GTA V PS4",
            "description": "Juego en buen estado",
            "price": 15.0,
            "currency": "EUR",
            "web_slug": "gta-v-ps4-123456",
        }

        # Mock game detector to return target game
        mock_game_detector.detect_games.return_value = [target_game]

        # Mock comparable filter to accept
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is not None
        assert isinstance(result, ComparableListing)
        assert not isinstance(result, CandidateListing)
        assert result.listing_id == "123456"
        assert result.title == "GTA V PS4"
        assert result.description == "Juego en buen estado"
        assert result.price == 15.0
        assert result.currency == "EUR"
        assert result.detected_game == target_game
        assert result.url == "https://es.wallapop.com/item/gta-v-ps4-123456"
        assert result.raw_listing is raw_listing

    @pytest.mark.parametrize(
        ("raw_id", "expected"),
        [("ABC-001", "ABC-001"), (" 00123 ", "00123"), (123456, "123456")],
    )
    def test_normalizes_supported_external_listing_ids(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
        raw_id: object,
        expected: str,
    ) -> None:
        raw_listing = {
            "id": raw_id,
            "title": "GTA V PS4",
            "description": "Juego",
            "price": 15,
            "currency": "EUR",
        }
        mock_game_detector.detect_games.return_value = [target_game]
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is not None
        assert result.listing_id == expected

    @pytest.mark.parametrize("raw_id", [None, "", "   ", True, False, 123.0])
    def test_rejects_missing_or_unsupported_external_listing_ids(
        self,
        price_collector: WallapopPriceCollector,
        target_game: DetectedGame,
        raw_id: object,
    ) -> None:
        raw_listing = {
            "id": raw_id,
            "title": "GTA V PS4",
            "description": "Juego",
            "price": 15,
            "currency": "EUR",
        }

        assert price_collector._process_listing(raw_listing, target_game) is None

    def test_game_not_detected(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should return None if target game not detected."""
        raw_listing = {
            "id": 123456,
            "title": "FIFA 23 PS4",
            "description": "Juego de fútbol",
            "price": 20.0,
            "currency": "EUR",
            "web_slug": "fifa-23-ps4-123456",
        }

        # Mock detector to return different game
        other_game = DetectedGame(
            canonical_name="FIFA 23",
            matched_text="fifa 23",
            platform=Platform.PS4,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        mock_game_detector.detect_games.return_value = [other_game]

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is None

    def test_same_canonical_name_on_different_platform_is_rejected(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """A canonical-name match must not hide a platform mismatch."""
        ps5_game = DetectedGame(
            canonical_name=target_game.canonical_name,
            matched_text="gta v ps5",
            platform=Platform.PS5,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        raw_listing = {
            "id": "ps5-result",
            "title": "GTA V PS5",
            "description": "Juego",
            "price": 20,
            "currency": "EUR",
        }
        mock_game_detector.detect_games.return_value = [ps5_game]

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is None
        mock_comparable_filter.is_valid_comparable.assert_not_called()

    def test_unknown_platform_is_not_a_wildcard(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """UNKNOWN must compare exactly like every other platform."""
        unknown_game = DetectedGame(
            canonical_name=target_game.canonical_name,
            matched_text="gta v",
            platform=Platform.UNKNOWN,
            confidence=1.0,
            detection_method=DetectionMethod.EXACT_MATCH,
        )
        raw_listing = {
            "id": "unknown-platform",
            "title": "GTA V",
            "description": "Juego",
            "price": 20,
            "currency": "EUR",
        }
        mock_game_detector.detect_games.return_value = [unknown_game]

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is None
        mock_comparable_filter.is_valid_comparable.assert_not_called()

    def test_no_games_detected(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should return None if no games detected."""
        raw_listing = {
            "id": 123456,
            "title": "Mando PS4",
            "description": "Controller",
            "price": 25.0,
            "currency": "EUR",
            "web_slug": "mando-ps4-123456",
        }

        # Mock detector to return no games
        mock_game_detector.detect_games.return_value = []

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is None

    def test_rejected_by_comparable_filter(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should return None if comparable filter rejects listing."""
        raw_listing = {
            "id": 123456,
            "title": "Lote GTA V + FIFA 23",
            "description": "2 juegos",
            "price": 30.0,
            "currency": "EUR",
            "web_slug": "lote-juegos-123456",
        }

        # Mock game detector to return target game
        mock_game_detector.detect_games.return_value = [target_game]

        # Mock comparable filter to reject
        mock_comparable_filter.is_valid_comparable.return_value = False

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is None

    def test_missing_required_fields(
        self,
        price_collector: WallapopPriceCollector,
        target_game: DetectedGame,
    ) -> None:
        """Should return None if required fields missing."""
        # Missing title
        raw_listing_no_title = {
            "id": 123456,
            "description": "Juego",
            "price": 15.0,
        }
        assert price_collector._process_listing(raw_listing_no_title, target_game) is None

        # Missing price
        raw_listing_no_price = {
            "id": 123456,
            "title": "GTA V PS4",
            "description": "Juego",
        }
        assert price_collector._process_listing(raw_listing_no_price, target_game) is None

        # Missing id
        raw_listing_no_id = {
            "title": "GTA V PS4",
            "description": "Juego",
            "price": 15.0,
        }
        assert price_collector._process_listing(raw_listing_no_id, target_game) is None

    def test_invalid_price_format(
        self,
        price_collector: WallapopPriceCollector,
        target_game: DetectedGame,
    ) -> None:
        """Should return None if price cannot be converted to float."""
        raw_listing = {
            "id": 123456,
            "title": "GTA V PS4",
            "description": "Juego",
            "price": "invalid",
            "currency": "EUR",
        }

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is None

    def test_missing_web_slug(
        self,
        price_collector: WallapopPriceCollector,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should handle missing web_slug gracefully."""
        raw_listing = {
            "id": 123456,
            "title": "GTA V PS4",
            "description": "Juego",
            "price": 15.0,
            "currency": "EUR",
        }

        # Mock game detector and filter
        mock_game_detector.detect_games.return_value = [target_game]
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = price_collector._process_listing(raw_listing, target_game)

        assert result is not None
        assert result.url == ""


class TestCollectComparables:
    """Test end-to-end comparable collection."""

    @pytest.mark.asyncio
    async def test_successful_collection(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should collect valid comparables successfully."""
        # Mock Wallapop response
        mock_wallapop_client.search_listings.return_value = [
            {
                "id": 1,
                "title": "GTA V PS4",
                "description": "Juego en buen estado",
                "price": 15.0,
                "currency": "EUR",
                "web_slug": "gta-v-ps4-1",
            },
            {
                "id": 2,
                "title": "GTA V Premium PS4",
                "description": "Edición premium",
                "price": 18.0,
                "currency": "EUR",
                "web_slug": "gta-v-premium-ps4-2",
            },
        ]

        # Mock game detector to always return target game
        mock_game_detector.detect_games.return_value = [target_game]

        # Mock comparable filter to always accept
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        assert len(result) == 2
        assert all(isinstance(c, ComparableListing) for c in result)
        assert result[0].price == 15.0
        assert result[1].price == 18.0

    @pytest.mark.asyncio
    async def test_mixed_results_keep_only_complete_game_identity_in_input_order(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Collection filters name and platform without mutation or deduplication."""
        ps5 = DetectedGame(
            target_game.canonical_name,
            "gta v ps5",
            Platform.PS5,
            1.0,
            DetectionMethod.EXACT_MATCH,
        )
        fifa_ps4 = DetectedGame(
            "FIFA 24",
            "fifa 24 ps4",
            Platform.PS4,
            1.0,
            DetectionMethod.EXACT_MATCH,
        )
        xbox = DetectedGame(
            target_game.canonical_name,
            "gta v xbox one",
            Platform.XBOX_ONE,
            1.0,
            DetectionMethod.EXACT_MATCH,
        )
        raw_listings = [
            {"id": "1", "title": "GTA V PS5", "description": "", "price": 21, "currency": "EUR"},
            {"id": "valid-duplicate", "title": "GTA V PS4", "description": "", "price": 12, "currency": "EUR"},
            {"id": "3", "title": "FIFA 24 PS4", "description": "", "price": 14, "currency": "EUR"},
            {"id": "4", "title": "GTA V Xbox One", "description": "", "price": 16, "currency": "EUR"},
            {"id": "valid-duplicate", "title": "GTA V PS4", "description": "", "price": 18, "currency": "EUR"},
        ]
        original = [dict(item) for item in raw_listings]
        mock_wallapop_client.search_listings.return_value = raw_listings
        mock_game_detector.detect_games.side_effect = [[ps5], [target_game], [fifa_ps4], [xbox], [target_game]]
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = await price_collector.collect_comparables(
            target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        assert [item.listing_id for item in result] == ["valid-duplicate"] * 2
        assert [item.detected_game.platform for item in result] == [Platform.PS4, Platform.PS4]
        assert raw_listings == original
        assert mock_comparable_filter.is_valid_comparable.call_count == 2

    @pytest.mark.asyncio
    async def test_invalid_external_ids_never_enter_canonical_collection(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        mock_wallapop_client.search_listings.return_value = [
            {
                "id": None,
                "title": "Invalid",
                "description": "",
                "price": 10,
                "currency": "EUR",
            },
            {
                "id": " valid-id ",
                "title": "GTA V PS4",
                "description": "",
                "price": 15,
                "currency": "EUR",
            },
        ]
        mock_game_detector.detect_games.return_value = [target_game]
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        assert [item.listing_id for item in result] == ["valid-id"]

    @pytest.mark.asyncio
    async def test_empty_search_results(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should return empty list if no listings found."""
        # Mock empty Wallapop response
        mock_wallapop_client.search_listings.return_value = []

        result = await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_all_listings_filtered(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should return empty list if all listings filtered out."""
        # Mock Wallapop response
        mock_wallapop_client.search_listings.return_value = [
            {
                "id": 1,
                "title": "Lote GTA V + FIFA 23",
                "description": "2 juegos",
                "price": 30.0,
                "currency": "EUR",
                "web_slug": "lote-1",
            },
        ]

        # Mock game detector
        mock_game_detector.detect_games.return_value = [target_game]

        # Mock comparable filter to reject all
        mock_comparable_filter.is_valid_comparable.return_value = False

        result = await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_max_results_limit(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should respect max_results parameter."""
        # Mock Wallapop response with 5 listings
        mock_wallapop_client.search_listings.return_value = [
            {
                "id": i,
                "title": f"GTA V PS4 {i}",
                "description": "Juego",
                "price": 15.0 + i,
                "currency": "EUR",
                "web_slug": f"gta-v-{i}",
            }
            for i in range(1, 6)
        ]

        # Mock game detector and filter
        mock_game_detector.detect_games.return_value = [target_game]
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
            max_results=3,
        )

        assert len(result) == 3

        # Verify Wallapop was called with 3x max_results to account for filtering
        mock_wallapop_client.search_listings.assert_called_once()
        call_args = mock_wallapop_client.search_listings.call_args
        assert call_args.kwargs["max_results"] == 9  # 3 * 3

    @pytest.mark.asyncio
    async def test_wallapop_api_error(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should return empty list on Wallapop API error."""
        # Mock Wallapop to raise exception
        mock_wallapop_client.search_listings.side_effect = Exception("API Error")

        result = await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_partial_listing_failures(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        mock_game_detector: Mock,
        mock_comparable_filter: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should continue processing after individual listing failures."""
        # Mock Wallapop response with 3 listings
        mock_wallapop_client.search_listings.return_value = [
            {
                "id": 1,
                "title": "GTA V PS4",
                "description": "Good listing",
                "price": 15.0,
                "currency": "EUR",
                "web_slug": "gta-v-1",
            },
            {
                "id": 2,
                "title": "GTA V PS4",
                "description": "Bad listing",
                "price": "invalid_price",  # Will cause error
                "currency": "EUR",
                "web_slug": "gta-v-2",
            },
            {
                "id": 3,
                "title": "GTA V PS4",
                "description": "Good listing",
                "price": 18.0,
                "currency": "EUR",
                "web_slug": "gta-v-3",
            },
        ]

        # Mock game detector and filter
        mock_game_detector.detect_games.return_value = [target_game]
        mock_comparable_filter.is_valid_comparable.return_value = True

        result = await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        # Should have 2 valid comparables (skipped the bad one)
        assert len(result) == 2
        assert result[0].price == 15.0
        assert result[1].price == 18.0

    @pytest.mark.asyncio
    async def test_search_query_passed_to_wallapop(
        self,
        price_collector: WallapopPriceCollector,
        mock_wallapop_client: Mock,
        target_game: DetectedGame,
    ) -> None:
        """Should pass generated search query to Wallapop client."""
        # Mock Wallapop response
        mock_wallapop_client.search_listings.return_value = []

        await price_collector.collect_comparables(
            game=target_game,
            latitude=40.4168,
            longitude=-3.7038,
        )

        # Verify search query
        mock_wallapop_client.search_listings.assert_called_once()
        call_args = mock_wallapop_client.search_listings.call_args
        assert call_args.kwargs["keywords"] == "gta v"  # short matched_text
        assert call_args.kwargs["latitude"] == 40.4168
        assert call_args.kwargs["longitude"] == -3.7038
