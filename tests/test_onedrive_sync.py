"""Unit tests for OneDrive sync service."""

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from FitParser.onedrive_sync import OneDrivePersonalSyncService, OneDriveSyncConfig


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
    service = OneDrivePersonalSyncService(_config(), storage, ingest_payload_fn=lambda _: ({}, 200))

    url = service.build_authorize_url(state="rob:token")

    assert "login.microsoftonline.com" in url
    assert "state=rob%3Atoken" in url


def test_complete_authorization_stores_tokens(monkeypatch):
    storage = MagicMock()
    service = OneDrivePersonalSyncService(_config(), storage, ingest_payload_fn=lambda _: ({}, 200))

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


def test_sync_uses_ingest_payload(monkeypatch):
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

    def ingest(payload):
        payload_calls.append(payload)
        return {"status": "success"}, 200

    service = OneDrivePersonalSyncService(_config(), storage, ingest_payload_fn=ingest)

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
    assert payload_calls[0]["source_file_name"] == "test.fit"
    assert base64.b64decode(payload_calls[0]["file_content_b64"]) == b"fit-bytes"


def test_sync_skips_when_no_tokens():
    storage = MagicMock()
    storage.get_onedrive_tokens.return_value = None

    service = OneDrivePersonalSyncService(_config(), storage, ingest_payload_fn=lambda _: ({}, 200))

    with pytest.raises(ValueError):
        service.sync(athlete_id="rob", lookback_days=30)
