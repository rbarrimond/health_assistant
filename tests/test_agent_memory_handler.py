"""Tests for AgentMemoryHandler."""

# pylint: disable=line-too-long
# pylint: disable=protected-access
# pylint: disable=unused-argument

from unittest.mock import Mock, MagicMock

import pytest

from TrainingAnalyticsPlatform.handlers import AgentMemoryHandler


class TestAgentMemoryHandler:
    """Test suite for AgentMemoryHandler."""

    @pytest.fixture
    def mock_table_storage(self):
        """Create mock storage coordinator."""
        storage = Mock()
        storage.infrastructure = Mock()
        storage.infrastructure.get_table_client = Mock()
        return storage

    @pytest.fixture
    def handler(self, mock_table_storage):
        """Create handler instance with mocked dependencies."""
        return AgentMemoryHandler(mock_table_storage)

    # ========================================================================
    # get_context tests
    # ========================================================================

    def test_get_context_success(self, handler, mock_table_storage):
        """Test successful retrieval of complete agent context."""
        # Arrange
        mock_prefs_client = MagicMock()
        mock_obs_client = MagicMock()

        def get_table_client(table_name):
            if table_name == "AgentPreferences":
                return mock_prefs_client
            return mock_obs_client

        mock_table_storage.infrastructure.get_table_client.side_effect = get_table_client

        # Mock preferences entity
        prefs_entity = {
            "PartitionKey": "rob",
            "RowKey": "preferences",
            "current_goal": "Build base",
            "training_phase": "base-building",
            "preferred_sports": "cycling,running",
            "ftp_test_frequency_weeks": 6,
            "last_ftp_test_date": "2026-01-15",
            "notes": "Focus on Z2",
            "updated_at": "2026-02-01T00:00:00+00:00"
        }

        # Mock observations
        obs_entities = [
            {
                "PartitionKey": "rob",
                "RowKey": "obs-1",
                "category": "pattern",
                "summary": "Low decoupling",
                "details": "Consistent <5%",
                "referenced_workout_ids": "w1,w2",
                "priority": "normal",
                "status": "active",
                "created_at": "2026-02-01T00:00:00+00:00",
                "expires_at": None
            }
        ]

        mock_prefs_client.query_entities.return_value = [prefs_entity]
        mock_obs_client.query_entities.return_value = obs_entities

        # Act
        result, status = handler.get_context("rob")

        # Assert
        assert status == 200
        assert result["athlete_id"] == "rob"
        assert "preferences" in result
        assert any(
            pref["category"] == "current_goal"
            and pref["summary"] == "Build base"
            for pref in result["preferences"]
        )
        assert "active_observations" in result
        assert len(result["active_observations"]) == 1
        assert "instruction_addendum" in result
        assert "Build base" in result["instruction_addendum"]

    def test_get_context_missing_athlete_id(self, handler, mock_table_storage):
        """Test get_context with missing athlete_id."""
        # Act
        result, status = handler.get_context(None)

        # Assert
        assert status == 400
        assert "error" in result
        assert "athlete_id" in result["error"].lower()

    def test_get_context_empty_athlete_id(self, handler, mock_table_storage):
        """Test get_context with empty athlete_id."""
        # Act
        result, status = handler.get_context("")

        # Assert
        assert status == 400
        assert "error" in result

    # ========================================================================
    # get_preferences tests
    # ========================================================================

    def test_get_preferences_success(self, handler, mock_table_storage):
        """Test successful retrieval of preferences."""
        # Arrange
        mock_client = MagicMock()
        mock_table_storage.infrastructure.get_table_client.return_value = mock_client

        prefs_entity = {
            "PartitionKey": "rob",
            "RowKey": "preferences",
            "current_goal": "Build base",
            "training_phase": "base-building",
            "preferred_sports": "cycling",
            "ftp_test_frequency_weeks": 6,
            "last_ftp_test_date": None,
            "notes": None,
            "updated_at": "2026-02-01T00:00:00+00:00"
        }

        mock_client.query_entities.return_value = [prefs_entity]

        # Act
        result, status = handler.get_preferences("rob")

        # Assert
        assert status == 200
        assert result["athlete_id"] == "rob"
        assert "preferences" in result
        assert any(
            pref["category"] == "current_goal"
            and pref["summary"] == "Build base"
            for pref in result["preferences"]
        )

    def test_get_preferences_not_found(self, handler, mock_table_storage):
        """Test get_preferences when no preferences exist."""
        # Arrange
        mock_client = MagicMock()
        mock_table_storage.infrastructure.get_table_client.return_value = mock_client
        mock_client.query_entities.return_value = []

        # Act
        result, status = handler.get_preferences("rob")

        # Assert
        assert status == 200
        assert result["athlete_id"] == "rob"
        assert result["preferences"] == []

    def test_get_preferences_missing_athlete_id(self, handler, mock_table_storage):
        """Test get_preferences with missing athlete_id."""
        # Act
        result, status = handler.get_preferences(None)

        # Assert
        assert status == 400
        assert "error" in result

    # ========================================================================
    # update_preferences tests
    # ========================================================================

    def test_update_preferences_success(self, handler, mock_table_storage):
        """Test successful update of preferences."""
        # Arrange
        mock_client = MagicMock()
        mock_table_storage.infrastructure.get_table_client.return_value = mock_client

        preferences = {
            "current_goal": "Build base for spring races",
            "training_phase": "base-building",
            "preferred_sports": ["cycling", "running"],
            "ftp_test_frequency_weeks": 6
        }

        # Act
        result, status = handler.update_preferences("rob", preferences)

        # Assert
        assert status == 200
        assert result["athlete_id"] == "rob"
        assert "preferences" in result
        assert result["preferences"]["current_goal"] == "Build base for spring races"
        mock_client.upsert_entity.assert_called_once()

    def test_update_preferences_missing_athlete_id(self, handler, mock_table_storage):
        """Test update_preferences with missing athlete_id."""
        # Act
        result, status = handler.update_preferences(None, {})

        # Assert
        assert status == 400
        assert "error" in result

    def test_update_preferences_validation_error(self, handler, mock_table_storage):
        """Test update_preferences with invalid data."""
        # Arrange
        preferences = {
            "ftp_test_frequency_weeks": "not_a_number"  # Invalid type
        }

        # Act
        result, status = handler.update_preferences("rob", preferences)

        # Assert
        assert status == 500
        assert "error" in result

    # ========================================================================
    # add_observation tests
    # ========================================================================

    def test_add_observation_success(self, handler, mock_table_storage):
        """Test successful addition of observation."""
        # Arrange
        mock_client = MagicMock()
        mock_table_storage.infrastructure.get_table_client.return_value = mock_client

        # Act
        result, status = handler.add_observation(
            athlete_id="rob",
            category="pattern",
            summary="Low decoupling trend",
            details="Last 6 sessions <5%",
            workout_ids=["w1", "w2"],
            priority="normal",
            expires_days=30
        )

        # Assert
        assert status == 201
        assert "observation_id" in result
        assert "observation" in result
        assert result["observation"]["summary"] == "Low decoupling trend"
        mock_client.upsert_entity.assert_called_once()

    def test_add_observation_missing_required_fields(self, handler, mock_table_storage):
        """Test add_observation with missing required fields."""
        # Act - missing summary
        result, status = handler.add_observation(
            athlete_id="rob",
            category="pattern",
            summary="",
        )

        # Assert
        assert status == 400
        assert "error" in result

    # ========================================================================
    # list_observations tests
    # ========================================================================

    def test_list_observations_success(self, handler, mock_table_storage):
        """Test successful listing of observations."""
        # Arrange
        mock_client = MagicMock()
        mock_table_storage.infrastructure.get_table_client.return_value = mock_client

        obs_entities = [
            {
                "PartitionKey": "rob",
                "RowKey": "obs-1",
                "category": "pattern",
                "summary": "Pattern 1",
                "details": None,
                "referenced_workout_ids": "",
                "priority": "high",
                "status": "active",
                "created_at": "2026-02-01T00:00:00+00:00",
                "expires_at": None
            },
            {
                "PartitionKey": "rob",
                "RowKey": "obs-2",
                "category": "flag",
                "summary": "Flag 1",
                "details": "Details",
                "referenced_workout_ids": "w1",
                "priority": "normal",
                "status": "active",
                "created_at": "2026-02-02T00:00:00+00:00",
                "expires_at": None
            }
        ]

        mock_client.query_entities.return_value = obs_entities

        # Act
        result, status = handler.list_observations("rob", status="active", limit=20)

        # Assert
        assert status == 200
        assert result["athlete_id"] == "rob"
        assert result["count"] == 2
        assert len(result["observations"]) == 2
        # High priority should come first
        assert result["observations"][0]["priority"] == "high"

    def test_list_observations_missing_athlete_id(self, handler, mock_table_storage):
        """Test list_observations with missing athlete_id."""
        # Act
        result, status = handler.list_observations(None)

        # Assert
        assert status == 400
        assert "error" in result

    # ========================================================================
    # update_observation_status tests
    # ========================================================================

    def test_update_observation_status_success(self, handler, mock_table_storage):
        """Test successful update of observation status."""
        # Arrange
        mock_client = MagicMock()
        mock_table_storage.infrastructure.get_table_client.return_value = mock_client

        existing_entity = {
            "PartitionKey": "rob",
            "RowKey": "obs-1",
            "category": "pattern",
            "summary": "Test",
            "status": "active"
        }

        mock_client.get_entity.return_value = existing_entity

        # Act
        result, status = handler.update_observation_status(
            athlete_id="rob",
            observation_id="obs-1",
            status="resolved"
        )

        # Assert
        assert status == 200
        assert result["observation_id"] == "obs-1"
        assert result["status"] == "resolved"
        mock_client.update_entity.assert_called_once()

    def test_update_observation_status_not_found(self, handler, mock_table_storage):
        """Test update_observation_status when observation doesn't exist."""
        # Arrange
        mock_client = MagicMock()
        mock_table_storage.infrastructure.get_table_client.return_value = mock_client
        mock_client.get_entity.side_effect = Exception("Not found")

        # Act
        result, status = handler.update_observation_status(
            athlete_id="rob",
            observation_id="nonexistent",
            status="resolved"
        )

        # Assert
        assert status == 404
        assert "error" in result

    def test_update_observation_status_invalid_status(self, handler, mock_table_storage):
        """Test update_observation_status with invalid status."""
        # Act
        result, status = handler.update_observation_status(
            athlete_id="rob",
            observation_id="obs-1",
            status="invalid_status"
        )

        # Assert
        assert status == 400
        assert "error" in result
        assert "Invalid status" in result["error"]

    def test_update_observation_status_missing_params(self, handler, mock_table_storage):
        """Test update_observation_status with missing parameters."""
        # Act
        result, status = handler.update_observation_status(
            athlete_id=None,
            observation_id="obs-1",
            status="resolved"
        )

        # Assert
        assert status == 400
        assert "error" in result
