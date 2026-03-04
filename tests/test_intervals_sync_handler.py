"""Tests for Intervals.icu sync handler."""
from unittest.mock import MagicMock, Mock, patch

import pytest

from TrainingAnalyticsPlatform.handlers.intervals_sync_handler import IntervalsSyncHandler
from TrainingAnalyticsPlatform.ingestion.wellness_adapters import IntervalsPhysiometricsAdapter
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot
from TrainingAnalyticsPlatform.platform.exceptions import ExternalServiceError, StorageError


@pytest.fixture
def mock_storage():
    """Provide a mock storage coordinator."""
    storage = Mock()
    storage.physiometrics = Mock()
    storage.physiometrics.store_physiometrics = Mock(return_value="2025-03-01T00:00:00Z")
    return storage


@pytest.fixture
def mock_client():
    """Provide a mock Intervals.icu client."""
    client = Mock()
    return client


@pytest.fixture
def handler(mock_storage, mock_client):
    """Provide a handler with mocked dependencies."""
    return IntervalsSyncHandler(storage=mock_storage, client=mock_client)


class TestIntervalsSyncHandlerInit:
    """Tests for handler initialization."""

    def test_init_with_provided_client(self, mock_storage, mock_client):
        """Test initialization with provided client."""
        handler = IntervalsSyncHandler(storage=mock_storage, client=mock_client)
        assert handler.storage is mock_storage
        assert handler.client is mock_client
        assert isinstance(handler.adapter, IntervalsPhysiometricsAdapter)

    def test_init_without_client(self, mock_storage):
        """Test initialization without client (creates default)."""
        with patch(
            "TrainingAnalyticsPlatform.handlers.intervals_sync_handler.IntervalsicuClient"
        ):
            handler = IntervalsSyncHandler(storage=mock_storage)
            assert handler.storage is mock_storage


class TestIntervalsSyncHandlerHandle:
    """Tests for handler.handle() method."""

    def test_handle_missing_athlete_id(self, handler):
        """Test handle with missing athlete_id."""
        response, status = handler.handle(athlete_id=None)
        assert status == 400
        assert "athlete_id" in response.get("error", "").lower()

    def test_handle_empty_athlete_id(self, handler):
        """Test handle with empty string athlete_id."""
        response, status = handler.handle(athlete_id="")
        assert status == 400
        assert "athlete_id" in response.get("error", "").lower()

    def test_handle_no_measurements(self, handler, mock_client):
        """Test handle when API returns no measurements."""
        mock_client.get_athlete_measurements.return_value = []

        response, status = handler.handle(athlete_id="test_athlete")

        assert status == 200
        assert response["count"] == 0
        assert "no measurements" in response.get("message", "").lower()

    def test_handle_success_single_measurement(self, handler, mock_storage, mock_client):
        """Test successful handling of a single measurement."""
        measurement = {
            "date": "2025-03-01",
            "hrv": 42.5,
            "rhr": 52,
            "sleep": 480,
            "readiness": 78,
        }
        mock_client.get_athlete_measurements.return_value = [measurement]

        response, status = handler.handle(athlete_id="test_athlete")

        assert status == 200
        assert response["count"] == 1
        assert "synced" in response.get("message", "").lower()
        mock_storage.physiometrics.store_physiometrics.assert_called_once()

    def test_handle_success_multiple_measurements(self, handler, mock_storage, mock_client):
        """Test successful handling of multiple measurements."""
        measurements = [
            {
                "date": "2025-02-28",
                "hrv": 40.0,
                "rhr": 53,
                "sleep": 450,
                "readiness": 75,
            },
            {
                "date": "2025-03-01",
                "hrv": 42.5,
                "rhr": 52,
                "sleep": 480,
                "readiness": 78,
            },
        ]
        mock_client.get_athlete_measurements.return_value = measurements

        response, status = handler.handle(athlete_id="test_athlete")

        assert status == 200
        assert response["count"] == 2
        assert mock_storage.physiometrics.store_physiometrics.call_count == 2

    def test_handle_with_lookback_days(self, handler, mock_client):
        """Test handle with custom lookback days."""
        mock_client.get_athlete_measurements.return_value = []

        handler.handle(athlete_id="test_athlete", lookback_days=60)

        # Verify client was called with dates matching lookback
        assert mock_client.get_athlete_measurements.called
        call_kwargs = mock_client.get_athlete_measurements.call_args[1]
        assert call_kwargs["athlete_id"] == "test_athlete"
        assert "start_date" in call_kwargs
        assert "end_date" in call_kwargs

    def test_handle_api_error(self, handler, mock_client):
        """Test handle when API call fails."""
        mock_client.get_athlete_measurements.side_effect = ExternalServiceError(
            "API connection failed"
        )

        response, status = handler.handle(athlete_id="test_athlete")

        assert status == 502
        assert "error" in response
        assert "api" in response.get("error", "").lower()

    def test_handle_storage_error(self, handler, mock_storage, mock_client):
        """Test handle when storage call fails."""
        measurement = {
            "date": "2025-03-01",
            "hrv": 42.5,
            "rhr": 52,
            "sleep": 480,
            "readiness": 78,
        }
        mock_client.get_athlete_measurements.return_value = [measurement]
        mock_storage.physiometrics.store_physiometrics.side_effect = StorageError(
            "Storage failed"
        )

        response, status = handler.handle(athlete_id="test_athlete")

        assert status == 200  # Partial success - error caught and logged
        assert response["count"] == 0
        assert response.get("errors") is not None

    def test_handle_partial_success_with_errors(self, handler, mock_storage, mock_client):
        """Test handle with partial success (some measurements fail)."""
        measurements = [
            {
                "date": "2025-02-28",
                "hrv": 40.0,
                "rhr": 53,
                "sleep": 450,
                "readiness": 75,
            },
            {
                "date": "2025-03-01",
                # Invalid - missing sleep field
            },
        ]
        mock_client.get_athlete_measurements.return_value = measurements

        response, status = handler.handle(athlete_id="test_athlete")

        # First measurement succeeds, second fails validation
        assert status == 200
        assert response["count"] == 1
        assert response.get("errors") is not None
        assert len(response["errors"]) > 0

    def test_handle_unexpected_error(self, handler, mock_client):
        """Test handle when unexpected error occurs."""
        mock_client.get_athlete_measurements.side_effect = RuntimeError("Unexpected error")

        response, status = handler.handle(athlete_id="test_athlete")

        assert status == 500
        assert "error" in response
        assert "internal" in response.get("error", "").lower()

    def test_handle_converts_snapshot_to_storage_dict(
        self, handler, mock_storage, mock_client
    ):
        """Test that snapshot is properly converted to storage dict."""
        measurement = {
            "date": "2025-03-01",
            "hrv": 42.5,
            "rhr": 52,
            "sleep": 480,
            "readiness": 78,
        }
        mock_client.get_athlete_measurements.return_value = [measurement]

        _, status = handler.handle(athlete_id="test_athlete")

        assert status == 200
        # Verify storage was called with proper structure
        call_args = mock_storage.physiometrics.store_physiometrics.call_args
        assert call_args is not None
        kwargs = call_args[1]
        assert kwargs["athlete_id"] == "test_athlete"
        assert kwargs["data_source"] == "intervals"
        assert kwargs["effective_date"] == "2025-03-01"
        assert "heart_rate" in kwargs["physiometrics_data"]
        assert "resting_hr_bpm" in kwargs["physiometrics_data"]["heart_rate"]
