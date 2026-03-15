"""Tests for OAuthTokenStorage OneDrive delta reset operations."""

from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.oauth_token_storage import OAuthTokenStorage


def test_reset_onedrive_delta_state_resets_existing_row() -> None:
    infra = MagicMock()
    table_client = MagicMock()
    infra.get_table_client.return_value = table_client

    storage = OAuthTokenStorage(infra)
    storage.get_onedrive_tokens = MagicMock(return_value={"PartitionKey": "rob"})

    reset_applied = storage.reset_onedrive_delta_state("rob")

    assert reset_applied is True
    table_client.upsert_entity.assert_called_once()
    entity = table_client.upsert_entity.call_args.args[0]
    assert entity["PartitionKey"] == "rob"
    assert entity["RowKey"] == "onedrive"
    assert entity["delta_token"] == ""
    assert entity["delta_sync_state"] == "initial"
    assert entity["last_delta_sync_at_utc"] == ""


def test_reset_onedrive_delta_state_returns_false_when_missing() -> None:
    infra = MagicMock()
    table_client = MagicMock()
    infra.get_table_client.return_value = table_client

    storage = OAuthTokenStorage(infra)
    storage.get_onedrive_tokens = MagicMock(return_value=None)

    reset_applied = storage.reset_onedrive_delta_state("rob")

    assert reset_applied is False
    table_client.upsert_entity.assert_not_called()


def test_reset_all_onedrive_delta_states_resets_all_rows() -> None:
    infra = MagicMock()
    table_client = MagicMock()
    table_client.query_entities.return_value = [
        {"PartitionKey": "rob", "RowKey": "onedrive"},
        {"PartitionKey": "jane", "RowKey": "onedrive"},
    ]
    infra.get_table_client.return_value = table_client

    storage = OAuthTokenStorage(infra)

    reset_count = storage.reset_all_onedrive_delta_states()

    assert reset_count == 2
    assert table_client.upsert_entity.call_count == 2


def test_reset_onedrive_delta_state_translates_http_error() -> None:
    infra = MagicMock()
    table_client = MagicMock()
    table_client.upsert_entity.side_effect = HttpResponseError("boom")
    infra.get_table_client.return_value = table_client

    storage = OAuthTokenStorage(infra)
    storage.get_onedrive_tokens = MagicMock(return_value={"PartitionKey": "rob"})

    with pytest.raises(StorageError):
        storage.reset_onedrive_delta_state("rob")
