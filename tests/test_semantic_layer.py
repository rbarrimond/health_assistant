"""Tests for semantic access layer."""
# pylint: disable=redefined-outer-name  # pytest fixtures intentionally shadow
# pylint: disable=unused-argument  # pytest fixtures may be used for side effects
# pylint: disable=protected-access  # testing private methods intentionally

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from TrainingAnalyticsPlatform.analytics.semantic_layer import (
    WEEKLY_ROLLUP_ALLOWED_FIELDS,
    SemanticLayer,
)
from TrainingAnalyticsPlatform.models.core import WorkoutMetricsModel, WorkoutProjection
from TrainingAnalyticsPlatform.platform.exceptions import ValidationError


def build_rollup_metrics_model(flat_metrics):
    """Build a typed WorkoutMetricsModel for weekly rollup tests."""
    return WorkoutMetricsModel.from_flat_metrics(
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
            "source_system": "onedrive",
            "sport": "Cycling",
            "duration_sec": 3600,
        }
        mock_table_client.query_entities.return_value = [mock_entity]

        workout = semantic_layer.get_workout_detail("rob", "workout-001")

        assert workout is not None
        assert workout["workout_id"] == "workout-001"
        assert workout["athlete_id"] == "rob"

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

        workout = semantic_layer.get_workout_detail(
            "rob",
            "workout-001",
            include_developer_fields=True,
        )

        assert workout is not None
        assert "developer_fields_summary" in workout
        assert workout["developer_fields_summary"]["field_count"] == 1

    def test_get_workout_detail_falls_back_to_basic_sample_metrics_on_non_1hz(
        self,
        semantic_layer,
        mock_storage,
    ):
        """Populate sample counts from canonical records when strict analytics rejects cadence gaps."""
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
            workout = semantic_layer.get_workout_detail("rob", mock_entity["workout_id"])

        assert workout is not None
        samples = workout["metrics"]["samples"]
        assert samples["hr_samples_count"] == 2
        assert samples["cad_samples_count"] == 2
        assert samples["pwr_samples_count"] == 0


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

        assert result["requested_athletes"] == 3
        assert result["requested_weeks"] == 1
        assert result["succeeded"] == ["a1"]
        assert result["skipped"] == ["a2"]
        assert result["failed"] == ["a3"]

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

        assert result["requested_athletes"] == 1
        assert result["requested_weeks"] == 3
        assert result["succeeded"] == ["rob"]
        assert result["skipped"] == []
        assert result["failed"] == []
        assert mock_compute.call_count == 3
        assert mock_compute.call_args_list[0].kwargs["weeks_ago"] == 1
        assert mock_compute.call_args_list[1].kwargs["weeks_ago"] == 2
        assert mock_compute.call_args_list[2].kwargs["weeks_ago"] == 3

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

    def test_entity_to_workout_dict_basic(self, semantic_layer):
        """Test entity conversion to workout dict."""
        entity = {
            "PartitionKey": "rob|2026-02",
            "RowKey": "20260214|abc",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ing-001",
            "sport": "Cycling",
            "duration_sec": 3600,
        }
        
        # Mock metadata blob with session/enrichment zones
        metadata_blob = {
            "session": {
                "hr_avg_bpm": 145,
                "duration_sec": 3600,
            },
            "enrichment": {},
            "activity_metadata": {
                "local_tz_offset": "UTC-05:00",
            },
        }
        semantic_layer.storage.workouts.load_metadata_json.return_value = metadata_blob

        workout = semantic_layer._entity_to_workout_dict(entity)

        assert workout["workout_id"] == "workout-001"
        assert workout["sport"] == "Cycling"
        assert workout["hr_avg_bpm"] == 145
        assert workout["local_tz_offset"] == "UTC-05:00"
        assert workout["timezone"] == "UTC-05:00"

    def test_entity_to_workout_dict_timezone_falls_back_to_local_offset(self, semantic_layer):
        """Test timezone field falls back to local_tz_offset when timezone is absent."""
        entity = {
            "PartitionKey": "rob|2026-02",
            "RowKey": "20260214|abc",
            "workout_id": "workout-002",
            "athlete_id": "rob",
            "ingestion_id": "ing-002",
            "sport": "Running",
            "duration_sec": 1800,
        }
        
        # Mock metadata blob with activity_metadata zone containing local_tz_offset
        metadata_blob = {
            "session": {
                "duration_sec": 1800,
            },
            "enrichment": {},
            "activity_metadata": {
                "local_tz_offset": "UTC+01:00",
            },
        }
        semantic_layer.storage.workouts.load_metadata_json.return_value = metadata_blob

        workout = semantic_layer._entity_to_workout_dict(entity)

        assert workout["local_tz_offset"] == "UTC+01:00"
        assert workout["timezone"] == "UTC+01:00"

    def test_entity_to_workout_dict_with_records(self, semantic_layer):
        """Test entity conversion ignores time series when not stored."""
        entity = {
            "PartitionKey": "rob|2026-02",
            "RowKey": "20260214|abc",
            "workout_id": "workout-001",
            "athlete_id": "rob",
            "ingestion_id": "ing-001",
            "records_json": json.dumps([{"heart_rate": 145}]),
        }

        workout = semantic_layer._entity_to_workout_dict(entity)

        assert "records" not in workout


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
