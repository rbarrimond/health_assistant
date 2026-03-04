"""Tests for Intervals.icu API client."""
import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from TrainingAnalyticsPlatform.integrations.intervals_client import IntervalsicuClient
from TrainingAnalyticsPlatform.platform.exceptions import ExternalServiceError


class TestIntervalsicuClientInit:
    """Tests for client initialization."""

    def test_init_with_api_key_from_env(self):
        """Test initialization with API key from environment."""
        with patch.dict(os.environ, {"INTERVALS_API_KEY": "test-api-key-123"}):
            client = IntervalsicuClient()
            assert client.api_key == "test-api-key-123"

    def test_init_with_api_key_argument(self):
        """Test initialization with API key as argument."""
        client = IntervalsicuClient(api_key="direct-key-456")
        assert client.api_key == "direct-key-456"

    def test_init_with_athlete_id_from_env(self):
        """Test initialization with athlete ID from environment."""
        with patch.dict(os.environ, {"INTERVALS_API_KEY": "test-key", "INTERVALS_ATHLETE_ID": "i508584"}):
            client = IntervalsicuClient()
            assert client.athlete_id == "i508584"

    def test_init_with_athlete_id_argument(self):
        """Test initialization with athlete ID as argument."""
        client = IntervalsicuClient(api_key="test-key", athlete_id="custom-id-123")
        assert client.athlete_id == "custom-id-123"

    def test_init_athlete_id_from_env_can_be_overridden(self):
        """Test that athlete ID argument overrides environment."""
        with patch.dict(os.environ, {"INTERVALS_API_KEY": "test-key", "INTERVALS_ATHLETE_ID": "i508584"}):
            client = IntervalsicuClient(athlete_id="override-id")
            assert client.athlete_id == "override-id"

    def test_init_missing_api_key_raises_error(self):
        """Test that missing API key raises ExternalServiceError."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ExternalServiceError) as exc_info:
                IntervalsicuClient()
            assert "API key not configured" in str(exc_info.value)


class TestIntervalsicuClientMeasurements:
    """Tests for fetching measurements."""

    @pytest.fixture
    def client(self):
        """Provide a client with mocked session."""
        client = IntervalsicuClient(api_key="test-key")
        return client

    def test_get_athlete_measurements_success(self, client):
        """Test successful measurements fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "date": "2025-03-01",
                "hrv": 42.5,
                "rhr": 52,
                "sleep": 480,
                "readiness": 78,
            }
        ]

        with patch.object(client.session, "request", return_value=mock_response):
            response = client.get_athlete_measurements(
                athlete_id="test_athlete",
                start_date="2025-03-01",
                end_date="2025-03-01",
            )

        assert response == mock_response.json.return_value
        assert len(response) == 1
        assert response[0]["hrv"] == pytest.approx(42.5)

    def test_get_athlete_measurements_default_dates(self, client):
        """Test measurements fetch with default date range."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        with patch.object(client.session, "request", return_value=mock_response) as mock_request:
            client.get_athlete_measurements(athlete_id="test_athlete")

        # Verify request was made with proper params (dates filled in)
        assert mock_request.called
        call_kwargs = mock_request.call_args[1]
        assert "params" in call_kwargs
        assert "start_date" in call_kwargs["params"]
        assert "end_date" in call_kwargs["params"]

    def test_get_athlete_measurements_api_error_401(self, client):
        """Test handling of 401 Unauthorized response."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(client.session, "request", return_value=mock_response):
            with pytest.raises(ExternalServiceError) as exc_info:
                client.get_athlete_measurements(athlete_id="test_athlete")
            assert "authentication failed" in str(exc_info.value).lower()

    def test_get_athlete_measurements_api_error_404(self, client):
        """Test handling of 404 Not Found response."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch.object(client.session, "request", return_value=mock_response):
            with pytest.raises(ExternalServiceError) as exc_info:
                client.get_athlete_measurements(athlete_id="unknown_athlete")
            assert "not found" in str(exc_info.value).lower()

    def test_get_athlete_measurements_api_error_429(self, client):
        """Test handling of 429 Rate Limited response."""
        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch.object(client.session, "request", return_value=mock_response):
            with pytest.raises(ExternalServiceError) as exc_info:
                client.get_athlete_measurements(athlete_id="test_athlete")
            assert "rate limited" in str(exc_info.value).lower()

    def test_get_athlete_measurements_timeout(self, client):
        """Test handling of request timeout."""
        with patch.object(
            client.session, "request", side_effect=requests.Timeout("Timeout")
        ):
            with pytest.raises(ExternalServiceError) as exc_info:
                client.get_athlete_measurements(athlete_id="test_athlete")
            assert "timeout" in str(exc_info.value).lower()

    def test_get_athlete_measurements_connection_error(self, client):
        """Test handling of connection error."""
        with patch.object(
            client.session, "request", side_effect=requests.ConnectionError("Connection")
        ):
            with pytest.raises(ExternalServiceError) as exc_info:
                client.get_athlete_measurements(athlete_id="test_athlete")
            assert "connection error" in str(exc_info.value).lower()


class TestIntervalsicuClientHRV:
    """Tests for fetching HRV data."""

    @pytest.fixture
    def client(self):
        """Provide a client with mocked session."""
        client = IntervalsicuClient(api_key="test-key")
        return client

    def test_get_athlete_hrv_success(self, client):
        """Test successful HRV fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "date": "2025-03-01",
            "hrv": 42.5,
            "unit": "ln(ms)",
        }

        with patch.object(client.session, "request", return_value=mock_response):
            response = client.get_athlete_hrv(
                athlete_id="test_athlete",
                start_date="2025-03-01",
                end_date="2025-03-01",
            )

        assert response == mock_response.json.return_value
        assert response["hrv"] == pytest.approx(42.5)


class TestIntervalsicuClientReadiness:
    """Tests for fetching readiness scores."""

    @pytest.fixture
    def client(self):
        """Provide a client with mocked session."""
        client = IntervalsicuClient(api_key="test-key")
        return client

    def test_get_athlete_readiness_success(self, client):
        """Test successful readiness fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "date": "2025-03-01",
            "readiness": 78,
        }

        with patch.object(client.session, "request", return_value=mock_response):
            response = client.get_athlete_readiness(
                athlete_id="test_athlete",
                start_date="2025-03-01",
                end_date="2025-03-01",
            )

        assert response == mock_response.json.return_value
        assert response["readiness"] == 78
