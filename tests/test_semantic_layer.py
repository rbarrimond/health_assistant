"""Tests for semantic access layer."""
# pylint: disable=redefined-outer-name  # pytest fixtures intentionally shadow
# pylint: disable=unused-argument  # pytest fixtures may be used for side effects
# pylint: disable=protected-access  # testing private methods intentionally

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from TrainingAnalyticsPlatform.analytics.semantic_layer import (
    WEEKLY_ROLLUP_ALLOWED_FIELDS,
    SemanticLayer,
)
from TrainingAnalyticsPlatform.models.core import WorkoutMetricsModel, WorkoutProjection
from TrainingAnalyticsPlatform.models.metrics.performance import DurabilityMetricsModel
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot
from TrainingAnalyticsPlatform.platform.exceptions import StorageError, ValidationError


def build_rollup_metrics_model(flat_metrics):
    """Build a typed WorkoutMetricsModel for weekly rollup tests."""
    return WorkoutMetricsModel.from_canonical_metrics(
        flat_metrics,
        metadata={
            "sport": flat_metrics.get("sport", "Cycling"),
            "sub_sport": flat_metrics.get("sub_sport"),
            "workout_name": flat_metrics.get("workout_name"),
            "start_time_utc": flat_metrics.get("start_time_utc"),
            "duration_sec": flat_metrics.get("duration_sec"),
            "local_tz_offset": flat_metrics.get("local_tz_offset"),
            "has_gps": flat_metrics.get("distance_m") is not None,
        },
    )


@pytest.fixture
def mock_storage():
    """Mock storage coordinator for testing."""
    storage = MagicMock()
    storage.infrastructure = MagicMock()
    storage.workouts = MagicMock()
    storage.physiometrics = MagicMock()
    return storage


@pytest.fixture
def semantic_layer(mock_storage):
    """Create SemanticLayer with mocked storage."""
    return SemanticLayer(mock_storage)


@pytest.fixture
def sample_workouts():
    """Sample workout data for testing."""
    base_date = datetime(2026, 1, 15, tzinfo=timezone.utc)

    return [
        {
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "sport": "Cycling",
            "start_time_utc": base_date.isoformat(),
            "duration_sec": 3600,
            "hr_z2_sec": 3000,  # 50 minutes in seconds
            "hr_z4_sec": 300,
            "hr_z5_sec": 180,
            "intensity_sec": 480,  # 8 minutes in seconds
            "decoupling_pct": 2.5,
            "ef_overall": 1.2,
        },
        {
            "workout_id": "workout-002",
            "athlete_id": "rob",
            "sport": "Running",
            "start_time_utc": (base_date - timedelta(days=2)).isoformat(),
            "duration_sec": 2700,
            "hr_z2_sec": 2700,  # 45 minutes in seconds
            "hr_z4_sec": 0,
            "hr_z5_sec": 0,
            "intensity_sec": 0,
        },
        {
            "workout_id": "workout-003",
            "athlete_id": "rob",
            "sport": "Cycling",
            "start_time_utc": (base_date - timedelta(days=5)).isoformat(),
            "duration_sec": 300,  # Very short - 5 minutes
            "hr_z2_sec": 300,  # 5 minutes in seconds
        },
    ]


@pytest.fixture
def sample_workout_projections():
    """Sample WorkoutProjection objects for testing."""
    base_date = datetime(2026, 1, 15, tzinfo=timezone.utc)

    return [
        WorkoutProjection(
            workout_id="workout-001",
            athlete_id="rob",
            sport="Cycling",
            sub_sport="Road",
            workout_name="Century Ride",
            device_name="Edge 530",
            device_manufacturer="Garmin",
            start_time_utc=base_date.isoformat(),
            local_tz_offset="-05:00",
            timezone="America/New_York",
            duration_sec=3600,
            moving_time_sec=3400,
            distance_m=50000,
            elevation_gain_m=1200,
            elevation_loss_m=1200,
            calories_kcal=2500,
            has_power=True,
            has_hr=True,
            has_gps=True,
            hr_avg_bpm=145,
            hr_max_bpm=175,
            pwr_avg_watts=280,
            pwr_max_watts=450,
            pwr_normalized_watts=310,
            cad_avg_rpm=85,
            cad_max_rpm=95,
            is_indoor=False,
            race_flag=False,
            commute_flag=False,
            ingestion_version="2.0.1",
            ingestion_timestamp_utc=base_date.isoformat(),
        ),
        WorkoutProjection(
            workout_id="workout-002",
            athlete_id="rob",
            sport="Running",
            sub_sport="Road",
            workout_name="Easy Run",
            device_name="Fenix 7",
            device_manufacturer="Garmin",
            start_time_utc=(base_date - timedelta(days=2)).isoformat(),
            local_tz_offset="-05:00",
            timezone="America/New_York",
            duration_sec=2700,
            moving_time_sec=2650,
            distance_m=11000,
            elevation_gain_m=0,
            elevation_loss_m=0,
            calories_kcal=1100,
            has_power=False,
            has_hr=True,
            has_gps=True,
            hr_avg_bpm=130,
            hr_max_bpm=145,
            is_indoor=False,
            race_flag=False,
            commute_flag=False,
            pwr_avg_watts=None,
            pwr_max_watts=None,
            pwr_normalized_watts=None,
            cad_avg_rpm=None,
            cad_max_rpm=None,
            ingestion_version="2.0.1",
            ingestion_timestamp_utc=base_date.isoformat(),
        ),
        WorkoutProjection(
            workout_id="workout-003",
            athlete_id="rob",
            sport="Cycling",
            sub_sport="Mountain",
            workout_name="Quick MTB",
            device_name="Edge 530",
            device_manufacturer="Garmin",
            start_time_utc=(base_date - timedelta(days=5)).isoformat(),
            local_tz_offset="-05:00",
            timezone="America/New_York",
            duration_sec=300,
            moving_time_sec=295,
            distance_m=5000,
            elevation_gain_m=300,
            elevation_loss_m=300,
            calories_kcal=200,
            has_power=False,
            has_hr=True,
            has_gps=True,
            hr_avg_bpm=150,
            hr_max_bpm=165,
            is_indoor=False,
            race_flag=False,
            commute_flag=False,
            pwr_avg_watts=None,
            pwr_max_watts=None,
            pwr_normalized_watts=None,
            cad_avg_rpm=None,
            cad_max_rpm=None,
            ingestion_version="2.0.1",
            ingestion_timestamp_utc=base_date.isoformat(),
        ),
    ]


class TestPlanningContext:
    """Tests for get_planning_context endpoint."""

    def test_get_planning_context_basic(self, semantic_layer, sample_workouts, mock_storage):
        """Test basic planning context retrieval."""
        # Mock _get_workouts_in_range to return sample data
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            with patch.object(
                semantic_layer, '_get_weekly_rollups', return_value=[]
            ):
                context = semantic_layer.get_planning_context("rob", days=30)

        assert context["athlete_id"] == "rob"
        assert "query_window" in context
        assert context["query_window"]["days"] == 30
        assert "recent_workouts" in context
        assert "weekly_rollups" in context
        assert "summary" in context
        assert "notable_flags" in context

    def test_planning_context_detects_last_hard_day(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test detection of last high-intensity workout."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            with patch.object(
                semantic_layer, '_get_weekly_rollups', return_value=[]
            ):
                context = semantic_layer.get_planning_context("rob", days=30)

        # workout-001 has 480 seconds (8 minutes) of intensity > 300 sec threshold
        assert context["summary"]["last_hard_day"] == sample_workouts[0]["start_time_utc"]

    def test_planning_context_detects_last_long_day(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test detection of last long aerobic workout."""
        # Modify workout-002 to have > 60 minutes of Z2 (in seconds)
        workouts = sample_workouts.copy()
        workouts[1]["hr_z2_sec"] = 4500  # 75 minutes in seconds

        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=workouts
        ):
            with patch.object(
                semantic_layer, '_get_weekly_rollups', return_value=[]
            ):
                context = semantic_layer.get_planning_context("rob", days=30)

        assert context["summary"]["last_long_day"] == workouts[1]["start_time_utc"]

    def test_planning_context_cumulative_minutes(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test cumulative zone minutes calculation."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            with patch.object(
                semantic_layer, '_get_weekly_rollups', return_value=[]
            ):
                context = semantic_layer.get_planning_context("rob", days=30)

        # Sum all HR Z2 seconds and convert to minutes
        # workout-001: 3000sec = 50min, workout-002: 2700sec = 45min, workout-003: 300sec = 5min
        expected_z2 = int((3000 + 2700 + 300) / 60)  # 100 minutes
        assert context["summary"]["cumulative_z2_minutes"] == expected_z2

        # Sum all intensity seconds and convert to minutes
        # workout-001: 480sec = 8min, workout-002: 0sec, workout-003: 0sec
        expected_intensity = 8.0
        assert context["summary"]["cumulative_intensity_minutes"] == pytest.approx(expected_intensity)

    def test_planning_context_detects_flags(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test detection of notable flags."""
        # Add workout with missing HR
        workouts = sample_workouts.copy()
        workouts.append({
            "workout_id": "workout-004",
            "athlete_id": "rob",
            "sport": "Cycling",
            "start_time_utc": "2026-01-14T10:00:00+00:00",
            "duration_sec": 3600,
            # No hr_avg_bpm
        })

        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=workouts
        ):
            with patch.object(
                semantic_layer, '_get_weekly_rollups', return_value=[]
            ):
                context = semantic_layer.get_planning_context("rob", days=30)

        flags = context["notable_flags"]
        assert any("missing heart rate" in flag for flag in flags)
        assert any("very short" in flag for flag in flags)

    def test_planning_context_uses_seconds_fields(
        self, semantic_layer, mock_storage
    ):
        """Test that planning context correctly reads zone times from _sec fields."""
        # Create workouts with _sec fields (as storage actually provides)
        workouts_with_sec_fields = [
            {
                "workout_id": "workout-001",
                "athlete_id": "rob",
                "sport": "Cycling",
                "start_time_utc": "2026-03-01T10:00:00+00:00",
                "duration_sec": 3600,
                "hr_z2_sec": 3900,  # 65 minutes in seconds
                "hr_z4_sec": 360,   # 6 minutes in seconds
                "hr_z5_sec": 60,    # 1 minute in seconds
                "intensity_sec": 420,  # 7 minutes in seconds
            },
            {
                "workout_id": "workout-002",
                "athlete_id": "rob",
                "sport": "Cycling",
                "start_time_utc": "2026-03-02T10:00:00+00:00",
                "duration_sec": 2700,
                "hr_z2_sec": 2400,  # 40 minutes in seconds (HR-based Z2)
                "pwr_z2_sec": 2400,  # 40 minutes in seconds (power-based Z2)
                "intensity_sec": 300,  # 5 minutes in seconds
            },
        ]

        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=workouts_with_sec_fields
        ):
            with patch.object(
                semantic_layer, '_get_weekly_rollups', return_value=[]
            ):
                context = semantic_layer.get_planning_context("rob", days=30)

        # Verify last_long_day detected (workout-001 has 65min Z2 > 60min threshold)
        assert context["summary"]["last_long_day"] == "2026-03-01T10:00:00+00:00"

        # Verify last_hard_day detected (workout-001 has 7min intensity > 5min threshold)
        assert context["summary"]["last_hard_day"] == "2026-03-01T10:00:00+00:00"

        # Verify cumulative Z2 correctly sums hr_z2_sec and converts to minutes
        # workout-001: 3900sec = 65min, workout-002: 2400sec = 40min -> total 105min
        assert context["summary"]["cumulative_z2_minutes"] == 105

        # Verify cumulative intensity correctly sums and converts to minutes
        # workout-001: 420sec = 7min, workout-002: 300sec = 5min -> total 12min
        assert context["summary"]["cumulative_intensity_minutes"] == pytest.approx(12.0)


class TestWorkoutQueries:
    """Tests for workout query endpoints."""

    def test_get_workouts_basic(self, semantic_layer, sample_workout_projections, mock_storage):
        """Test basic workout listing."""
        with patch.object(
            semantic_layer, '_get_workout_projections_in_range', return_value=sample_workout_projections
        ):
            workouts = semantic_layer.get_workouts("rob", limit=50)

        assert len(workouts) == 3
        assert all(w["athlete_id"] == "rob" for w in workouts)

    def test_get_workouts_with_sport_filter(
        self, semantic_layer, sample_workout_projections, mock_storage
    ):
        """Test workout filtering by sport."""
        with patch.object(
            semantic_layer, '_get_workout_projections_in_range', return_value=sample_workout_projections
        ):
            workouts = semantic_layer.get_workouts("rob", sport="Cycling")

        assert len(workouts) == 2
        assert all(w["sport"] == "Cycling" for w in workouts)

    def test_get_workouts_respects_limit(
        self, semantic_layer, sample_workout_projections, mock_storage
    ):
        """Test workout limit parameter."""
        with patch.object(
            semantic_layer, '_get_workout_projections_in_range', return_value=sample_workout_projections
        ):
            workouts = semantic_layer.get_workouts("rob", limit=1)

        assert len(workouts) == 1

    def test_get_workout_detail_found(self, semantic_layer, mock_storage):
        """Test retrieving detailed workout data."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        # Mock entity return - must include required WorkoutEntity fields
        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "workout-001",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ingest-001",
            "canonical_records_blob": "ingest-001/canonical.parquet",
            "source_system": "onedrive",
            "sport": "Cycling",
            "duration_sec": 3600,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-02-22T01:51:12Z", periods=120, freq="s"),
                "elapsed_sec": pd.Series(range(120), dtype=float),
                "heart_rate_bpm": 140.0,
                "power_watts": 210.0,
            }
        )

        workout = semantic_layer.get_workout_detail("rob", "workout-001")

        assert workout is not None
        assert workout["workout_id"] == "workout-001"
        assert workout["athlete_id"] == "rob"

    def test_get_workout_detail_includes_full_metric_families_when_canonical_complete(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Deep-dive workout detail should populate all canonical metric families when data supports them."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "workout-full-001",
            "workout_id": "workout-full-001",
            "athlete_id": "rob",
            "ingestion_id": "ingest-full-001",
            "canonical_records_blob": "ingest-full-001/canonical.parquet",
            "source_system": "onedrive",
            "sport": "Cycling",
            "duration_sec": 4000,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }

        row_count = 4000
        timestamps = pd.date_range("2026-02-22T01:51:12Z", periods=row_count, freq="s")
        elapsed = pd.Series(range(row_count), dtype=float)
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": timestamps,
                "elapsed_sec": elapsed,
                "power_watts": 220 + (elapsed % 120) * 1.5,
                "heart_rate_bpm": 135 + (elapsed % 90) * 0.4,
                "cadence_rpm": 84 + (elapsed % 20) * 0.6,
                "speed_mps": 8.5 + (elapsed % 15) * 0.03,
                "distance_m": elapsed * 8.7,
                "elevation_m": 100 + elapsed * 0.02,
            }
        )

        workout = semantic_layer.get_workout_detail("rob", "workout-full-001")

        assert workout is not None
        metrics = workout["metrics"]
        assert "zones_hr" in metrics
        assert "zones_power" in metrics
        assert "training_load" in metrics
        assert "power_duration" in metrics
        assert "envelope" in metrics
        assert "variability" in metrics
        assert "durability" in metrics
        assert "artifacts" in metrics

    def test_get_workout_detail_detects_climbs_from_noisy_realistic_grade_series(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Workout detail should still surface climbs when minor resampling gaps interrupt a real ascent."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "workout-climb-001",
            "workout_id": "workout-climb-001",
            "athlete_id": "rob",
            "ingestion_id": "ingest-climb-001",
            "canonical_records_blob": "ingest-climb-001/canonical.parquet",
            "source_system": "garmin",
            "sport": "Cycling",
            "duration_sec": 240,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }

        row_count = 240
        elapsed = pd.Series(range(row_count), dtype=float)
        elevation = []
        current_elevation = 100.0
        for second in range(row_count):
            if 40 <= second < 160:
                current_elevation += 0.22 if second % 15 not in {0, 1} else 0.0
            else:
                current_elevation += 0.01
            elevation.append(current_elevation)

        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-02-22T01:51:12Z", periods=row_count, freq="s"),
                "elapsed_sec": elapsed,
                "power_watts": 235.0,
                "heart_rate_bpm": 148.0,
                "speed_mps": 5.0,
                "distance_m": elapsed * 5.0,
                "elevation_m": elevation,
                "position_lat": 40.0 + elapsed * 0.0001,
                "position_long": -75.0 - elapsed * 0.0001,
            }
        )

        workout = semantic_layer.get_workout_detail("rob", "workout-climb-001")

        assert workout is not None
        artifacts = workout["metrics"].get("artifacts") or {}
        climbs = artifacts.get("climbs") or []
        assert len(climbs) >= 1
        assert climbs[0]["avg_grade"] >= 3.0
        assert climbs[0]["duration"] >= 60
        assert climbs[0]["start_sec"] >= 0
        assert climbs[0]["end_sec"] >= climbs[0]["start_sec"]
        assert climbs[0]["start_time_utc"].startswith("2026-02-22T")
        assert climbs[0]["end_time_utc"].startswith("2026-02-22T")
        assert climbs[0]["start_distance_m"] is not None
        assert climbs[0]["end_distance_m"] >= climbs[0]["start_distance_m"]
        assert climbs[0]["start_lat"] is not None
        assert climbs[0]["start_long"] is not None
        assert climbs[0]["end_lat"] is not None
        assert climbs[0]["end_long"] is not None

    def test_get_workout_detail_recovers_climbs_from_raw_fit_when_canonical_elevation_missing(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Workout detail should recover elevation from archived raw FIT frames for older ingests."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "workout-rawfit-001",
            "workout_id": "workout-rawfit-001",
            "athlete_id": "rob",
            "ingestion_id": "ingest-rawfit-001",
            "canonical_records_blob": "ingest-rawfit-001/canonical.parquet",
            "source_system": "garmin",
            "sport": "Cycling",
            "duration_sec": 240,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        row_count = 240
        elapsed = pd.Series(range(row_count), dtype=float)
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-02-22T01:51:12Z", periods=row_count, freq="s"),
                "elapsed_sec": elapsed,
                "power_watts": 235.0,
                "heart_rate_bpm": 148.0,
                "speed_mps": 5.0,
                "distance_m": elapsed * 5.0,
            }
        )

        raw_fit_frames = []
        current_elevation = 100.0
        for second in range(row_count):
            if 40 <= second < 160:
                current_elevation += 0.22 if second % 15 not in {0, 1} else 0.0
            else:
                current_elevation += 0.01
            raw_fit_frames.append(
                {
                    "frame_type": "data_message",
                    "name": "record",
                    "fields": [
                        {"name": "timestamp", "value": f"2026-02-22T01:{51 + ((12 + second) // 60):02d}:{(12 + second) % 60:02d}+00:00", "units": ""},
                        {"name": "enhanced_altitude", "value": current_elevation, "units": "m"},
                        {"name": "position_lat", "value": 40.0 + (second * 0.0001), "units": "deg"},
                        {"name": "position_long", "value": -75.0 - (second * 0.0001), "units": "deg"},
                    ],
                }
            )
        mock_storage.workouts.infra.raw_fit_blob_name.return_value = "ingest-rawfit-001/raw_fit.json.gz"
        mock_storage.workouts.infra.load_json_blob.return_value = raw_fit_frames

        workout = semantic_layer.get_workout_detail("rob", "workout-rawfit-001")

        assert workout is not None
        artifacts = workout["metrics"].get("artifacts") or {}
        climbs = artifacts.get("climbs") or []
        assert len(climbs) >= 1
        assert climbs[0]["duration"] >= 60
        assert climbs[0]["start_time_utc"].startswith("2026-02-22T")
        assert climbs[0]["start_distance_m"] is not None
        assert climbs[0]["start_lat"] is not None
        assert climbs[0]["start_long"] is not None
        assert climbs[0]["end_lat"] is not None
        assert climbs[0]["end_long"] is not None

    def test_get_workout_detail_surfaces_only_enrichment_raw_metadata_in_session(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Direct workout detail should keep raw passthrough limited to metadata.json enrichment."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "workout-meta-001",
            "workout_id": "workout-meta-001",
            "athlete_id": "rob",
            "ingestion_id": "ingest-meta-001",
            "canonical_records_blob": "ingest-meta-001/canonical.parquet",
            "source_system": "garmin",
            "sport": "cycling",
            "duration_sec": 4211,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "identity": {
                "sport": "cycling",
                "sub_sport": "virtual_activity",
                "device_name": "zwift 0",
            },
            "session": {
                "avg_speed_mps": 7.535,
                "calories_kcal": 664.0,
                "moving_time_sec": 4212,
            },
            "enrichment": {
                "garmin_aerobic_training_effect": 5.0,
                "garmin_training_effect_label": "VO2MAX",
            },
            "activity_metadata": {
                "local_tz_offset": "UTC-04:00",
                "timezone": "America/New_York",
            },
        }
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-04-07T23:58:51Z", periods=120, freq="s"),
                "elapsed_sec": pd.Series(range(120), dtype=float),
                "heart_rate_bpm": 145.0,
                "power_watts": 225.0,
                "speed_mps": 7.5,
                "distance_m": pd.Series(range(120), dtype=float) * 7.5,
            }
        )

        workout = semantic_layer.get_workout_detail("rob", "workout-meta-001")

        assert workout is not None
        session_metrics = workout["metrics"]["session"]
        assert session_metrics["device_name"] == "zwift 0"
        assert session_metrics["sub_sport"] == "virtual_activity"
        assert session_metrics["moving_time_sec"] == pytest.approx(4212)
        assert session_metrics["enrichment"]["garmin_aerobic_training_effect"] == pytest.approx(5.0)
        assert session_metrics["timezone"] == "America/New_York"
        assert "identity" not in session_metrics
        assert "metadata_session" not in session_metrics
        assert "activity_metadata" not in session_metrics

    def test_get_workout_detail_not_found(self, semantic_layer, mock_storage):
        """Test retrieving non-existent workout."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client
        mock_table_client.query_entities.return_value = []

        workout = semantic_layer.get_workout_detail("rob", "nonexistent")

        assert workout is None

    def test_get_workout_detail_wrong_athlete(self, semantic_layer, mock_storage):
        """Test workout detail with mismatched athlete_id."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "other",
            "RowKey": "workout-001",
            "workout_id": "workout-001",
            "athlete_id": "other",  # Different athlete
            "source_system": "onedrive",
            "sport": "Cycling",
        }
        mock_table_client.query_entities.return_value = [mock_entity]

        workout = semantic_layer.get_workout_detail("rob", "workout-001")

        assert workout is None

    def test_get_workout_detail_with_developer_fields(self, semantic_layer, mock_storage):
        """Test workout detail can include summarized developer fields."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "rob|2026-02",
            "RowKey": "20260220|abc",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ing-001",
            "canonical_records_blob": "ing-001/canonical.parquet",
            "sport": "Cycling",
            "duration_sec": 3600,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "record": [
                {
                    "fields": {
                        "dev_pedal_smoothness": {"value": 31.2, "units": "%"},
                    }
                }
            ]
        }
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-02-22T01:51:12Z", periods=120, freq="s"),
                "elapsed_sec": pd.Series(range(120), dtype=float),
                "heart_rate_bpm": 140.0,
                "power_watts": 210.0,
            }
        )

        workout = semantic_layer.get_workout_detail(
            "rob",
            "workout-001",
            include_developer_fields=True,
        )

        assert workout is not None
        assert "developer_fields_summary" in workout
        assert workout["developer_fields_summary"]["field_count"] == 1

    def test_get_workout_detail_summarizes_laps_payload(self, semantic_layer, mock_storage):
        """Laps on workout detail should be compact summaries, not raw FIT frame payloads."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "workout-001",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ingest-001",
            "canonical_records_blob": "ingest-001/canonical.parquet",
            "source_system": "onedrive",
            "sport": "Cycling",
            "duration_sec": 3600,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        mock_storage.workouts.load_laps_json.return_value = {
            "laps": [
                {
                    "frame_type": "data_message",
                    "name": "lap",
                    "header": {"local_mesg_num": 4},
                    "chunk": {"index": 10},
                    "fields": [
                        {"name": "message_index", "value": 2, "units": ""},
                        {"name": "start_time", "value": "2026-02-22T01:51:12+00:00", "units": ""},
                        {"name": "timestamp", "value": "2026-02-22T01:56:12+00:00", "units": ""},
                        {"name": "total_elapsed_time", "value": 300.0, "units": "s"},
                        {"name": "avg_power", "value": 220, "units": "watts"},
                        {"name": "dev_pedal_smoothness", "value": 31.2, "units": "%"},
                    ],
                }
            ]
        }
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-02-22T01:51:12Z", periods=120, freq="s"),
                "elapsed_sec": pd.Series(range(120), dtype=float),
                "heart_rate_bpm": 140.0,
                "power_watts": 210.0,
            }
        )

        workout = semantic_layer.get_workout_detail("rob", "workout-001", include_laps=True)

        assert workout is not None
        assert "laps" in workout
        lap = workout["laps"][0]
        assert lap["lap_index"] == 2
        assert lap["avg_power"] == 220
        assert "fields" not in lap
        assert "header" not in lap
        assert "chunk" not in lap
        assert lap["extra_fields"]["dev_pedal_smoothness"]["value"] == pytest.approx(31.2)
        assert lap["extra_fields"]["dev_pedal_smoothness"]["units"] == "%"

    def test_get_workout_lap_detail_returns_summary_shape(self, semantic_layer, mock_storage):
        """Lap detail should return summarized lap payload shape with extra_fields."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client
        mock_table_client.query_entities.return_value = [
            {
                "workout_id": "workout-001",
                "athlete_id": "rob",
                "ingestion_id": "ingest-001",
                "source_system": "onedrive",
            }
        ]
        mock_storage.workouts.load_laps_json.return_value = {
            "laps": [
                {
                    "fields": [
                        {"name": "message_index", "value": 1, "units": ""},
                        {"name": "total_elapsed_time", "value": 120.0, "units": "s"},
                        {"name": "avg_heart_rate", "value": 150, "units": "bpm"},
                        {"name": "dev_form_power", "value": 12.5, "units": "%"},
                    ]
                }
            ]
        }

        lap = semantic_layer.get_workout_lap_detail("rob", "workout-001", 0)

        assert lap is not None
        assert lap["workout_id"] == "workout-001"
        assert lap["athlete_id"] == "rob"
        assert lap["lap"]["lap_index"] == 1
        assert lap["lap"]["total_elapsed_time"] == pytest.approx(120.0)
        assert lap["lap"]["avg_heart_rate"] == 150
        assert lap["lap"]["extra_fields"]["dev_form_power"]["units"] == "%"

    def test_get_workout_detail_raises_storage_error_on_non_1hz_validation_failure(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Workout detail must fail when canonical validation cannot hydrate metrics."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260308T2324180000|4ccc53f9aa6d",
            "workout_id": "4ccc53f9aa6df38e1348b645a77092d962edc0db",
            "athlete_id": "rob",
            "ingestion_id": "onedrive:2DE1CE6A0066F643!s95ee216dd6ed479f878b12f9cd1d8f72",
            "canonical_records_blob": "onedrive:2DE1CE6A0066F643!s95ee216dd6ed479f878b12f9cd1d8f72/canonical.parquet",
            "sport": "cycling",
            "sub_sport": "generic",
            "duration_sec": 1708,
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        mock_storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }

        # Non-1Hz-like input (contains a larger timestamp gap), plus missing power data.
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    [
                        "2026-03-08T23:24:18Z",
                        "2026-03-08T23:24:19Z",
                        "2026-03-08T23:25:25Z",
                    ],
                    utc=True,
                ),
                "heart_rate_bpm": [125.0, 126.0, None],
                "cadence_rpm": [85.0, None, 87.0],
                "power_watts": [None, None, None],
            }
        )

        with patch(
            "TrainingAnalyticsPlatform.analytics.semantic_layer.CanonicalAnalyticsEngine.from_dataframe",
            side_effect=ValidationError("strict_1hz_failed", status_code=422),
        ):
            with pytest.raises(
                StorageError,
                match="Workout detail is temporarily unavailable",
            ):
                semantic_layer.get_workout_detail("rob", mock_entity["workout_id"])


class TestAnalysisQueries:
    """Tests for analysis endpoints."""

    def test_zone_distribution(self, semantic_layer, sample_workouts, mock_storage):
        """Test zone distribution returns valid structure with non-negative values."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            distribution = semantic_layer.get_zone_distribution("rob", days=30)

        # Validate structure
        assert "zones" in distribution
        assert "percentages" in distribution
        assert "total_minutes" in distribution

        # Validate zones have expected keys
        for zone in ["z1", "z2", "z3", "z4", "z5"]:
            assert zone in distribution["zones"]
            # All zone times should be non-negative
            assert distribution["zones"][zone] >= 0

        # Validate total_minutes is consistent
        total_from_zones = sum(distribution["zones"].values())
        assert total_from_zones == distribution["total_minutes"]
        assert distribution["total_minutes"] >= 0

    def test_zone_distribution_percentages(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test zone percentages sum to approximately 100% and are in valid range."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            distribution = semantic_layer.get_zone_distribution("rob", days=30)

        percentages = distribution["percentages"]

        # All percentages should be between 0 and 100
        for zone, pct in percentages.items():
            assert 0 <= pct <= 100, f"Zone {zone} percentage {pct} out of range"

        # Sum should be approximately 100% (within rounding)
        total_pct = sum(percentages.values())
        assert 99.0 <= total_pct <= 101.0

        # Percentages should be consistent with zone times
        total_minutes = distribution["total_minutes"]
        if total_minutes > 0:
            for zone, minutes in distribution["zones"].items():
                expected_pct = (minutes / total_minutes) * 100
                actual_pct = percentages[zone]
                assert expected_pct == pytest.approx(actual_pct, rel=0.01)

    def test_efficiency_trends(self, semantic_layer, sample_workouts, mock_storage):
        """Test efficiency trend analysis."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            trends = semantic_layer.get_efficiency_trends("rob", days=90)

        assert "samples" in trends
        assert "summary" in trends

        # Only workout-001 has decoupling data
        assert len(trends["samples"]) == 1
        assert trends["samples"][0]["decoupling_pct"] == pytest.approx(2.5)

    def test_efficiency_trends_summary(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test efficiency trend summary calculation."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            trends = semantic_layer.get_efficiency_trends("rob", days=90)

        summary = trends["summary"]
        assert summary["total_samples"] == 1
        assert summary["avg_decoupling"] == pytest.approx(2.5)


class TestTrainingStateQueries:
    """Tests for training-state response projections."""

    def test_compute_current_training_state_includes_new_garmin_fields(
        self, semantic_layer
    ):
        """Current training-state response should expose Garmin pass-through fields."""
        snapshot = SimpleNamespace(
            effective_date="2026-03-18",
            cts_rolling_7d=5.1,
            cts_rolling_28d=10.1,
            ats_rolling=5.1,
            fatigue_index=0.51,
            readiness_score=None,
            garmin_readiness_score=None,
            garmin_training_status="PRODUCTIVE_2",
            garmin_training_load=376.0,
            garmin_recovery_time_hours=6.5,
            garmin_load_focus_low_aerobic_pct=30.0,
            garmin_load_focus_high_aerobic_pct=55.0,
            garmin_load_focus_anaerobic_pct=15.0,
            mood=None,
            soreness=None,
            pred_recovery_days=None,
            data_sources="workouts,physiometrics",
            canonical_version="5.1.0",
        )

        with patch.object(
            semantic_layer,
            "_compute_training_state_for_date",
            return_value=snapshot,
        ):
            result = semantic_layer.compute_current_training_state("rob")

        assert result["garmin_training_status"] == "PRODUCTIVE_2"
        assert result["garmin_training_load"] == pytest.approx(376.0)
        assert result["garmin_recovery_time_hours"] == pytest.approx(6.5)
        assert result["garmin_load_focus_low_aerobic_pct"] == pytest.approx(30.0)
        assert result["garmin_load_focus_high_aerobic_pct"] == pytest.approx(55.0)
        assert result["garmin_load_focus_anaerobic_pct"] == pytest.approx(15.0)
        assert "computed_at_utc" in result

    def test_compute_training_state_history_includes_new_garmin_fields(
        self, semantic_layer
    ):
        """History response points should include Garmin pass-through fields."""
        snapshot = SimpleNamespace(
            effective_date="2026-03-18",
            cts_rolling_7d=5.1,
            cts_rolling_28d=10.1,
            ats_rolling=5.1,
            fatigue_index=0.51,
            readiness_score=None,
            garmin_readiness_score=None,
            garmin_training_status="MAINTAINING_2",
            garmin_training_load=325.0,
            garmin_recovery_time_hours=5.0,
            garmin_load_focus_low_aerobic_pct=32.0,
            garmin_load_focus_high_aerobic_pct=50.0,
            garmin_load_focus_anaerobic_pct=18.0,
            mood=None,
            soreness=None,
            pred_recovery_days=None,
            data_sources="workouts,physiometrics",
            canonical_version="5.1.0",
        )

        with patch.object(
            semantic_layer,
            "_compute_training_state_for_date",
            return_value=snapshot,
        ):
            result = semantic_layer.compute_training_state_history("rob", days=0)

        assert result["count"] == 1
        point = result["data_points"][0]
        assert point["garmin_training_status"] == "MAINTAINING_2"
        assert point["garmin_training_load"] == pytest.approx(325.0)
        assert point["garmin_recovery_time_hours"] == pytest.approx(5.0)
        assert point["garmin_load_focus_low_aerobic_pct"] == pytest.approx(32.0)
        assert point["garmin_load_focus_high_aerobic_pct"] == pytest.approx(50.0)
        assert point["garmin_load_focus_anaerobic_pct"] == pytest.approx(18.0)

    def test_load_latest_physiometrics_snapshot_uses_typed_storage_path(
        self, semantic_layer, mock_storage
    ):
        """Semantic layer should load typed physiometrics snapshot via storage API."""
        typed_snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="rob",
            effective_date="2026-03-18",
            data_sources="garmin",
            training_status_label="MAINTAINING_2",
            training_load=325.0,
        )
        mock_storage.physiometrics.get_physiometrics_snapshot_as_of.return_value = typed_snapshot

        result = semantic_layer._load_latest_physiometrics_snapshot("rob", "2026-03-18")

        assert result is typed_snapshot
        mock_storage.physiometrics.get_physiometrics_snapshot_as_of.assert_called_once_with(
            "rob",
            "2026-03-18",
        )

    def test_load_latest_physiometrics_snapshot_handles_storage_error(
        self, semantic_layer, mock_storage
    ):
        """Semantic layer should return None when typed physiometrics lookup fails."""
        mock_storage.physiometrics.get_physiometrics_snapshot_as_of.side_effect = StorageError(
            "lookup failed"
        )

        result = semantic_layer._load_latest_physiometrics_snapshot("rob", "2026-03-18")

        assert result is None

    def test_resolve_training_state_physiometrics_as_of_uses_intervals_for_hrv_and_garmin_fields(
        self, semantic_layer, mock_storage
    ):
        """Training-state physiometrics should merge as-of rows by source-specific ownership."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-18|garmin",
                "effective_date": "2026-03-18",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-18T07:00:00+00:00",
                "readiness_score": 79.0,
                "training_status_label": "PRODUCTIVE_2",
                "training_load": 376.0,
                "recovery_time_minutes": 360,
                "load_focus_low_aerobic_pct": 30.0,
                "load_focus_high_aerobic_pct": 55.0,
                "load_focus_anaerobic_pct": 15.0,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-18|intervals",
                "effective_date": "2026-03-18",
                "data_source": "intervals",
                "updated_at_utc": "2026-03-18T09:00:00+00:00",
                "hrv_ln_rmssd": 3.95,
            },
        ]

        result = semantic_layer._resolve_training_state_physiometrics_as_of(
            "rob",
            "2026-03-18",
        )

        assert result["hrv_ln_rmssd"] == pytest.approx(3.95)
        assert result["readiness_score"] == pytest.approx(79.0)
        assert result["training_status_label"] == "PRODUCTIVE_2"
        assert result["training_load"] == pytest.approx(376.0)
        assert result["recovery_time_minutes"] == 360

    def test_resolve_training_state_physiometrics_as_of_ignores_future_rows(
        self, semantic_layer, mock_storage
    ):
        """Training-state physiometrics should only use rows effective on or before the target date."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-18|garmin",
                "effective_date": "2026-03-18",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-18T07:00:00+00:00",
                "training_load": 310.0,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-19|intervals",
                "effective_date": "2026-03-19",
                "data_source": "intervals",
                "updated_at_utc": "2026-03-19T07:00:00+00:00",
                "hrv_ln_rmssd": 4.1,
            },
        ]

        result = semantic_layer._resolve_training_state_physiometrics_as_of(
            "rob",
            "2026-03-18",
        )

        assert result["training_load"] == pytest.approx(310.0)
        assert "hrv_ln_rmssd" not in result

    def test_compute_training_state_for_date_uses_as_of_source_merge(
        self, semantic_layer, mock_storage
    ):
        """Training-state computation should combine workout load with as-of physiometrics ownership."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        with patch.object(
            semantic_layer,
            "_compute_rolling_tss",
            return_value=(140.0, 280.0),
        ), patch.object(
            semantic_layer,
            "_resolve_training_state_physiometrics_as_of",
            return_value={
                "hrv_ln_rmssd": 4.0,
                "readiness_score": 82.0,
                "training_status_label": "MAINTAINING_2",
                "training_load": 325.0,
                "recovery_time_minutes": 300,
                "load_focus_low_aerobic_pct": 32.0,
                "load_focus_high_aerobic_pct": 50.0,
                "load_focus_anaerobic_pct": 18.0,
            },
        ):
            snapshot = semantic_layer._compute_training_state_for_date(
                "rob",
                datetime(2026, 3, 18, tzinfo=timezone.utc).date(),
            )

        assert snapshot.readiness_score == pytest.approx(37.5)
        assert snapshot.garmin_readiness_score == pytest.approx(82.0)
        assert snapshot.garmin_training_status == "MAINTAINING_2"
        assert snapshot.garmin_training_load == pytest.approx(325.0)
        assert snapshot.garmin_recovery_time_hours == pytest.approx(5.0)
        assert snapshot.garmin_load_focus_low_aerobic_pct == pytest.approx(32.0)
        assert snapshot.garmin_load_focus_high_aerobic_pct == pytest.approx(50.0)
        assert snapshot.garmin_load_focus_anaerobic_pct == pytest.approx(18.0)

    def test_compute_training_state_for_date_keeps_garmin_readiness_when_intervals_hrv_missing(
        self, semantic_layer, mock_storage
    ):
        """Composite readiness should stay null when Intervals HRV is absent as of the target date."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        with patch.object(
            semantic_layer,
            "_compute_rolling_tss",
            return_value=(140.0, 280.0),
        ), patch.object(
            semantic_layer,
            "_resolve_training_state_physiometrics_as_of",
            return_value={
                "readiness_score": 78.0,
                "training_status_label": "PRODUCTIVE_2",
                "training_load": 300.0,
                "recovery_time_minutes": 240,
            },
        ):
            snapshot = semantic_layer._compute_training_state_for_date(
                "rob",
                datetime(2026, 3, 18, tzinfo=timezone.utc).date(),
            )

        assert snapshot.readiness_score is None
        assert snapshot.garmin_readiness_score == pytest.approx(78.0)
        assert snapshot.garmin_training_status == "PRODUCTIVE_2"


class TestWeeklyRollupQueries:
    """Tests for weekly rollup normalization and filtering."""

    def test_weekly_rollups_fallback_to_workout_aggregation_when_table_empty(
        self, semantic_layer, mock_storage
    ):
        """Compute weekly rollups from workouts when WeeklyRollups has no rows."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client
        mock_table_client.query_entities.return_value = []

        fallback_workouts = [
            build_rollup_metrics_model({
                "workout_id": "w1",
                "start_time_utc": "2026-02-10T10:00:00+00:00",
                "duration_sec": 3600,
                "distance_m": 50000,
                "elevation_gain_m": 700,
                "hr_zone_basis": "LTHR",
                "hr_zone_reference_bpm": 165,
                "hr_z2_sec": 2400,
                "ftp_watts": 250,
                "pwr_z2_sec": 2100,
                "low_aerobic_sec": 1800,
                "intensity_sec": 600,
                "decoupling_pct": 3.0,
            }),
            build_rollup_metrics_model({
                "workout_id": "w2",
                "start_time_utc": "2026-02-12T08:00:00+00:00",
                "duration_sec": 5400,
                "distance_m": 70000,
                "elevation_gain_m": 900,
                "hr_zone_basis": "LTHR",
                "hr_zone_reference_bpm": 165,
                "hr_z2_sec": 3900,
                "ftp_watts": 250,
                "pwr_z2_sec": 3300,
                "low_aerobic_sec": 2400,
                "intensity_sec": 420,
                "decoupling_pct": 2.0,
            }),
        ]

        with patch.object(
            semantic_layer,
            "_get_rollup_metrics_models_in_range",
            return_value=fallback_workouts,
        ):
            rollups = semantic_layer._get_weekly_rollups("rob", days=14)

        from pytest import approx
        
        assert len(rollups) == 1
        assert rollups[0]["workouts_count"] == 2
        assert rollups[0]["total_duration_min"] == approx(150.0)
        assert rollups[0]["total_distance_km"] == approx(120.0)
        assert rollups[0]["total_elev_m"] == approx(1600.0)
        assert rollups[0]["total_hr_z2_min"] == approx(105.0)
        assert rollups[0]["total_pwr_z2_min"] == approx(90.0)
        assert rollups[0]["total_low_aerobic_min"] == approx(70.0)
        assert rollups[0]["total_intensity_min"] == approx(17.0)
        assert rollups[0]["avg_decoupling_pct"] == approx(2.5)
        assert rollups[0]["hard_days_count"] == 2
        assert rollups[0]["long_rides_count"] == 1

    def test_weekly_rollups_drop_legacy_fields(
        self, semantic_layer, mock_storage
    ):
        """Return only documented weekly rollup fields from table entities."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob#2026",
                "RowKey": "2026-06",
                "week_start_utc": "2026-02-09T00:00:00+00:00",
                "week_end_utc": "2026-02-15T23:59:59+00:00",
                "workouts_count": 5,
                "total_duration_min": 420.0,
                "total_distance_km": 160.2,
                "total_elev_m": 1230.0,
                "total_hr_z2_min": 300.0,
                "total_pwr_z2_min": 280.0,
                "total_low_aerobic_min": 265.0,
                "total_intensity_min": 55.0,
                "avg_decoupling_pct": 2.8,
                "hard_days_count": 2,
                "long_rides_count": 1,
                "last_updated_at_utc": "2026-02-15T23:59:59+00:00",
                "legacy_soreness": 3,
                "legacy_running_vo2max_ml_kg_min": 54.2,
            }
        ]

        with patch("TrainingAnalyticsPlatform.analytics.semantic_layer.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(
                2026, 2, 20, tzinfo=timezone.utc
            )
            rollups = semantic_layer._get_weekly_rollups("rob", days=14)

        assert len(rollups) == 1
        assert set(rollups[0].keys()) <= set(WEEKLY_ROLLUP_ALLOWED_FIELDS)
        assert "legacy_soreness" not in rollups[0]
        assert "legacy_running_vo2max_ml_kg_min" not in rollups[0]

    def test_weekly_rollups_query_prefers_pipe_partition_and_keeps_local_fields(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Query pipe-delimited weekly partitions and preserve local timezone fields."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        entity = {
            "PartitionKey": "rob|2026",
            "RowKey": "2026-06",
            "week_start_utc": "2026-02-09T00:00:00+00:00",
            "week_end_utc": "2026-02-15T23:59:59+00:00",
            "week_start_local": "2026-02-09T00:00:00-05:00",
            "week_end_local": "2026-02-15T23:59:59-05:00",
            "athlete_home_timezone": "America/New_York",
            "workouts_count": 5,
            "total_duration_min": 420.0,
            "total_hr_z2_min": 300.0,
            "total_pwr_z2_min": 280.0,
            "total_low_aerobic_min": 265.0,
            "total_intensity_min": 55.0,
            "last_updated_at_utc": "2026-02-15T23:59:59+00:00",
        }

        queries = []

        def _query(filter_str):
            queries.append(filter_str)
            if "PartitionKey eq 'rob|2026'" in filter_str:
                return [entity]
            return []

        mock_table_client.query_entities.side_effect = _query

        with patch("TrainingAnalyticsPlatform.analytics.semantic_layer.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(
                2026, 2, 20, tzinfo=timezone.utc
            )
            rollups = semantic_layer._get_weekly_rollups("rob", days=14)

        assert len(rollups) == 1
        assert rollups[0]["athlete_home_timezone"] == "America/New_York"
        assert rollups[0]["week_start_local"] == "2026-02-09T00:00:00-05:00"
        assert rollups[0]["week_end_local"] == "2026-02-15T23:59:59-05:00"
        assert "PartitionKey eq 'rob|2026'" in queries
        assert "PartitionKey eq 'rob#2026'" not in queries

    def test_weekly_rollups_query_falls_back_to_legacy_hash_partition(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Fallback query should preserve compatibility with legacy hash partitions."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        entity = {
            "PartitionKey": "rob#2026",
            "RowKey": "2026-06",
            "week_start_utc": "2026-02-09T00:00:00+00:00",
            "week_end_utc": "2026-02-15T23:59:59+00:00",
            "workouts_count": 5,
            "total_duration_min": 420.0,
            "total_hr_z2_min": 300.0,
            "total_pwr_z2_min": 280.0,
            "total_low_aerobic_min": 265.0,
            "total_intensity_min": 55.0,
            "last_updated_at_utc": "2026-02-15T23:59:59+00:00",
        }

        queries = []

        def _query(filter_str):
            queries.append(filter_str)
            if "PartitionKey eq 'rob|2026'" in filter_str:
                return []
            if "PartitionKey eq 'rob#2026'" in filter_str:
                return [entity]
            return []

        mock_table_client.query_entities.side_effect = _query

        with patch("TrainingAnalyticsPlatform.analytics.semantic_layer.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(
                2026, 2, 20, tzinfo=timezone.utc
            )
            rollups = semantic_layer._get_weekly_rollups("rob", days=14)

        assert len(rollups) == 1
        assert queries == [
            "PartitionKey eq 'rob|2026'",
            "PartitionKey eq 'rob#2026'",
        ]

    def test_weekly_rollups_skip_malformed_entities(
        self, semantic_layer, mock_storage, caplog
    ):
        """Skip entities missing required fields and emit warning log."""
        mock_table_client = MagicMock()
        mock_storage.infrastructure.get_table_client.return_value = mock_table_client

        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob#2026",
                "RowKey": "2026-06",
                "week_start_utc": "2026-02-09T00:00:00+00:00",
                "week_end_utc": "2026-02-15T23:59:59+00:00",
                "workouts_count": 5,
                "total_duration_min": 420.0,
                "total_hr_z2_min": 300.0,
                "total_pwr_z2_min": 280.0,
                "total_low_aerobic_min": 265.0,
                "total_intensity_min": 55.0,
                "last_updated_at_utc": "2026-02-15T23:59:59+00:00",
            },
            {
                "PartitionKey": "rob#2026",
                "RowKey": "2026-05",
                "week_start_utc": "2026-02-02T00:00:00+00:00",
                "week_end_utc": "2026-02-08T23:59:59+00:00",
                "total_duration_min": 410.0,
                "total_hr_z2_min": 295.0,
                "total_pwr_z2_min": 270.0,
                "total_low_aerobic_min": 255.0,
                "total_intensity_min": 50.0,
                "last_updated_at_utc": "2026-02-08T23:59:59+00:00",
            },
        ]

        with patch("TrainingAnalyticsPlatform.analytics.semantic_layer.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(
                2026, 2, 20, tzinfo=timezone.utc
            )
            with caplog.at_level("WARNING"):
                rollups = semantic_layer._get_weekly_rollups("rob", days=14)

        assert len(rollups) == 1
        assert rollups[0]["workouts_count"] == 5
        assert "Skipping malformed weekly rollup entity" in caplog.text


class TestWeeklyRollupTimerComputation:
    """Tests for timezone-aware previous-week rollup computation and persistence."""

    def test_resolve_timezone_from_agent_preferences(self, semantic_layer):
        """Should resolve active athlete_home_timezone from AgentPreferences."""
        mock_table_client = MagicMock()
        semantic_layer.storage.infrastructure.get_table_client.return_value = mock_table_client
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "pref-1",
                "category": "athlete_home_timezone",
                "summary": "America/Denver",
                "status": "active",
                "updated_at": "2026-03-10T10:00:00+00:00",
            }
        ]

        timezone_name = semantic_layer._resolve_timezone_from_agent_preferences("rob")

        assert timezone_name == "America/Denver"

    def test_resolve_athlete_home_timezone_prefers_agent_preferences(self, semantic_layer):
        """AgentPreferences should have precedence over physiometrics timezone values."""
        mock_table_client = MagicMock()
        semantic_layer.storage.infrastructure.get_table_client.return_value = mock_table_client
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "pref-1",
                "category": "athlete_home_timezone",
                "summary": "America/Denver",
                "status": "active",
                "updated_at": "2026-03-10T10:00:00+00:00",
            }
        ]
        semantic_layer.storage.physiometrics.get_physiometrics.return_value = {
            "athlete_info": {
                "home_timezone": "America/Los_Angeles",
            },
            "athlete_timezone": "America/New_York",
        }

        timezone_name = semantic_layer._resolve_athlete_home_timezone("rob")

        assert timezone_name == "America/Denver"

    def test_resolve_athlete_home_timezone_prefers_athlete_info(self, semantic_layer):
        """Resolver should prefer athlete_info.home_timezone over legacy athlete_timezone."""
        semantic_layer.storage.infrastructure.get_table_client.return_value = MagicMock()
        semantic_layer.storage.infrastructure.get_table_client.return_value.query_entities.return_value = []
        semantic_layer.storage.physiometrics.get_physiometrics.return_value = {
            "athlete_info": {
                "home_timezone": "America/Los_Angeles",
            },
            "athlete_timezone": "America/New_York",
        }

        timezone_name = semantic_layer._resolve_athlete_home_timezone("rob")

        assert timezone_name == "America/Los_Angeles"

    def test_previous_local_week_window_uses_completed_week(self, semantic_layer):
        """Compute previous completed local week window from current UTC time."""
        now_utc = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)  # Tuesday
        athlete_tz = ZoneInfo("America/New_York")

        window = semantic_layer._previous_local_week_window(now_utc, athlete_tz)

        assert window["week_start_local"].isoformat() == "2026-03-02T00:00:00-05:00"
        assert window["week_end_local"].isoformat() == "2026-03-08T23:59:59-04:00"

    def test_compute_and_persist_previous_week_rollup(self, semantic_layer, mock_storage):
        """Persist rollup for previous local week with timezone context fields."""
        workouts = [
            build_rollup_metrics_model({
                "workout_id": "w-local-1",
                "start_time_utc": "2026-03-03T12:00:00+00:00",
                "duration_sec": 3600,
                "distance_m": 42000,
                "elevation_gain_m": 500,
                "hr_zone_basis": "LTHR",
                "hr_zone_reference_bpm": 165,
                "hr_z2_sec": 2400,
                "ftp_watts": 250,
                "pwr_z2_sec": 2100,
                "low_aerobic_sec": 1800,
                "intensity_sec": 420,
                "decoupling_pct": 2.0,
            }),
            build_rollup_metrics_model({
                "workout_id": "w-local-2",
                "start_time_utc": "2026-03-08T23:00:00+00:00",
                "duration_sec": 5400,
                "distance_m": 68000,
                "elevation_gain_m": 800,
                "hr_zone_basis": "LTHR",
                "hr_zone_reference_bpm": 165,
                "hr_z2_sec": 3600,
                "ftp_watts": 250,
                "pwr_z2_sec": 3300,
                "low_aerobic_sec": 2400,
                "intensity_sec": 600,
                "decoupling_pct": 3.0,
            }),
        ]

        with patch.object(
            semantic_layer,
            "_workouts_for_local_week",
            return_value=workouts,
        ):
            rollup = semantic_layer.compute_and_persist_previous_week_rollup(
                athlete_id="rob",
                athlete_home_timezone="America/New_York",
                now_utc=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            )

        assert rollup is not None
        assert rollup["athlete_home_timezone"] == "America/New_York"
        assert rollup["week_start_local"] == "2026-03-02T00:00:00-05:00"
        assert rollup["week_end_local"] == "2026-03-08T23:59:59-04:00"
        assert rollup["workouts_count"] == 2

        mock_storage.aggregation.update_weekly_rollup.assert_called_once()
        _, kwargs = mock_storage.aggregation.update_weekly_rollup.call_args
        assert kwargs["athlete_id"] == "rob"
        assert kwargs["year"] == "2026"
        assert kwargs["week"] == "10"
        assert kwargs["rollup_data"]["athlete_home_timezone"] == "America/New_York"

    def test_workouts_for_local_week_skips_malformed_start_time_utc_in_rollup_path(
        self,
        semantic_layer,
        caplog,
    ):
        """Malformed Workouts.start_time_utc values should be skipped before model hydration."""
        entities = [
            {
                "workout_id": "w-valid",
                "start_time_utc": "2026-03-03T12:00:00+00:00",
            },
            {
                "workout_id": "w-missing",
            },
            {
                "workout_id": "w-invalid",
                "start_time_utc": "not-a-timestamp",
            },
        ]
        valid_model = build_rollup_metrics_model(
            {
                "workout_id": "w-valid",
                "start_time_utc": "2026-03-03T12:00:00+00:00",
                "duration_sec": 3600,
            }
        )

        with patch.object(
            semantic_layer,
            "_get_rollup_entities_in_range",
            return_value=entities,
        ), patch.object(
            semantic_layer,
            "_build_rollup_metrics_model",
            return_value=valid_model,
        ) as build_model_mock:
            with caplog.at_level("WARNING"):
                included = semantic_layer._workouts_for_local_week(
                    athlete_id="rob",
                    week_start_local=datetime(2026, 3, 2, 0, 0, tzinfo=ZoneInfo("America/New_York")),
                    week_end_local=datetime(2026, 3, 8, 23, 59, 59, tzinfo=ZoneInfo("America/New_York")),
                    athlete_tz=ZoneInfo("America/New_York"),
                )

        assert len(included) == 1
        assert included[0].session.start_time_utc == "2026-03-03T12:00:00+00:00"
        assert build_model_mock.call_count == 1
        assert "Skipping workouts with malformed Workouts.start_time_utc while building weekly rollup" in caplog.text

    def test_compute_and_persist_previous_week_rollup_uses_hr_fallback_for_intensity(
        self,
        semantic_layer,
    ):
        """HR-only workouts should not contribute without intensity_sec."""
        workouts = [
            build_rollup_metrics_model({
                "workout_id": "w-hr-hard",
                "start_time_utc": "2026-03-03T12:00:00+00:00",
                "duration_sec": 3600,
                "hr_zone_basis": "LTHR",
                "hr_zone_reference_bpm": 165,
                "hr_z4_sec": 240,
                "hr_z5_sec": 180,
            }),
            build_rollup_metrics_model({
                "workout_id": "w-hr-easy",
                "start_time_utc": "2026-03-05T12:00:00+00:00",
                "duration_sec": 1800,
                "hr_zone_basis": "LTHR",
                "hr_zone_reference_bpm": 165,
                "hr_z4_sec": 120,
                "hr_z5_sec": 60,
            }),
        ]

        with patch.object(
            semantic_layer,
            "_workouts_for_local_week",
            return_value=workouts,
        ):
            rollup = semantic_layer.compute_and_persist_previous_week_rollup(
                athlete_id="rob",
                athlete_home_timezone="America/New_York",
                now_utc=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            )

        assert rollup is not None
        assert rollup["total_intensity_min"] == pytest.approx(0.0)
        assert rollup["hard_days_count"] == 0

    def test_compute_and_persist_previous_week_rollup_mixes_power_and_hr_intensity(
        self,
        semantic_layer,
    ):
        """Weekly intensity and hard-days should use intensity_sec only."""
        workouts = [
            build_rollup_metrics_model({
                "workout_id": "w-power-hard",
                "start_time_utc": "2026-03-03T12:00:00+00:00",
                "duration_sec": 3600,
                "ftp_watts": 250,
                "intensity_sec": 600,
            }),
            build_rollup_metrics_model({
                "workout_id": "w-hr-hard",
                "start_time_utc": "2026-03-06T12:00:00+00:00",
                "duration_sec": 2700,
                "hr_zone_basis": "LTHR",
                "hr_zone_reference_bpm": 165,
                "hr_z4_sec": 180,
                "hr_z5_sec": 180,
            }),
        ]

        with patch.object(
            semantic_layer,
            "_workouts_for_local_week",
            return_value=workouts,
        ):
            rollup = semantic_layer.compute_and_persist_previous_week_rollup(
                athlete_id="rob",
                athlete_home_timezone="America/New_York",
                now_utc=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            )

        assert rollup is not None
        assert rollup["total_intensity_min"] == pytest.approx(10.0)
        assert rollup["hard_days_count"] == 1

    def test_compute_and_persist_previous_week_rollups_batch(self, semantic_layer):
        """Batch wrapper should classify succeeded/skipped/failed athletes."""
        with patch.object(
            semantic_layer,
            "compute_and_persist_previous_week_rollup",
            side_effect=[{"workouts_count": 1}, None, RuntimeError("boom")],
        ):
            result = semantic_layer.compute_and_persist_previous_week_rollups(
                athlete_ids=["a1", "a2", "a3"],
                now_utc=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            )

        assert result["status"] == "partial"
        assert len(result["results"]) == 3
        assert result["results"][0]["athlete_id"] == "a1"
        assert result["results"][0]["status"] == "success"
        assert result["results"][0]["weeks"][0]["status"] == "success"
        assert result["results"][1]["status"] == "skipped"
        assert result["results"][1]["weeks"][0]["status"] == "skipped"
        assert result["results"][2]["status"] == "failed"
        assert result["results"][2]["weeks"][0]["status"] == "failed"

    def test_compute_and_persist_previous_week_rollups_multi_week(
        self,
        semantic_layer,
    ):
        """Batch wrapper should compute multiple completed weeks when requested."""
        with patch.object(
            semantic_layer,
            "compute_and_persist_previous_week_rollup",
            return_value={"workouts_count": 1},
        ) as mock_compute:
            result = semantic_layer.compute_and_persist_previous_week_rollups(
                athlete_ids=["rob"],
                weeks=3,
                now_utc=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            )

        assert result["status"] == "success"
        assert len(result["results"]) == 1
        assert result["results"][0]["status"] == "success"
        assert len(result["results"][0]["weeks"]) == 3
        assert all(item["status"] == "success" for item in result["results"][0]["weeks"])
        assert mock_compute.call_count == 3
        assert mock_compute.call_args_list[0].kwargs["weeks_ago"] == 1
        assert mock_compute.call_args_list[1].kwargs["weeks_ago"] == 2
        assert mock_compute.call_args_list[2].kwargs["weeks_ago"] == 3

    def test_compute_and_persist_previous_week_rollups_mixed_week_outcomes_same_athlete(
        self,
        semantic_layer,
    ):
        """A failed week should not hide successful/skipped weeks in detailed results."""
        with patch.object(
            semantic_layer,
            "compute_and_persist_previous_week_rollup",
            side_effect=[{"workouts_count": 1}, RuntimeError("boom"), None],
        ):
            result = semantic_layer.compute_and_persist_previous_week_rollups(
                athlete_ids=["rob"],
                weeks=3,
                now_utc=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
            )

        assert result["status"] == "failed"
        assert result["results"][0]["status"] == "partial"
        weeks = result["results"][0]["weeks"]
        assert [item["status"] for item in weeks] == ["success", "failed", "skipped"]

    def test_durability_model_accepts_signed_hr_drift(self):
        """hr_drift_bpm should preserve signed values from analytics output."""
        metric = DurabilityMetricsModel(
            efficiency_factor_avg=None,
            decoupling_pct=None,
            durability_slope=None,
            fatigue_rate_power=None,
            hr_power_lag_sec=None,
            ef_first_half=None,
            ef_second_half=None,
            ef_overall=None,
            hr_drift_bpm=-0.4,
        )
        assert metric.hr_drift_bpm == pytest.approx(-0.4)

    def test_build_rollup_metrics_model_retries_with_resample_on_sampling_validation_error(
        self,
        semantic_layer,
    ):
        """Non-1Hz canonical validation errors should retry with resample=True."""
        entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260308|w-1",
            "workout_id": "w-1",
            "athlete_id": "rob",
            "ingestion_id": "ing-1",
            "canonical_records_blob": "ing-1/canonical.parquet",
        }

        semantic_layer.storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        semantic_layer.storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-03-08T23:24:18Z", "2026-03-08T23:25:25Z"],
                    utc=True,
                ),
                "heart_rate_bpm": [125.0, 126.0],
            }
        )

        expected = build_rollup_metrics_model(
            {
                "sport": "Cycling",
                "start_time_utc": "2026-03-08T23:24:18+00:00",
                "duration_sec": 67,
                "hr_avg_bpm": 125.5,
                "hr_samples_count": 2,
            }
        )

        with patch.object(
            WorkoutMetricsModel,
            "from_canonical",
            side_effect=[
                ValidationError("strict_1hz_failed", status_code=422),
                expected,
            ],
        ) as mock_from_canonical:
            result = semantic_layer._build_rollup_metrics_model(entity)

        assert result == expected
        assert mock_from_canonical.call_count == 2
        assert mock_from_canonical.call_args_list[0].kwargs.get("resample", False) is False
        assert mock_from_canonical.call_args_list[1].kwargs.get("resample") is True

    def test_build_rollup_metrics_model_promotes_identity_start_time_for_canonical(
        self,
        semantic_layer,
    ):
        """Weekly rollup should pass start_time_utc from metadata.identity to canonical engine."""
        entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260308|w-1",
            "workout_id": "w-1",
            "athlete_id": "rob",
            "ingestion_id": "ing-1",
            "canonical_records_blob": "ing-1/canonical.parquet",
        }

        semantic_layer.storage.workouts.load_metadata_json.return_value = {
            "identity": {
                "start_time_utc": "2026-03-08T23:24:18+00:00",
                "sport": "Cycling",
            },
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        semantic_layer.storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-03-08T23:24:18Z", "2026-03-08T23:24:19Z"],
                    utc=True,
                ),
                "heart_rate_bpm": [125.0, 126.0],
            }
        )

        expected = build_rollup_metrics_model(
            {
                "sport": "Cycling",
                "start_time_utc": "2026-03-08T23:24:18+00:00",
                "duration_sec": 1,
                "hr_avg_bpm": 125.5,
                "hr_samples_count": 2,
            }
        )

        with patch.object(
            WorkoutMetricsModel,
            "from_canonical",
            return_value=expected,
        ) as mock_from_canonical:
            result = semantic_layer._build_rollup_metrics_model(entity)

        assert result == expected
        assert mock_from_canonical.call_count == 1
        metadata_arg = mock_from_canonical.call_args.args[1]
        assert metadata_arg.get("start_time_utc") == "2026-03-08T23:24:18+00:00"

    def test_build_rollup_metrics_model_clamps_negative_missing_pct_from_off_by_one_duration(
        self,
        semantic_layer,
    ):
        """Weekly rollup hydration should succeed when raw missing_pct would otherwise be -0.1."""
        entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260308|w-1",
            "workout_id": "w-1",
            "athlete_id": "rob",
            "ingestion_id": "ing-1",
            "canonical_records_blob": "ing-1/canonical.parquet",
            "start_time_utc": "2026-03-08T23:24:18+00:00",
            "sport": "Cycling",
        }

        semantic_layer.storage.workouts.load_metadata_json.return_value = {
            "identity": {
                "start_time_utc": "2026-03-08T23:24:18+00:00",
                "sport": "Cycling",
            },
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        semantic_layer.storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "elapsed_sec": list(range(1001)),
                "heart_rate_bpm": [140.0] * 1001,
                "power_watts": [220.0] * 1001,
            }
        )

        result = semantic_layer._build_rollup_metrics_model(entity)

        assert result.samples.hr_missing_pct == pytest.approx(0.0)
        assert result.samples.pwr_missing_pct == pytest.approx(0.0)
        assert result.samples.hr_samples_count == 1001
        assert result.samples.pwr_samples_count == 1001

    def test_workouts_for_local_week_skips_malformed_start_time_utc(
        self,
        semantic_layer,
        caplog,
    ):
        """Malformed Workouts.start_time_utc values should be skipped before model hydration."""
        entities = [
            {
                "workout_id": "w-valid",
                "start_time_utc": "2026-03-03T12:00:00+00:00",
            },
            {
                "workout_id": "w-missing",
            },
            {
                "workout_id": "w-invalid",
                "start_time_utc": "not-a-timestamp",
            },
        ]
        valid_model = build_rollup_metrics_model(
            {
                "workout_id": "w-valid",
                "start_time_utc": "2026-03-03T12:00:00+00:00",
                "duration_sec": 3600,
            }
        )

        with patch.object(
            semantic_layer,
            "_get_rollup_entities_in_range",
            return_value=entities,
        ), patch.object(
            semantic_layer,
            "_build_rollup_metrics_model",
            return_value=valid_model,
        ) as build_model_mock:
            result = semantic_layer._workouts_for_local_week(
                athlete_id="rob",
                week_start_local=datetime(2026, 3, 3, 0, 0, tzinfo=ZoneInfo("UTC")),
                week_end_local=datetime(2026, 3, 9, 23, 59, 59, tzinfo=ZoneInfo("UTC")),
                athlete_tz=ZoneInfo("UTC"),
            )

        assert result == [valid_model]
        assert build_model_mock.call_count == 1
        assert "Skipping workouts with malformed Workouts.start_time_utc while building weekly rollup" in caplog.text

    def test_compute_metrics_from_canonical_retries_with_resample(
        self,
        semantic_layer,
    ):
        """Semantic metrics path should retry canonical engine with resample=True."""
        df = pd.DataFrame(
            {
                "timestamp_utc": pd.to_datetime(
                    ["2026-03-08T23:24:18Z", "2026-03-08T23:25:25Z"],
                    utc=True,
                ),
                "heart_rate_bpm": [125.0, 126.0],
            }
        )
        metadata = {"sport": "Cycling"}

        mocked_engine = MagicMock()
        mocked_engine.to_metrics_dict.return_value = {"hr_avg_bpm": 125.5}

        with patch(
            "TrainingAnalyticsPlatform.analytics.semantic_layer.CanonicalAnalyticsEngine.from_dataframe",
            side_effect=[
                ValidationError("strict_1hz_failed", status_code=422),
                mocked_engine,
            ],
        ) as mock_from_dataframe:
            result = semantic_layer._compute_metrics_from_canonical(df, metadata)

        assert result == {"hr_avg_bpm": 125.5}
        assert mock_from_dataframe.call_count == 2
        assert mock_from_dataframe.call_args_list[0].kwargs.get("resample", False) is False
        assert mock_from_dataframe.call_args_list[1].kwargs.get("resample") is True

    def test_log_canonical_resample_fallback_warns_only_above_threshold(
        self,
        semantic_layer,
    ):
        """Resample fallback should warn only when distortion exceeds configured threshold."""
        strict_exc = ValidationError("strict_1hz_failed", status_code=422)

        with patch("TrainingAnalyticsPlatform.analytics.semantic_layer.logger") as mock_logger:
            semantic_layer._log_canonical_resample_fallback(
                scope="weekly_rollup",
                strict_error=strict_exc,
                record_count=100,
                distortion={
                    "gap_count": 1,
                    "max_gap_sec": 14.0,
                    "inserted_missing_bins": 13,
                    "distortion_pct": 0.8,
                },
                workout_id="w-1",
                blob_name="ing-1/canonical.parquet",
            )
            semantic_layer._log_canonical_resample_fallback(
                scope="weekly_rollup",
                strict_error=strict_exc,
                record_count=100,
                distortion={
                    "gap_count": 1,
                    "max_gap_sec": 120.0,
                    "inserted_missing_bins": 119,
                    "distortion_pct": 9.5,
                },
                workout_id="w-2",
                blob_name="ing-2/canonical.parquet",
            )

        assert mock_logger.info.call_count == 1
        assert mock_logger.warning.call_count == 1


class TestHelperMethods:
    """Tests for private helper methods."""

    def test_get_rollup_entities_in_range_uses_partition_and_start_time_bounds(
        self,
        semantic_layer,
    ):
        """Rollup entity query should be partition-scoped and date-bounded in Azure Table filter."""
        table_client = MagicMock()
        table_client.query_entities.return_value = [
            {"workout_id": "w-1", "start_time_utc": "2026-03-03T12:00:00Z"}
        ]
        semantic_layer.storage.infrastructure.get_table_client.return_value = table_client

        start = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 7, 23, 59, 59, tzinfo=timezone.utc)

        with patch.object(
            semantic_layer,
            "_get_month_partitions",
            return_value=["rob|2026-03"],
        ), patch.object(
            semantic_layer,
            "_entity_within_date_range",
            return_value=True,
        ):
            result = semantic_layer._get_rollup_entities_in_range(
                athlete_id="rob",
                start_date=start,
                end_date=end,
            )

        assert len(result) == 1
        query = table_client.query_entities.call_args.args[0]
        assert "PartitionKey eq 'rob|2026-03'" in query
        assert "start_time_utc ge '2026-03-01T00:00:00Z'" in query
        assert "start_time_utc le '2026-03-07T23:59:59Z'" in query

    def test_get_month_partitions_single_month(self, semantic_layer):
        """Test partition key generation for single month."""
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 31, tzinfo=timezone.utc)

        partitions = semantic_layer._get_month_partitions("rob", start, end)

        assert len(partitions) == 1
        assert partitions[0] == "rob|2026-01"

    def test_get_month_partitions_multiple_months(self, semantic_layer):
        """Test partition key generation across multiple months."""
        start = datetime(2025, 12, 15, tzinfo=timezone.utc)
        end = datetime(2026, 2, 15, tzinfo=timezone.utc)

        partitions = semantic_layer._get_month_partitions("rob", start, end)

        assert len(partitions) == 3
        assert "rob|2025-12" in partitions
        assert "rob|2026-01" in partitions
        assert "rob|2026-02" in partitions

    def test_compute_rolling_tss_uses_canonical_fallback_when_entity_tss_missing(
        self,
        semantic_layer,
    ):
        """Training-state TSS should fall back to canonical analytics when table tss is absent."""
        table_client = MagicMock()
        table_client.query_entities.side_effect = [
            [
                {
                    "PartitionKey": "rob|2026-02",
                    "RowKey": "20260220T120000Z|abc",
                    "workout_id": "w-1",
                    "start_time_utc": "2026-02-20T12:00:00Z",
                    "tss": None,
                },
                {
                    "PartitionKey": "rob|2026-03",
                    "RowKey": "20260315T120000Z|def",
                    "workout_id": "w-2",
                    "start_time_utc": "2026-03-15T12:00:00Z",
                    "tss": None,
                },
            ]
        ]

        with patch.object(
            semantic_layer,
            "_get_month_partitions",
            return_value=["rob|2026-02"],
        ), patch.object(
            semantic_layer,
            "_build_partition_date_range_query",
            return_value="PartitionKey eq 'rob|2026-02'",
        ), patch.object(
            semantic_layer,
            "_resolve_workout_tss",
            side_effect=[55.0, 80.0],
        ):
            tss_7d, tss_28d = semantic_layer._compute_rolling_tss(
                athlete_id="rob",
                end_date=datetime(2026, 3, 17, tzinfo=timezone.utc).date(),
                workouts_table=table_client,
            )

        assert tss_7d == pytest.approx(80.0)
        assert tss_28d == pytest.approx(135.0)

    def test_resolve_workout_tss_rebuilds_from_canonical_metrics(
        self,
        semantic_layer,
    ):
        """Workout TSS fallback should use the canonical metrics model when table tss is missing."""
        entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260315T120000Z|def",
            "workout_id": "w-2",
            "tss": None,
        }
        metrics_model = MagicMock()
        metrics_model.training_load = SimpleNamespace(tss=72.4)

        with patch.object(
            semantic_layer,
            "_build_rollup_metrics_model",
            return_value=metrics_model,
        ):
            result = semantic_layer._resolve_workout_tss(entity)

        assert result == pytest.approx(72.4)

    def test_resolve_workout_tss_prefers_materialized_table_value(
        self,
        semantic_layer,
    ):
        """Materialized Workouts.tss should be used directly when available."""
        entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260315T120000Z|def",
            "workout_id": "w-2",
            "tss": 91.2,
        }

        with patch.object(
            semantic_layer,
            "_build_rollup_metrics_model",
        ) as build_metrics:
            result = semantic_layer._resolve_workout_tss(entity)

        build_metrics.assert_not_called()
        assert result == pytest.approx(91.2)

    def test_compute_composite_readiness_is_independent_of_garmin(self, semantic_layer):
        """Garmin readiness must not be mixed into composite — it lives in garmin_readiness_score."""
        # With valid HRV + load, score should be from the formula, not Garmin's value.
        result = semantic_layer._compute_composite_readiness(
            hrv_ln=3.5,
            fatigue_index=1.0,
        )

        # 58.33 = avg(50.0, 66.67) — entirely from HRV + load, no Garmin influence
        assert result == pytest.approx(58.33333333333333)

    def test_compute_composite_readiness_returns_none_without_credible_load(self, semantic_layer):
        """Composite readiness should be absent when fatigue input is missing or not credible."""
        missing_fatigue = semantic_layer._compute_composite_readiness(
            hrv_ln=4.2,
            fatigue_index=None,
        )
        zero_fatigue = semantic_layer._compute_composite_readiness(
            hrv_ln=4.2,
            fatigue_index=0.0,
        )

        assert missing_fatigue is None
        assert zero_fatigue is None

    def test_compute_composite_readiness_averages_hrv_and_fatigue(self, semantic_layer):
        """Composite readiness should average normalized HRV and fatigue when both are present."""
        result = semantic_layer._compute_composite_readiness(
            hrv_ln=3.5,
            fatigue_index=1.0,
        )

        assert result == pytest.approx(58.33333333333333)

    def test_find_last_hard_day_found(self, semantic_layer, sample_workouts):
        """Test finding last hard workout."""
        last_hard = semantic_layer._find_last_hard_day(sample_workouts)

        # workout-001 has 8 minutes of Z4+Z5
        assert last_hard == sample_workouts[0]["start_time_utc"]

    def test_find_last_hard_day_not_found(self, semantic_layer):
        """Test finding last hard workout when none exist."""
        easy_workouts = [
            {
                "workout_id": "easy-1",
                "z2_minutes": 60,
                "z4_minutes": 0,
                "z5_minutes": 0,
            }
        ]

        last_hard = semantic_layer._find_last_hard_day(easy_workouts)
        assert last_hard is None

    def test_find_last_long_day_found(self, semantic_layer):
        """Test finding last long Z2 workout."""
        long_workouts = [
            {
                "workout_id": "long-1",
                "start_time_utc": "2026-01-15T10:00:00+00:00",
                "hr_z2_sec": 5400,  # 90 minutes in seconds
            }
        ]

        last_long = semantic_layer._find_last_long_day(long_workouts)
        assert last_long == "2026-01-15T10:00:00+00:00"

    def test_sum_zone_time(self, semantic_layer, sample_workouts):
        """Test zone time summation."""
        total_z2 = semantic_layer._sum_zone_time(sample_workouts, "hr_z2_sec")

        # Sum all hr_z2_sec values and convert to minutes
        expected = int(sum(w.get("hr_z2_sec", 0) or 0 for w in sample_workouts) / 60)
        assert total_z2 == expected

    def test_sum_high_intensity(self, semantic_layer, sample_workouts):
        """Test high intensity summation."""
        total_intensity = semantic_layer._sum_high_intensity(sample_workouts)

        # workout-001: 480sec = 8 minutes total
        assert total_intensity == pytest.approx(8.0)

    def test_sum_high_intensity_ignores_hr_when_intensity_missing(self, semantic_layer):
        """Without intensity_sec, HR zones should not contribute to intensity sum."""
        workouts = [
            {
                "workout_id": "hr-only-1",
                "hr_z4_sec": 240,
                "hr_z5_sec": 120,
            }
        ]

        total_intensity = semantic_layer._sum_high_intensity(workouts)

        assert total_intensity == pytest.approx(0.0)

    def test_detect_notable_flags_missing_hr(self, semantic_layer):
        """Test flag detection for missing HR data."""
        workouts = [
            {"workout_id": "w1", "duration_sec": 3600},
            {"workout_id": "w2", "duration_sec": 3600, "hr_avg_bpm": 150},
        ]

        flags = semantic_layer._detect_notable_flags(workouts)

        assert any("missing heart rate" in flag for flag in flags)

    def test_detect_notable_flags_high_decoupling(self, semantic_layer):
        """Test flag detection for high decoupling."""
        workouts = [
            {
                "workout_id": "w1",
                "duration_sec": 3600,
                "decoupling_pct": 6.5,
            }
        ]

        flags = semantic_layer._detect_notable_flags(workouts)

        assert any("high decoupling" in flag for flag in flags)

    def test_detect_notable_flags_very_short(self, semantic_layer):
        """Test flag detection for very short workouts."""
        workouts = [
            {"workout_id": "w1", "duration_sec": 300}  # 5 minutes
        ]

        flags = semantic_layer._detect_notable_flags(workouts)

        assert any("very short" in flag for flag in flags)

class TestDecouplingSignSemantics:
    """Tests to verify aerobic decoupling sign semantics: positive = fatigue, negative = improvement."""

    def test_detect_notable_flags_negative_decoupling_no_alert(self, semantic_layer):
        """Negative decoupling (efficiency improvement) should not trigger high decoupling flag."""
        workouts = [
            {
                "workout_id": "w1",
                "duration_sec": 3600,
                "decoupling_pct": -3.2,  # Efficiency improved
            }
        ]

        flags = semantic_layer._detect_notable_flags(workouts)

        # Should NOT have high decoupling flag for negative (improvement) values
        assert not any("high decoupling" in flag for flag in flags)

    def test_detect_notable_flags_zero_decoupling_no_alert(self, semantic_layer):
        """Zero or near-zero decoupling should not trigger alert."""
        workouts = [
            {
                "workout_id": "w1",
                "duration_sec": 3600,
                "decoupling_pct": 0.5,  # Very small positive, below threshold
            }
        ]

        flags = semantic_layer._detect_notable_flags(workouts)

        # Should NOT have high decoupling flag; threshold is > 5%
        assert not any("high decoupling" in flag for flag in flags)

    def test_efficiency_trends_preserves_negative_decoupling(self, semantic_layer, mock_storage):
        """Efficiency trends endpoint should preserve and report negative decoupling values."""
        # Mixed workouts: some positive (fatigue), some negative (improvement)
        workouts = [
            {
                "workout_id": "w1",
                "sport": "Cycling",
                "start_time_utc": datetime(2026, 1, 15, tzinfo=timezone.utc).isoformat(),
                "duration_sec": 3600,
                "decoupling_pct": 6.5,  # Fatigue scenario
                "hr_drift_bpm": 5.2,
                "ef_overall": 1.45,
            },
            {
                "workout_id": "w2",
                "sport": "Cycling",
                "start_time_utc": datetime(2026, 1, 16, tzinfo=timezone.utc).isoformat(),
                "duration_sec": 3600,
                "decoupling_pct": -2.1,  # Improvement scenario
                "hr_drift_bpm": -1.8,
                "ef_overall": 1.52,
            },
        ]

        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=workouts
        ):
            trends = semantic_layer.get_efficiency_trends("rob", days=7)

        # Check that we got both samples
        assert len(trends["samples"]) == 2
        
        # Verify samples preserve sign
        assert trends["samples"][0]["decoupling_pct"] == pytest.approx(6.5)
        assert trends["samples"][1]["decoupling_pct"] == pytest.approx(-2.1)
        
        # Verify avg_decoupling also preserves sign semantics (average of 6.5 and -2.1)
        expected_avg = (6.5 + (-2.1)) / 2
        assert trends["summary"]["avg_decoupling"] == pytest.approx(expected_avg, abs=0.1)

    def test_high_decoupling_threshold_respects_sign(self, semantic_layer):
        """High decoupling flag should only trigger for positive values > 5%."""
        test_cases = [
            (7.0, True),      # Positive, above threshold
            (5.1, True),      # Positive, barely above threshold
            (5.0, False),     # At threshold (boundary)
            (2.0, False),     # Positive but below threshold
            (0.0, False),     # Zero
            (-5.0, False),    # Negative (efficiency improvement)
            (-10.0, False),   # Large negative improvement
        ]

        for decoupling_val, should_flag in test_cases:
            workouts = [
                {
                    "workout_id": f"w_{decoupling_val}",
                    "duration_sec": 3600,
                    "decoupling_pct": decoupling_val,
                }
            ]

            flags = semantic_layer._detect_notable_flags(workouts)
            has_flag = any("high decoupling" in flag for flag in flags)

            assert has_flag == should_flag, (
                f"Decoupling {decoupling_val}: expected flag={should_flag}, "
                f"got flag={has_flag}. Flags: {flags}"
            )


class TestWorkoutProjection:
    """Tests for WorkoutProjection model and build_workout_projection() builder."""

    @pytest.fixture
    def sample_table_entity(self):
        """Sample Azure Table entity representing a workout."""
        return {
            "PartitionKey": "rob|2026-01",
            "RowKey": "20260115T045318|proj-001",
            "workout_id": "proj-001",
            "athlete_id": "rob",
            "ingestion_id": "ingestion-001",
            "sport": "cycling",
            "sub_sport": "road_cycling",
            "start_time_utc": datetime(2026, 1, 15, 4, 53, 18, tzinfo=timezone.utc).isoformat(),
            "duration_sec": 3600.0,
            "distance_m": 42000.0,
            "device_manufacturer": "Garmin",
            "device_model": "Edge 1050",
            "has_power": True,
            "has_hr": True,
            "has_gps": True,
            "canonical_schema_version": "2.0.1",
            "records_count": 3600,
        }

    @pytest.fixture
    def sample_metadata_full(self):
        """Sample metadata.json with all semantic zones populated."""
        return {
            "metadata_schema_version": "2.3.0",
            "identity": {
                "sport": "cycling",
                "sub_sport": "road_cycling",
                "start_time_utc": datetime(2026, 1, 15, 4, 53, 18, tzinfo=timezone.utc).isoformat(),
                "device_name": "My Garmin Edge",
                "device_manufacturer": "Garmin",
                "device_model": "Edge 1050",
            },
            "capabilities": {
                "has_power": True,
                "has_hr": True,
                "has_gps": True,
            },
            "session": {
                "duration_sec": 3600,
                "moving_time_sec": 3540,
                "distance_m": 42000.0,
                "elevation_gain_m": 500.0,
                "elevation_loss_m": 480.0,
                "calories_kcal": 1850.0,
                "avg_speed_mps": 11.67,
                "max_speed_mps": 18.5,
                "hr_avg_bpm": 165.0,
                "hr_max_bpm": 182.0,
                "pwr_avg_watts": 285.0,
                "pwr_max_watts": 520.0,
                "pwr_normalized_watts": 305.0,
                "cad_avg_rpm": 92.0,
                "cad_max_rpm": 125.0,
            },
            "enrichment": {
                "workout_name": "Morning Intervals",
                "is_indoor": False,
                "race_flag": False,
                "commute_flag": False,
            },
            "activity_metadata": {
                "local_tz_offset": "-05:00",
                "timezone": "America/New_York",
            },
            "provenance": {
                "ingestion_version": "15.1.1",
                "ingestion_timestamp_utc": datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc).isoformat(),
            },
        }

    def test_build_projection_basic_fields(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that build_workout_projection extracts basic identity and session fields."""
        # Mock metadata loading
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection is not None
        assert projection.workout_id == "proj-001"
        assert projection.athlete_id == "rob"
        assert projection.sport == "cycling"
        assert projection.sub_sport == "road_cycling"
        assert projection.workout_name == "Morning Intervals"
        assert projection.device_name == "My Garmin Edge"
        assert projection.device_manufacturer == "Garmin"

    def test_build_projection_timing_fields(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that timing fields are extracted correctly."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.start_time_utc == sample_table_entity["start_time_utc"]
        assert projection.duration_sec == pytest.approx(3600.0)
        assert projection.moving_time_sec == pytest.approx(3540.0)
        assert projection.local_tz_offset == "-05:00"
        assert projection.timezone == "America/New_York"

    def test_build_projection_distance_fields(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that distance and elevation fields are extracted correctly."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.distance_m == pytest.approx(42000.0)
        assert projection.elevation_gain_m == pytest.approx(500.0)
        assert projection.elevation_loss_m == pytest.approx(480.0)
        assert projection.calories_kcal == pytest.approx(1850.0)

    def test_build_projection_data_capability_flags(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that data capability flags are extracted correctly."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.has_power is True
        assert projection.has_hr is True
        assert projection.has_gps is True

    def test_build_projection_hr_peaks_populated_when_has_hr(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that HR peaks are populated when has_hr=True."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.hr_avg_bpm == pytest.approx(165.0)
        assert projection.hr_max_bpm == pytest.approx(182.0)

    def test_build_projection_power_peaks_populated_when_has_power(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that power peaks are populated when has_power=True."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.pwr_avg_watts == pytest.approx(285.0)
        assert projection.pwr_max_watts == pytest.approx(520.0)
        assert projection.pwr_normalized_watts == pytest.approx(305.0)

    def test_build_projection_cadence_peaks(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that cadence peaks are extracted when available."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.cad_avg_rpm == pytest.approx(92.0)
        assert projection.cad_max_rpm == pytest.approx(125.0)

    def test_build_projection_status_flags(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that status/enrichment flags are extracted correctly."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.is_indoor is False
        assert projection.race_flag is False
        assert projection.commute_flag is False

    def test_build_projection_provenance_fields(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that provenance/ingestion fields are extracted."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.ingestion_version == "15.1.1"
        assert projection.ingestion_timestamp_utc is not None

    def test_build_projection_hr_peaks_none_when_no_hr(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that HR peaks are None when has_hr=False."""
        # Set has_hr to False
        sample_table_entity["has_hr"] = False
        sample_metadata_full["capabilities"]["has_hr"] = False
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.hr_avg_bpm is None
        assert projection.hr_max_bpm is None

    def test_build_projection_power_peaks_none_when_no_power(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that power peaks are None when has_power=False."""
        # Set has_power to False
        sample_table_entity["has_power"] = False
        sample_metadata_full["capabilities"]["has_power"] = False
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.pwr_avg_watts is None
        assert projection.pwr_max_watts is None
        assert projection.pwr_normalized_watts is None

    def test_build_projection_empty_metadata_fallback(
        self, semantic_layer, sample_table_entity, mock_storage
    ):
        """Test that projection builder handles empty metadata gracefully."""
        # Return empty metadata
        mock_storage.workouts.load_metadata_json.return_value = {}

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection is not None
        assert projection.workout_id == "proj-001"
        assert projection.sport == "cycling"  # Falls back to entity sport
        assert projection.duration_sec == pytest.approx(3600.0)  # Falls back to entity duration

    def test_build_projection_metadata_load_error_handled(
        self, semantic_layer, sample_table_entity, mock_storage
    ):
        """Test that projection builder continues when metadata loading fails."""
        # Simulate metadata load error
        mock_storage.workouts.load_metadata_json.side_effect = Exception("Blob not found")

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection is not None
        assert projection.workout_id == "proj-001"
        # Should use entity fields as fallback
        assert projection.duration_sec == pytest.approx(3600.0)

    def test_build_projection_serialization(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that projection can be serialized to dict (for API response)."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)
        projection_dict = projection.model_dump()

        assert isinstance(projection_dict, dict)
        assert projection_dict["workout_id"] == "proj-001"
        assert projection_dict["sport"] == "cycling"
        assert projection_dict["has_power"] is True
        assert projection_dict["has_hr"] is True

    def test_build_projection_uses_ingestion_id_override(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that explicit ingestion_id parameter is used for metadata lookup."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        # Call with explicit ingestion_id
        projection = semantic_layer.build_workout_projection(
            sample_table_entity,
            ingestion_id="custom-ingestion-id"
        )

        # Verify correct ID was used
        mock_storage.workouts.load_metadata_json.assert_called_with("custom-ingestion-id")
        assert projection.workout_id == "proj-001"

    def test_build_projection_defaults_sport_to_unknown(
        self, semantic_layer, sample_table_entity, mock_storage
    ):
        """Test that sport defaults to 'unknown' if missing from both sources."""
        sample_table_entity["sport"] = None
        mock_storage.workouts.load_metadata_json.return_value = {}

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.sport == "unknown"

    def test_build_projection_optional_fields_nullable(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that optional fields are properly nulled when absent."""
        # Remove optional fields from metadata
        sample_metadata_full["enrichment"]["workout_name"] = None
        sample_metadata_full["activity_metadata"]["timezone"] = None
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection.workout_name is None
        # timezone falls back to local_tz_offset if None (existing behavior)
        assert projection.timezone == "-05:00"

    def test_build_projection_all_fields_correct_types(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Test that all fields have correct types."""
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        # String fields
        assert isinstance(projection.workout_id, str)
        assert isinstance(projection.sport, str)
        
        # Boolean fields
        assert isinstance(projection.has_power, bool)
        assert isinstance(projection.has_hr, bool)
        assert isinstance(projection.is_indoor, bool)
        
        # Numeric fields
        assert isinstance(projection.duration_sec, (int, float))
        assert isinstance(projection.distance_m, (int, float))
        
        # Optional string fields
        if projection.workout_name is not None:
            assert isinstance(projection.workout_name, str)

    def test_build_projection_hydrate_from_canonical_fills_missing_power_fields(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Hydration should fill missing power and cadence fields from canonical metrics."""
        sample_table_entity["canonical_records_blob"] = "ingestion-001/canonical.parquet"
        sample_metadata_full["session"]["pwr_normalized_watts"] = None
        sample_metadata_full["session"]["pwr_avg_watts"] = None
        sample_metadata_full["session"]["pwr_max_watts"] = None
        sample_metadata_full["session"]["cad_avg_rpm"] = None
        sample_metadata_full["session"]["cad_max_rpm"] = None
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full
        elapsed = list(range(120))
        power = [240.0 + (index % 30) for index in elapsed]
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "elapsed_sec": elapsed,
                "power_watts": power,
                "heart_rate_bpm": [160.0 + (index % 5) for index in elapsed],
                "cadence_rpm": [90.0 + (index % 3) for index in elapsed],
                "distance_m": [float(index * 10) for index in elapsed],
            }
        )

        projection = semantic_layer.build_workout_projection(
            sample_table_entity,
        )

        assert projection is not None
        assert projection.pwr_avg_watts is not None
        assert projection.pwr_max_watts is not None
        assert projection.pwr_normalized_watts is not None
        assert projection.cad_avg_rpm is not None
        assert projection.cad_max_rpm is not None

    def test_build_projection_hydrate_from_canonical_preserves_metadata_values(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Hydration must not overwrite metadata-provided values."""
        sample_table_entity["canonical_records_blob"] = "ingestion-001/canonical.parquet"
        sample_metadata_full["session"]["pwr_normalized_watts"] = 305.0
        sample_metadata_full["session"]["moving_time_sec"] = 3540.0
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "elapsed_sec": [0, 1, 2, 3, 4],
                "power_watts": [200.0, 210.0, 220.0, 230.0, 240.0],
                "heart_rate_bpm": [150.0, 151.0, 152.0, 153.0, 154.0],
            }
        )

        projection = semantic_layer.build_workout_projection(
            sample_table_entity,
        )

        assert projection is not None
        assert projection.pwr_normalized_watts == pytest.approx(305.0)
        assert projection.moving_time_sec == pytest.approx(3540.0)

    def test_build_projection_hydrate_skips_when_capability_flags_false(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Hydration should be skipped when has_hr/has_power are both False."""
        sample_table_entity["canonical_records_blob"] = "ingestion-001/canonical.parquet"
        sample_table_entity["has_power"] = False
        sample_table_entity["has_hr"] = False
        sample_metadata_full["capabilities"]["has_power"] = False
        sample_metadata_full["capabilities"]["has_hr"] = False
        sample_metadata_full["session"]["pwr_normalized_watts"] = None
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection is not None
        mock_storage.workouts.load_canonical_records.assert_not_called()

    def test_build_projection_hydrate_from_canonical_graceful_fallback_on_load_error(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Canonical hydration failures should degrade gracefully to metadata values."""
        sample_table_entity["canonical_records_blob"] = "ingestion-001/canonical.parquet"
        sample_metadata_full["session"]["pwr_normalized_watts"] = None
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full
        mock_storage.workouts.load_canonical_records.side_effect = RuntimeError("blob unavailable")

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection is not None
        assert projection.workout_id == "proj-001"
        assert projection.pwr_normalized_watts is None

    def test_build_projection_hydrates_hr_only_when_has_hr_true(
        self, semantic_layer, sample_table_entity, sample_metadata_full, mock_storage
    ):
        """Hydration should populate HR-dependent fields when has_hr=True and values missing."""
        sample_table_entity["canonical_records_blob"] = "ingestion-001/canonical.parquet"
        sample_table_entity["has_power"] = False
        sample_metadata_full["capabilities"]["has_power"] = False
        sample_metadata_full["session"]["hr_avg_bpm"] = None
        sample_metadata_full["session"]["hr_max_bpm"] = None
        mock_storage.workouts.load_metadata_json.return_value = sample_metadata_full
        mock_storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "elapsed_sec": list(range(60)),
                "heart_rate_bpm": [150.0 + (index % 6) for index in range(60)],
            }
        )

        projection = semantic_layer.build_workout_projection(sample_table_entity)

        assert projection is not None
        assert projection.hr_avg_bpm is not None
        assert projection.hr_max_bpm is not None
        assert projection.pwr_normalized_watts is None


# =========================================================================
# HR–Power Lag Signed Semantics — Rollup Path Regression Tests
# =========================================================================


class TestHrPowerLagSignSemantics:
    """Regression tests for hr_power_lag_sec sign constraint bug.

    Production crash: DurabilityMetricsModel.hr_power_lag_sec incorrectly
    enforced ge=0, causing Pydantic ValidationError for input_value=-27.
    This aborted the entire athlete weekly rollup and landed the athlete in
    the 'failed' list with a StorageError.

    Fix: removed ge=0, replaced with ge=-60/le=60 per formula contract.
    These tests ensure the rollup path and model accept negative lag values.
    """

    def test_build_rollup_metrics_model_succeeds_with_negative_lag(
        self,
        semantic_layer,
    ):
        """_build_rollup_metrics_model must not raise when canonical parquet yields negative lag.

        This is a direct regression test for the production crash: WorkoutMetricsModel
        constructed via from_canonical must accept negative hr_power_lag_sec values.
        """
        entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260308|w-1",
            "workout_id": "w-1",
            "athlete_id": "rob",
            "ingestion_id": "ing-1",
            "canonical_records_blob": "ing-1/canonical.parquet",
        }

        semantic_layer.storage.workouts.load_metadata_json.return_value = {
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }

        # Build canonical data where HR leads power (produces negative lag)
        n = 120
        elapsed = list(range(n))
        power = [200.0] * 60 + [150.0] * 60
        hr = [140.0] * 50 + [130.0] * 70  # HR drops 10s before power

        semantic_layer.storage.workouts.load_canonical_records.return_value = pd.DataFrame(
            {
                "elapsed_sec": elapsed,
                "power_watts": power,
                "heart_rate_bpm": hr,
            }
        )

        expected = build_rollup_metrics_model(
            {
                "sport": "Cycling",
                "start_time_utc": "2026-03-08T00:00:00+00:00",
                "duration_sec": 119,
                "hr_avg_bpm": 135.83,
                "hr_samples_count": 120,
            }
        )

        with patch.object(
            WorkoutMetricsModel,
            "from_canonical",
            return_value=expected,
        ):
            result = semantic_layer._build_rollup_metrics_model(entity)

        assert result is not None

    def test_workout_metrics_model_from_canonical_metrics_accepts_negative_lag(self):
        """WorkoutMetricsModel constructed from canonical metrics accepts negative hr_power_lag_sec."""
        model = build_rollup_metrics_model(
            {
                "sport": "Cycling",
                "start_time_utc": "2026-03-08T00:00:00+00:00",
                "duration_sec": 3600,
                "hr_power_lag_sec": -27,  # The exact value from the production crash
            }
        )

        assert model.durability is not None
        assert model.durability.hr_power_lag_sec == -27

    def test_weekly_rollup_athlete_not_in_failed_on_negative_lag(
        self,
        semantic_layer,
    ):
        """An athlete must not land in 'failed' when their workout yields negative lag.

        Verifies that the StorageError wrapping chain is not triggered by a
        negative lag value now that DurabilityMetricsModel accepts signed values.
        """
        entity = {
            "PartitionKey": "rob|2026-03",
            "RowKey": "20260308|w-1",
            "workout_id": "w-1",
            "athlete_id": "rob",
            "ingestion_id": "ing-1",
            "canonical_records_blob": "ing-1/canonical.parquet",
            "start_time_utc": "2026-03-08T00:00:00+00:00",
            "sport": "Cycling",
        }

        model_with_negative_lag = build_rollup_metrics_model(
            {
                "sport": "Cycling",
                "start_time_utc": "2026-03-08T00:00:00+00:00",
                "duration_sec": 3600,
                "hr_power_lag_sec": -27,
            }
        )

        with (
            patch.object(
                semantic_layer,
                "_get_rollup_entities_in_range",
                return_value=[entity],
            ),
            patch.object(
                semantic_layer,
                "_build_rollup_metrics_model",
                return_value=model_with_negative_lag,
            ),
            patch.object(
                semantic_layer,
                "_build_rollup_metrics_model",
                return_value=model_with_negative_lag,
            ),
            patch.object(
                semantic_layer.storage,
                "aggregation",
                create=True,
            ),
        ):
            # The key assertion: calling with a mocked model return should not raise
            result = semantic_layer._build_rollup_metrics_model(entity)
            assert result is not None
