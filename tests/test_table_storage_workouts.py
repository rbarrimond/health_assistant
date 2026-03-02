"""Unit tests for workout Azure Table Storage write-path behavior."""

# pylint: disable=protected-access

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from TrainingAnalyticsPlatform.storage.table_storage import WorkoutEntity
from TrainingAnalyticsPlatform.storage.workout_storage import WorkoutStorage


class TestStoreWorkoutPartitioning:
    """Tests for Workouts PartitionKey/RowKey derivation."""

    def test_store_workout_uses_start_time_month_partition(self) -> None:
        """Verify canonical start_time_utc drives athlete|YYYY-MM partitioning."""
        storage = WorkoutStorage.__new__(WorkoutStorage)
        mock_table_client = MagicMock()
        storage.infra = MagicMock()
        storage.infra.get_table_client = MagicMock(return_value=mock_table_client)

        workout_id = "0123456789abcdef0123456789abcdef01234567"
        # Note: source_system, normalized_source_system, source_item_id are no longer
        # part of WorkoutEntity schema (removed in v2.0.0 refactor). They're only stored
        # in IngestionState table for audit purposes.
        metadata = {
            "identity": {
                "start_time_utc": "2026-02-14T16:38:37+00:00",
                "sport": "functional",
                "device_manufacturer": "Apple",
                "device_model": "Apple Watch Series 9",
            },
        }

        storage.store_workout(
            "rob",
            metadata,
            workout_id=workout_id,
            ingestion_id="ing-1",
        )

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["PartitionKey"] == "rob|2026-02"
        assert entity["device_manufacturer"] == "Apple"
        assert entity["device_model"] == "Apple Watch Series 9"

    def test_store_workout_uses_unknown_partition_without_start_time(self) -> None:
        """Verify missing start_time_utc falls back to unknown partitioning."""
        storage = WorkoutStorage.__new__(WorkoutStorage)
        mock_table_client = MagicMock()
        storage.infra = MagicMock()
        storage.infra.get_table_client = MagicMock(return_value=mock_table_client)

        workout_id = "fedcba9876543210fedcba9876543210fedcba98"
        # Note: source_system, normalized_source_system, source_item_id are no longer
        # part of WorkoutEntity schema (removed in v2.0.0 refactor). They're only stored
        # in IngestionState table for audit purposes.
        metadata = {
            "identity": {
                "sport": "indoor",
            },
        }

        storage.store_workout(
            "rob",
            metadata,
            workout_id=workout_id,
            ingestion_id="ing-2",
        )

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["PartitionKey"] == "rob|unknown"

class TestWorkoutEntitySchemaValidation:
    """Tests for WorkoutEntity Pydantic schema validation with extra='forbid'."""

    def test_workout_entity_rejects_source_system_field(self) -> None:
        """Verify WorkoutEntity correctly rejects removed 'source_system' field."""
        with pytest.raises(ValidationError) as exc_info:
            WorkoutEntity(
                partition_key="test",
                row_key="test",
                workout_id="test",
                athlete_id="test",
                ingestion_id="test",
                source_system="HealthFit",  # ← Removed in v2.0.0
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_workout_entity_rejects_normalized_source_system_field(self) -> None:
        """Verify WorkoutEntity correctly rejects removed 'normalized_source_system' field."""
        with pytest.raises(ValidationError) as exc_info:
            WorkoutEntity(
                partition_key="test",
                row_key="test",
                workout_id="test",
                athlete_id="test",
                ingestion_id="test",
                normalized_source_system="Garmin",  # ← Removed in v2.0.0
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_workout_entity_rejects_source_item_id_field(self) -> None:
        """Verify WorkoutEntity correctly rejects removed 'source_item_id' field."""
        with pytest.raises(ValidationError) as exc_info:
            WorkoutEntity(
                partition_key="test",
                row_key="test",
                workout_id="test",
                athlete_id="test",
                ingestion_id="test",
                source_item_id="onedrive:item-123",  # ← Removed in v2.0.0
            )
        assert "Extra inputs are not permitted" in str(exc_info.value)

    def test_workout_entity_accepts_valid_device_fields(self) -> None:
        """Verify WorkoutEntity accepts new clean device fields."""
        entity = WorkoutEntity(
            partition_key="test",
            row_key="test",
            workout_id="test",
            athlete_id="test",
            ingestion_id="test",
            device_manufacturer="Apple",
            device_model="Apple Watch Series 9",
        )
        assert entity.device_manufacturer == "Apple"
        assert entity.device_model == "Apple Watch Series 9"