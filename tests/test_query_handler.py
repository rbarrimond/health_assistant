"""Tests for QueryHandler."""

from unittest.mock import Mock

import pytest

from FitParser.handlers import QueryHandler


class TestQueryHandler:
    """Test suite for QueryHandler."""

    @pytest.fixture
    def mock_semantic_layer(self):
        """Create mock SemanticLayer."""
        return Mock()

    @pytest.fixture
    def handler(self, mock_semantic_layer):
        """Create handler instance with mocked dependencies."""
        return QueryHandler(mock_semantic_layer)

    def test_get_planning_context_success(self, handler, mock_semantic_layer):
        """Test successful planning context retrieval."""
        # Arrange
        expected_data = {
            "athlete_id": "athlete1",
            "days": 30,
            "summary": {"total_workouts": 15, "total_duration_hours": 20}
        }
        mock_semantic_layer.get_planning_context.return_value = expected_data

        # Act
        result, status = handler.query_planning_context("athlete1", 30)

        # Assert
        assert status == 200
        assert result == expected_data
        mock_semantic_layer.get_planning_context.assert_called_once_with(
            "athlete1", 30
        )

    def test_get_planning_context_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test planning context with missing athlete_id - semantic layer raises ValueError."""
        # Arrange
        mock_semantic_layer.get_planning_context.side_effect = ValueError("athlete_id required")

        # Act
        result, status = handler.query_planning_context(None, 30)

        # Assert
        assert status == 400  # ValueError caught, returns 400
        assert result == {}  # Handler returns empty dict on validation error

    def test_get_planning_context_default_days(self, handler, mock_semantic_layer):
        """Test planning context uses default days value."""
        # Arrange
        mock_semantic_layer.get_planning_context.return_value = {}

        # Act
        _, status = handler.query_planning_context("athlete1")

        # Assert
        assert status == 200
        # Verify default days=45 was used (positional args)
        mock_semantic_layer.get_planning_context.assert_called_once_with(
            "athlete1", 45
        )

    def test_get_planning_context_exception(self, handler, mock_semantic_layer):
        """Test planning context handles exceptions."""
        # Arrange
        mock_semantic_layer.get_planning_context.side_effect = Exception("DB error")

        # Act
        _, status = handler.query_planning_context("athlete1", 30)

        # Assert
        assert status == 500
        assert _ == {}  # Handler returns empty dict on exception

    def test_get_athlete_workouts_success(self, handler, mock_semantic_layer):
        """Test successful athlete workouts retrieval."""
        # Arrange
        expected_data = [
            {"date": "2026-01-31", "sport": "cycling"},
            {"date": "2026-01-30", "sport": "running"}
        ]
        mock_semantic_layer.get_workouts.return_value = expected_data

        # Act
        result, status = handler.query_athlete_workouts("athlete1", 7)

        # Assert
        assert status == 200
        assert result == expected_data
        mock_semantic_layer.get_workouts.assert_called_once_with(
            "athlete1", limit=7
        )

    def test_get_athlete_workouts_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test athlete workouts with missing athlete_id - semantic layer raises ValueError."""
        # Arrange
        mock_semantic_layer.get_workouts.side_effect = ValueError("athlete_id required")

        # Act
        result, status = handler.query_athlete_workouts(None, 7)

        # Assert
        assert status == 400  # ValueError caught, returns 400
        assert result == []  # Handler returns empty list on validation error

    def test_query_athlete_workouts_default_limit(self, handler, mock_semantic_layer):
        """Test athlete workouts uses default limit."""
        # Arrange
        mock_semantic_layer.get_workouts.return_value = []

        # Act
        _, status = handler.query_athlete_workouts("athlete1")

        # Assert
        assert status == 200
        mock_semantic_layer.get_workouts.assert_called_once_with(
            "athlete1", limit=20  # Default limit
        )

    def test_get_training_zones_success(self, handler, mock_semantic_layer):
        """Test successful training zones retrieval."""
        # Arrange
        expected_data = {
            "athlete_id": "athlete1",
            "hr_zones": [120, 140, 160, 175],
            "power_zones": [150, 200, 250, 300]
        }
        mock_semantic_layer.get_zone_distribution.return_value = expected_data

        # Act
        result, status = handler.query_training_zones("athlete1")

        # Assert
        assert status == 200
        assert result == expected_data
        mock_semantic_layer.get_zone_distribution.assert_called_once_with(
            "athlete1", 30  # Default days
        )

    def test_get_training_zones_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test training zones with missing athlete_id - semantic layer raises ValueError."""
        # Arrange
        mock_semantic_layer.get_zone_distribution.side_effect = ValueError("athlete_id required")

        # Act
        result, status = handler.query_training_zones(None)

        # Assert
        assert status == 400
        assert result == {}

    def test_get_training_zones_exception(self, handler, mock_semantic_layer):
        """Test training zones handles exceptions."""
        # Arrange
        mock_semantic_layer.get_zone_distribution.side_effect = Exception("Config error")

        # Act
        result, status = handler.query_training_zones("athlete1")

        # Assert
        assert status == 500
        assert result == {}

    def test_get_efficiency_trends_success(self, handler, mock_semantic_layer):
        """Test successful efficiency trends retrieval."""
        # Arrange
        expected_data = {
            "athlete_id": "athlete1",
            "trends": [
                {"date": "2026-01-31", "efficiency": 0.95},
                {"date": "2026-01-30", "efficiency": 0.93}
            ]
        }
        mock_semantic_layer.get_efficiency_trends.return_value = expected_data

        # Act
        result, status = handler.query_efficiency_trends("athlete1", 14)

        # Assert
        assert status == 200
        assert result == expected_data
        mock_semantic_layer.get_efficiency_trends.assert_called_once_with(
            "athlete1", 14
        )

    def test_get_efficiency_trends_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test efficiency trends with missing athlete_id."""
        # Arrange
        mock_semantic_layer.get_efficiency_trends.side_effect = ValueError("athlete_id required")

        # Act
        result, status = handler.query_efficiency_trends(None, 14)

        # Assert
        assert status == 400
        assert result == {}  # Handler returns empty dict on ValueError

    def test_get_efficiency_trends_default_days(self, handler, mock_semantic_layer):
        """Test efficiency trends uses default days."""
        # Arrange
        mock_semantic_layer.get_efficiency_trends.return_value = {}

        # Act
        _, status = handler.query_efficiency_trends("athlete1")

        # Assert
        assert status == 200
        mock_semantic_layer.get_efficiency_trends.assert_called_once_with(
            "athlete1", 90  # Default is 90 days
        )

    def test_get_weekly_rollups_success(self, handler, mock_semantic_layer):
        """Test successful weekly rollups retrieval."""
        # Arrange
        rollups_data = [
            {"week": "2026-W05", "total_hours": 12, "total_distance_km": 150},
            {"week": "2026-W04", "total_hours": 10, "total_distance_km": 120}
        ]
        mock_semantic_layer.get_weekly_rollups.return_value = rollups_data

        # Act
        result, status = handler.query_weekly_rollups("athlete1", 8)

        # Assert
        assert status == 200
        assert result["athlete_id"] == "athlete1"
        assert result["weeks"] == 8
        assert result["count"] == 2
        assert result["rollups"] == rollups_data
        mock_semantic_layer.get_weekly_rollups.assert_called_once_with(
            "athlete1", 8
        )

    def test_get_weekly_rollups_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test weekly rollups with missing athlete_id."""
        # Arrange
        mock_semantic_layer.get_weekly_rollups.side_effect = ValueError("athlete_id required")

        # Act
        result, status = handler.query_weekly_rollups(None, 8)

        # Assert
        assert status == 400
        assert result == {}  # Handler returns empty dict on ValueError

    def test_get_weekly_rollups_default_weeks(self, handler, mock_semantic_layer):
        """Test weekly rollups uses default weeks."""
        # Arrange
        mock_semantic_layer.get_weekly_rollups.return_value = []

        # Act
        result, status = handler.query_weekly_rollups("athlete1")

        # Assert
        assert status == 200
        assert result["weeks"] == 16  # Default is 16 weeks
        mock_semantic_layer.get_weekly_rollups.assert_called_once_with(
            "athlete1", 16
        )

    def test_get_weekly_rollups_exception(self, handler, mock_semantic_layer):
        """Test weekly rollups handles exceptions."""
        # Arrange
        mock_semantic_layer.get_weekly_rollups.side_effect = Exception("Aggregation error")

        # Act
        result, status = handler.query_weekly_rollups("athlete1", 8)

        # Assert
        assert status == 500
        assert result == {}  # Handler returns empty dict on exception

    def test_all_methods_handle_empty_string_athlete_id(self, handler, mock_semantic_layer):
        """Test all query methods handle empty string athlete_id via semantic layer ValueError."""
        # Arrange - semantic layer raises ValueError for invalid athlete_id
        mock_semantic_layer.get_planning_context.side_effect = ValueError("Invalid athlete_id")
        mock_semantic_layer.get_workouts.side_effect = ValueError("Invalid athlete_id")
        mock_semantic_layer.get_zone_distribution.side_effect = ValueError("Invalid athlete_id")
        mock_semantic_layer.get_efficiency_trends.side_effect = ValueError("Invalid athlete_id")
        mock_semantic_layer.get_weekly_rollups.side_effect = ValueError("Invalid athlete_id")

        # Act & Assert for each method - all should return 400 with empty dict/list
        result, status = handler.query_planning_context("", 30)
        assert status == 400
        assert result == {}

        result, status = handler.query_athlete_workouts("", 30)
        assert status == 400
        assert result == []

        result, status = handler.query_training_zones("", 30)
        assert status == 400
        assert result == {}

        result, status = handler.query_efficiency_trends("", 30)
        assert status == 400
        assert result == {}

        result, status = handler.query_weekly_rollups("", 12)
        assert status == 400
        assert result == {}
