"""Tests for Garmin sync request parsing and ingestion handler."""

# pylint: disable=protected-access

import pytest
from unittest.mock import MagicMock, patch

from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import (
    GarminSyncConfig,
    GarminSyncHandler,
    GarminSyncIngestionHandler,
    GarminSyncRequest,
)
from TrainingAnalyticsPlatform.platform.exceptions import FitParsingError
from TrainingAnalyticsPlatform.platform.exceptions import WorkoutIdCalculationError
from TrainingAnalyticsPlatform.platform.exceptions import ConfigError
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.integrations.garmin_client import GarminConnectError
from TrainingAnalyticsPlatform.integrations.garmin_client import GarminConnectRateLimitError


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

    def test_handle_uses_normalized_alias_activity_id_for_download(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        client = MagicMock()
        client.download_activity_fit.return_value = b"fit-bytes"
        handler = GarminSyncIngestionHandler(storage=storage, client=client)
        handler._skip_if_unchanged = MagicMock(return_value=(True, "workout-1"))  # type: ignore[attr-defined]

        body, status = handler.handle(
            athlete_id="rob",
            activity={
                "activity_id": "alias-42",
                "activity_name": "Alias Activity",
                "activityTypeDTO": {"typeKey": "walking"},
                "startTimeGmt": "2026-02-20T10:00:00+00:00",
                "durationInSeconds": 1800,
            },
        )

        assert status == 200
        assert body["status"] == "skipped"
        client.download_activity_fit.assert_called_once_with("alias-42")

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

    def test_build_source_info_uses_alias_fields_when_primary_keys_missing(self):
        storage = MagicMock()
        handler = GarminSyncIngestionHandler(storage=storage, client=MagicMock())

        source_info = handler._build_source_info(  # pylint: disable=protected-access
            {
                "activity_id": "alias-1",
                "activity_name": "Alias Activity",
                "activityTypeDTO": {"typeKey": "virtual_ride"},
                "startTimeGmt": "2026-02-20T10:00:00+00:00",
                "startTimeGmtLocal": "2026-02-20T06:00:00",
                "durationInSeconds": 3599,
                "distanceMeters": 24500,
                "avgHR": 142,
                "maximumHR": 179,
                "calories": 610,
            }
        )

        assert source_info["source_item_id"] == "alias-1"
        assert source_info["source_activity_name"] == "Alias Activity"
        assert source_info["source_activity_type"] == "virtual_ride"
        assert source_info["source_start_time_utc"] == "2026-02-20T10:00:00+00:00"
        assert source_info["source_start_time_local"] == "2026-02-20T06:00:00"
        assert source_info["source_duration_sec"] == 3599
        assert source_info["source_distance_meters"] == 24500
        assert source_info["source_average_hr_bpm"] == 142
        assert source_info["source_max_hr_bpm"] == 179
        assert source_info["source_calories"] == 610

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

    def test_find_near_duplicate_workout_accepts_time_and_duration_aliases(self):
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
            {
                "activityId": "a1",
                "startTimeGmt": "2026-02-20T10:00:00+00:00",
                "durationInSeconds": 3600,
            },
        )

        assert workout_id == "existing-123"


class TestGarminSyncConfig:
    def test_from_env_raises_config_error_when_credentials_missing(self, monkeypatch):
        monkeypatch.delenv("GARMIN_EMAIL", raising=False)
        monkeypatch.delenv("GARMIN_PASSWORD", raising=False)

        with pytest.raises(ConfigError, match="Missing Garmin credentials"):
            GarminSyncConfig.from_env()

    def test_from_env_defaults_lookback_to_30_when_invalid(self, monkeypatch):
        monkeypatch.setenv("GARMIN_EMAIL", "user@example.com")
        monkeypatch.setenv("GARMIN_PASSWORD", "secret")
        monkeypatch.setenv("GARMIN_SYNC_LOOKBACK_DAYS", "not-a-number")

        config = GarminSyncConfig.from_env()

        assert config.lookback_days == 30

    def test_from_env_reads_activity_request_delay(self, monkeypatch):
        monkeypatch.setenv("GARMIN_EMAIL", "user@example.com")
        monkeypatch.setenv("GARMIN_PASSWORD", "secret")
        monkeypatch.setenv("GARMIN_ACTIVITY_REQUEST_DELAY_SEC", "1.5")

        config = GarminSyncConfig.from_env()

        assert config.activity_request_delay_sec == pytest.approx(1.5)

    def test_from_env_reads_activity_index_window_and_freshness(self, monkeypatch):
        monkeypatch.setenv("GARMIN_EMAIL", "user@example.com")
        monkeypatch.setenv("GARMIN_PASSWORD", "secret")
        monkeypatch.setenv("GARMIN_ACTIVITY_INDEX_ROLLING_WINDOW_DAYS", "2")
        monkeypatch.setenv("GARMIN_ACTIVITY_INDEX_FRESHNESS_HOURS", "12")

        config = GarminSyncConfig.from_env()

        assert config.activity_index_rolling_window_days == 2
        assert config.activity_index_freshness_hours == 12

    def test_from_env_defaults_activity_index_window_and_freshness_on_invalid(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("GARMIN_EMAIL", "user@example.com")
        monkeypatch.setenv("GARMIN_PASSWORD", "secret")
        monkeypatch.setenv("GARMIN_ACTIVITY_INDEX_ROLLING_WINDOW_DAYS", "invalid")
        monkeypatch.setenv("GARMIN_ACTIVITY_INDEX_FRESHNESS_HOURS", "invalid")

        config = GarminSyncConfig.from_env()

        assert config.activity_index_rolling_window_days == 3
        assert config.activity_index_freshness_hours == 24

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

    def test_handle_force_true_bypasses_unchanged_skip(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        context = MagicMock()
        context.should_skip.return_value = True
        context.existing_state = {"workout_id": "existing-workout"}
        context.ingestion_key = "a1"
        storage.workouts.get_ingestion_context.return_value = context

        client = MagicMock()
        client.download_activity_fit.return_value = b"fit-bytes"

        handler = GarminSyncIngestionHandler(storage=storage, client=client)
        handler._find_near_duplicate_workout = MagicMock(return_value=None)  # type: ignore[attr-defined]
        handler._parse_and_store = MagicMock(return_value=({}, "new-workout"))  # type: ignore[attr-defined]

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
            force=True,
        )

        assert status == 200
        assert body["status"] == "success"
        assert body["workout_id"] == "new-workout"
        handler._parse_and_store.assert_called_once()

    def test_handle_force_true_bypasses_duplicate_skip(self):
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
        handler._find_near_duplicate_workout = MagicMock(return_value="existing-workout")  # type: ignore[attr-defined]
        handler._parse_and_store = MagicMock(return_value=({}, "new-workout"))  # type: ignore[attr-defined]

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
            force=True,
        )

        assert status == 200
        assert body["status"] == "success"
        assert body["workout_id"] == "new-workout"
        handler._parse_and_store.assert_called_once()
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

    def test_handle_pre_filters_disallowed_manufacturer_before_fit_download(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        client = MagicMock()
        handler = GarminSyncIngestionHandler(storage=storage, client=client)

        # Inject source_info with a clearly disallowed manufacturer code (255 = development)
        handler._build_source_info = MagicMock(return_value={  # type: ignore[attr-defined]
            "source_system": "Garmin",
            "source_item_id": "a1",
            "source_file_name": "a1.fit",
            "source_file_path": "/garmin/a1.fit",
            "source_manufacturer": "DEVELOPMENT",
            "source_manufacturer_code": 255,
        })

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert status == 400
        assert body["status"] == "filtered"
        assert body["error_code"] == "DEVICE_FILTERED"
        assert body["manufacturer_code"] == 255
        client.download_activity_fit.assert_not_called()
        storage.workouts.record_ingestion_state.assert_called_once()

    def test_handle_allowlisted_manufacturer_proceeds_to_fit_download(self):
        storage = MagicMock()
        storage.workouts = MagicMock()
        client = MagicMock()
        client.download_activity_fit.return_value = b"fit-bytes"
        handler = GarminSyncIngestionHandler(storage=storage, client=client)

        # Inject source_info with an allowlisted manufacturer code (1 = Garmin)
        handler._build_source_info = MagicMock(return_value={  # type: ignore[attr-defined]
            "source_system": "Garmin",
            "source_item_id": "a1",
            "source_file_name": "a1.fit",
            "source_file_path": "/garmin/a1.fit",
            "source_manufacturer": "GARMIN",
            "source_manufacturer_code": 1,
        })
        handler._skip_if_unchanged = MagicMock(return_value=(True, "workout-1"))  # type: ignore[attr-defined]

        body, status = handler.handle(
            athlete_id="rob",
            activity=_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
        )

        assert status == 200
        client.download_activity_fit.assert_called_once_with("a1")


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

    def test_lookback_days_preserves_explicit_zero(self):
        request = GarminSyncRequest({"lookback_days": "0"}, {})

        assert request.lookback_days == 0

    def test_lookback_days_body_takes_precedence_over_query(self):
        request = GarminSyncRequest(
            {"lookback_days": "0"},
            {"lookback_days": "7"},
        )

        assert request.lookback_days == 0

    def test_lookback_days_invalid_value(self):
        request = GarminSyncRequest({"lookback_days": "invalid"}, {})

        assert request.lookback_days is None

    def test_force_from_body_true(self):
        request = GarminSyncRequest({"force": "true"}, {})

        assert request.force is True

    def test_force_from_query_false(self):
        request = GarminSyncRequest({}, {"force": "false"})

        assert request.force is False

    def test_request_id_from_body(self):
        request = GarminSyncRequest({"request_id": "req-123"}, {})

        assert request.request_id == "req-123"

    def test_correlation_id_from_query(self):
        request = GarminSyncRequest({}, {"correlation_id": "corr-456"})

        assert request.correlation_id == "corr-456"

    def test_request_and_correlation_id_none_when_missing(self):
        request = GarminSyncRequest({}, {})

        assert request.request_id is None
        assert request.correlation_id is None


class TestGarminSyncHandler:
    """Tests for Garmin sync response status mapping."""

    def test_handle_returns_400_for_negative_lookback(self):
        storage = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
        )

        response, status = handler.handle(
            GarminSyncRequest(
                {
                    "athlete_id": "rob",
                    "lookback_days": -1,
                },
                {},
            )
        )

        assert status == 400
        assert response["error"] == "lookback_days must be a non-negative integer"

    def test_handle_preserves_explicit_zero_lookback(self):
        storage = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
        )
        handler._handle_sync = MagicMock(return_value=({"status": "ok"}, 200))  # type: ignore[method-assign]

        response, status = handler.handle(
            GarminSyncRequest(
                {
                    "athlete_id": "rob",
                    "lookback_days": 0,
                },
                {},
            )
        )

        assert status == 200
        assert response["status"] == "ok"
        handler._handle_sync.assert_called_once_with("rob", 0, False)

    def test_handle_async_thread_returns_operation_metadata(self):
        storage = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
        )
        handler.sync = MagicMock(return_value={"status": "success"})  # type: ignore[method-assign]

        response, status = handler.handle(
            GarminSyncRequest(
                {
                    "athlete_id": "rob",
                    "lookback_days": 7,
                    "async": True,
                },
                {},
            )
        )

        assert status == 202
        assert response["status"] == "queued"
        assert response["mode"] == "async_thread"
        assert response["operation_id"]
        assert response["queued_at_utc"]
        storage.async_operations.upsert_state.assert_called_once()

    def test_handle_async_queue_enqueues_work_item(self):
        storage = MagicMock()
        async_queue = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
            async_queue=async_queue,
        )
        handler.sync = MagicMock(return_value={"status": "success"})  # type: ignore[method-assign]

        response, status = handler.handle(
            GarminSyncRequest(
                {
                    "athlete_id": "rob",
                    "lookback_days": 7,
                    "force": True,
                    "async": True,
                },
                {},
            )
        )

        assert status == 202
        assert response["status"] == "queued"
        assert response["mode"] == "async_queue"
        assert response["operation_id"]
        handler.sync.assert_not_called()
        async_queue.enqueue.assert_called_once()
        storage.async_operations.upsert_state.assert_called_once()
        enqueued_item = async_queue.enqueue.call_args.kwargs["item"]
        assert enqueued_item.source == "garmin"
        assert enqueued_item.athlete_id == "rob"
        assert enqueued_item.lookback_days == 7
        assert enqueued_item.context["force"] is True

    def test_handle_async_queue_propagates_trace_ids(self):
        storage = MagicMock()
        async_queue = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
            async_queue=async_queue,
        )
        handler.sync = MagicMock(return_value={"status": "success"})  # type: ignore[method-assign]

        response, status = handler.handle(
            GarminSyncRequest(
                {
                    "athlete_id": "rob",
                    "lookback_days": 7,
                    "force": True,
                    "async": True,
                    "request_id": "req-async-1",
                    "correlation_id": "corr-async-1",
                },
                {},
            )
        )

        assert status == 202
        assert response["status"] == "queued"
        enqueued_item = async_queue.enqueue.call_args.kwargs["item"]
        assert enqueued_item.request_id == "req-async-1"
        assert enqueued_item.correlation_id == "corr-async-1"
        upserted_state = storage.async_operations.upsert_state.call_args.args[0]
        assert upserted_state.request_id == "req-async-1"
        assert upserted_state.correlation_id == "corr-async-1"

    def test_sync_skips_previously_seen_activity_ids_without_download(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
        for call in ingestion_handler.handle.call_args_list:
            assert call.kwargs["force"] is True
        storage.workouts.get_ingestion_state.assert_not_called()

    def test_sync_applies_delay_between_successful_ingestions(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
        storage.workouts = MagicMock()
        storage.workouts.get_ingestion_state.return_value = None

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
            config=GarminSyncConfig(
                email="user@example.com",
                password="x" * 12,
                lookback_days=30,
                activity_request_delay_sec=0.25,
            ),
            storage=storage,
            client=client,
            ingestion_handler=ingestion_handler,
        )

        with patch("TrainingAnalyticsPlatform.handlers.garmin_sync_handler.time.sleep") as sleep_mock:
            results = handler.sync(athlete_id="rob", lookback_days=30)

        assert results["status"] == "success"
        assert results["ingested"] == 2
        sleep_mock.assert_called_once_with(0.25)

    def test_handle_sync_returns_429_for_rate_limited_authentication_failures(self):
        storage = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
        )
        handler.sync = MagicMock(return_value={  # type: ignore[method-assign]
            "status": "error",
            "message": "Authentication failed: Garmin Connect rate limited this login attempt",
            "error_code": "GARMIN_RATE_LIMITED",
        })

        body, status = handler._handle_sync("rob", 30)  # pylint: disable=protected-access

        assert status == 429
        assert body["status"] == "error"

    def test_handle_sync_returns_401_for_non_throttle_authentication_failures(self):
        storage = MagicMock()
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=MagicMock(),
        )
        handler.sync = MagicMock(return_value={  # type: ignore[method-assign]
            "status": "error",
            "message": "Authentication failed: Authentication failed - check credentials",
            "error_code": "GARMIN_AUTH_ERROR",
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

    def test_handle_sync_returns_429_when_list_activities_is_rate_limited(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
        client = MagicMock()
        client.rate_limited_until = None
        client.list_activities.side_effect = GarminConnectRateLimitError(
            "Garmin Connect rate limited the activity list request"
        )
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=30),
            storage=storage,
            client=client,
        )

        body, status = handler._handle_sync("rob", 30)  # pylint: disable=protected-access

        assert status == 429
        assert body["status"] == "error"
        assert body.get("error_code") == "GARMIN_RATE_LIMITED"

    def test_sync_persists_rate_limit_cooldown_when_list_activities_rate_limited(self):
        from datetime import timezone
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
        storage.oauth_tokens.get_garmin_tokens.return_value = None
        blocked_until = MagicMock()
        client = MagicMock()
        client.rate_limited_until = blocked_until
        client.list_activities.side_effect = GarminConnectRateLimitError(
            "Garmin Connect rate limited the activity list request"
        )
        handler = GarminSyncHandler(
            config=GarminSyncConfig(email="user@example.com", password="x" * 12, lookback_days=7),
            storage=storage,
            client=client,
        )

        result = handler.sync(athlete_id="rob", lookback_days=7)

        assert result["status"] == "error"
        assert result.get("error_code") == "GARMIN_RATE_LIMITED"
        storage.oauth_tokens.set_garmin_rate_limit_blocked_until.assert_called_once_with(
            "rob", blocked_until
        )


class TestGarminSyncHandlerTokenLifecycle:
    """Token restore / save lifecycle in GarminSyncHandler.sync()."""

    def _make_handler(
        self, storage: MagicMock, client: MagicMock
    ) -> GarminSyncHandler:
        config = GarminSyncConfig(
            email="user@example.com", password="x" * 12, lookback_days=7
        )
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
        return GarminSyncHandler(config=config, storage=storage, client=client)

    def test_sync_restores_session_from_stored_token_and_skips_login(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_tokens.return_value = "stored-garth-token"
        client = MagicMock()
        client.list_activities.return_value = []
        client.dump_tokens.return_value = "refreshed-garth-token"

        handler = self._make_handler(storage, client)
        result = handler.sync(athlete_id="rob", lookback_days=7)

        client.authenticate.assert_called_once_with("stored-garth-token")
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

        client.authenticate.assert_called_once_with(None)
        storage.oauth_tokens.store_garmin_tokens.assert_called_once_with(
            "rob", "fresh-garth-token"
        )
        assert result["status"] == "success"

    def test_sync_falls_back_to_login_on_stale_token(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_tokens.return_value = "expired-token"
        client = MagicMock()
        client.list_activities.return_value = []
        client.dump_tokens.return_value = "fresh-garth-token"

        handler = self._make_handler(storage, client)
        result = handler.sync(athlete_id="rob", lookback_days=7)

        # Handler passes the stored token to authenticate(); the fallback logic
        # (restore → login) is the responsibility of GarminConnectClient.authenticate()
        # and is covered by test_garmin_client.py.
        client.authenticate.assert_called_once_with("expired-token")
        storage.oauth_tokens.store_garmin_tokens.assert_called_once_with(
            "rob", "fresh-garth-token"
        )
        assert result["status"] == "success"


class TestGarminSyncHandlerCacheFirstSelection:
    """Cache-first activity selection behavior (Phase 3)."""

    def test_sync_merges_recent_and_cached_candidates_by_activity_id(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
        storage.oauth_tokens.get_garmin_tokens.return_value = None
        storage.workouts.get_ingestion_state.return_value = None
        storage.garmin_activity_index.query_activity_payloads_by_lookback.return_value = [
            _build_activity("a2", "2026-02-20T11:00:00+00:00", 3500),
            _build_activity("a3", "2026-02-20T12:00:00+00:00", 3400),
        ]
        storage.garmin_activity_index.get_indexed_day_coverage.return_value = {
            "2026-02-20"
        }

        client = MagicMock()
        client.list_activities.return_value = [
            _build_activity("a1", "2026-02-20T10:00:00+00:00", 3600),
            _build_activity("a2", "2026-02-20T11:00:00+00:00", 3500),
        ]
        client.dump_tokens.return_value = "new-token"

        ingestion_handler = MagicMock()
        ingestion_handler.handle.side_effect = [
            ({"status": "success", "workout_id": "w1"}, 200),
            ({"status": "success", "workout_id": "w2"}, 200),
            ({"status": "success", "workout_id": "w3"}, 200),
        ]

        handler = GarminSyncHandler(
            config=GarminSyncConfig(
                email="user@example.com",
                password="x" * 12,
                lookback_days=30,
                activity_index_rolling_window_days=3,
            ),
            storage=storage,
            client=client,
            ingestion_handler=ingestion_handler,
        )

        result = handler.sync(athlete_id="rob", lookback_days=1)

        assert result["status"] == "success"
        assert result["found"] == 3
        assert result["ingested"] == 3
        assert result["list_calls_made"] == 1
        assert storage.garmin_activity_index.upsert_activity_payload.call_count >= 2

    def test_sync_falls_back_to_direct_listing_when_index_query_fails(self):
        storage = MagicMock()
        storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
        storage.oauth_tokens.get_garmin_tokens.return_value = None
        storage.workouts.get_ingestion_state.return_value = None
        storage.garmin_activity_index.query_activity_payloads_by_lookback.side_effect = (
            StorageError("index unavailable")
        )

        client = MagicMock()
        client.list_activities.side_effect = [
            [_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600)],
            [_build_activity("a1", "2026-02-20T10:00:00+00:00", 3600), _build_activity("a2", "2026-02-20T11:00:00+00:00", 3500)],
        ]
        client.dump_tokens.return_value = "new-token"

        ingestion_handler = MagicMock()
        ingestion_handler.handle.side_effect = [
            ({"status": "success", "workout_id": "w1"}, 200),
            ({"status": "success", "workout_id": "w2"}, 200),
        ]

        handler = GarminSyncHandler(
            config=GarminSyncConfig(
                email="user@example.com",
                password="x" * 12,
                lookback_days=30,
                activity_index_rolling_window_days=3,
            ),
            storage=storage,
            client=client,
            ingestion_handler=ingestion_handler,
        )

        result = handler.sync(athlete_id="rob", lookback_days=30)

        assert result["status"] == "success"
        assert result["found"] == 2
        assert result["list_calls_made"] == 2

