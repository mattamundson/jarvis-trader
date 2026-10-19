"""Tests for ZeroGEX ES gamma levels adapter."""

import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from data.zerogex_levels import (
    ZeroGEXLevels,
    _parse_gamma_line,
    clear_cache,
    fetch_es_gamma_levels,
)


@pytest.fixture
def zerogex_html_fixture():
    """Load the saved ZeroGEX HTML fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "zerogex_es_levels.html"
    return fixture_path.read_text(encoding="utf-8")


class TestParseGammaLine:
    """Test the gamma line parser with saved fixtures."""

    def test_parse_valid_line(self, zerogex_html_fixture):
        """Parse a valid gamma levels line from the fixture."""
        result = _parse_gamma_line(zerogex_html_fixture)
        
        assert result is not None
        assert isinstance(result, ZeroGEXLevels)
        assert result.contract == "ESZ26"
        assert result.spot == 7743.0
        assert result.call_wall == 7743.0
        assert result.put_wall == 7733.0
        assert result.gamma_flip == 7809.0
        assert "-$25.26B" in result.net_gex
        assert result.delayed is True
        assert isinstance(result.fetched_at, datetime)

    def test_parse_missing_pattern_returns_none(self):
        """Parse failure when pattern not found."""
        html = "<html><body>No gamma data here</body></html>"
        result = _parse_gamma_line(html)
        assert result is None

    def test_parse_malformed_numbers_returns_none(self):
        """Parse failure when numbers are malformed."""
        html = "ES (ESZ26): spot INVALID | Call Wall 7743 | Put Wall 7733 | Gamma Flip 7809 | Net GEX -$25B (delayed"
        result = _parse_gamma_line(html)
        assert result is None

    def test_parse_case_insensitive(self):
        """Parser is case-insensitive."""
        html = "es (esz26): SPOT 7743 | call wall 7743 | put wall 7733 | gamma flip 7809 | net gex -$25.26B (delayed"
        result = _parse_gamma_line(html)
        
        assert result is not None
        assert result.spot == 7743.0


class TestFetchESGammaLevels:
    """Test the main fetch function with mocked network calls."""

    @pytest.fixture(autouse=True)
    def clear_cache_before_test(self):
        """Clear cache before each test."""
        clear_cache()
        yield
        clear_cache()

    def test_fetch_success(self, zerogex_html_fixture):
        """Successful fetch returns parsed levels."""
        mock_response = Mock()
        mock_response.text = zerogex_html_fixture
        mock_response.raise_for_status = Mock()
        
        with patch("data.zerogex_levels.requests.get", return_value=mock_response):
            result = fetch_es_gamma_levels()
        
        assert result is not None
        assert result.contract == "ESZ26"
        assert result.spot == 7743.0

    def test_fetch_timeout_returns_none(self):
        """Timeout returns None and logs error."""
        import requests
        
        with patch("data.zerogex_levels.requests.get", side_effect=requests.Timeout):
            result = fetch_es_gamma_levels()
        
        assert result is None

    def test_fetch_network_error_returns_none(self):
        """Network error returns None and logs error."""
        import requests
        
        with patch("data.zerogex_levels.requests.get", side_effect=requests.RequestException("Network error")):
            result = fetch_es_gamma_levels()
        
        assert result is None

    def test_fetch_http_error_returns_none(self):
        """HTTP error returns None and logs error."""
        import requests
        
        mock_response = Mock()
        mock_response.raise_for_status = Mock(side_effect=requests.HTTPError("404"))
        
        with patch("data.zerogex_levels.requests.get", return_value=mock_response):
            result = fetch_es_gamma_levels()
        
        assert result is None

    def test_fetch_parse_failure_returns_none(self):
        """Parse failure returns None."""
        mock_response = Mock()
        mock_response.text = "<html>No gamma data</html>"
        mock_response.raise_for_status = Mock()
        
        with patch("data.zerogex_levels.requests.get", return_value=mock_response):
            result = fetch_es_gamma_levels()
        
        assert result is None

    def test_cache_returns_same_instance_within_ttl(self, zerogex_html_fixture):
        """Cache returns same data within TTL."""
        mock_response = Mock()
        mock_response.text = zerogex_html_fixture
        mock_response.raise_for_status = Mock()
        
        with patch("data.zerogex_levels.requests.get", return_value=mock_response) as mock_get:
            result1 = fetch_es_gamma_levels()
            result2 = fetch_es_gamma_levels()
        
        assert result1 is not None
        assert result2 is not None
        assert result1 is result2  # Same cached instance
        assert mock_get.call_count == 1  # Only one network call

    def test_cache_refreshes_after_ttl(self, zerogex_html_fixture):
        """Cache refreshes after TTL expires."""
        mock_response = Mock()
        mock_response.text = zerogex_html_fixture
        mock_response.raise_for_status = Mock()
        
        with patch("data.zerogex_levels.requests.get", return_value=mock_response) as mock_get:
            with patch("data.zerogex_levels.CACHE_TTL_SECONDS", 0.1):
                result1 = fetch_es_gamma_levels()
                time.sleep(0.2)  # Wait for TTL to expire
                result2 = fetch_es_gamma_levels()
        
        assert result1 is not None
        assert result2 is not None
        assert mock_get.call_count == 2  # Two network calls

    def test_use_cache_false_bypasses_cache(self, zerogex_html_fixture):
        """use_cache=False forces fresh fetch."""
        mock_response = Mock()
        mock_response.text = zerogex_html_fixture
        mock_response.raise_for_status = Mock()
        
        with patch("data.zerogex_levels.requests.get", return_value=mock_response) as mock_get:
            result1 = fetch_es_gamma_levels(use_cache=True)
            result2 = fetch_es_gamma_levels(use_cache=False)
        
        assert result1 is not None
        assert result2 is not None
        assert mock_get.call_count == 2  # Two network calls

    def test_fetch_requests_unavailable_returns_none(self):
        """Fetch returns None when requests library is unavailable."""
        with patch("data.zerogex_levels.REQUESTS_AVAILABLE", False):
            result = fetch_es_gamma_levels()
        
        assert result is None


class TestClearCache:
    """Test cache clearing."""

    def test_clear_cache_resets_state(self, zerogex_html_fixture):
        """Clear cache resets cached data."""
        mock_response = Mock()
        mock_response.text = zerogex_html_fixture
        mock_response.raise_for_status = Mock()
        
        with patch("data.zerogex_levels.requests.get", return_value=mock_response) as mock_get:
            fetch_es_gamma_levels()  # Populate cache
            clear_cache()
            fetch_es_gamma_levels()  # Should fetch again
        
        assert mock_get.call_count == 2
