"""Unit tests for physiometrics Azure Table Storage methods."""

# Allow protected member access in tests for internal state verification.
# pylint: disable=protected-access

import json
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.table_storage import WorkoutTableStorage


class TestStorePhysiometrics:
    """Tests for store_physiometrics method."""

    def test_store_physiometrics_success(self) -> None:
        """Verify physiometrics are stored with timestamp."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        physiometrics_data = {
            "heart_rate": {
                "basis": "HRmax",
                "lthr_bpm": 175,
                "hr_max_bpm": 195,
                "resting_hr_bpm": 52,
            },
            "power": {"ftp_watts": 285}
        }

        timestamp = storage.store_physiometrics("rob", physiometrics_data)

        assert isinstance(timestamp, str)
        assert "T" in timestamp  # ISO format
        mock_table_client.upsert_entity.assert_called_once()

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["PartitionKey"] == "rob"
        assert entity["heart_rate_basis"] == "HRmax"
        assert entity["power_ftp_watts"] == 285

    def test_store_physiometrics_stores_full_json(self) -> None:
        """Verify full config JSON is stored for auditability."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        physiometrics_data = {
            "heart_rate": {"basis": "HRmax"},
            "power": {"ftp_watts": 250}
        }

        storage.store_physiometrics("rob", physiometrics_data)

        entity = mock_table_client.upsert_entity.call_args[0][0]
        stored_json = json.loads(entity["full_config_json"])
        assert stored_json == physiometrics_data

    def test_store_physiometrics_handles_null_values(self) -> None:
        """Verify null values are handled gracefully."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        physiometrics_data = {
            "heart_rate": {
                "basis": "HRmax",
                "lthr_bpm": None,
                "hr_max_bpm": None
            },
            "power": {"ftp_watts": None}
        }

        storage.store_physiometrics("rob", physiometrics_data)

        mock_table_client.upsert_entity.assert_called_once()

    def test_store_physiometrics_error(self) -> None:
        """Verify error is raised on storage failure."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        mock_table_client.upsert_entity.side_effect = HttpResponseError("Storage error")
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        physiometrics_data = {"heart_rate": {}, "power": {}}

        with pytest.raises(HttpResponseError):
            storage.store_physiometrics("rob", physiometrics_data)


class TestGetPhysiometrics:
    """Tests for get_physiometrics method."""

    def test_get_physiometrics_latest(self) -> None:
        """Verify latest physiometrics are retrieved."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()

        config_json = json.dumps({
            "heart_rate": {"basis": "HRmax", "hr_max_bpm": 195},
            "power": {"ftp_watts": 285}
        })
        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "2026-01-18T10:30:00+00:00",
            "full_config_json": config_json,
            "heart_rate_basis": "HRmax",
        }

        mock_table_client.query_entities.return_value = [mock_entity]
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is not None
        assert result["heart_rate"]["basis"] == "HRmax"
        assert result["power"]["ftp_watts"] == 285

    def test_get_physiometrics_fallback_to_fields(self) -> None:
        """Verify fallback reconstruction from individual fields."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "2026-01-18T10:30:00+00:00",
            "full_config_json": None,
            "heart_rate_basis": "LTHR",
            "heart_rate_lthr_bpm": 170,
            "heart_rate_hr_max_bpm": 190,
            "heart_rate_resting_bpm": 48,
            "power_ftp_watts": 300,
        }

        mock_table_client.query_entities.return_value = [mock_entity]
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is not None
        assert result["heart_rate"]["basis"] == "LTHR"
        assert result["heart_rate"]["lthr_bpm"] == 170
        assert result["power"]["ftp_watts"] == 300

    def test_get_physiometrics_not_found(self) -> None:
        """Verify None returned when no physiometrics found."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        mock_table_client.query_entities.return_value = []
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is None

    def test_get_physiometrics_query_error(self) -> None:
        """Verify None returned on query error."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        mock_table_client.query_entities.side_effect = HttpResponseError("Query error")
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is None


class TestListPhysiometricsHistory:
    """Tests for list_physiometrics_history method."""

    def test_list_physiometrics_history_success(self) -> None:
        """Verify history is sorted newest first."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()

        mock_entities = [
            {"RowKey": "2026-01-18T09:30:00+00:00", "heart_rate_basis": "HRmax"},
            {"RowKey": "2026-01-18T10:30:00+00:00", "heart_rate_basis": "LTHR"},
            {"RowKey": "2026-01-18T08:30:00+00:00", "heart_rate_basis": "HRR"},
        ]

        mock_table_client.query_entities.return_value = mock_entities
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        result = storage.list_physiometrics_history("rob", limit=10)

        # Should be sorted by RowKey descending
        assert result[0]["RowKey"] == "2026-01-18T10:30:00+00:00"
        assert result[1]["RowKey"] == "2026-01-18T09:30:00+00:00"
        assert result[2]["RowKey"] == "2026-01-18T08:30:00+00:00"

    def test_list_physiometrics_history_limit(self) -> None:
        """Verify limit is respected."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()

        mock_entities = [
            {"RowKey": f"2026-01-18T{i:02d}:30:00+00:00"} for i in range(10)
        ]

        mock_table_client.query_entities.return_value = mock_entities
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        result = storage.list_physiometrics_history("rob", limit=5)

        assert len(result) == 5

    def test_list_physiometrics_history_query_error(self) -> None:
        """Verify empty list returned on error."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        mock_table_client.query_entities.side_effect = HttpResponseError("Query error")
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        result = storage.list_physiometrics_history("rob", limit=10)

        assert result == []


class TestEnsurePhysiometricsTable:
    """Tests for Physiometrics table creation."""

    # Test classes don't need multiple public methods.
    # pylint: disable=too-few-public-methods
    def test_ensure_tables_exist_includes_physiometrics(self) -> None:
        """Verify Physiometrics table is created on init."""
        mock_service_client = MagicMock()

        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        storage.service_client = mock_service_client
        storage._ensure_tables_exist()

        table_names = [
            call[0][0]
            for call in (
                mock_service_client
                .create_table_if_not_exists
                .call_args_list
            )
        ]
        assert "Physiometrics" in table_names
