"""Unit tests for workout Azure Table Storage write-path behavior."""

# pylint: disable=protected-access

from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.storage.table_storage import WorkoutTableStorage


class TestStoreWorkoutPartitioning:
    """Tests for Workouts PartitionKey/RowKey derivation."""

    def test_store_workout_uses_start_time_month_partition(self) -> None:
        """Verify canonical start_time_utc drives athlete|YYYY-MM partitioning."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        workout_id = "0123456789abcdef0123456789abcdef01234567"
        source_info = {
            "source_system": "HealthFit",
            "normalized_source_system": "Garmin",
            "source_item_id": "onedrive:item-1",
        }
        metadata = {
            "start_time_utc": "2026-02-14T16:38:37+00:00",
            "timezone": "UTC+00:00",
            "sport": "functional",
        }

        storage.store_workout(
            "rob",
            metadata,
            source_info,
            workout_id=workout_id,
            ingestion_id="ing-1",
        )

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["PartitionKey"] == "rob|2026-02"
        assert entity["timezone"] == "UTC+00:00"

    def test_store_workout_accepts_legacy_precise_only_start_time(self) -> None:
        """Verify legacy start_time_utc_precise metadata can still derive partitioning."""
        storage = WorkoutTableStorage.__new__(WorkoutTableStorage)
        mock_table_client = MagicMock()
        storage._get_table_client = MagicMock(return_value=mock_table_client)

        workout_id = "fedcba9876543210fedcba9876543210fedcba98"
        source_info = {
            "source_system": "HealthFit",
            "normalized_source_system": "Garmin",
            "source_item_id": "onedrive:item-2",
        }
        metadata = {
            "start_time_utc_precise": "2026-01-30T12:27:36+00:00",
            "sport": "indoor",
        }

        storage.store_workout(
            "rob",
            metadata,
            source_info,
            workout_id=workout_id,
            ingestion_id="ing-2",
        )

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["PartitionKey"] == "rob|2026-01"
