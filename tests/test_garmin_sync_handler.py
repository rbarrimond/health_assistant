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
from TrainingAnalyticsPlatform.integrations.garmin_client import GarminConnectError


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

    def test_force_from_body_true(self):
        request = GarminSyncRequest({"force": "true"}, {})

        assert request.force is True

    def test_force_from_query_false(self):
        request = GarminSyncRequest({}, {"force": "false"})

        assert request.force is False


class TestGarminSyncHandler:
    """Tests for Garmin sync response status mapping."""

    def test_sync_skips_previously_seen_activity_ids_without_download(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        storage.workouts.get_ingestion_state.side_effect = [
            {"status": "ingested"},
            None,
        ]

        client = MagicMock()
        client.list_activities.return_value = [
            _build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
            _build_activity("a2", "2026-02-20T11:00:00+00:00", 3500),
        ]

        ingestion_handler = MagicMock()
        ingestion_handler.handle.return_value = (
            {"status": "success", "workout_id": "w2"},
            200,
        )

        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=client,
            ingestion_handler=ingestion_handler,
        )

        results = handler.sync(athlete_id="rob", lookback_days=30)

        assert results["status"] == "success"
        assert results["found"] == 2
        assert results["ingested"] == 1
        assert results["skipped"] == 1
        assert results["skipped_by_id"] == 1
        assert any(item["status"] == "skipped_seen_id" for item in results["items"])
        assert ingestion_handler.handle.call_count == 1

    def test_sync_force_true_bypasses_seen_id_skip(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        storage.workouts.get_ingestion_state.return_value = {"status": "ingested"}

        client = MagicMock()
        client.list_activities.return_value = [
            _build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
            _build_activity("a2", "2026-02-20T11:00:00+00:00", 3500),
        ]

        ingestion_handler = MagicMock()
        ingestion_handler.handle.side_effect = [
            ({"status": "success", "workout_id": "w1"}, 200),
            ({"status": "success", "workout_id": "w2"}, 200),
        ]

        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=client,
            ingestion_handler=ingestion_handler,
        )

        results = handler.sync(athlete_id="rob", lookback_days=30, force=True)

        assert results["status"] == "success"
        assert results["force"] is True
        assert results["ingested"] == 2
        assert results["skipped_by_id"] == 0
        assert ingestion_handler.handle.call_count == 2
        storage.workouts.get_ingestion_state.assert_not_called()

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


class TestGarminSyncHandlerTokenLifecycle:
    """Token restore / save lifecycle in GarminSyncHandler.sync()."""

    def _make_handler(
        self, storage: MagicMock, client: MagicMock
    ) -> GarminSyncHandler:
        config = GarminSyncConfig(
            email="user@example.com", password="x" * 12, lookback_days=7
        )
        return GarminSyncHandler(config=config, storage=storage, client=client)

    def test_sync_restores_session_from_stored_token_and_skips_login(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_tokens.return_value = "stored-garth-token"
        client = MagicMock()
        client.list_activities.return_value = []
        client.dump_tokens.return_value = "refreshed-garth-token"

        handler = self._make_handler(storage, client)
        result = handler.sync(athlete_id="rob", lookback_days=7)

        client.restore_from_tokens.assert_called_once_with("stored-garth-token")
        client.login.assert_not_called()
        storage.oauth_tokens.store_garmin_tokens.assert_called_once_with(
            "rob", "refreshed-garth-token"
        )
        assert result["status"] == "success"

    def test_sync_falls_back_to_login_when_no_stored_token(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_tokens.return_value = None
        client = MagicMock()
        client.list_activities.return_value = []
        client.dump_tokens.return_value = "fresh-garth-token"

        handler = self._make_handler(storage, client)
        result = handler.sync(athlete_id="rob", lookback_days=7)

        client.restore_from_tokens.assert_not_called()
        client.login.assert_called_once()
        storage.oauth_tokens.store_garmin_tokens.assert_called_once_with(
            "rob", "fresh-garth-token"
        )
        assert result["status"] == "success"

    def test_sync_falls_back_to_login_on_stale_token(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_tokens.return_value = "expired-token"
        client = MagicMock()
        client.restore_from_tokens.side_effect = GarminConnectError("token expired")
        client.list_activities.return_value = []
        client.dump_tokens.return_value = "fresh-garth-token"

        handler = self._make_handler(storage, client)
        result = handler.sync(athlete_id="rob", lookback_days=7)

        client.restore_from_tokens.assert_called_once_with("expired-token")
        client.login.assert_called_once()
        storage.oauth_tokens.store_garmin_tokens.assert_called_once_with(
            "rob", "fresh-garth-token"
        )
        assert result["status"] == "success"
