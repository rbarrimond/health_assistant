"""Unit tests for OneDrive Graph client delta sync behavior."""

from unittest.mock import MagicMock

import pytest

from TrainingAnalyticsPlatform.integrations.onedrive_client import (
    OneDriveDeltaTokenExpiredError,
    OneDriveGraphClient,
)


class _Response:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _client() -> OneDriveGraphClient:
    return OneDriveGraphClient(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://example.com/callback",
        scopes="Files.ReadWrite offline_access",
    )


def test_list_files_delta_returns_files_and_delta_link(monkeypatch):
    client = _client()

    responses = [
        _Response(
            200,
            {
                "value": [
                    {
                        "id": "item-1",
                        "name": "activity.fit",
                        "file": {"hashes": {}},
                    },
                    {
                        "id": "item-2",
                        "name": "folder",
                        "folder": {},
                    },
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/drive/root/delta?token=abc",
            },
        )
    ]

    def _fake_get(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr("TrainingAnalyticsPlatform.integrations.onedrive_client.requests.get", _fake_get)

    items, delta_link = client.list_files_delta(
        access_token="token",
        folder_path="/Apps/HealthFit",
        delta_link=None,
        extensions={".fit"},
    )

    assert len(items) == 1
    assert items[0]["id"] == "item-1"
    assert delta_link == "https://graph.microsoft.com/v1.0/me/drive/root/delta?token=abc"


def test_list_files_delta_raises_when_delta_token_expired(monkeypatch):
    client = _client()

    monkeypatch.setattr(
        "TrainingAnalyticsPlatform.integrations.onedrive_client.requests.get",
        MagicMock(return_value=_Response(410, {})),
    )

    with pytest.raises(OneDriveDeltaTokenExpiredError):
        client.list_files_delta(
            access_token="token",
            folder_path="/Apps/HealthFit",
            delta_link="https://graph.microsoft.com/v1.0/me/drive/root/delta?token=expired",
            extensions={".fit"},
        )
