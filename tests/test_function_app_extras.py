"""Additional coverage for function_app helpers and endpoints."""

# pyright: reportPrivateUsage=false, reportPrivateImportUsage=false
# pylint: disable=line-too-long,protected-access,missing-function-docstring,missing-class-docstring

import base64
import json
from unittest.mock import MagicMock, patch

import pytest
import azure.functions as func

import function_app
from FitParser.onedrive_sync import (
    ONEDRIVE_CLIENT_ID,
    ONEDRIVE_CLIENT_SECRET,
    ONEDRIVE_REDIRECT_URI,
    ONEDRIVE_SYNC_LOOKBACK_DAYS,
    OneDriveSyncConfig,
)


class TestPublicBaseUrlHelper:
    def test_public_base_url_env_override(self, monkeypatch):
        monkeypatch.setenv(function_app.ENV_PUBLIC_BASE_URL, "https://example.com/base/")
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://ignored.example.com/path"
        assert function_app._public_base_url(req) == "https://example.com/base"

    def test_public_base_url_from_request(self, monkeypatch):
        monkeypatch.delenv(function_app.ENV_PUBLIC_BASE_URL, raising=False)
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://api.example.com/some/path?x=1"
        assert function_app._public_base_url(req) == "https://api.example.com"


class TestDocsAssetEndpoints:
    def test_serve_ai_plugin_manifest_populates_urls(self, monkeypatch):
        manifest = {
            "schema_version": "v1",
            "api": {"type": "openapi", "url": "placeholder"},
            "logo_url": "https://old.logo",
            "contact_email": "old@example.com",
            "legal_info_url": "https://old.legal",
        }
        monkeypatch.setenv(function_app.ENV_PLUGIN_LOGO_URL, "https://logo.example.com")
        monkeypatch.setenv(function_app.ENV_PLUGIN_CONTACT_EMAIL, "support@example.com")
        monkeypatch.setenv(function_app.ENV_PLUGIN_LEGAL_URL, "https://legal.example.com")

        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://health.example.com/.well-known/ai-plugin.json"

        with patch("function_app._read_text_file", return_value=json.dumps(manifest)):
            response = function_app.serve_ai_plugin_manifest(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["api"]["url"] == "https://health.example.com/openapi.yaml"
        assert body["logo_url"] == "https://logo.example.com"
        assert body["contact_email"] == "support@example.com"
        assert body["legal_info_url"] == "https://legal.example.com"

    def test_serve_openapi_spec_rewrites_base_url(self):
        raw = "servers:\n  - url: https://health-assistant.azurewebsites.net"
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://api.example.com/openapi.yaml"

        with patch("function_app._read_text_file", return_value=raw):
            response = function_app.serve_openapi_spec(req)

        assert response.status_code == 200
        body = response.get_body().decode("utf-8")
        assert "https://api.example.com" in body
        assert "health-assistant.azurewebsites.net" not in body


class TestPhysiometricsEndpointHandlers:
    def test_get_current_physiometrics_requires_athlete(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {}

        response = function_app.get_current_physiometrics(req)

        assert response.status_code == 400

    def test_get_current_physiometrics_success(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob"}

        mock_layer = MagicMock()
        mock_layer.get_current_physiometrics.return_value = {"athlete_id": "rob"}

        with patch("function_app.SemanticLayer", return_value=mock_layer):
            response = function_app.get_current_physiometrics(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["athlete_id"] == "rob"

    def test_get_physiometrics_history_parses_metrics(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {
            "athlete_id": "rob",
            "days": "999",
            "metrics": "weight_kg,cycling_vo2max_ml_kg_min",
        }

        mock_layer = MagicMock()
        mock_layer.get_physiometrics_trends.return_value = {"athlete_id": "rob"}

        with patch("function_app.SemanticLayer", return_value=mock_layer):
            function_app.get_physiometrics_history(req)

        mock_layer.get_physiometrics_trends.assert_called_once_with(
            athlete_id="rob",
            days=365,
            metrics=["weight_kg", "cycling_vo2max_ml_kg_min"],
        )

    def test_update_physiometrics_single_metric(self):
        req = MagicMock(spec=func.HttpRequest)
        req.get_json.return_value = {
            "athlete_id": "rob",
            "metric": "weight_kg",
            "value": 75.5,
            "effective_date": "2026-01-20",
        }

        mock_layer = MagicMock()
        mock_layer.update_physiometric_value.return_value = {"status": "success"}

        with patch("function_app.SemanticLayer", return_value=mock_layer):
            response = function_app.update_physiometrics(req)

        assert response.status_code == 200
        mock_layer.update_physiometric_value.assert_called_once()

    def test_update_physiometrics_bulk(self):
        req = MagicMock(spec=func.HttpRequest)
        req.get_json.return_value = {
            "athlete_id": "rob",
            "metrics": {"weight_kg": 75.5, "cycling_vo2max_ml_kg_min": 52.1},
            "effective_date": "2026-01-20",
        }

        mock_layer = MagicMock()
        mock_layer.update_physiometric_value.return_value = {"status": "success"}

        with patch("function_app.SemanticLayer", return_value=mock_layer):
            response = function_app.update_physiometrics(req)

        assert response.status_code == 200
        assert mock_layer.update_physiometric_value.call_count == 2

    def test_update_physiometrics_invalid_payload(self):
        req = MagicMock(spec=func.HttpRequest)
        req.get_json.return_value = {"athlete_id": "rob"}

        with patch("function_app.SemanticLayer"):
            response = function_app.update_physiometrics(req)

        assert response.status_code == 400


class TestWithingsEndpointHandlers:
    def test_withings_authorize_requires_athlete(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {}

        response = function_app.withings_authorize(req)

        assert response.status_code == 400

    def test_withings_authorize_success(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob"}

        mock_client = MagicMock()
        mock_client.get_authorization_url.return_value = ("https://auth", "state")

        with patch("function_app.WithingsClient", return_value=mock_client):
            response = function_app.withings_authorize(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["authorization_url"] == "https://auth"

    def test_withings_callback_requires_code_state(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"code": "abc"}

        response = function_app.withings_callback(req)

        assert response.status_code == 400

    def test_withings_callback_success(self):
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://health.example.com/api/withings/callback"
        req.params = {"code": "abc", "state": "token:rob"}

        mock_client = MagicMock()
        mock_client.exchange_auth_code.return_value = {
            "athlete_id": "rob",
            "userid": "123",
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "scope": "user.metrics",
        }
        mock_storage = MagicMock()

        with patch("function_app.WithingsClient", return_value=mock_client):
            with patch("function_app.WorkoutTableStorage", return_value=mock_storage):
                response = function_app.withings_callback(req)

        assert response.status_code == 200
        mock_storage.store_withings_tokens.assert_called_once()
        mock_client.subscribe_to_notifications.assert_called_once()

    def test_withings_webhook_missing_fields(self):
        req = MagicMock(spec=func.HttpRequest)
        req.form = {"userid": "123"}

        response = function_app.withings_webhook(req)

        assert response.status_code == 400

    def test_withings_webhook_non_weight(self):
        req = MagicMock(spec=func.HttpRequest)
        req.form = {
            "userid": "123",
            "appli": "2",
            "startdate": "1",
            "enddate": "2",
        }

        response = function_app.withings_webhook(req)

        assert response.status_code == 200

    def test_withings_webhook_weight(self):
        req = MagicMock(spec=func.HttpRequest)
        req.form = {
            "userid": "123",
            "appli": "1",
            "startdate": "1",
            "enddate": "2",
        }

        response = function_app.withings_webhook(req)

        assert response.status_code == 200


class TestIngestionHelpersAndFlow:
    def test_decode_fit_file_content_invalid_base64(self):
        with pytest.raises(ValueError):
            function_app._decode_fit_file_content("not-base64")

    def test_ingest_fit_payload_skips_duplicate(self):
        payload = {
            "athlete_id": "rob",
            "source_file_name": "file.fit",
            "file_content_b64": base64.b64encode(b"data").decode("utf-8"),
        }

        mock_storage = MagicMock()
        mock_storage.get_ingestion_state.return_value = {
            "status": "ingested",
            "workout_id": "workout-123",
        }

        with patch("function_app.compute_file_hash", return_value="hash"):
            with patch("function_app._get_storage_instance", return_value=mock_storage):
                body, status_code = function_app._ingest_fit_payload(payload)

        assert status_code == 200
        assert body["status"] == "skipped"
        assert body["workout_id"] == "workout-123"

    def test_ingest_fit_payload_success(self):
        payload = {
            "athlete_id": "rob",
            "source_file_name": "file.fit",
            "file_content_b64": base64.b64encode(b"data").decode("utf-8"),
        }

        mock_storage = MagicMock()
        mock_storage.get_ingestion_state.return_value = None
        mock_storage.store_workout.return_value = "workout-456"

        mock_parser = MagicMock()
        mock_parser.parse.return_value = {
            "sport": "Cycling",
            "duration_sec": 3600,
            "start_time_utc": "2026-01-01T10:00:00Z",
            "pwr_avg_watts": 220,
            "hr_avg_bpm": 150,
        }

        with patch("function_app.compute_file_hash", return_value="hash"):
            with patch("function_app._get_storage_instance", return_value=mock_storage):
                with patch("function_app.FitParser", return_value=mock_parser):
                    body, status_code = function_app._ingest_fit_payload(payload)

        assert status_code == 200
        assert body["status"] == "success"
        mock_storage.record_ingestion_state.assert_called_once()


class TestOneDriveHelpersAndEndpoints:
    def test_onedrive_default_lookback_invalid(self, monkeypatch):
        monkeypatch.setenv(ONEDRIVE_CLIENT_ID, "client-id")
        monkeypatch.setenv(ONEDRIVE_CLIENT_SECRET, "client-secret")
        monkeypatch.setenv(ONEDRIVE_REDIRECT_URI, "https://example.com/callback")
        monkeypatch.setenv(ONEDRIVE_SYNC_LOOKBACK_DAYS, "invalid")
        assert OneDriveSyncConfig.from_env().lookback_days == 30

    def test_onedrive_default_lookback_minimum(self, monkeypatch):
        monkeypatch.setenv(ONEDRIVE_CLIENT_ID, "client-id")
        monkeypatch.setenv(ONEDRIVE_CLIENT_SECRET, "client-secret")
        monkeypatch.setenv(ONEDRIVE_REDIRECT_URI, "https://example.com/callback")
        monkeypatch.setenv(ONEDRIVE_SYNC_LOOKBACK_DAYS, "0")
        assert OneDriveSyncConfig.from_env().lookback_days == 1

    def test_onedrive_sync_http_calls_sync(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"days": 7, "athlete_id": "rob"}

        mock_service = MagicMock()
        mock_service.config.lookback_days = 30
        mock_service.sync.return_value = {"status": "success"}

        with patch("function_app._get_onedrive_sync_service", return_value=mock_service):
            response = function_app.onedrive_sync_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        mock_service.sync.assert_called_once_with(athlete_id="rob", lookback_days=7)

    def test_onedrive_authorize_returns_url(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob"}

        mock_service = MagicMock()
        mock_service.build_authorize_url.return_value = "https://login.example.com/auth"

        with patch("function_app._get_onedrive_sync_service", return_value=mock_service):
            response = function_app.onedrive_authorize(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["authorization_url"] == "https://login.example.com/auth"
        assert body["athlete_id"] == "rob"

    def test_onedrive_callback_missing_code(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"state": "rob:token"}

        response = function_app.onedrive_callback(req)

        assert response.status_code == 400

    def test_onedrive_callback_success(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"code": "auth-code", "state": "rob:token"}

        mock_service = MagicMock()

        with patch("function_app._get_onedrive_sync_service", return_value=mock_service):
            response = function_app.onedrive_callback(req)

        assert response.status_code == 200
        mock_service.complete_authorization.assert_called_once_with(
            athlete_id="rob", code="auth-code"
        )
