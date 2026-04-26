"""Regression tests for timezone propagation and fallback semantics."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from TrainingAnalyticsPlatform.analytics.workout_query_service import WorkoutQueryService
from TrainingAnalyticsPlatform.analytics.utils import prepare_rollup_metadata_for_canonical
from TrainingAnalyticsPlatform.ingestion.fit_models import PayloadFitModel
from TrainingAnalyticsPlatform.models.core import WorkoutMetricsModel
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity


@pytest.fixture(autouse=True)
def _stub_fit_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub FIT parsing for focused timezone tests."""
    monkeypatch.setattr(
        PayloadFitModel,
        "_parse_fit_messages",
        lambda self, file_bytes: ([], [], {}),
    )


@pytest.fixture
def payload_model() -> PayloadFitModel:
    """Create a minimal PayloadFitModel instance for testing."""
    return PayloadFitModel.model_construct()


def test_activity_metadata_emits_timezone_and_offset(payload_model: PayloadFitModel) -> None:
    """Canonical activity metadata should include both offset and canonical timezone."""
    with patch.object(
        PayloadFitModel,
        "local_tz_offset",
        new_callable=PropertyMock,
        return_value="UTC-05:00",
    ), patch.object(
        PayloadFitModel,
        "timezone",
        new_callable=PropertyMock,
        return_value="America/New_York",
    ):
        metadata = payload_model._build_canonical_activity_metadata()

    assert metadata["local_tz_offset"] == "UTC-05:00"
    assert metadata["timezone"] == "America/New_York"


def test_build_session_prefers_timezone_over_offset() -> None:
    """Session model should prefer canonical timezone with offset fallback."""
    session = WorkoutMetricsModel._build_session(
        metrics={},
        metadata={
            "local_tz_offset": "UTC-05:00",
            "timezone": "America/New_York",
        },
    )

    assert session.local_tz_offset == "UTC-05:00"
    assert session.timezone == "America/New_York"


def test_build_session_falls_back_to_offset_when_timezone_missing() -> None:
    """Session model should still populate timezone from offset when IANA is unavailable."""
    session = WorkoutMetricsModel._build_session(
        metrics={},
        metadata={
            "local_tz_offset": "UTC-05:00",
        },
    )

    assert session.local_tz_offset == "UTC-05:00"
    assert session.timezone == "UTC-05:00"


def test_semantic_base_dict_prefers_activity_timezone() -> None:
    """Semantic-layer workout base dict should preserve canonical timezone."""
    workout_service = WorkoutQueryService(MagicMock())
    workout_entity = WorkoutEntity.from_table_entity(
        {
            "PartitionKey": "rob|2026-01",
            "RowKey": "w-1",
            "workout_id": "w-1",
            "athlete_id": "rob",
            "ingestion_id": "ing-1",
            "sport": "cycling",
            "sub_sport": "road_cycling",
            "start_time_utc": "2026-01-15T12:00:00+00:00",
            "duration_sec": 3600.0,
            "distance_m": 42000.0,
        }
    )

    result = workout_service._build_workout_base_dict(
        workout_entity=workout_entity,
        identity={},
        session={},
        enrichment={},
        activity_metadata={
            "local_tz_offset": "UTC-05:00",
            "timezone": "America/New_York",
        },
        metrics={},
    )

    assert result["local_tz_offset"] == "UTC-05:00"
    assert result["timezone"] == "America/New_York"


def test_prepare_rollup_metadata_promotes_timezone_with_fallback() -> None:
    """Canonical rollup metadata promotion should set timezone from activity metadata."""
    workout_entity = WorkoutEntity.from_table_entity(
        {
            "PartitionKey": "rob|2026-01",
            "RowKey": "w-1",
            "workout_id": "w-1",
            "athlete_id": "rob",
            "ingestion_id": "ing-1",
            "start_time_utc": "2026-01-15T12:00:00+00:00",
            "sport": "cycling",
            "sub_sport": "road_cycling",
            "duration_sec": 3600.0,
            "distance_m": 42000.0,
            "device_model": "Edge 540",
        }
    )
    metadata_blob = {
        "identity": {},
        "session": {},
        "enrichment": {},
        "activity_metadata": {"local_tz_offset": "UTC-05:00"},
    }

    promoted = prepare_rollup_metadata_for_canonical(
        metadata_blob,
        workout_entity,
    )

    assert promoted["local_tz_offset"] == "UTC-05:00"
    assert promoted["timezone"] == "UTC-05:00"
