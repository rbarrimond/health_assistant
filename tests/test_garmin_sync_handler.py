"""Tests for Garmin sync request parsing and ingestion handler."""

# pylint: disable=protected-access

from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import (
    GarminSyncConfig,
    GarminSyncHandler,
    GarminSyncIngestionHandler,
    GarminSyncRequest,
)
from TrainingAnalyticsPlatform.platform.exceptions import FitParsingError
from TrainingAnalyticsPlatform.platform.exceptions import WorkoutIdCalculationError


def _build_activity(
    activity_id: str,
    start_time: str,
    duration: int,
    *,
    start_time_local: str | None = None,
) -> dict:
    return {
        "activityId": activity_id,
        "activityName": "Test Ride",
        "startTimeGMT": start_time,
        "startTimeLocal": start_time_local or start_time,
        "duration": duration,
        "distance": 25000,
        "activityType": {"typeKey": "cycling"},
    }


class TestGarminSyncIngestionHandler:
    """Targeted duplicate detection tests for Garmin ingestion."""

    def test_build_source_info_includes_local_and_utc_start_times(self):
        storage = MagicMock()
        handler = GarminSyncIngestionHandler(storage=storage, client=MagicMock())

        source_info = handler._build_source_info(  # pylint: disable=protected-access
            _build_activity(
                "a1",
                "2026-02-20T10:00:00+00:00",
                3600,
                start_time_local="2026-02-20T06:00:00",
            )
        )

        assert source_info["source_start_time_utc"] == "2026-02-20T10:00:00+00:00"
        assert source_info["source_start_time_local"] == "2026-02-20T06:00:00"

    def test_find_near_duplicate_workout_matches_by_time_and_duration(self):
        storage = MagicMock()
        storage.infrastructure = MagicMock()
        table_client = MagicMock()
        storage.infrastructure.get_table_client.return_value = table_client
        table_client.query_entities.return_value = [
            {
                "athlete_id": "rob",
                "workout_id": "existing-123",
                "start_time_utc": "2026-02-20T10:00:30+00:00",
                "duration_sec": 3605,
            }
        ]
        handler = GarminSyncIngestionHandler(storage=storage, client=MagicMock())

        workout_id = handler._find_near_duplicate_workout(  # pylint: disable=protected-access
            "rob",
            _build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert workout_id == "existing-123"

    def test_find_near_duplicate_workout_ignores_distant_duration(self):
        storage = MagicMock()
        storage.infrastructure = MagicMock()
        table_client = MagicMock()
        storage.infrastructure.get_table_client.return_value = table_client
        table_client.query_entities.return_value = [
            {
                "athlete_id": "rob",
                "workout_id": "existing-123",
                "start_time_utc": "2026-02-20T10:01:00+00:00",
                "duration_sec": 5000,
            }
        ]
        handler = GarminSyncIngestionHandler(storage=storage, client=MagicMock())

        workout_id = handler._find_near_duplicate_workout(  # pylint: disable=protected-access
            "rob",
            _build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert workout_id is None

    def test_find_near_duplicate_workout_handles_invalid_start(self):
        storage = MagicMock()
        handler = GarminSyncIngestionHandler(storage=storage, client=MagicMock())
        workout_id = handler._find_near_duplicate_workout(  # pylint: disable=protected-access
            "rob",
            _build_activity("a1", "not-a-date", 3600),
        )
        assert workout_id is None

    def test_handle_returns_error_code_on_ingestion_id_failure(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        client = MagicMock()
        handler = GarminSyncIngestionHandler(storage=storage, client=client)

        handler._build_source_info = MagicMock(return_value={})  # type: ignore[attr-defined]

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert status == 422
        assert body["error_code"] == "INGESTION_ID_RESOLUTION_FAILED"

    def test_handle_skips_unchanged_without_recording_ingestion_state(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        storage.workouts.get_ingestion_state.return_value = {
            "status": "ingested",
            "workout_id": "workout-1",
            "file_sha256": "hash",
        }

        client = MagicMock()
        client.download_activity_fit.return_value = b"fit-bytes"

        handler = GarminSyncIngestionHandler(storage=storage, client=client)
        handler._skip_if_unchanged = MagicMock(return_value=(True, "workout-1"))  # type: ignore[attr-defined]

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert status == 200
        assert body["status"] == "skipped"
        assert body["workout_id"] == "workout-1"
        storage.workouts.record_ingestion_state.assert_not_called()

    def test_handle_returns_error_code_on_workout_id_failure(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        context = MagicMock()
        context.should_skip.return_value = False
        context.existing_state = None
        context.ingestion_key = "a1"
        storage.workouts.get_ingestion_context.return_value = context

        client = MagicMock()
        client.download_activity_fit.return_value = b"fit-bytes"

        handler = GarminSyncIngestionHandler(storage=storage, client=client)
        handler._find_near_duplicate_workout = MagicMock(return_value=None)  # type: ignore[attr-defined]
        handler._parse_and_store = MagicMock(  # type: ignore[attr-defined]
            side_effect=WorkoutIdCalculationError("semantic id missing")
        )

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert status == 422
        assert body["error_code"] == "WORKOUT_ID_CALCULATION_FAILED"

    def test_handle_returns_error_code_on_fit_parsing_failure(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        context = MagicMock()
        context.should_skip.return_value = False
        context.existing_state = None
        context.ingestion_key = "a1"
        storage.workouts.get_ingestion_context.return_value = context

        client = MagicMock()
        client.download_activity_fit.return_value = b"fit-bytes"

        handler = GarminSyncIngestionHandler(storage=storage, client=client)
        handler._find_near_duplicate_workout = MagicMock(return_value=None)  # type: ignore[attr-defined]
        handler._parse_and_store = MagicMock(  # type: ignore[attr-defined]
            side_effect=FitParsingError("invalid fit bytes")
        )

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert status == 422
        assert body["error_code"] == "FIT_PARSING_FAILED"


class TestGarminSyncRequest:
    """Tests for Garmin sync request parsing."""

    def test_lookback_days_from_body(self):
        request = GarminSyncRequest({"lookback_days": "14"}, {})

        assert request.lookback_days == 14

    def test_lookback_days_from_query(self):
        request = GarminSyncRequest({}, {"lookback_days": "21"})

        assert request.lookback_days == 21

    def test_lookback_days_none_when_missing(self):
        request = GarminSyncRequest({}, {})

        assert request.lookback_days is None

    def test_lookback_days_invalid_value(self):
        request = GarminSyncRequest({"lookback_days": "invalid"}, {})

        assert request.lookback_days is None


class TestGarminSyncHandler:
    """Tests for Garmin sync response status mapping."""

    def test_handle_sync_returns_401_for_authentication_failures(self):
        storage = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
        )
        handler.sync = MagicMock(return_value={  # type: ignore[method-assign]
            "status": "error",
            "message": "Authentication failed: Garmin Connect rate limited this login attempt",
        })

        body, status = handler._handle_sync("rob", 30)  # pylint: disable=protected-access

        assert status == 401
        assert body["status"] == "error"

    def test_handle_sync_returns_500_for_non_auth_sync_errors(self):
        storage = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
        )
        handler.sync = MagicMock(return_value={  # type: ignore[method-assign]
            "status": "error",
            "message": "Failed to list activities: upstream service unavailable",
        })

        body, status = handler._handle_sync("rob", 30)  # pylint: disable=protected-access

        assert status == 500
        assert body["status"] == "error"
