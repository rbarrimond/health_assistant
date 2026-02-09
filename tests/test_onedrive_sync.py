"""Unit tests for OneDrive sync service."""

# pylint: disable=missing-function-docstring,missing-class-docstring,unused-argument,protected-access,line-too-long

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from FitParser.handlers import onedrive_sync_handler
from FitParser.handlers.onedrive_sync_handler import (
    OneDriveSyncIngestionHandler,
    OneDriveSyncConfig,
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
    service = OneDriveSyncIngestionHandler(_config(), storage)

    url = service.build_authorize_url(state="rob:token")

    assert "login.microsoftonline.com" in url
    assert "state=rob%3Atoken" in url


def test_complete_authorization_stores_tokens(monkeypatch):
    storage = MagicMock()
    service = OneDriveSyncIngestionHandler(_config(), storage)

    token_data = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "scope": "Files.ReadWrite",
    }

    service._client.exchange_code = MagicMock(return_value=token_data)  # type: ignore[attr-defined]
    service._client.get_drive_id = MagicMock(return_value="drive-id")  # type: ignore[attr-defined]

    service.complete_authorization(athlete_id="rob", code="auth-code")

    storage.store_onedrive_tokens.assert_called_once()


def test_sync_uses_ingest_bytes(monkeypatch):
    storage = MagicMock()
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    tokens = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat().replace("+00:00", "Z"),
        "drive_id": "drive-id",
    }
    storage.get_onedrive_tokens.return_value = tokens

    payload_calls = []
    service = OneDriveSyncIngestionHandler(_config(), storage)
    service.ingest_bytes = MagicMock()
    service.ingest_bytes.side_effect = (
        lambda athlete_id, source_info, file_bytes, file_path=None: (
            payload_calls.append({
                "athlete_id": athlete_id,
                "file_bytes": file_bytes,
                "source_info": source_info,
                "file_path": file_path,
            }) or ({"status": "success"}, 200)
        )
    )

    service._client.list_files = MagicMock(return_value=[{
        "id": "file-id",
        "name": "test.fit",
        "size": 10,
        "eTag": "etag",
        "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
    }])  # type: ignore[attr-defined]
    service._client.download_file = MagicMock(return_value=b"fit-bytes")  # type: ignore[attr-defined]

    result = service.sync(athlete_id="rob", lookback_days=30)

    assert result["status"] == "success"
    assert result["ingested"] == 1
    assert len(payload_calls) == 1
    assert payload_calls[0]["athlete_id"] == "rob"
    assert payload_calls[0]["file_bytes"] == b"fit-bytes"
    assert payload_calls[0]["source_info"]["source_file_name"] == "test.fit"


def test_parse_workout_date_from_filename():
    assert (
        onedrive_sync_handler._parse_workout_date("2026-01-15-ride.fit")
        == date(2026, 1, 15)
    )
    assert onedrive_sync_handler._parse_workout_date("no-date.fit") is None
    assert onedrive_sync_handler._parse_workout_date("2026-13-40-ride.fit") is None


def test_sync_filters_by_filename_date(monkeypatch):
    storage = MagicMock()
    future = datetime(2026, 2, 1, tzinfo=timezone.utc) + timedelta(hours=2)
    tokens = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat().replace("+00:00", "Z"),
        "drive_id": "drive-id",
    }
    storage.get_onedrive_tokens.return_value = tokens

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(onedrive_sync_handler, "datetime", FixedDateTime)

    service = OneDriveSyncIngestionHandler(_config(), storage)
    service.ingest_bytes = MagicMock()
    service.ingest_bytes.return_value = ({"status": "success"}, 200)

    service._client.list_files = MagicMock(return_value=[{
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
    }])  # type: ignore[attr-defined]
    service._client.download_file = MagicMock(return_value=b"fit-bytes")  # type: ignore[attr-defined]

    result = service.sync(athlete_id="rob", lookback_days=30)

    assert result["found"] == 1
    assert result["ingested"] == 1
    service._client.list_files.assert_called_once()
    _, kwargs = service._client.list_files.call_args
    assert kwargs["modified_since"] is None
    service._client.download_file.assert_called_once_with(access_token="access", item_id="recent")


def test_sync_falls_back_to_modified_date(monkeypatch):
    storage = MagicMock()
    future = datetime(2026, 2, 1, tzinfo=timezone.utc) + timedelta(hours=2)
    tokens = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at_utc": future.isoformat().replace("+00:00", "Z"),
        "drive_id": "drive-id",
    }
    storage.get_onedrive_tokens.return_value = tokens

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 2, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(onedrive_sync_handler, "datetime", FixedDateTime)

    service = OneDriveSyncIngestionHandler(_config(), storage)
    service.ingest_bytes = MagicMock()
    service.ingest_bytes.return_value = ({"status": "success"}, 200)

    service._client.list_files = MagicMock(return_value=[{
        "id": "unknown",
        "name": "workout.fit",
        "size": 10,
        "eTag": "etag",
        "parentReference": {"path": "/drive/root:/Apps/HealthFit", "driveId": "drive-id"},
        "lastModifiedDateTime": "2025-12-01T12:00:00Z",
    }])  # type: ignore[attr-defined]
    service._client.download_file = MagicMock(return_value=b"fit-bytes")  # type: ignore[attr-defined]

    result = service.sync(athlete_id="rob", lookback_days=30)

    assert result["found"] == 0
    assert result["ingested"] == 0
    service._client.download_file.assert_not_called()


def test_sync_skips_when_no_tokens():
    storage = MagicMock()
    storage.get_onedrive_tokens.return_value = None

    service = OneDriveSyncIngestionHandler(_config(), storage)

    with pytest.raises(ValueError):
        service.sync(athlete_id="rob", lookback_days=30)
