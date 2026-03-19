"""Tests for OneDriveSyncHandler."""

# pylint: disable=redefined-outer-name, protected-access

from datetime import datetime, timezone
import gzip
from unittest.mock import MagicMock
import time

import pytest

from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import (
    OneDriveSyncConfig,
    OneDriveSyncIngestionHandler,
    OneDriveResetRequest,
    OneDriveSyncHandler,
    OneDriveSyncRequest,
)
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.platform.exceptions import IngestionIdResolutionError
from TrainingAnalyticsPlatform.platform.exceptions import FitParsingError
from TrainingAnalyticsPlatform.platform.exceptions import WorkoutIdCalculationError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import IngestionContext


# Minimal valid FIT file for testing (header with .FIT signature)
VALID_FIT_HEADER = bytes([
    0x0E,  # Header size (14 bytes)
    0x10,  # Protocol version 1.0
    0x20, 0x00,  # Profile version (little-endian)
    0x00, 0x00, 0x00, 0x00,  # Data size (0 for minimal test)
    ord('.'), ord('F'), ord('I'), ord('T'),  # ".FIT" signature
    0x00, 0x00  # CRC
])
MINIMAL_FIT_FILE = VALID_FIT_HEADER + b'\x00' * 10


def _config(lookback_days: int = 30) -> OneDriveSyncConfig:
    return OneDriveSyncConfig(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        scopes="Files.ReadWrite offline_access",
        folder_path="/Apps/HealthFit",
        lookback_days=lookback_days,
    )


@pytest.fixture
def handler():
    """Create OneDriveSyncHandler instance."""
    return OneDriveSyncHandler(
        _config(),
        MagicMock(),
        client=MagicMock(),
        ingestion_handler=MagicMock(),
    )


class TestOneDriveSyncRequest:
    """Test OneDriveSyncRequest parsing."""

    def test_athlete_id_from_body(self):
        """Test athlete_id extracted from body."""
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, {})
        assert req.athlete_id == "athlete1"

    def test_athlete_id_from_query(self):
        """Test athlete_id extracted from query params."""
        req = OneDriveSyncRequest({}, {"athlete_id": "athlete2"})
        assert req.athlete_id == "athlete2"

    def test_athlete_id_default(self):
        """Test athlete_id defaults to 'rob'."""
        req = OneDriveSyncRequest({}, {})
        assert req.athlete_id == "rob"

    def test_athlete_id_body_takes_precedence(self):
        """Test body athlete_id takes precedence over query."""
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1"}, {"athlete_id": "athlete2"}
        )
        assert req.athlete_id == "athlete1"

    def test_lookback_days_from_body(self):
        """Test lookback_days extracted from body."""
        req = OneDriveSyncRequest({"days": "14"}, {})
        assert req.lookback_days == 14

    def test_lookback_days_from_query(self):
        """Test lookback_days extracted from query params."""
        req = OneDriveSyncRequest({}, {"days": "21"})
        assert req.lookback_days == 21

    def test_lookback_days_none_when_missing(self):
        """Test lookback_days is None when not provided."""
        req = OneDriveSyncRequest({}, {})
        assert req.lookback_days is None

    def test_lookback_days_invalid_value(self):
        """Test lookback_days returns None for invalid values."""
        req = OneDriveSyncRequest({"days": "invalid"}, {})
        assert req.lookback_days is None

    def test_async_mode_from_body_true(self):
        """Test async flag extracted from body."""
        for value in ["1", "true", "True", "TRUE", "yes", "YES", "y", "Y"]:
            req = OneDriveSyncRequest({"async": value}, {})
            assert req.async_mode is True, f"Failed for async={value}"

    def test_async_mode_from_query(self):
        """Test async flag extracted from query params."""
        req = OneDriveSyncRequest({}, {"async": "true"})
        assert req.async_mode is True

    def test_async_mode_default_false(self):
        """Test async defaults to False."""
        req = OneDriveSyncRequest({}, {})
        assert req.async_mode is False

    def test_async_mode_false_values(self):
        """Test async flag with false-like values."""
        for value in ["0", "false", "False", "no", "n", ""]:
            req = OneDriveSyncRequest({"async": value}, {})
            assert req.async_mode is False, f"Failed for async={value}"


class TestOneDriveResetRequest:
    """Test OneDriveResetRequest parsing."""

    def test_athlete_id_from_body(self):
        req = OneDriveResetRequest({"athlete_id": "athlete1"}, {})
        assert req.athlete_id == "athlete1"

    def test_athlete_id_none_when_missing(self):
        req = OneDriveResetRequest({}, {})
        assert req.athlete_id is None

    def test_athlete_id_strips_whitespace(self):
        req = OneDriveResetRequest({"athlete_id": "  rob  "}, {})
        assert req.athlete_id == "rob"

    def test_reset_all_true_values(self):
        for value in ["1", "true", "True", "yes", "y"]:
            req = OneDriveResetRequest({"all": value}, {})
            assert req.reset_all is True

    def test_reset_all_false_when_missing(self):
        req = OneDriveResetRequest({}, {})
        assert req.reset_all is False


class TestOneDriveSyncHandler:
    """Test OneDriveSyncHandler sync execution."""

    def test_handle_sync_success(self, handler):
        """Test successful synchronous sync."""
        # Arrange
        expected_result = {"files_processed": 5, "errors": 0}
        handler.sync = MagicMock(return_value=expected_result)
        req = OneDriveSyncRequest({"athlete_id": "athlete1", "days": "14"}, {})

        # Act
        result, status = handler.handle(req)

        # Assert
        assert status == 200
        assert result == expected_result
        handler.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=14)

    def test_handle_sync_uses_default_lookback_days(self):
        """Test sync uses default lookback days from config."""
        # Arrange
        handler = OneDriveSyncHandler(
            _config(lookback_days=45),
            MagicMock(),
            client=MagicMock(),
            ingestion_handler=MagicMock(),
        )
        handler.sync = MagicMock(return_value={"files_processed": 2})
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, {})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        handler.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=45)

    def test_handle_sync_validation_error(self, handler):
        """Test sync returns 400 for validation errors."""
        # Arrange
        handler.sync = MagicMock(side_effect=ValueError("Invalid athlete_id"))
        req = OneDriveSyncRequest({"athlete_id": ""}, {})

        # Act
        error_resp, status = handler.handle(req)

        # Assert
        assert status == 400
        assert "error" in error_resp
        assert "Invalid athlete_id" in error_resp["error"]

    def test_handle_sync_exception(self, handler):
        """Test sync returns 500 for unexpected errors."""
        # Arrange
        handler.sync = MagicMock(side_effect=Exception("OneDrive API error"))
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, {})

        # Act
        error_resp, status = handler.handle(req)

        # Assert
        assert status == 500
        assert "error" in error_resp

    def test_handle_async_queued(self, handler):
        """Test asynchronous sync returns 202 immediately."""
        # Arrange
        handler.sync = MagicMock(return_value={"files_processed": 0})
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "days": "14", "async": "true"}, {}
        )

        # Act
        start_time = datetime.now(timezone.utc)
        result, status = handler.handle(req)
        end_time = datetime.now(timezone.utc)

        # Assert
        assert status == 202
        assert result["status"] == "queued"
        assert result["athlete_id"] == "athlete1"
        assert result["lookback_days"] == 14
        assert result["mode"] == "async_thread"
        assert result["operation_id"]

        # Verify queued_at is within expected time range
        queued_time = datetime.fromisoformat(result["queued_at_utc"])
        assert start_time <= queued_time <= end_time

    def test_handle_async_runs_in_background(self, handler):
        """Test async sync runs in background thread."""
        # Arrange
        handler.sync = MagicMock(return_value={"files_processed": 3})
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "days": "7", "async": "true"}, {}
        )

        # Act
        _, status = handler.handle(req)

        # Assert - immediate response
        assert status == 202

        # Verify async flag
        assert _["status"] == "queued"
        time.sleep(0.1)

        # Verify service.sync was called in background
        handler.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=7)

    def test_handle_async_exception_logged(self, handler):
        """Test async sync exceptions are logged but don't affect response."""
        # Arrange
        handler.sync = MagicMock(side_effect=Exception("Sync error"))
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "async": "true"}, {}
        )

        # Act
        _, status = handler.handle(req)

        # Assert - response is successful 202
        assert status == 202
        assert _["status"] == "queued"

        # Wait for background thread
        time.sleep(0.1)

        # Verify sync was attempted
        handler.sync.assert_called_once()

    def test_handle_async_default_lookback_days(self):
        """Test async sync uses default lookback days from config."""
        # Arrange
        handler = OneDriveSyncHandler(
            _config(lookback_days=60),
            MagicMock(),
            client=MagicMock(),
            ingestion_handler=MagicMock(),
        )
        handler.sync = MagicMock(return_value={})
        req = OneDriveSyncRequest({"athlete_id": "athlete1", "async": "true"}, {})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 202
        assert _["lookback_days"] == 60

        # Wait for background thread
        time.sleep(0.1)

        handler.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=60)

    def test_handle_async_queues_when_async_queue_configured(self):
        """Test async mode enqueues OneDrive work item when queue integration is provided."""
        async_queue = MagicMock()
        storage = MagicMock()
        handler = OneDriveSyncHandler(
            _config(lookback_days=30),
            storage,
            client=MagicMock(),
            ingestion_handler=MagicMock(),
            async_queue=async_queue,
        )
        handler.sync = MagicMock()
        req = OneDriveSyncRequest({"athlete_id": "athlete1", "days": "10", "async": "true"}, {})

        result, status = handler.handle(req)

        assert status == 202
        assert result["status"] == "queued"
        assert result["mode"] == "async_queue"
        assert result["athlete_id"] == "athlete1"
        assert result["lookback_days"] == 10
        assert result["operation_id"]
        async_queue.enqueue.assert_called_once()
        storage.async_operations.upsert_state.assert_called_once()
        handler.sync.assert_not_called()

    def test_handle_reset_single_success(self, handler):
        handler._storage.oauth_tokens.reset_onedrive_delta_state.return_value = True
        req = OneDriveResetRequest({"athlete_id": "rob"}, {})

        body, status = handler.handle_reset(req)

        assert status == 200
        assert body["status"] == "success"
        assert body["scope"] == "single"
        assert body["athlete_id"] == "rob"
        assert body["reset_count"] == 1
        assert body["reset_applied"] is True
        handler._storage.oauth_tokens.reset_onedrive_delta_state.assert_called_once_with("rob")

    def test_handle_reset_bulk_success(self, handler):
        handler._storage.oauth_tokens.reset_all_onedrive_delta_states.return_value = 3
        req = OneDriveResetRequest({"all": True}, {})

        body, status = handler.handle_reset(req)

        assert status == 200
        assert body["status"] == "success"
        assert body["scope"] == "bulk"
        assert body["reset_count"] == 3
        handler._storage.oauth_tokens.reset_all_onedrive_delta_states.assert_called_once_with()

    def test_handle_reset_missing_scope_validation(self, handler):
        req = OneDriveResetRequest({}, {})

        body, status = handler.handle_reset(req)

        assert status == 400
        assert "athlete_id" in body["error"]

    def test_handle_reset_typed_error(self, handler):
        handler._storage.oauth_tokens.reset_onedrive_delta_state.side_effect = StorageError("boom")
        req = OneDriveResetRequest({"athlete_id": "rob"}, {})

        body, status = handler.handle_reset(req)

        assert status == 500
        assert body["status"] == "error"
        assert body["error_code"] == "STORAGE_ERROR"


class TestOneDriveIngestionIdentity:
    """Test OneDrive ingestion identity requirements."""

    def test_handle_preserves_raw_source_file_name_when_preprocessing_changes_logical_name(self):
        """Verify source_file_name remains raw OneDrive item.name (.fit.gz) after preprocessing."""
        storage = MagicMock()
        storage.workouts = MagicMock()
        context = MagicMock()
        context.should_skip.return_value = False
        storage.workouts.get_ingestion_context.return_value = context

        client = MagicMock()
        client.download_file.return_value = gzip.compress(MINIMAL_FIT_FILE)

        handler = OneDriveSyncIngestionHandler(storage=storage, client=client)
        handler._parse_and_store = MagicMock(  # type: ignore[attr-defined]
            return_value=({}, "workout-1")
        )

        body, status = handler.handle(
            athlete_id="rob",
            access_token="token",
            item={
                "id": "item-1",
                "name": "2026-03-02-093346-Functional-Strength-Training-Robert's-Apple-Watch-7.fit.gz",
                "size": 1,
                "parentReference": {
                    "path": "/drive/root:/Apps/HealthFit",
                    "driveId": "drive-id",
                },
                "file": {"hashes": {}},
            },
            drive_id="drive-id",
        )

        assert status == 200
        assert body["status"] == "success"

        parse_call = handler._parse_and_store.call_args  # type: ignore[attr-defined]
        source_info = parse_call.args[1]
        assert source_info["source_file_name"].endswith(".fit.gz")
        assert source_info["source_logical_file_name"].endswith(".fit")

    def test_handle_skips_unchanged_without_recording_ingestion_state(self):
        """Already-ingested unchanged OneDrive FIT should short-circuit with debug-only behavior."""
        storage = MagicMock()
        storage.workouts = MagicMock()
        item = {
            "id": "item-1",
            "name": "2026-03-02-093346-Indoor Cycling-Apple Watch Ultra.fit",
            "size": 1,
            "lastModifiedDateTime": "2026-03-02T09:34:46Z",
            "eTag": "etag-1",
            "parentReference": {
                "path": "/drive/root:/Apps/HealthFit",
                "driveId": "drive-id",
            },
            "file": {"hashes": {}},
        }

        source_info = {
            "source_system": "OneDrive",
            "source_file_name": item["name"],
            "source_file_path": "/drive/root:/Apps/HealthFit/" + item["name"],
            "source_item_id": "onedrive:item-1",
            "source_drive_id": "drive-id",
            "source_etag": "etag-1",
            "source_ctag": None,
            "source_quickxor_hash": None,
            "source_modified_at_utc": "2026-03-02T09:34:46Z",
            "file_size_bytes": 1,
            "ingestion_id": "onedrive:item-1",
        }
        context = IngestionContext(
            athlete_id="rob",
            file_info=source_info,
            workout_id=None,
            storage=storage.workouts,
            ingestion_id="onedrive:item-1",
            ingestion_key="onedrive:item-1",
            existing_state={
                "status": "ingested",
                "workout_id": "workout-1",
                "source_etag": "etag-1",
            },
        )
        storage.workouts.get_ingestion_context.return_value = context

        handler = OneDriveSyncIngestionHandler(storage=storage, client=MagicMock())

        body, status = handler.handle(
            athlete_id="rob",
            access_token="token",
            item=item,
            drive_id="drive-id",
        )

        assert status == 200
        assert body["status"] == "skipped"
        assert body["workout_id"] == "workout-1"
        storage.workouts.record_ingestion_state.assert_not_called()

    def test_resolve_ingestion_id_uses_source_item_id(self):
        """Verify ingestion ID is extracted from source_item_id."""
        source_info = {"source_item_id": "onedrive:12345", "file_sha256": "abc"}

        assert (
            OneDriveSyncIngestionHandler._resolve_ingestion_id(source_info)
            == "onedrive:12345"
        )

    def test_resolve_ingestion_id_requires_source_item_id(self):
        """Verify ingestion ID resolution fails without source_item_id."""
        source_info = {"file_sha256": "abc"}

        with pytest.raises(
            IngestionIdResolutionError,
            match="OneDrive ingestion requires source_item_id",
        ):
            OneDriveSyncIngestionHandler._resolve_ingestion_id(source_info)

    def test_handle_returns_error_code_on_ingestion_id_failure(self):
        """Verify handler returns 422 with INGESTION_ID_RESOLUTION_FAILED on missing source_item_id."""
        storage = MagicMock()
        client = MagicMock()
        handler = OneDriveSyncIngestionHandler(storage=storage, client=client)

        with pytest.raises(IngestionIdResolutionError):
            OneDriveSyncIngestionHandler._resolve_ingestion_id({"file_sha256": "abc"})

        # Force source metadata missing source_item_id
        handler._build_source_info = MagicMock(return_value={})  # type: ignore[attr-defined]

        body, status = handler.handle(
            athlete_id="rob",
            access_token="token",
            item={"id": "item-1", "name": "workout.fit", "parentReference": {}},
            drive_id="drive-id",
        )

        assert status == 422
        assert body["error_code"] == "INGESTION_ID_RESOLUTION_FAILED"

    def test_handle_returns_error_code_on_workout_id_failure(self):
        """Verify handler returns 422 with WORKOUT_ID_CALCULATION_FAILED on ID calculation error."""
        storage = MagicMock()
        context = MagicMock()
        context.should_skip.return_value = False
        storage.get_ingestion_context.return_value = context

        client = MagicMock()
        # Use valid FIT bytes so preprocessing passes
        client.download_file.return_value = MINIMAL_FIT_FILE

        handler = OneDriveSyncIngestionHandler(storage=storage, client=client)
        handler._parse_and_store = MagicMock(  # type: ignore[attr-defined]
            side_effect=WorkoutIdCalculationError("semantic id missing")
        )

        body, status = handler.handle(
            athlete_id="rob",
            access_token="token",
            item={
                "id": "item-1",
                "name": "workout.fit",
                "size": 1,
                "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
            },
            drive_id="drive-id",
        )

        assert status == 422
        assert body["error_code"] == "WORKOUT_ID_CALCULATION_FAILED"

    def test_handle_returns_error_code_on_fit_parsing_failure(self):
        """Verify handler returns error code on FIT parsing failure."""
        storage = MagicMock()
        context = MagicMock()
        context.should_skip.return_value = False
        storage.get_ingestion_context.return_value = context

        client = MagicMock()
        # Use valid FIT bytes so preprocessing passes
        client.download_file.return_value = MINIMAL_FIT_FILE

        handler = OneDriveSyncIngestionHandler(storage=storage, client=client)
        handler._parse_and_store = MagicMock(  # type: ignore[attr-defined]
            side_effect=FitParsingError("invalid fit bytes")
        )

        body, status = handler.handle(
            athlete_id="rob",
            access_token="token",
            item={
                "id": "item-1",
                "name": "workout.fit",
                "size": 1,
                "parentReference": {
                    "path": "/drive/root:/Apps/HealthFit",
                    "driveId": "drive-id",
                },
            },
            drive_id="drive-id",
        )

        assert status == 422
        assert body["error_code"] == "FIT_PARSING_FAILED"

    def test_handle_sync_with_query_params(self, handler):
        """Test sync with query parameters."""
        # Arrange
        handler.sync = MagicMock(return_value={"files_processed": 1})
        req = OneDriveSyncRequest({}, {"athlete_id": "athlete2", "days": "28"})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        handler.sync.assert_called_once_with(athlete_id="athlete2", lookback_days=28)

    def test_handle_sync_body_overrides_query(self, handler):
        """Test body parameters override query parameters."""
        # Arrange
        handler.sync = MagicMock(return_value={})
        req = OneDriveSyncRequest(
            {"athlete_id": "athlete1", "days": "14"},
            {"athlete_id": "athlete2", "days": "7"},
        )

        # Act
        _, _ = handler.handle(req)

        # Assert
        handler.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=14)

    def test_handle_sync_none_body(self, handler):
        """Test handler works with None body."""
        # Arrange
        handler.sync = MagicMock(return_value={})
        req = OneDriveSyncRequest(None, {"athlete_id": "athlete1"})

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        handler.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=30)

    def test_handle_sync_none_query_params(self, handler):
        """Test handler works with None query params."""
        # Arrange
        handler.sync = MagicMock(return_value={})
        req = OneDriveSyncRequest({"athlete_id": "athlete1"}, None)

        # Act
        _, status = handler.handle(req)

        # Assert
        assert status == 200
        handler.sync.assert_called_once_with(athlete_id="athlete1", lookback_days=30)


class TestSyncStatus:
    """Test that sync status field correctly reflects results."""

    def test_sync_status_success_when_all_ingested(self, handler):
        """Test status='success' when all files ingested."""
        # Arrange: 3 files, all ingested
        handler._client.list_files_delta = MagicMock(return_value=([
            {"id": "1", "name": "file1.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "2", "name": "file2.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "3", "name": "file3.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
        ], "delta-link"))
        handler._ingestion_handler.handle = MagicMock(return_value=(
            {"status": "success", "workout_id": "w1"}, 200
        ))
        handler._storage.oauth_tokens = MagicMock()
        handler._storage.oauth_tokens.get_onedrive_tokens = MagicMock(return_value={
            "access_token": "token123",
            "drive_id": "drive1",
            "refresh_token": "refresh-123",
            "expires_at_utc": "2026-03-01T00:00:00+00:00",
        })

        # Act
        result = handler.sync(athlete_id="athlete1", lookback_days=30)

        # Assert
        assert result["status"] == "success"
        assert result["ingested"] == 3
        assert result["failed"] == 0

    def test_sync_status_failed_when_all_fail(self, handler):
        """Test status='failed' when all files fail."""
        # Arrange: 5 files, all failed
        handler._client.list_files_delta = MagicMock(return_value=([
            {"id": "1", "name": "f1.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "2", "name": "f2.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "3", "name": "f3.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "4", "name": "f4.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "5", "name": "f5.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
        ], "delta-link"))
        handler._ingestion_handler.handle = MagicMock(side_effect=Exception("Parse error"))
        handler._storage.oauth_tokens = MagicMock()
        handler._storage.oauth_tokens.get_onedrive_tokens = MagicMock(return_value={
            "access_token": "token123",
            "drive_id": "drive1",
            "refresh_token": "refresh-123",
            "expires_at_utc": "2026-03-01T00:00:00+00:00",
        })

        # Act
        result = handler.sync(athlete_id="athlete1", lookback_days=30)

        # Assert
        assert result["status"] == "failed"
        assert result["ingested"] == 0
        assert result["failed"] == 5

    def test_sync_status_partial_when_mixed_results(self, handler):
        """Test status='partial' when some succeed and some fail."""
        # Arrange: 5 files, 2 ingested, 1 skipped, 2 failed
        handler._client.list_files_delta = MagicMock(return_value=([
            {"id": "1", "name": "f1.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "2", "name": "f2.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "3", "name": "f3.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "4", "name": "f4.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "5", "name": "f5.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
        ], "delta-link"))
        # First 2 success, 3rd skipped, 4th-5th fail
        handler._ingestion_handler.handle = MagicMock(side_effect=[
            ({"status": "success", "workout_id": "w1"}, 200),
            ({"status": "success", "workout_id": "w2"}, 200),
            ({"status": "skipped", "workout_id": "w3"}, 200),
            Exception("Parse error"),
            Exception("Parse error"),
        ])
        handler._storage.oauth_tokens = MagicMock()
        handler._storage.oauth_tokens.get_onedrive_tokens = MagicMock(return_value={
            "access_token": "token123",
            "drive_id": "drive1",
            "refresh_token": "refresh-123",
            "expires_at_utc": "2026-03-01T00:00:00+00:00",
        })

        # Act
        result = handler.sync(athlete_id="athlete1", lookback_days=30)

        # Assert
        assert result["status"] == "partial"
        assert result["ingested"] == 2
        assert result["skipped"] == 1
        assert result["failed"] == 2

    def test_sync_status_skipped_when_none_ingested(self, handler):
        """Test status='skipped' when no files ingested but none failed."""
        # Arrange: 3 files, all skipped
        handler._client.list_files_delta = MagicMock(return_value=([
            {"id": "1", "name": "f1.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "2", "name": "f2.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "3", "name": "f3.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
        ], "delta-link"))
        handler._ingestion_handler.handle = MagicMock(return_value=(
            {"status": "skipped", "workout_id": None}, 200
        ))
        handler._storage.oauth_tokens = MagicMock()
        handler._storage.oauth_tokens.get_onedrive_tokens = MagicMock(return_value={
            "access_token": "token123",
            "drive_id": "drive1",
            "refresh_token": "refresh-123",
            "expires_at_utc": "2026-03-01T00:00:00+00:00",
        })

        # Act
        result = handler.sync(athlete_id="athlete1", lookback_days=30)

        # Assert
        assert result["status"] == "skipped"
        assert result["ingested"] == 0
        assert result["skipped"] == 3
        assert result["failed"] == 0

    def test_sync_status_partial_with_only_skipped_and_failed(self, handler):
        """Test status='partial' when some skipped and some failed."""
        # Arrange: 4 files, 2 skipped, 2 failed
        handler._client.list_files_delta = MagicMock(return_value=([
            {"id": "1", "name": "f1.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "2", "name": "f2.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "3", "name": "f3.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
            {"id": "4", "name": "f4.fit", "lastModifiedDateTime": "2026-02-18T00:00:00Z"},
        ], "delta-link"))
        handler._ingestion_handler.handle = MagicMock(side_effect=[
            ({"status": "skipped"}, 200),
            ({"status": "skipped"}, 200),
            Exception("Parse error"),
            Exception("Parse error"),
        ])
        handler._storage.oauth_tokens = MagicMock()
        handler._storage.oauth_tokens.get_onedrive_tokens = MagicMock(return_value={
            "access_token": "token123",
            "drive_id": "drive1",
            "refresh_token": "refresh-123",
            "expires_at_utc": "2026-03-01T00:00:00+00:00",
        })

        # Act
        result = handler.sync(athlete_id="athlete1", lookback_days=30)

        # Assert
        assert result["status"] == "partial"
        assert result["ingested"] == 0
        assert result["skipped"] == 2
        assert result["failed"] == 2
