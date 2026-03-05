"""Tests for WorkoutEntity schema enforcement.

Validates that WorkoutEntity enforces the documented queryable subset
and rejects undefined fields to prevent artifact conflation.
"""
# pylint: disable=redefined-outer-name  # pytest fixtures intentionally shadow

from datetime import datetime, timezone
from typing import Dict
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity


class TestWorkoutEntitySchema:
    """Schema enforcement for WorkoutEntity queryable subset."""

    EXPECTED_FIELDS = {
        "partition_key",
        "row_key",
        "workout_id",
        "athlete_id",
        "ingestion_id",
        "canonical_schema_version",
        "canonical_records_blob",
        "records_count",
        "laps_count",
        "start_time_utc",
        "sport",
        "sub_sport",
        "duration_sec",
        "distance_m",
        "device_manufacturer",
        "device_model",
        "has_power",
        "has_hr",
        "has_gps",
    }

    def test_workout_entity_queryable_fields_only(self):
        """Verify WorkoutEntity schema contains exactly the documented queryable fields."""
        fields = set(WorkoutEntity.model_fields.keys())
        assert fields == self.EXPECTED_FIELDS

    def test_workout_entity_forbids_extra_fields(self):
        """Verify ValidationError raised when extra fields passed to constructor."""
        with pytest.raises(ValidationError):
            WorkoutEntity(
                partition_key="rob|2026-02",
                row_key="20260214|abc",
                workout_id="w-001",
                athlete_id="rob",
                ingestion_id="ing-001",
                records_count=100,
                laps_count=0,
                start_time_utc="2026-02-14T10:00:00Z",
                distance_m=45000,
                device_manufacturer="Garmin",
                device_model="Edge 1040",
                sport="Cycling",
                duration_sec=3600,
                hr_avg_bpm=145,  # type: ignore # EXTRA: session metric
            )

    def test_workout_entity_forbids_provenance_fields(self):
        """Verify provenance fields rejected when passed to constructor."""
        with pytest.raises(ValidationError):
            WorkoutEntity(
                partition_key="rob|2026-02",
                row_key="20260214|abc",
                workout_id="w-001",
                athlete_id="rob",
                ingestion_id="ing-001",
                records_count=100,
                laps_count=0,
                start_time_utc="2026-02-14T10:00:00Z",
                distance_m=45000,
                device_manufacturer="Garmin",
                device_model="Edge 1040",
                sport="Cycling",
                duration_sec=3600,
                ingestion_version="v13",  # type: ignore # EXTRA: provenance field
            )

    def test_workout_entity_forbids_enrichment_fields(self):
        """Verify enrichment zone fields rejected from constructor."""
        with pytest.raises(ValidationError):
            WorkoutEntity(
                partition_key="rob|2026-02",
                row_key="20260214|abc",
                workout_id="w-001",
                athlete_id="rob",
                ingestion_id="ing-001",
                records_count=100,
                laps_count=0,
                start_time_utc="2026-02-14T10:00:00Z",
                distance_m=45000,
                device_manufacturer="Garmin",
                device_model="Edge 1040",
                sport="Cycling",
                duration_sec=3600,
                is_indoor=True,  # type: ignore # EXTRA: enrichment field
            )

    def test_workout_entity_forbids_activity_metadata_fields(self):
        """Verify activity_metadata zone fields rejected from constructor."""
        with pytest.raises(ValidationError):
            WorkoutEntity(
                partition_key="rob|2026-02",
                row_key="20260214|abc",
                workout_id="w-001",
                athlete_id="rob",
                ingestion_id="ing-001",
                records_count=100,
                laps_count=0,
                start_time_utc="2026-02-14T10:00:00Z",
                distance_m=45000,
                device_manufacturer="Garmin",
                device_model="Edge 1040",
                sport="Cycling",
                duration_sec=3600,
                local_tz_offset="UTC-05:00",  # type: ignore # EXTRA: activity_metadata field
            )

    def test_workout_entity_forbids_session_metrics(self):
        """Verify session zone metrics rejected from constructor."""
        with pytest.raises(ValidationError):
            WorkoutEntity(
                partition_key="rob|2026-02",
                row_key="20260214|abc",
                workout_id="w-001",
                athlete_id="rob",
                ingestion_id="ing-001",
                records_count=100,
                laps_count=0,
                start_time_utc="2026-02-14T10:00:00Z",
                distance_m=45000,
                device_manufacturer="Garmin",
                device_model="Edge 1040",
                sport="Cycling",
                duration_sec=3600,
                pwr_avg_watts=250,  # type: ignore # EXTRA: session metric
            )

    def test_workout_entity_from_table_entity_ignores_extra_fields(self):
        """Verify from_table_entity safely ignores extra fields (selective extraction)."""
        table_entity = {
            "PartitionKey": "rob|2026-02",
            "RowKey": "20260214|abc",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ing-001",
            "sport": "Cycling",
            "duration_sec": 3600,
            "hr_avg_bpm": 145,  # EXTRA: ignored by from_table_entity
            "pwr_avg_watts": 250,  # EXTRA: ignored by from_table_entity
            "is_indoor": True,  # EXTRA: ignored by from_table_entity
        }

        # from_table_entity doesn't raise, it just extracts the fields it needs
        entity = WorkoutEntity.from_table_entity(table_entity)

        # Verify only queryable fields are present
        assert entity.workout_id == "workout-001"
        assert entity.sport == "Cycling"
        assert not hasattr(entity, "hr_avg_bpm")
        assert not hasattr(entity, "pwr_avg_watts")
        assert not hasattr(entity, "is_indoor")

    def test_workout_entity_from_valid_table_entity(self):
        """Verify from_table_entity works with valid queryable fields."""
        table_entity = {
            "PartitionKey": "rob|2026-02",
            "RowKey": "20260214|abc",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ing-001",
            "sport": "Cycling",
            "sub_sport": "Road",
            "duration_sec": 3600,
            "distance_m": 45000,
            "start_time_utc": datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc).isoformat(),
            "device_manufacturer": "Garmin",
            "device_model": "Edge 1040",
            "has_power": True,
            "has_hr": True,
            "has_gps": True,
            "canonical_schema_version": "2.0.1",
            "canonical_records_blob": "metadata/w-001.parquet",
            "records_count": 3600,
            "laps_count": 0,
        }

        entity = WorkoutEntity.from_table_entity(table_entity)

        assert entity.workout_id == "workout-001"
        assert entity.athlete_id == "rob"
        assert entity.sport == "Cycling"
        assert entity.duration_sec == 3600
        assert entity.has_power is True

    def test_workout_entity_to_entity_returns_only_queryable_fields(self):
        """Verify to_entity method returns only queryable fields, no metrics dict expansion."""
        table_entity = {
            "PartitionKey": "rob|2026-02",
            "RowKey": "20260214|abc",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ing-001",
            "sport": "Cycling",
            "duration_sec": 3600,
        }

        entity = WorkoutEntity.from_table_entity(table_entity)
        output_entity = entity.to_entity()

        # Verify only core fields present
        assert "workout_id" in output_entity
        assert "athlete_id" in output_entity
        assert "sport" in output_entity
        assert "duration_sec" in output_entity

        # Verify no extra fields added
        assert len(output_entity) <= 19  # Max queryable fields

    def test_workout_entity_forbids_metrics_field_directly(self):
        """Verify metrics field cannot be set directly on WorkoutEntity."""
        with pytest.raises(ValidationError):
            WorkoutEntity(
                partition_key="rob|2026-02",
                row_key="20260214|abc",
                workout_id="w-001",
                athlete_id="rob",
                ingestion_id="ing-001",
                records_count=100,
                laps_count=0,
                start_time_utc="2026-02-14T10:00:00Z",
                distance_m=45000,
                device_manufacturer="Garmin",
                device_model="Edge 1040",
                sport="Cycling",
                duration_sec=3600,
                metrics={"hr_avg_bpm": 145},  # type: ignore # FORBIDDEN
            )

    def test_workout_entity_strict_config(self):
        """Verify WorkoutEntity uses extra=forbid in ConfigDict."""
        # ConfigDict should prevent unknown fields
        # This is enforced at the Pydantic model level
        config = WorkoutEntity.model_config
        assert config.get("extra") == "forbid"
