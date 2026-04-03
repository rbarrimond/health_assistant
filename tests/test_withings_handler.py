"""Tests for WithingsHandler."""

# pylint: disable=line-too-long

from unittest.mock import Mock

import pytest

from TrainingAnalyticsPlatform.handlers import WithingsHandler
from TrainingAnalyticsPlatform.platform.exceptions import (
    ExternalServiceError,
    ValidationError,
)


class TestWithingsHandler:
    """Test suite for WithingsHandler."""

    @pytest.fixture
    def mock_withings_client(self):
        """Create mock WithingsClient."""
        return Mock()

    @pytest.fixture
    def mock_storage(self):
        """Create mock storage coordinator."""
        storage = Mock()
        storage.oauth_tokens = Mock()
        storage.webhooks = Mock()
        storage.physiometrics = Mock()
        return storage

    @pytest.fixture
    def handler(self, mock_withings_client, mock_storage):
        """Create handler instance with mocked dependencies."""
        return WithingsHandler(mock_withings_client, mock_storage)

    def test_get_authorization_url_success(self, handler, mock_withings_client):
        """Test successful OAuth URL generation."""
        # Arrange
        mock_withings_client.get_authorization_url.return_value = (
            "https://account.withings.com/oauth2/authorize?...",
            "state_token_123"
        )

        # Act
        result, status = handler.get_authorization_url("athlete1")

        # Assert
        assert status == 200
        assert "authorization_url" in result
        assert "https://account.withings.com" in result["authorization_url"]
        assert "athlete_id" in result
        assert result["athlete_id"] == "athlete1"
        mock_withings_client.get_authorization_url.assert_called_once_with("athlete1")

    def test_get_authorization_url_missing_athlete_id(self, handler, mock_withings_client):
        """Test OAuth URL generation with missing athlete_id."""
        # Act
        result, status = handler.get_authorization_url(None)

        # Assert
        assert status == 400
        assert "error" in result
        assert "athlete_id" in result["error"].lower()
        mock_withings_client.get_authorization_url.assert_not_called()

    def test_get_authorization_url_empty_athlete_id(self, handler, mock_withings_client):
        """Test OAuth URL generation with empty athlete_id."""
        # Act
        result, status = handler.get_authorization_url("")

        # Assert
        assert status == 400
        assert "error" in result
        mock_withings_client.get_authorization_url.assert_not_called()

    def test_get_authorization_url_exception(self, handler, mock_withings_client):
        """Test OAuth URL generation handles exceptions."""
        # Arrange
        mock_withings_client.get_authorization_url.side_effect = ExternalServiceError("API error")

        # Act
        result, status = handler.get_authorization_url("athlete1")

        # Assert
        assert status == 500
        assert "error" in result
        assert "Failed to generate authorization URL" in result["error"]

    def test_handle_oauth_callback_success(self, handler, mock_withings_client, mock_storage):
        """Test successful OAuth callback processing."""
        # Arrange
        token_data = {
            "athlete_id": "athlete1",
            "userid": "12345",
            "access_token": "access_token_abc",
            "refresh_token": "refresh_token_xyz",
            "expires_in": 3600,
            "scope": "user.metrics"
        }
        mock_withings_client.exchange_auth_code.return_value = token_data

        # Act
        html, status, content_type = handler.handle_oauth_callback(
            code="auth_code_123",
            state="state_token_123",
            webhook_callback_url="https://example.com/api/withings/webhook"
        )

        # Assert
        assert status == 200
        assert content_type == "text/html"
        assert "Success" in html
        assert "athlete1" in html
        mock_withings_client.exchange_auth_code.assert_called_once_with(
            "auth_code_123", "state_token_123"
        )
        mock_storage.oauth_tokens.store_withings_tokens.assert_called_once()
        mock_withings_client.subscribe_to_notifications.assert_called_once()

    def test_handle_oauth_callback_missing_code(self, handler, mock_withings_client):
        """Test OAuth callback with missing code."""
        # Act
        html, status, content_type = handler.handle_oauth_callback(
            code=None,
            state="state_token_123",
            webhook_callback_url="https://example.com/webhook"
        )

        # Assert
        assert status == 400
        assert content_type == "text/html"
        assert "Error" in html
        assert "Missing" in html
        mock_withings_client.exchange_auth_code.assert_not_called()

    def test_handle_oauth_callback_missing_state(self, handler, mock_withings_client):
        """Test OAuth callback with missing state."""
        # Act
        html, status, content_type = handler.handle_oauth_callback(
            code="auth_code_123",
            state=None,
            webhook_callback_url="https://example.com/webhook"
        )

        # Assert
        assert status == 400
        assert content_type == "text/html"
        assert "Error" in html
        mock_withings_client.exchange_auth_code.assert_not_called()

    def test_handle_oauth_callback_exchange_failure(self, handler, mock_withings_client):
        """Test OAuth callback handles token exchange failures."""
        # Arrange
        mock_withings_client.exchange_auth_code.side_effect = ValidationError("Invalid code")

        # Act
        html, status, content_type = handler.handle_oauth_callback(
            code="bad_code",
            state="state_token_123",
            webhook_callback_url="https://example.com/webhook"
        )

        # Assert
        assert status == 400
        assert content_type == "text/html"
        assert "Error" in html
        assert "Invalid code" in html

    def test_handle_oauth_callback_constructs_webhook_url(self, handler, mock_withings_client, mock_storage):
        """Test OAuth callback constructs webhook URL from base."""
        # Arrange
        token_data = {
            "athlete_id": "athlete1",
            "userid": "12345",
            "access_token": "access_token_abc",
            "refresh_token": "refresh_token_xyz",
            "expires_in": 3600,
            "scope": "user.metrics"
        }
        mock_withings_client.exchange_auth_code.return_value = token_data

        # Act
        _, status, _ = handler.handle_oauth_callback(
            code="auth_code_123",
            state="state_token_123",
            webhook_callback_url=""  # Empty callback URL
        )

        # Assert
        assert status == 200
        mock_storage.oauth_tokens.store_withings_tokens.assert_called_once()
        # Handler always attempts subscription, constructs URL from base or env var
        mock_withings_client.subscribe_to_notifications.assert_called_once()

    def test_handle_oauth_callback_succeeds_when_subscription_fails(
        self,
        handler,
        mock_withings_client,
        mock_storage,
    ):
        """Test OAuth callback still succeeds when webhook subscription fails."""
        # Arrange
        token_data = {
            "athlete_id": "athlete1",
            "userid": "12345",
            "access_token": "access_token_abc",
            "refresh_token": "refresh_token_xyz",
            "expires_in": 3600,
            "scope": "user.metrics",
        }
        mock_withings_client.exchange_auth_code.return_value = token_data
        mock_withings_client.subscribe_to_notifications.side_effect = ExternalServiceError(
            "Withings API error: callback URL invalid"
        )

        # Act
        html, status, content_type = handler.handle_oauth_callback(
            code="auth_code_123",
            state="state_token_123",
            webhook_callback_url="https://example.com/api/withings/webhook",
        )

        # Assert
        assert status == 200
        assert content_type == "text/html"
        assert "Success" in html
        assert "OAuth completed, but webhook subscription failed" in html
        mock_storage.oauth_tokens.store_withings_tokens.assert_called_once()
        mock_withings_client.subscribe_to_notifications.assert_called_once()

    def test_process_webhook_success_weight_notification(self, handler):
        """Test successful processing of weight notification."""
        # Act
        result, status = handler.process_webhook(
            userid="12345",
            appli="1",  # Weight notification
            startdate="1643673600",
            enddate="1643760000"
        )

        # Assert
        assert status == 200
        assert result == "OK"

    def test_process_webhook_ignores_non_weight(self, handler):
        """Test webhook ignores non-weight notifications."""
        # Act
        result, status = handler.process_webhook(
            userid="12345",
            appli="4",  # Non-weight notification
            startdate="1643673600",
            enddate="1643760000"
        )

        # Assert
        assert status == 200
        assert result == "OK"  # Still returns OK, but logs ignore

    def test_process_webhook_missing_userid(self, handler):
        """Test webhook with missing userid."""
        # Act
        result, status = handler.process_webhook(
            userid=None,
            appli="1",
            startdate="1643673600",
            enddate="1643760000"
        )

        # Assert
        assert status == 400
        assert "missing" in result.lower()

    def test_process_webhook_missing_appli(self, handler):
        """Test webhook with missing appli."""
        # Act
        result, status = handler.process_webhook(
            userid="12345",
            appli=None,
            startdate="1643673600",
            enddate="1643760000"
        )

        # Assert
        assert status == 400
        assert "missing" in result.lower()

    def test_process_webhook_missing_timestamps(self, handler):
        """Test webhook with missing timestamps."""
        # Act
        _, status = handler.process_webhook(
            userid="12345",
            appli="1",
            startdate=None,
            enddate="1643760000"
        )

        # Assert
        assert status == 400

    def test_process_webhook_exception_handling(self, handler, mocker):
        """Test webhook handles unexpected exceptions gracefully."""
        # Arrange
        # Mock logger to raise exception
        mocker.patch(
            'TrainingAnalyticsPlatform.handlers.wellness_sync.logger.info',
            side_effect=Exception("Logging error"),
        )

        # Act
        _, status = handler.process_webhook(
            userid="12345",
            appli="1",
            startdate="1643673600",
            enddate="1643760000"
        )

        # Assert
        assert status == 503

    def test_get_authorization_url_includes_instructions(self, handler, mock_withings_client):
        """Test authorization URL response includes helpful instructions."""
        # Arrange
        mock_withings_client.get_authorization_url.return_value = (
            "https://account.withings.com/oauth2/authorize?...",
            "state_123"
        )

        # Act
        result, status = handler.get_authorization_url("athlete1")

        # Assert
        assert status == 200
        assert "instructions" in result
        assert "authorize" in result["instructions"].lower()

    def test_sync_metrics_success_with_checkpoint(
        self,
        handler,
        mock_withings_client,
        mock_storage,
    ):
        """Test manual sync uses checkpoint and persists newest checkpoint."""
        mock_storage.oauth_tokens.get_withings_tokens.return_value = {
            "access_token": "token",
            "refresh_token": "refresh",
            "expires_at_utc": "2999-01-01T00:00:00Z",
            "withings_userid": "12345",
        }
        mock_storage.webhooks.get_latest_processed_enddate.return_value = 1700000000
        mock_withings_client.fetch_measurements.return_value = [
            {
                "measured_at": "2024-01-01T00:00:10+00:00",
                "weight_kg": 70.2,
                "body_fat_pct": 15.3,
            }
        ]

        result, status = handler.sync_metrics("athlete1", lookback_days=30)

        assert status == 200
        assert result["status"] == "success"
        assert result["checkpoint_source"] == "webhook_dedup"
        mock_withings_client.fetch_measurements.assert_called_once_with(
            access_token="token",
            lastupdate=1700000000,
        )
        mock_storage.physiometrics.store_physiometrics.assert_called_once()
        mock_storage.webhooks.mark_webhook_processed.assert_called_once()

    def test_sync_metrics_not_connected(self, handler, mock_storage):
        """Test manual sync returns 404 when athlete has no Withings tokens."""
        mock_storage.oauth_tokens.get_withings_tokens.return_value = None

        result, status = handler.sync_metrics("athlete1")

        assert status == 404
        assert "error" in result

    def test_sync_metrics_invalid_lookback(self, handler):
        """Test manual sync validates lookback_days."""
        result, status = handler.sync_metrics("athlete1", lookback_days=0)

        assert status == 400
        assert "lookback_days" in result["error"]

    def test_sync_metrics_invalid_token_payload_returns_auth_failure(
        self,
        handler,
        mock_storage,
    ):
        """Test malformed stored token payload is handled via business auth error path."""
        mock_storage.oauth_tokens.get_withings_tokens.return_value = {
            "access_token": "token",
            "refresh_token": "refresh",
            "expires_at_utc": "not-a-timestamp",
            "withings_userid": "12345",
        }

        result, status = handler.sync_metrics("athlete1", lookback_days=30)

        assert status == 401
        assert "error" in result
