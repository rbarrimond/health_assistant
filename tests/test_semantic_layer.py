"""Tests for semantic access layer."""
# pylint: disable=redefined-outer-name  # pytest fixtures intentionally shadow
# pylint: disable=unused-argument  # pytest fixtures may be used for side effects
# pylint: disable=protected-access  # testing private methods intentionally

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer


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
            "hr_z2_min": 50,
            "hr_z4_sec": 300,
            "hr_z5_sec": 180,
            "intensity_min": 8,
            "decoupling_pct": 2.5,
            "ef_overall": 1.2,
        },
        {
            "workout_id": "workout-002",
            "athlete_id": "rob",
            "sport": "Running",
            "start_time_utc": (base_date - timedelta(days=2)).isoformat(),
            "duration_sec": 2700,
            "hr_z2_min": 45,
            "hr_z4_sec": 0,
            "hr_z5_sec": 0,
            "intensity_min": 0,
        },
        {
            "workout_id": "workout-003",
            "athlete_id": "rob",
            "sport": "Cycling",
            "start_time_utc": (base_date - timedelta(days=5)).isoformat(),
            "duration_sec": 300,  # Very short - 5 minutes
            "hr_z2_min": 5,
        },
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

        # workout-001 has 8 minutes of Z4+Z5
        assert context["summary"]["last_hard_day"] == sample_workouts[0]["start_time_utc"]

    def test_planning_context_detects_last_long_day(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test detection of last long aerobic workout."""
        # Modify workout-002 to have > 60 minutes of Z2
        workouts = sample_workouts.copy()
        workouts[1]["hr_z2_min"] = 75

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

        # Sum all HR Z2 minutes
        expected_z2 = sum(w.get("hr_z2_min", 0) or 0 for w in sample_workouts)
        assert context["summary"]["cumulative_z2_minutes"] == expected_z2

        # Sum all intensity minutes
        expected_intensity = sum(w.get("intensity_min", 0) or 0 for w in sample_workouts)
        assert context["summary"]["cumulative_intensity_minutes"] == expected_intensity

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


class TestWorkoutQueries:
    """Tests for workout query endpoints."""

    def test_get_workouts_basic(self, semantic_layer, sample_workouts, mock_storage):
        """Test basic workout listing."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            workouts = semantic_layer.get_workouts("rob", limit=50)

        assert len(workouts) == 3
        assert all(w["athlete_id"] == "rob" for w in workouts)

    def test_get_workouts_with_sport_filter(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test workout filtering by sport."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
        ):
            workouts = semantic_layer.get_workouts("rob", sport="Cycling")

        assert len(workouts) == 2
        assert all(w["sport"] == "Cycling" for w in workouts)

    def test_get_workouts_respects_limit(
        self, semantic_layer, sample_workouts, mock_storage
    ):
        """Test workout limit parameter."""
        with patch.object(
            semantic_layer, '_get_workouts_in_range', return_value=sample_workouts
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


class TestHelperMethods:
    """Tests for private helper methods."""

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
                "hr_z2_min": 90,
            }
        ]

        last_long = semantic_layer._find_last_long_day(long_workouts)
        assert last_long == "2026-01-15T10:00:00+00:00"

    def test_sum_zone_time(self, semantic_layer, sample_workouts):
        """Test zone time summation."""
        total_z2 = semantic_layer._sum_zone_time(sample_workouts, "hr_z2_min")

        expected = sum(w.get("hr_z2_min", 0) or 0 for w in sample_workouts)
        assert total_z2 == expected

    def test_sum_high_intensity(self, semantic_layer, sample_workouts):
        """Test high intensity summation."""
        total_intensity = semantic_layer._sum_high_intensity(sample_workouts)

        # workout-001: Z5=5 + Z6=3 = 8 minutes total
        assert total_intensity == 8

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
