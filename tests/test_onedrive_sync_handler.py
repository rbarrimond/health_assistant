"""Tests for OneDriveSyncHandler."""

# pylint: disable=redefined-outer-name

from datetime import datetime, timezone
from unittest.mock import MagicMock
import time

import pytest

from FitParser.handlers.onedrive_sync_handler import (
    OneDriveSyncHandler,
    OneDriveSyncRequest,
)


@pytest.fixture
def mock_service():
    """Create a mock OneDriveSyncIngestionHandler."""
    service = MagicMock()
    service.config = MagicMock()
    service.config.lookback_days = 30
    return service


@pytest.fixture
def handler(mock_service):
    """Create OneDriveSyncHandler instance."""
    return OneDriveSyncHandler(mock_service)


class TestOneDriveSyncRequest:
    """Test OneDriveSyncRequest parsing."""

    def test_athlete_id_from_body(self):
        """Test athlete_id extracted from body."""
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, {})
        assert req.athlete_id == "athlete1"

    def test_athlete_id_from_query(self):
        """Test athlete_id extracted from query params."""
        req = OneDriveSyncRequest({}, {"athlete_id": "athlete2"})
        assert req.athlete_id == "athlete2"

    def test_athlete_id_default(self):
        """Test athlete_id defaults to 'rob'."""
        req = OneDriveSyncRequest({}, {})
        assert req.athlete_id == "rob"

    def test_athlete_id_body_takes_precedence(self):
        """Test body athlete_id takes precedence over query."""
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1"}, {"athlete_id": "athlete2"}
        )
        assert req.athlete_id == "athlete1"

    def test_lookback_days_from_body(self):
        """Test lookback_days extracted from body."""
        req = OneDriveSyncRequest({"days": "14"}, {})
        assert req.lookback_days == 14

    def test_lookback_days_from_query(self):
        """Test lookback_days extracted from query params."""
        req = OneDriveSyncRequest({}, {"days": "21"})
        assert req.lookback_days == 21

    def test_lookback_days_none_when_missing(self):
        """Test lookback_days is None when not provided."""
        req = OneDriveSyncRequest({}, {})
        assert req.lookback_days is None

    def test_lookback_days_invalid_value(self):
        """Test lookback_days returns None for invalid values."""
        req = OneDriveSyncRequest({"days": "invalid"}, {})
        assert req.lookback_days is None

    def test_async_mode_from_body_true(self):
        """Test async flag extracted from body."""
        for value in ["1", "true", "True", "TRUE", "yes", "YES", "y", "Y"]:
            req = OneDriveSyncRequest({"async": value}, {})
            assert req.async_mode is True, f"Failed for async={value}"

    def test_async_mode_from_query(self):
        """Test async flag extracted from query params."""
        req = OneDriveSyncRequest({}, {"async": "true"})
        assert req.async_mode is True

    def test_async_mode_default_false(self):
        """Test async defaults to False."""
        req = OneDriveSyncRequest({}, {})
        assert req.async_mode is False

    def test_async_mode_false_values(self):
        """Test async flag with false-like values."""
        for value in ["0", "false", "False", "no", "n", ""]:
            req = OneDriveSyncRequest({"async": value}, {})
            assert req.async_mode is False, f"Failed for async={value}"


class TestOneDriveSyncHandler:
    """Test OneDriveSyncHandler sync execution."""

    def test_handle_sync_success(self, handler, mock_service):
        """Test successful synchronous sync."""
        # Arrange
        expected_result = {"files_processed": 5, "errors": 0}
        mock_service.sync.return_value = expected_result
        req = OneDriveSyncRequest({"athlete_id": "athlete1", "days": "14"}, {})

        # Act
        result, status = handler.handle(req)

        # Assert
        assert status == 200
        assert result == expected_result
        mock_service.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=14)

    def test_handle_sync_uses_default_lookback_days(self, handler, mock_service):
        """Test sync uses default lookback days from config."""
        # Arrange
        mock_service.config.lookback_days = 45
        mock_service.sync.return_value = {"files_processed": 2}
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, {})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        mock_service.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=45)

    def test_handle_sync_validation_error(self, handler, mock_service):
        """Test sync returns 400 for validation errors."""
        # Arrange
        mock_service.sync.side_effect = ValueError("Invalid athlete_id")
        req = OneDriveSyncRequest({"athlete_id": ""}, {})

        # Act
        error_resp, status = handler.handle(req)

        # Assert
        assert status == 400
        assert "error" in error_resp
        assert "Invalid athlete_id" in error_resp["error"]

    def test_handle_sync_exception(self, handler, mock_service):
        """Test sync returns 500 for unexpected errors."""
        # Arrange
        mock_service.sync.side_effect = Exception("OneDrive API error")
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, {})

        # Act
        error_resp, status = handler.handle(req)

        # Assert
        assert status == 500
        assert "error" in error_resp

    def test_handle_async_queued(self, handler, mock_service):
        """Test asynchronous sync returns 202 immediately."""
        # Arrange
        mock_service.sync.return_value = {"files_processed": 0}
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "days": "14", "async": "true"}, {}
        )

        # Act
        start_time = datetime.now(timezone.utc)
        result, status = handler.handle(req)
        end_time = datetime.now(timezone.utc)

        # Assert
        assert status == 202
        assert result["status"] == "queued"
        assert result["athlete_id"] == "athlete1"
        assert result["lookback_days"] == 14
        assert result["mode"] == "async"

        # Verify queued_at is within expected time range
        queued_time = datetime.fromisoformat(result["queued_at_utc"])
        assert start_time <= queued_time <= end_time

    def test_handle_async_runs_in_background(self, handler, mock_service):
        """Test async sync runs in background thread."""
        # Arrange
        mock_service.sync.return_value = {"files_processed": 3}
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "days": "7", "async": "true"}, {}
        )

        # Act
        _, status = handler.handle(req)

        # Assert - immediate response
        assert status == 202

        # Verify async flag
        assert _["status"] == "queued"
        time.sleep(0.1)

        # Verify service.sync was called in background
        mock_service.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=7)

    def test_handle_async_exception_logged(self, handler, mock_service):
        """Test async sync exceptions are logged but don't affect response."""
        # Arrange
        mock_service.sync.side_effect = Exception("Sync error")
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "async": "true"}, {}
        )

        # Act
        _, status = handler.handle(req)

        # Assert - response is successful 202
        assert status == 202
        assert _["status"] == "queued"

        # Wait for background thread
        time.sleep(0.1)

        # Verify sync was attempted
        mock_service.sync.assert_called_once()

    def test_handle_async_default_lookback_days(self, handler, mock_service):
        """Test async sync uses default lookback days from config."""
        # Arrange
        mock_service.config.lookback_days = 60
        mock_service.sync.return_value = {}
        req = OneDriveSyncRequest({"athlete_id": "athlete1", "async": "true"}, {})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 202
        assert _["lookback_days"] == 60

        # Wait for background thread
        time.sleep(0.1)

        mock_service.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=60)

    def test_handle_sync_with_query_params(self, handler, mock_service):
        """Test sync with query parameters."""
        # Arrange
        mock_service.sync.return_value = {"files_processed": 1}
        req = OneDriveSyncRequest({}, {"athlete_id": "athlete2", "days": "28"})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        mock_service.sync.assert_called_once_with(athlete_id="athlete2", lookback_days=28)

    def test_handle_sync_body_overrides_query(self, handler, mock_service):
        """Test body parameters override query parameters."""
        # Arrange
        mock_service.sync.return_value = {}
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "days": "14"},
            {"athlete_id": "athlete2", "days": "7"},
        )

        # Act
        _, _ = handler.handle(req)

        # Assert
        mock_service.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=14)

    def test_handle_sync_none_body(self, handler, mock_service):
        """Test handler works with None body."""
        # Arrange
        mock_service.sync.return_value = {}
        req = OneDriveSyncRequest(None, {"athlete_id": "athlete1"})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        mock_service.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=30)

    def test_handle_sync_none_query_params(self, handler, mock_service):
        """Test handler works with None query params."""
        # Arrange
        mock_service.sync.return_value = {}
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, None)

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        mock_service.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=30)
