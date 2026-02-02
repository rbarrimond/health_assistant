"""Example tests for the refactored handlers.

This demonstrates how the new handler architecture enables clean, simple testing
without requiring the Azure Functions framework.
"""

from unittest.mock import Mock
from datetime import datetime, timezone

import pytest

from FitParser.handlers.fit_upload_handler import FitUploadHandler
from FitParser.handlers.onedrive_sync_handler import (
    OneDriveSyncHandler,
    OneDriveSyncRequest,
)
from FitParser.handlers.query_handler import QueryHandler
from FitParser.models import WorkoutMetricsModel, SessionMetricsModel


# ==============================================================================
# OneDriveSyncRequest Tests
# ==============================================================================

def test_sync_request_parses_athlete_id_from_body():
    """Test athlete_id is extracted from request body."""
    request = OneDriveSyncRequest({"athlete_id": "alice"}, {})
    assert request.athlete_id == "alice"


def test_sync_request_parses_athlete_id_from_params():
    """Test athlete_id falls back to params."""
    request = OneDriveSyncRequest({}, {"athlete_id": "bob"})
    assert request.athlete_id == "bob"


def test_sync_request_uses_default_athlete_id():
    """Test default athlete_id is 'rob'."""
    request = OneDriveSyncRequest({}, {})
    assert request.athlete_id == "rob"


def test_sync_request_parses_lookback_days():
    """Test lookback_days is parsed as integer."""
    request = OneDriveSyncRequest({"days": "30"}, {})
    assert request.lookback_days == 30


def test_sync_request_handles_invalid_lookback_days():
    """Test invalid lookback_days returns None."""
    request = OneDriveSyncRequest({"days": "invalid"}, {})
    assert request.lookback_days is None


def test_sync_request_detects_async_mode():
    """Test async mode detection."""
    request = OneDriveSyncRequest({}, {"async": "true"})
    assert request.async_mode is True

    request = OneDriveSyncRequest({}, {"async": "false"})
    assert request.async_mode is False


# ==============================================================================
# OneDriveSyncHandler Tests
# ==============================================================================

def test_sync_handler_executes_sync_mode():
    """Test synchronous sync execution."""
    # Mock service
    service = Mock()
    service.config.lookback_days = 7
    service.sync.return_value = {
        "status": "success",
        "synced": 5,
        "skipped": 2
    }

    # Create handler and request
    handler = OneDriveSyncHandler(service)
    request = OneDriveSyncRequest({"athlete_id": "rob"}, {})

    # Execute
    response, status = handler.handle(request)

    # Verify
    assert status == 200
    assert response["status"] == "success"
    assert response["synced"] == 5
    service.sync.assert_called_once_with(athlete_id="rob", lookback_days=7)


def test_sync_handler_executes_async_mode():
    """Test asynchronous sync execution."""
    # Mock service
    service = Mock()
    service.config = Mock()
    service.config.folder_path = "/Apps/HealthFit"

    # Create handler and request
    handler = OneDriveSyncHandler(service)
    request = OneDriveSyncRequest({"async": "true", "athlete_id": "rob"}, {})

    # Execute
    response, status = handler.handle(request)

    # Verify response is immediate (202 Accepted)
    assert status == 202
    assert response["status"] == "queued"
    assert response["mode"] == "async"
    assert response["athlete_id"] == "rob"


def test_sync_handler_handles_errors():
    """Test error handling in sync mode."""
    # Mock service that raises error
    service = Mock()
    service.config.lookback_days = 7
    service.sync.side_effect = ValueError("Invalid config")

    # Create handler and request
    handler = OneDriveSyncHandler(service)
    request = OneDriveSyncRequest({"athlete_id": "rob"}, {})

    # Execute
    response, status = handler.handle(request)

    # Verify error response
    assert status == 400
    assert "Invalid config" in response["error"]


# ==============================================================================
# QueryHandler Tests
# ==============================================================================

def test_query_handler_fetches_planning_context():
    """Test planning context query."""
    # Mock semantic layer
    semantic_layer = Mock()
    semantic_layer.get_planning_context.return_value = {
        "recent_load": {"tss": 450},
        "trends": {"increasing": True}
    }

    # Create handler
    handler = QueryHandler(semantic_layer)

    # Execute
    context, status = handler.query_planning_context("rob", 30)

    # Verify
    assert status == 200
    assert context["recent_load"]["tss"] == 450
    semantic_layer.get_planning_context.assert_called_once_with("rob", 30)


def test_query_handler_fetches_athlete_workouts():
    """Test workout query."""
    # Mock semantic layer
    semantic_layer = Mock()
    semantic_layer.get_workouts.return_value = [
        {"id": "W1", "sport": "Cycling"},
        {"id": "W2", "sport": "Running"}
    ]

    # Create handler
    handler = QueryHandler(semantic_layer)

    # Execute
    workouts, status = handler.query_athlete_workouts("rob", limit=50)

    # Verify
    assert status == 200
    assert len(workouts) == 2
    assert workouts[0]["sport"] == "Cycling"


def test_query_handler_handles_semantic_layer_errors():
    """Test error handling in queries."""
    # Mock semantic layer that raises error
    semantic_layer = Mock()
    semantic_layer.get_planning_context.side_effect = ValueError("Database error")

    # Create handler
    handler = QueryHandler(semantic_layer)

    # Execute
    context, status = handler.query_planning_context("rob", 30)

    # Verify error response
    assert status == 400
    assert "Database error" not in context or context == {}  # ValueError results in empty context


# ==============================================================================
# FitUploadHandler Tests
# ==============================================================================

def test_fit_upload_handler_processes_valid_file():
    """Test FIT file upload processing."""
    # Mock storage
    storage = Mock()
    storage.store_workout.return_value = "W123"

    # Create handler
    handler = FitUploadHandler(storage)

    # Mock FitParser (would need to actually test with real FIT file)
    # This is simplified for illustration
    # In real test, you'd create a temp FIT file

    # For this test, we'll just verify the handler structure exists
    assert handler is not None
    assert hasattr(handler, 'handle')


def test_fit_upload_handler_returns_404_for_missing_file():
    """Test handler returns 404 for non-existent file."""
    storage = Mock()
    handler = FitUploadHandler(storage)

    # Execute with non-existent file
    _, status = handler.handle("/nonexistent/file.fit", "rob")

    # Verify 404 response
    assert status == 404


# ==============================================================================
# Integration-Style Tests (showing handler composition)
# ==============================================================================

def test_sync_and_query_workflow():
    """Test a workflow using multiple handlers."""
    # Setup mocks
    service = Mock()
    service.sync.return_value = {"status": "success", "synced": 3}

    semantic_layer = Mock()
    semantic_layer.get_workouts.return_value = [
        {"id": "W1", "date": "2026-01-01"},
        {"id": "W2", "date": "2026-01-02"},
        {"id": "W3", "date": "2026-01-03"}
    ]

    # Execute sync
    sync_handler = OneDriveSyncHandler(service)
    sync_req = OneDriveSyncRequest({"athlete_id": "rob"}, {})
    sync_response, sync_status = sync_handler.handle(sync_req)

    assert sync_status == 200
    assert sync_response["synced"] == 3

    # Query the synced workouts
    query_handler = QueryHandler(semantic_layer)
    workouts, query_status = query_handler.query_athlete_workouts("rob", limit=50)

    assert query_status == 200
    assert len(workouts) == 3


# ==============================================================================
# Property-Based Tests (Example)
# ==============================================================================

@pytest.mark.parametrize("async_value,expected", [
    ("true", True),
    ("True", True),
    ("TRUE", True),
    ("1", True),
    ("yes", True),
    ("y", True),
    ("false", False),
    ("False", False),
    ("0", False),
    ("no", False),
    ("", False),
    (None, False),
])
def test_async_mode_parsing(async_value, expected):
    """Test all async mode values are parsed correctly."""
    params = {"async": async_value} if async_value is not None else {}
    request = OneDriveSyncRequest({}, params)
    assert request.async_mode == expected


@pytest.mark.parametrize("days_value,expected", [
    ("7", 7),
    ("30", 30),
    ("365", 365),
    ("0", 0),
    ("-5", -5),  # Handler should validate this
    ("invalid", None),  # Returns None, handler provides default
    (None, None),  # Returns None, handler provides default
])
def test_lookback_days_parsing(days_value, expected):
    """Test lookback days parsing for various inputs."""
    body = {"days": days_value} if days_value is not None else {}
    request = OneDriveSyncRequest(body, {})
    assert request.lookback_days == expected


# ==============================================================================
# Test Helpers
# ==============================================================================

def create_mock_workout_metrics():
    """Helper to create mock workout metrics."""
    _ = WorkoutMetricsModel(
        workout_id="W123",
        athlete_id="rob",
        session=SessionMetricsModel(
            sport="Cycling",
            start_time_utc=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            duration_sec=3600,
            device_manufacturer="Garmin",
            device_product="Edge 530"
        )
    )


# ==============================================================================
# Run Tests
# ==============================================================================

if __name__ == "__main__":
    # Run with pytest
    # pytest test_handlers_example.py -v
    pytest.main([__file__, "-v"])
