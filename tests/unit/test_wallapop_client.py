"""Unit tests for WallapopClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from infrastructure.marketplaces.wallapop.client import (
    WallapopAPIError,
    WallapopClient,
    WallapopClientError,
)


@pytest.mark.unit
class TestWallapopClient:
    """Test suite for WallapopClient."""

    def test_client_initialization(self) -> None:
        """Test that client can be initialized with default parameters."""
        client = WallapopClient()
        assert client.timeout == WallapopClient.DEFAULT_TIMEOUT
        assert client.max_retries == WallapopClient.DEFAULT_MAX_RETRIES
        assert client.retry_delay == WallapopClient.DEFAULT_RETRY_DELAY

    def test_client_initialization_custom_params(self) -> None:
        """Test client initialization with custom parameters."""
        client = WallapopClient(timeout=60.0, max_retries=5, retry_delay=2.0)
        assert client.timeout == 60.0
        assert client.max_retries == 5
        assert client.retry_delay == 2.0

    @pytest.mark.asyncio
    async def test_search_without_context_manager_raises_error(self) -> None:
        """Test that search raises error if client not initialized."""
        client = WallapopClient()

        with pytest.raises(WallapopClientError, match="Client not initialized"):
            await client.search("test", 40.0, -3.0)

    @pytest.mark.asyncio
    async def test_search_success(self) -> None:
        """Test successful search request."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "search_objects": [
                {"id": "1", "title": "Test listing"},
                {"id": "2", "title": "Another listing"},
            ],
            "next_page": "https://api.wallapop.com/api/v3/general/search?start=40",
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            async with WallapopClient() as client:
                result = await client.search("test", 40.0, -3.0)

                assert "search_objects" in result
                assert len(result["search_objects"]) == 2
                assert result["next_page"] is not None

    @pytest.mark.asyncio
    async def test_search_api_error(self) -> None:
        """Test that API errors are properly raised."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.json.return_value = {"error": "Not found"}
        mock_response.text = "Not found"

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            async with WallapopClient() as client:
                with pytest.raises(WallapopAPIError) as exc_info:
                    await client.search("test", 40.0, -3.0)

                assert exc_info.value.status_code == 404
                assert "Not found" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_search_with_pagination_params(self) -> None:
        """Test search with custom start parameter."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"search_objects": []}

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            async with WallapopClient() as client:
                await client.search("test", 40.0, -3.0, start=40)

                # Verify params passed to httpx
                call_args = mock_client.get.call_args
                assert call_args[1]["params"]["start"] == 40

    @pytest.mark.asyncio
    async def test_extract_start_from_next_page(self) -> None:
        """Test extraction of start parameter from next_page URL."""
        client = WallapopClient()

        # Test valid URL
        next_page_url = "https://api.wallapop.com/api/v3/general/search?start=40&keywords=test"
        start = client._extract_start_from_next_page(next_page_url)
        assert start == 40

        # Test URL without start parameter
        next_page_url = "https://api.wallapop.com/api/v3/general/search?keywords=test"
        start = client._extract_start_from_next_page(next_page_url)
        assert start is None

        # Test invalid URL
        start = client._extract_start_from_next_page("invalid-url")
        assert start is None

    @pytest.mark.asyncio
    async def test_search_all_pages(self) -> None:
        """Test automatic pagination through all results."""
        # Mock responses for multiple pages
        mock_response_page1 = MagicMock(spec=httpx.Response)
        mock_response_page1.status_code = 200
        mock_response_page1.json.return_value = {
            "search_objects": [{"id": "1"}, {"id": "2"}],
            "next_page": "https://api.wallapop.com/api/v3/general/search?start=2",
        }

        mock_response_page2 = MagicMock(spec=httpx.Response)
        mock_response_page2.status_code = 200
        mock_response_page2.json.return_value = {
            "search_objects": [{"id": "3"}, {"id": "4"}],
            "next_page": None,
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = [mock_response_page1, mock_response_page2]

        with patch("httpx.AsyncClient", return_value=mock_client):
            async with WallapopClient() as client:
                results = await client.search_all_pages("test", 40.0, -3.0)

                assert len(results) == 4
                assert results[0]["id"] == "1"
                assert results[3]["id"] == "4"

    @pytest.mark.asyncio
    async def test_search_all_pages_with_max_results(self) -> None:
        """Test pagination with max_results limit."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "search_objects": [{"id": str(i)} for i in range(10)],
            "next_page": "https://api.wallapop.com/api/v3/general/search?start=10",
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_client):
            async with WallapopClient() as client:
                results = await client.search_all_pages("test", 40.0, -3.0, max_results=5)

                assert len(results) == 5
