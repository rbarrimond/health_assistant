"""Integration tests for semantic layer HTTP endpoints.

These tests verify that the Azure Functions HTTP routes correctly
interface with the semantic layer.
"""
# pylint: disable=redefined-outer-name, line-too-long  # pytest fixtures intentionally shadow

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from TrainingAnalyticsPlatform.platform.dependencies import FunctionAppDependencies

from function_app import (
    planning_context,
    list_workouts,
    get_workout_detail,
    get_workout_lap_detail,
    weekly_rollups,
    zone_distribution,
    efficiency_trends,
)


@pytest.fixture
def mock_request():
    """Create a mock HTTP request."""
    request = MagicMock()
    request.params = {}
    request.route_params = {}
    return request


@pytest.fixture
def mock_semantic_layer():
    """Mock semantic layer for endpoint testing."""
    return MagicMock()


class TestPlanningContextEndpoint:
    """Tests for /api/planning/context endpoint."""

    def test_missing_athlete_id(self, mock_request, mock_semantic_layer):
        """Test endpoint defaults to 'rob' when athlete_id not provided."""
        mock_semantic_layer.get_planning_context.return_value = {"athlete_id": "rob"}

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = planning_context(mock_request)

        assert response.status_code == 200
        mock_semantic_layer.get_planning_context.assert_called_once_with("rob", 45)

    def test_success(self, mock_request, mock_semantic_layer):
        """Test successful planning context request."""
        mock_request.params = {"athlete_id": "rob", "days": "30"}

        mock_context = {
            "athlete_id": "rob",
            "query_window": {},
            "recent_workouts": [],
            "weekly_rollups": [],
            "summary": {},
            "notable_flags": [],
        }
        mock_semantic_layer.get_planning_context.return_value = mock_context

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = planning_context(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert data["athlete_id"] == "rob"
        mock_semantic_layer.get_planning_context.assert_called_once_with("rob", 30)

    def test_days_parameter_capped(self, mock_request, mock_semantic_layer):
        """Test that days parameter is capped at 365."""
        mock_request.params = {"athlete_id": "rob", "days": "500"}

        mock_semantic_layer.get_planning_context.return_value = {}

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            planning_context(mock_request)

        # Should cap at 365
        mock_semantic_layer.get_planning_context.assert_called_once_with("rob", 365)


class TestListWorkoutsEndpoint:
    """Tests for /api/workouts endpoint."""

    def test_missing_athlete_id(self, mock_request, mock_semantic_layer):
        """Test endpoint defaults to 'rob' when athlete_id not provided."""
        mock_semantic_layer.get_workouts.return_value = []

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = list_workouts(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert data["athlete_id"] == "rob"

    def test_success(self, mock_request, mock_semantic_layer):
        """Test successful workout list request."""
        mock_request.params = {"athlete_id": "rob", "limit": "10"}

        mock_workouts = [
            {
                "workout_id": "w1",
                "sport": "Cycling",
                "local_tz_offset": "UTC-05:00",
                "timezone": "America/New_York",
            },
            {"workout_id": "w2", "sport": "Running"},
        ]
        mock_semantic_layer.get_workouts.return_value = mock_workouts

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = list_workouts(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert data["count"] == 2
        assert len(data["workouts"]) == 2
        assert data["workouts"][0]["local_tz_offset"] == "UTC-05:00"
        assert data["workouts"][0]["timezone"] == "America/New_York"

    def test_with_filters(self, mock_request, mock_semantic_layer):
        """Test workout list with filters."""
        mock_request.params = {
            "athlete_id": "rob",
            "since": "2026-01-01",
            "until": "2026-01-31",
            "sport": "Cycling",
            "limit": "50",
        }

        mock_semantic_layer.get_workouts.return_value = []

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            list_workouts(mock_request)

        mock_semantic_layer.get_workouts.assert_called_once_with(
            "rob",
            since="2026-01-01",
            until="2026-01-31",
            limit=50,
            sport="Cycling",
        )


class TestGetWorkoutEndpoint:
    """Tests for /api/workouts/{workout_id} endpoint."""

    def test_missing_athlete_id(self, mock_request, mock_semantic_layer):
        """Test endpoint defaults to 'rob' when athlete_id not provided."""
        mock_request.route_params = {"workout_id": "abc123"}

        mock_workout = {
            "workout_id": "abc123",
            "sport": "Cycling",
            "duration_sec": 3600,
        }
        mock_semantic_layer.get_workout_detail.return_value = mock_workout

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = get_workout_detail(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert data["workout_id"] == "abc123"
        mock_semantic_layer.get_workout_detail.assert_called_once_with(
            "rob",
            "abc123",
            include_laps=False,
            include_developer_fields=False,
        )

    def test_workout_found(self, mock_request, mock_semantic_layer):
        """Test successful workout detail retrieval."""
        mock_request.params = {"athlete_id": "alice"}
        mock_request.route_params = {"workout_id": "xyz789"}

        mock_workout = {
            "workout_id": "xyz789",
            "sport": "Running",
            "duration_sec": 2400,
        }
        mock_semantic_layer.get_workout_detail.return_value = mock_workout

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = get_workout_detail(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert data["workout_id"] == "xyz789"
        mock_semantic_layer.get_workout_detail.assert_called_once_with(
            "alice",
            "xyz789",
            include_laps=False,
            include_developer_fields=False,
        )

    def test_workout_not_found(self, mock_request, mock_semantic_layer):
        """Test workout detail when workout doesn't exist."""
        mock_request.params = {"athlete_id": "rob"}
        mock_request.route_params = {"workout_id": "nonexistent"}

        mock_semantic_layer.get_workout_detail.return_value = None

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = get_workout_detail(mock_request)

        assert response.status_code == 404
        data = json.loads(response.get_body())
        assert "not found" in data["error"].lower()

    def test_workout_detail_with_laps(self, mock_request, mock_semantic_layer):
        """Test workout detail request with laps flag enabled."""
        mock_request.params = {
            "athlete_id": "rob",
            "laps": "true",
        }
        mock_request.route_params = {"workout_id": "abc123"}

        mock_workout = {
            "workout_id": "abc123",
            "records": [],
            "laps": [],
        }
        mock_semantic_layer.get_workout_detail.return_value = mock_workout

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = get_workout_detail(mock_request)

        assert response.status_code == 200
        mock_semantic_layer.get_workout_detail.assert_called_once_with(
            "rob",
            "abc123",
            include_laps=True,
            include_developer_fields=False,
        )


class TestGetWorkoutLapEndpoint:
    """Tests for /api/workouts/{workout_id}/laps/{lap_index} endpoint."""

    def test_workout_lap_detail_success(self, mock_request, mock_semantic_layer):
        """Test successful lap detail retrieval."""
        mock_request.params = {"athlete_id": "rob"}
        mock_request.route_params = {"workout_id": "abc123", "lap_index": "2"}

        mock_lap = {
            "workout_id": "abc123",
            "lap_index": 2,
            "records": [],
        }
        mock_semantic_layer.get_workout_lap_detail.return_value = mock_lap

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = get_workout_lap_detail(mock_request)

        assert response.status_code == 200
        mock_semantic_layer.get_workout_lap_detail.assert_called_once_with(
            "rob",
            "abc123",
            2,
        )

    def test_workout_lap_detail_invalid_index(self, mock_request, mock_semantic_layer):
        """Test lap detail with invalid lap index."""
        mock_request.params = {"athlete_id": "rob"}
        mock_request.route_params = {"workout_id": "abc123", "lap_index": "abc"}

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = get_workout_lap_detail(mock_request)

        assert response.status_code == 400


class TestWeeklyRollupsEndpoint:
    """Tests for /api/rollups/weekly endpoint."""

    def test_missing_athlete_id(self, mock_request, mock_semantic_layer):
        """Test endpoint defaults to 'rob' when athlete_id not provided."""
        mock_semantic_layer.get_weekly_rollups.return_value = []

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = weekly_rollups(mock_request)

        assert response.status_code == 200
        mock_semantic_layer.get_weekly_rollups.assert_called_once_with("rob", 16)

    def test_success(self, mock_request, mock_semantic_layer):
        """Test successful weekly rollups request."""
        mock_request.params = {"athlete_id": "rob", "weeks": "12"}

        mock_rollups = [
            {
                "week_start_utc": "2026-01-13T00:00:00+00:00",
                "week_end_utc": "2026-01-19T23:59:59+00:00",
                "workouts_count": 4,
                "total_duration_min": 240.0,
            },
        ]
        mock_semantic_layer.get_weekly_rollups.return_value = mock_rollups

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = weekly_rollups(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert data["weeks"] == 12
        assert data["count"] == 1

    def test_weeks_parameter_capped(self, mock_request, mock_semantic_layer):
        """Test that weeks parameter is capped at 52."""
        mock_request.params = {"athlete_id": "rob", "weeks": "100"}

        mock_semantic_layer.get_weekly_rollups.return_value = []

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            weekly_rollups(mock_request)

        # Should cap at 52
        mock_semantic_layer.get_weekly_rollups.assert_called_once_with("rob", 52)


class TestZoneDistributionEndpoint:
    """Tests for /api/analysis/zones endpoint."""

    def test_missing_athlete_id(self, mock_request, mock_semantic_layer):
        """Test endpoint defaults to 'rob' when athlete_id not provided."""
        mock_semantic_layer.get_zone_distribution.return_value = {"athlete_id": "rob"}

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = zone_distribution(mock_request)

        assert response.status_code == 200
        mock_semantic_layer.get_zone_distribution.assert_called_once_with("rob", 30)

    def test_success(self, mock_request, mock_semantic_layer):
        """Test successful zone distribution request."""
        mock_request.params = {"athlete_id": "rob", "days": "30"}

        mock_distribution = {
            "athlete_id": "rob",
            "total_minutes": 600,
            "zones": {"z1": 50, "z2": 400, "z3": 80, "z4": 50, "z5": 20},
            "percentages": {"z1": 8.3, "z2": 66.7, "z3": 13.3, "z4": 8.3, "z5": 3.3},
        }
        mock_semantic_layer.get_zone_distribution.return_value = mock_distribution

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = zone_distribution(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert data["total_minutes"] == 600
        assert "zones" in data
        assert "percentages" in data


class TestEfficiencyTrendsEndpoint:
    """Tests for /api/analysis/efficiency endpoint."""

    def test_missing_athlete_id(self, mock_request, mock_semantic_layer):
        """Test endpoint defaults to 'rob' when athlete_id not provided."""
        mock_semantic_layer.get_efficiency_trends.return_value = {"athlete_id": "rob"}

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = efficiency_trends(mock_request)

        assert response.status_code == 200
        mock_semantic_layer.get_efficiency_trends.assert_called_once_with("rob", 90)

    def test_success(self, mock_request, mock_semantic_layer):
        """Test successful efficiency trends request."""
        mock_request.params = {"athlete_id": "rob", "days": "90"}

        mock_trends = {
            "athlete_id": "rob",
            "samples": [
                {"date": "2026-01-15", "decoupling_pct": 2.5},
            ],
            "summary": {"total_samples": 1, "avg_decoupling": 2.5},
        }
        mock_semantic_layer.get_efficiency_trends.return_value = mock_trends

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            response = efficiency_trends(mock_request)

        assert response.status_code == 200
        data = json.loads(response.get_body())
        assert "samples" in data
        assert "summary" in data
        assert data["summary"]["total_samples"] == 1

    def test_days_parameter_capped(self, mock_request, mock_semantic_layer):
        """Test that days parameter is capped at 365."""
        mock_request.params = {"athlete_id": "rob", "days": "500"}

        mock_semantic_layer.get_efficiency_trends.return_value = {}

        with patch.object(FunctionAppDependencies, "semantic_layer", new=PropertyMock(return_value=mock_semantic_layer)):
            efficiency_trends(mock_request)

        # Should cap at 365
        mock_semantic_layer.get_efficiency_trends.assert_called_once_with("rob", 365)
