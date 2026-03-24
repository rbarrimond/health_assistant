"""Unit tests for OneDrive sync service."""

# pylint: disable=missing-function-docstring,missing-class-docstring,unused-argument,protected-access,line-too-long

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from TrainingAnalyticsPlatform.integrations.onedrive_client import (
    OneDriveDeltaTokenExpiredError,
)
from TrainingAnalyticsPlatform.handlers import onedrive_sync_handler
from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import (
    OneDriveSyncConfig,
    OneDriveSyncHandler,
)


def _config() -> OneDriveSyncConfig:
    return OneDriveSyncConfig(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        scopes="Files.ReadWrite offline_access",
        folder_path="/Apps/HealthFit",
        lookback_days=30,
    )


def test_build_authorize_url():
    storage = MagicMock()
    client = MagicMock()
    handler = OneDriveSyncHandler(_config(), storage, client=client)

    client.build_authorize_url.return_value = "https://login.microsoftonline.com/..."
    url = handler.build_authorize_url(state="rob:token")

    assert "login.microsoftonline.com" in url
    client.build_authorize_url.assert_called_once_with(state="rob:token")


def test_complete_authorization_stores_tokens(monkeypatch):
    storage = MagicMock()
    storage.oauth_tokens = MagicMock()
    client = MagicMock()
    handler = OneDriveSyncHandler(_config(), storage, client=client)

    token_data = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "scope": "Files.ReadWrite",
    }

    client.exchange_code = MagicMock(return_value=token_data)
    client.get_drive_id = MagicMock(return_value="drive-id")

    handler.complete_authorization(athlete_id="rob", code="auth-code")

    storage.oauth_tokens.store_onedrive_tokens.assert_called_once()


def test_sync_calls_ingestion_handler(monkeypatch):
    storage = MagicMock()
    storage.oauth_tokens = MagicMock()
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    tokens = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat(),
        "drive_id": "drive-id",
        "delta_token": "delta-link-1",
    }
    storage.oauth_tokens.get_onedrive_tokens.return_value = tokens

    client = MagicMock()
    ingestion_handler = MagicMock()
    ingestion_handler.handle.return_value = ({"status": "success"}, 200)

    handler = OneDriveSyncHandler(
        _config(),
        storage,
        client=client,
        ingestion_handler=ingestion_handler,
    )

    client.list_files_delta = MagicMock(return_value=([{
        "id": "file-id",
        "name": "test.fit",
        "size": 10,
        "eTag": "etag",
        "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
    }], "delta-link-2"))

    result = handler.sync(athlete_id="rob", lookback_days=30)

    assert result["status"] == "success"
    assert result["ingested"] == 1
    assert result["sync_mode"] == "incremental"
    storage.oauth_tokens.update_onedrive_delta_state.assert_called_once_with(
        "rob",
        delta_token="delta-link-2",
        delta_sync_state="active",
    )
    ingestion_handler.handle.assert_called_once()


def test_parse_workout_date_from_filename():
    assert (
        onedrive_sync_handler._parse_workout_date("2026-01-15-ride.fit")
        == date(2026, 1, 15)
    )
    assert onedrive_sync_handler._parse_workout_date("no-date.fit") is None
    assert onedrive_sync_handler._parse_workout_date("2026-13-40-ride.fit") is None


def test_sync_filters_by_filename_date(monkeypatch):
    storage = MagicMock()
    storage.oauth_tokens = MagicMock()
    future = datetime(2026, 2, 1, tzinfo=timezone.utc) + timedelta(hours=2)
    tokens = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat(),
        "drive_id": "drive-id",
        "delta_token": "delta-link-1",
    }
    storage.oauth_tokens.get_onedrive_tokens.return_value = tokens

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(onedrive_sync_handler, "datetime", FixedDateTime)

    client = MagicMock()
    ingestion_handler = MagicMock()
    ingestion_handler.handle.return_value = ({"status": "success"}, 200)
    handler = OneDriveSyncHandler(
        _config(),
        storage,
        client=client,
        ingestion_handler=ingestion_handler,
    )

    client.list_files_delta = MagicMock(return_value=([{
        "id": "recent",
        "name": "2026-01-15-ride.fit",
        "size": 10,
        "eTag": "etag",
        "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
        "lastModifiedDateTime": "2026-01-31T12:00:00Z",
    }, {
        "id": "old",
        "name": "2025-12-01-run.fit",
        "size": 10,
        "eTag": "etag",
        "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
        "lastModifiedDateTime": "2026-01-31T12:00:00Z",
    }], "delta-link-2"))

    result = handler.sync(athlete_id="rob", lookback_days=30)

    assert result["found"] == 1
    assert result["ingested"] == 1
    client.list_files_delta.assert_called_once()
    ingestion_handler.handle.assert_called_once()


def test_sync_falls_back_to_modified_date(monkeypatch):
    storage = MagicMock()
    storage.oauth_tokens = MagicMock()
    future = datetime(2026, 2, 1, tzinfo=timezone.utc) + timedelta(hours=2)
    tokens = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat(),
        "drive_id": "drive-id",
        "delta_token": "delta-link-1",
    }
    storage.oauth_tokens.get_onedrive_tokens.return_value = tokens

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(onedrive_sync_handler, "datetime", FixedDateTime)

    client = MagicMock()
    ingestion_handler = MagicMock()
    ingestion_handler.handle.return_value = ({"status": "success"}, 200)
    handler = OneDriveSyncHandler(
        _config(),
        storage,
        client=client,
        ingestion_handler=ingestion_handler,
    )

    client.list_files_delta = MagicMock(return_value=([{
        "id": "unknown",
        "name": "workout.fit",
        "size": 10,
        "eTag": "etag",
        "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
        "lastModifiedDateTime": "2025-12-01T12:00:00Z",
    }], "delta-link-2"))

    result = handler.sync(athlete_id="rob", lookback_days=30)

    assert result["found"] == 0
    assert result["ingested"] == 0
    ingestion_handler.handle.assert_not_called()


def test_sync_resets_delta_when_token_expired():
    storage = MagicMock()
    storage.oauth_tokens = MagicMock()
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    storage.oauth_tokens.get_onedrive_tokens.return_value = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat(),
        "drive_id": "drive-id",
        "delta_token": "expired-delta",
    }

    client = MagicMock()
    ingestion_handler = MagicMock()
    ingestion_handler.handle.return_value = ({"status": "success"}, 200)

    client.list_files_delta.side_effect = [
        OneDriveDeltaTokenExpiredError("expired"),
        ([{
            "id": "file-id",
            "name": "test.fit",
            "size": 10,
            "eTag": "etag",
            "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
        }], "new-delta-link"),
    ]

    handler = OneDriveSyncHandler(
        _config(),
        storage,
        client=client,
        ingestion_handler=ingestion_handler,
    )

    result = handler.sync(athlete_id="rob", lookback_days=30)

    assert result["status"] == "success"
    assert result["sync_mode"] == "fallback_reset"
    assert client.list_files_delta.call_count == 2
    storage.oauth_tokens.update_onedrive_delta_state.assert_called_once_with(
        "rob",
        delta_token="new-delta-link",
        delta_sync_state="active",
    )


def test_sync_skips_when_no_tokens():
    storage = MagicMock()
    storage.oauth_tokens = MagicMock()
    storage.oauth_tokens.get_onedrive_tokens.return_value = None

    handler = OneDriveSyncHandler(_config(), storage, client=MagicMock())

    with pytest.raises(ValueError):
        handler.sync(athlete_id="rob", lookback_days=30)


def test_sync_force_true_uses_full_rescan_and_bypasses_delta_token():
    storage = MagicMock()
    storage.oauth_tokens = MagicMock()
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    tokens = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat(),
        "drive_id": "drive-id",
        "delta_token": "delta-link-1",
    }
    storage.oauth_tokens.get_onedrive_tokens.return_value = tokens

    client = MagicMock()
    ingestion_handler = MagicMock()
    ingestion_handler.handle.return_value = ({"status": "success"}, 200)

    handler = OneDriveSyncHandler(
        _config(),
        storage,
        client=client,
        ingestion_handler=ingestion_handler,
    )

    client.list_files_delta = MagicMock(return_value=([{
        "id": "file-id",
        "name": "test.fit",
        "size": 10,
        "eTag": "etag",
        "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
    }], "delta-link-2"))

    result = handler.sync(athlete_id="rob", lookback_days=30, force=True)

    assert result["status"] == "success"
    assert result["sync_mode"] == "force_full"
    assert result["force"] is True
    assert result["ingested"] == 1
    client.list_files_delta.assert_called_once()
    assert client.list_files_delta.call_args.kwargs["delta_link"] is None
    ingestion_handler.handle.assert_called_once()
    assert ingestion_handler.handle.call_args.kwargs["force"] is True
