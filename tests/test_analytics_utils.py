"""Unit tests for TrainingAnalyticsPlatform.analytics.utils pure functions."""

from datetime import datetime, timezone, time as dt_time
from unittest.mock import MagicMock

import pandas as pd
import pytest

from TrainingAnalyticsPlatform.analytics.utils import (
    as_metadata_dict,
    build_partition_date_range_query,
    canonical_sampling_distortion,
    entity_within_date_range,
    get_month_partitions,
    parse_workout_query_bound,
    prepare_rollup_metadata_for_canonical,
    rollup_promoted_defaults,
    select_fields,
)
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _minimal_workout_entity(**kwargs) -> WorkoutEntity:
    defaults = {
        "partition_key": "athlete1|2026-01",
        "row_key": "wkt-001",
        "workout_id": "wkt-001",
        "athlete_id": "athlete1",
        "ingestion_id": "ing-001",
    }
    defaults.update(kwargs)
    return WorkoutEntity(**defaults)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# parse_workout_query_bound
# ---------------------------------------------------------------------------

class TestParseWorkoutQueryBound:
    _default = _utc(2026, 1, 1)

    def test_none_returns_default(self) -> None:
        result = parse_workout_query_bound(None, default_value=self._default, is_end=False)
        assert result == self._default

    def test_date_only_is_end_false_uses_time_min(self) -> None:
        result = parse_workout_query_bound(
            "2026-03-15", default_value=self._default, is_end=False
        )
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 15
        assert result.hour == 0
        assert result.minute == 0

    def test_date_only_is_end_true_uses_time_max(self) -> None:
        result = parse_workout_query_bound(
            "2026-03-15", default_value=self._default, is_end=True
        )
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 15
        assert result.hour == 23
        assert result.minute == 59

    def test_datetime_with_z_suffix_parses_correctly(self) -> None:
        result = parse_workout_query_bound(
            "2026-06-01T12:00:00Z", default_value=self._default, is_end=False
        )
        assert result == _utc(2026, 6, 1, 12, 0)

    def test_datetime_without_tz_assumes_utc(self) -> None:
        result = parse_workout_query_bound(
            "2026-06-01T09:30:00", default_value=self._default, is_end=False
        )
        assert result.tzinfo is not None
        assert result.hour == 9
        assert result.minute == 30

    def test_result_is_always_utc_aware(self) -> None:
        result = parse_workout_query_bound(
            "2026-01-01", default_value=self._default, is_end=False
        )
        assert result.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# get_month_partitions
# ---------------------------------------------------------------------------

class TestGetMonthPartitions:
    def test_single_month(self) -> None:
        result = get_month_partitions("rob", _utc(2026, 3, 1), _utc(2026, 3, 31))
        assert result == ["rob|2026-03"]

    def test_two_consecutive_months(self) -> None:
        result = get_month_partitions("rob", _utc(2026, 1, 15), _utc(2026, 2, 15))
        assert result == ["rob|2026-01", "rob|2026-02"]

    def test_year_boundary_crossing(self) -> None:
        result = get_month_partitions("rob", _utc(2025, 12, 1), _utc(2026, 1, 31))
        assert result == ["rob|2025-12", "rob|2026-01"]

    def test_athlete_id_in_partition_key(self) -> None:
        result = get_month_partitions("alice", _utc(2026, 6, 1), _utc(2026, 6, 30))
        assert result == ["alice|2026-06"]

    def test_three_month_range(self) -> None:
        result = get_month_partitions("rob", _utc(2026, 1, 1), _utc(2026, 3, 31))
        assert result == ["rob|2026-01", "rob|2026-02", "rob|2026-03"]


# ---------------------------------------------------------------------------
# build_partition_date_range_query
# ---------------------------------------------------------------------------

class TestBuildPartitionDateRangeQuery:
    def test_query_contains_partition_key(self) -> None:
        q = build_partition_date_range_query(
            "rob|2026-03", _utc(2026, 3, 1), _utc(2026, 3, 31)
        )
        assert "PartitionKey eq 'rob|2026-03'" in q

    def test_query_contains_start_time_ge(self) -> None:
        q = build_partition_date_range_query(
            "rob|2026-03", _utc(2026, 3, 1), _utc(2026, 3, 31)
        )
        assert "start_time_utc ge" in q

    def test_query_contains_start_time_le(self) -> None:
        q = build_partition_date_range_query(
            "rob|2026-03", _utc(2026, 3, 1), _utc(2026, 3, 31)
        )
        assert "start_time_utc le" in q

    def test_query_uses_z_utc_suffix(self) -> None:
        q = build_partition_date_range_query(
            "rob|2026-03", _utc(2026, 3, 1), _utc(2026, 3, 31)
        )
        assert "Z" in q
        assert "+00:00" not in q


# ---------------------------------------------------------------------------
# entity_within_date_range
# ---------------------------------------------------------------------------

class TestEntityWithinDateRange:
    _start = _utc(2026, 3, 1)
    _end = _utc(2026, 3, 31)

    def test_entity_within_range_returns_true(self) -> None:
        entity = {"start_time_utc": "2026-03-15T10:00:00Z"}
        assert entity_within_date_range(entity, self._start, self._end) is True

    def test_entity_before_range_returns_false(self) -> None:
        entity = {"start_time_utc": "2026-02-28T23:59:59Z"}
        assert entity_within_date_range(entity, self._start, self._end) is False

    def test_entity_after_range_returns_false(self) -> None:
        entity = {"start_time_utc": "2026-04-01T00:00:00Z"}
        assert entity_within_date_range(entity, self._start, self._end) is False

    def test_missing_start_time_returns_false(self) -> None:
        entity = {"sport": "cycling"}
        assert entity_within_date_range(entity, self._start, self._end) is False

    def test_entity_on_range_boundary_is_inclusive(self) -> None:
        entity = {"start_time_utc": "2026-03-01T00:00:00Z"}
        assert entity_within_date_range(entity, self._start, self._end) is True


# ---------------------------------------------------------------------------
# canonical_sampling_distortion
# ---------------------------------------------------------------------------

class TestCanonicalSamplingDistortion:
    def test_empty_dataframe_returns_zeroed_summary(self) -> None:
        result = canonical_sampling_distortion(pd.DataFrame())
        assert result["gap_count"] == 0
        assert result["distortion_pct"] is None

    def test_no_timestamp_column_returns_zeroed_summary(self) -> None:
        df = pd.DataFrame({"power": [100, 200, 300]})
        result = canonical_sampling_distortion(df)
        assert result["gap_count"] == 0
        assert result["distortion_pct"] is None

    def test_single_timestamp_returns_zeroed_summary(self) -> None:
        df = pd.DataFrame({"timestamp_utc": ["2026-03-15T10:00:00Z"]})
        result = canonical_sampling_distortion(df)
        assert result["gap_count"] == 0
        assert result["distortion_pct"] is None

    def test_continuous_1hz_returns_zero_distortion(self) -> None:
        timestamps = pd.date_range("2026-03-15T10:00:00", periods=60, freq="1s", tz="UTC")
        df = pd.DataFrame({"timestamp_utc": timestamps.astype(str)})
        result = canonical_sampling_distortion(df)
        assert result["gap_count"] == 0
        assert result["distortion_pct"] == pytest.approx(0.0)

    def test_gap_in_data_detected(self) -> None:
        # 10 seconds at 1Hz then a 10-second gap
        ts1 = pd.date_range("2026-03-15T10:00:00", periods=10, freq="1s", tz="UTC")
        ts2 = pd.date_range("2026-03-15T10:00:20", periods=10, freq="1s", tz="UTC")
        timestamps = list(ts1.astype(str)) + list(ts2.astype(str))
        df = pd.DataFrame({"timestamp_utc": timestamps})
        result = canonical_sampling_distortion(df)
        assert result["gap_count"] >= 1
        assert result["distortion_pct"] is not None


# ---------------------------------------------------------------------------
# select_fields
# ---------------------------------------------------------------------------

class TestSelectFields:
    def test_returns_only_requested_fields(self) -> None:
        source = {"a": 1, "b": 2, "c": 3}
        result = select_fields(source, ["a", "c"])
        assert result == {"a": 1, "c": 3}

    def test_missing_field_returns_none(self) -> None:
        source = {"a": 1}
        result = select_fields(source, ["a", "z"])
        assert result["z"] is None

    def test_empty_fields_returns_empty_dict(self) -> None:
        result = select_fields({"a": 1}, [])
        assert result == {}


# ---------------------------------------------------------------------------
# as_metadata_dict
# ---------------------------------------------------------------------------

class TestAsMetadataDict:
    def test_dict_returns_same_dict(self) -> None:
        d = {"key": "value"}
        assert as_metadata_dict(d) == d

    def test_none_returns_empty_dict(self) -> None:
        assert as_metadata_dict(None) == {}

    def test_string_returns_empty_dict(self) -> None:
        assert as_metadata_dict("not a dict") == {}

    def test_list_returns_empty_dict(self) -> None:
        assert as_metadata_dict(["a", "b"]) == {}

    def test_empty_dict_returns_empty_dict(self) -> None:
        assert as_metadata_dict({}) == {}


# ---------------------------------------------------------------------------
# rollup_promoted_defaults
# ---------------------------------------------------------------------------

class TestRollupPromotedDefaults:
    def test_returns_all_expected_keys(self) -> None:
        entity = _minimal_workout_entity()
        result = rollup_promoted_defaults(
            identity={},
            session={},
            enrichment={},
            activity={},
            workout_entity=entity,
        )
        for key in ("start_time_utc", "sport", "sub_sport", "workout_name", "device_name",
                    "is_indoor", "local_tz_offset", "timezone", "duration_sec",
                    "moving_time_sec", "distance_m", "elevation_gain_m",
                    "elevation_loss_m", "calories_kcal"):
            assert key in result

    def test_identity_sport_takes_precedence_over_entity(self) -> None:
        entity = _minimal_workout_entity(sport="cycling")
        result = rollup_promoted_defaults(
            identity={"sport": "running"},
            session={},
            enrichment={},
            activity={},
            workout_entity=entity,
        )
        assert result["sport"] == "running"

    def test_entity_sport_used_as_fallback(self) -> None:
        entity = _minimal_workout_entity(sport="swimming")
        result = rollup_promoted_defaults(
            identity={},
            session={},
            enrichment={},
            activity={},
            workout_entity=entity,
        )
        assert result["sport"] == "swimming"

    def test_activity_timezone_promotion(self) -> None:
        entity = _minimal_workout_entity()
        result = rollup_promoted_defaults(
            identity={},
            session={},
            enrichment={},
            activity={"timezone": "America/New_York"},
            workout_entity=entity,
        )
        assert result["timezone"] == "America/New_York"
        assert result["local_tz_offset"] is None


# ---------------------------------------------------------------------------
# prepare_rollup_metadata_for_canonical
# ---------------------------------------------------------------------------

class TestPrepareRollupMetadataForCanonical:
    def test_promotes_identity_sport_to_top_level(self) -> None:
        metadata_blob = {
            "identity": {"sport": "cycling", "start_time_utc": "2026-03-01T10:00:00Z"},
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        entity = _minimal_workout_entity()
        result = prepare_rollup_metadata_for_canonical(metadata_blob, entity)
        assert result["sport"] == "cycling"

    def test_existing_top_level_not_overwritten(self) -> None:
        metadata_blob = {
            "sport": "running",
            "identity": {"sport": "cycling"},
            "session": {},
            "enrichment": {},
            "activity_metadata": {},
        }
        entity = _minimal_workout_entity()
        result = prepare_rollup_metadata_for_canonical(metadata_blob, entity)
        assert result["sport"] == "running"

    def test_non_dict_metadata_blob_returns_empty_base(self) -> None:
        entity = _minimal_workout_entity()
        result = prepare_rollup_metadata_for_canonical(None, entity)  # type: ignore[arg-type]
        assert isinstance(result, dict)

    def test_preserves_extra_top_level_keys(self) -> None:
        metadata_blob = {"custom_field": "custom_value"}
        entity = _minimal_workout_entity()
        result = prepare_rollup_metadata_for_canonical(metadata_blob, entity)
        assert result["custom_field"] == "custom_value"
