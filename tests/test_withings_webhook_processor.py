"""Tests for Withings async webhook processor exception semantics."""

import json
from unittest.mock import Mock, patch

import pytest

from TrainingAnalyticsPlatform.integrations.withings_webhook_processor import process_webhook_async
from TrainingAnalyticsPlatform.platform.exceptions import AuthError, StorageError, ValidationError


def _valid_message() -> str:
    return json.dumps(
        {
            "userid": "12345",
            "startdate": 1700000000,
            "enddate": 1700003600,
            "athlete_id": "rob",
        }
    )


@patch("TrainingAnalyticsPlatform.integrations.withings_webhook_processor.WithingsClient")
@patch("TrainingAnalyticsPlatform.integrations.withings_webhook_processor.StorageCoordinator")
def test_process_webhook_async_invalid_json_raises_validation_error(
    mock_storage_cls: Mock,
    mock_client_cls: Mock,
) -> None:
    mock_storage_cls.return_value = Mock()
    mock_client_cls.return_value = Mock()

    with pytest.raises(ValidationError):
        process_webhook_async("not-json")


@patch("TrainingAnalyticsPlatform.integrations.withings_webhook_processor.WithingsClient")
@patch("TrainingAnalyticsPlatform.integrations.withings_webhook_processor.StorageCoordinator")
def test_process_webhook_async_missing_tokens_raises_auth_error(
    mock_storage_cls: Mock,
    mock_client_cls: Mock,
) -> None:
    storage = Mock()
    storage.webhooks.webhook_already_processed.return_value = False
    storage.oauth_tokens.get_withings_tokens.return_value = None
    mock_storage_cls.return_value = storage

    client = Mock()
    mock_client_cls.return_value = client

    with pytest.raises(AuthError):
        process_webhook_async(_valid_message())

    client.fetch_measurements.assert_not_called()


@patch("TrainingAnalyticsPlatform.integrations.withings_webhook_processor.WithingsClient")
@patch("TrainingAnalyticsPlatform.integrations.withings_webhook_processor.StorageCoordinator")
def test_process_webhook_async_dedup_check_storage_failure_propagates(
    mock_storage_cls: Mock,
    mock_client_cls: Mock,
) -> None:
    storage = Mock()
    storage.webhooks.webhook_already_processed.side_effect = StorageError("storage unavailable")
    mock_storage_cls.return_value = storage
    mock_client_cls.return_value = Mock()

    with pytest.raises(StorageError):
        process_webhook_async(_valid_message())
