"""Tests for Garmin sync ingestion handler."""

# pylint: disable=protected-access

from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import GarminSyncIngestionHandler
from TrainingAnalyticsPlatform.platform.exceptions import FitParsingError
from TrainingAnalyticsPlatform.platform.exceptions import WorkoutIdCalculationError


def _build_activity(activity_id: str, start_time: str, duration: int) -> dict:
    return {
        "activityId": activity_id,
        "activityName": "Test Ride",
        "startTimeGMT": start_time,
        "duration": duration,
        "distance": 25000,
        "activityType": {"typeKey": "cycling"},
    }


class TestGarminSyncIngestionHandler:
    """Targeted duplicate detection tests for Garmin ingestion."""

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
