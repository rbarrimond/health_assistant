"""Additional coverage for function_app helpers and endpoints."""

# pyright: reportPrivateUsage=false, reportPrivateImportUsage=false
# pylint: disable=line-too-long,protected-access,missing-function-docstring,missing-class-docstring,no-member

import base64
import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import azure.functions as func

import function_app
from FitParser.dependencies import FunctionAppDependencies
from config.constants import ENV_PUBLIC_BASE_URL
from FitParser.onedrive_sync import (
    ONEDRIVE_CLIENT_ID,
    ONEDRIVE_CLIENT_SECRET,
    ONEDRIVE_REDIRECT_URI,
    ONEDRIVE_SYNC_LOOKBACK_DAYS,
    OneDriveSyncConfig,
)


def _patch_dependency(attr, value):
    return patch.object(FunctionAppDependencies, attr, new=PropertyMock(return_value=value))


class TestPublicBaseUrlHelper:
    def test_public_base_url_env_override(self, monkeypatch):
        monkeypatch.setenv(ENV_PUBLIC_BASE_URL, "https://example.com/base/")
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://ignored.example.com/path"
        assert function_app.public_base_url(req) == "https://example.com/base"

    def test_public_base_url_from_request(self, monkeypatch):
        monkeypatch.delenv(ENV_PUBLIC_BASE_URL, raising=False)
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://api.example.com/some/path?x=1"
        assert function_app.public_base_url(req) == "https://api.example.com"


class TestDocsAssetEndpoints:
    def test_api_docs_dir_default_name(self):
        assert os.path.basename(function_app.API_DOCS_DIR) == "api_docs"

    def test_serve_ai_plugin_manifest_populates_urls(self, monkeypatch):
        manifest = {
            "schema_version": "v1",
            "api": {"type": "openapi", "url": "https://health.example.com/openapi.yaml"},
            "logo_url": "https://logo.example.com",
            "contact_email": "support@example.com",
            "legal_info_url": "https://legal.example.com",
        }
        monkeypatch.setenv(function_app.ENV_PLUGIN_LOGO_URL, "https://logo.example.com")
        monkeypatch.setenv(function_app.ENV_PLUGIN_CONTACT_EMAIL, "support@example.com")
        monkeypatch.setenv(function_app.ENV_PLUGIN_LEGAL_URL, "https://legal.example.com")

        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://health.example.com/.well-known/ai-plugin.json"

        mock_handler = MagicMock()
        mock_handler.get_plugin_manifest.return_value = (manifest, 200)

        with _patch_dependency("storage", MagicMock()):
            with patch("function_app.HealthHandler", return_value=mock_handler) as handler_cls:
                response = function_app.serve_ai_plugin_manifest(req)

        handler_cls.assert_called_once()
        mock_handler.get_plugin_manifest.assert_called_once_with(
            "https://health.example.com",
            {
                "logo_url": "https://logo.example.com",
                "contact_email": "support@example.com",
                "legal_info_url": "https://legal.example.com",
            },
        )

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["api"]["url"] == "https://health.example.com/openapi.yaml"
        assert body["logo_url"] == "https://logo.example.com"
        assert body["contact_email"] == "support@example.com"
        assert body["legal_info_url"] == "https://legal.example.com"

    def test_serve_openapi_spec_rewrites_base_url(self):
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://api.example.com/openapi.yaml"

        mock_handler = MagicMock()
        mock_handler.get_openapi_spec.return_value = ("openapi: 3.0.1\n", 200)

        with _patch_dependency("storage", MagicMock()):
            with patch("function_app.HealthHandler", return_value=mock_handler):
                response = function_app.serve_openapi_spec(req)

        assert response.status_code == 200
        body = response.get_body().decode("utf-8")
        assert "openapi: 3.0.1" in body
        mock_handler.get_openapi_spec.assert_called_once_with("https://api.example.com")

    def test_serve_logo_returns_svg(self):
        req = MagicMock(spec=func.HttpRequest)
        svg_body = "<svg><rect width=\"10\" height=\"10\"/></svg>"

        mock_handler = MagicMock()
        mock_handler.get_logo.return_value = (svg_body, 200)

        with _patch_dependency("storage", MagicMock()):
            with patch("function_app.HealthHandler", return_value=mock_handler):
                response = function_app.serve_logo(req)

        assert response.status_code == 200
        body = response.get_body().decode("utf-8")
        assert "<svg" in body


class TestPhysiometricsEndpointHandlers:
    def test_get_current_physiometrics_defaults_athlete(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.get_current.return_value = ({"athlete_id": "rob"}, 200)

        with _patch_dependency("semantic_layer", MagicMock()):
            with patch("function_app.PhysiometricsHandler", return_value=mock_handler):
                response = function_app.get_current_physiometrics(req)

        assert response.status_code == 200
        mock_handler.get_current.assert_called_once_with("rob")

    def test_get_current_physiometrics_success(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob"}

        mock_handler = MagicMock()
        mock_handler.get_current.return_value = ({"athlete_id": "rob"}, 200)

        with _patch_dependency("semantic_layer", MagicMock()):
            with patch("function_app.PhysiometricsHandler", return_value=mock_handler):
                response = function_app.get_current_physiometrics(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["athlete_id"] == "rob"
        mock_handler.get_current.assert_called_once_with("rob")

    def test_get_physiometrics_history_parses_metrics(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {
            "athlete_id": "rob",
            "days": "999",
            "metrics": "weight_kg,cycling_vo2max_ml_kg_min",
        }

        mock_handler = MagicMock()
        mock_handler.get_history.return_value = ({"athlete_id": "rob"}, 200)

        with _patch_dependency("semantic_layer", MagicMock()):
            with patch("function_app.PhysiometricsHandler", return_value=mock_handler):
                function_app.get_physiometrics_history(req)

        mock_handler.get_history.assert_called_once_with(
            "rob",
            999,
            ["weight_kg", "cycling_vo2max_ml_kg_min"],
        )

    def test_update_physiometrics_single_metric(self):
        req = MagicMock(spec=func.HttpRequest)
        req.get_json.return_value = {
            "athlete_id": "rob",
            "metric": "weight_kg",
            "value": 75.5,
            "effective_date": "2026-01-20",
        }

        mock_handler = MagicMock()
        mock_handler.update_metric.return_value = ({"status": "success"}, 200)

        with _patch_dependency("semantic_layer", MagicMock()):
            with patch("function_app.PhysiometricsHandler", return_value=mock_handler):
                response = function_app.update_physiometrics(req)

        assert response.status_code == 200
        mock_handler.update_metric.assert_called_once_with(
            athlete_id="rob",
            metric="weight_kg",
            value=75.5,
            effective_date="2026-01-20",
            source="chatgpt",
        )

    def test_update_physiometrics_bulk(self):
        req = MagicMock(spec=func.HttpRequest)
        req.get_json.return_value = {
            "athlete_id": "rob",
            "metrics": {"weight_kg": 75.5, "cycling_vo2max_ml_kg_min": 52.1},
            "effective_date": "2026-01-20",
        }

        mock_handler = MagicMock()
        mock_handler.update_metrics.return_value = ({"status": "success"}, 200)

        with _patch_dependency("semantic_layer", MagicMock()):
            with patch("function_app.PhysiometricsHandler", return_value=mock_handler):
                response = function_app.update_physiometrics(req)

        assert response.status_code == 200
        mock_handler.update_metrics.assert_called_once_with(
            athlete_id="rob",
            metrics={"weight_kg": 75.5, "cycling_vo2max_ml_kg_min": 52.1},
            effective_date="2026-01-20",
            source="chatgpt",
        )

    def test_update_physiometrics_invalid_payload(self):
        req = MagicMock(spec=func.HttpRequest)
        req.get_json.return_value = {"athlete_id": "rob"}

        response = function_app.update_physiometrics(req)

        assert response.status_code == 400


class TestWithingsEndpointHandlers:
    def test_withings_authorize_requires_athlete(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.get_authorization_url.return_value = (
            {"authorization_url": "https://auth"},
            200,
        )

        with _patch_dependency("storage", MagicMock()):
            with _patch_dependency("withings_client", MagicMock()):
                with patch("function_app.WithingsHandler", return_value=mock_handler):
                    response = function_app.withings_authorize(req)

        assert response.status_code == 200
        mock_handler.get_authorization_url.assert_called_once_with("rob")

    def test_withings_authorize_success(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob"}

        mock_handler = MagicMock()
        mock_handler.get_authorization_url.return_value = (
            {"authorization_url": "https://auth"},
            200,
        )

        with _patch_dependency("storage", MagicMock()):
            with _patch_dependency("withings_client", MagicMock()):
                with patch("function_app.WithingsHandler", return_value=mock_handler):
                    response = function_app.withings_authorize(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["authorization_url"] == "https://auth"
        mock_handler.get_authorization_url.assert_called_once_with("rob")

    def test_withings_callback_requires_code_state(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"code": "abc"}
        req.url = "https://health.example.com/api/withings/callback"

        mock_handler = MagicMock()
        mock_handler.handle_oauth_callback.return_value = (
            "<html></html>",
            400,
            "text/html",
        )

        with _patch_dependency("storage", MagicMock()):
            with _patch_dependency("withings_client", MagicMock()):
                with patch("function_app.WithingsHandler", return_value=mock_handler):
                    response = function_app.withings_callback(req)

        assert response.status_code == 400
        mock_handler.handle_oauth_callback.assert_called_once()

    def test_withings_callback_success(self):
        req = MagicMock(spec=func.HttpRequest)
        req.url = "https://health.example.com/api/withings/callback"
        req.params = {"code": "abc", "state": "token:rob"}

        mock_handler = MagicMock()
        mock_handler.handle_oauth_callback.return_value = (
            "<html><body>OK</body></html>",
            200,
            "text/html",
        )

        with _patch_dependency("storage", MagicMock()):
            with _patch_dependency("withings_client", MagicMock()):
                with patch("function_app.WithingsHandler", return_value=mock_handler):
                    response = function_app.withings_callback(req)

        assert response.status_code == 200
        mock_handler.handle_oauth_callback.assert_called_once_with(
            "abc",
            "token:rob",
            "https://health.example.com/api/withings/webhook",
        )

    def test_withings_webhook_missing_fields(self):
        req = MagicMock(spec=func.HttpRequest)
        req.form = {"userid": "123"}

        mock_handler = MagicMock()
        mock_handler.process_webhook.return_value = ("OK", 200)

        with _patch_dependency("storage", MagicMock()):
            with _patch_dependency("withings_client", MagicMock()):
                with patch("function_app.WithingsHandler", return_value=mock_handler):
                    response = function_app.withings_webhook(req)

        assert response.status_code == 200

    def test_withings_webhook_non_weight(self):
        req = MagicMock(spec=func.HttpRequest)
        req.form = {
            "userid": "123",
            "appli": "2",
            "startdate": "1",
            "enddate": "2",
        }

        mock_handler = MagicMock()
        mock_handler.process_webhook.return_value = ("OK", 200)

        with _patch_dependency("storage", MagicMock()):
            with _patch_dependency("withings_client", MagicMock()):
                with patch("function_app.WithingsHandler", return_value=mock_handler):
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

        mock_handler = MagicMock()
        mock_handler.process_webhook.return_value = ("OK", 200)

        with _patch_dependency("storage", MagicMock()):
            with _patch_dependency("withings_client", MagicMock()):
                with patch("function_app.WithingsHandler", return_value=mock_handler):
                    response = function_app.withings_webhook(req)

        assert response.status_code == 200


class TestIngestionHelpersAndFlow:
    def test_ingest_fit_payload_missing_file_content(self):
        payload = {
            "athlete_id": "rob",
        }

        with _patch_dependency("storage", MagicMock()):
            body, status_code = function_app.dependencies.ingest_fit_payload(payload)

        assert status_code == 400
        assert body["error"] == "No file content"

    def test_ingest_fit_payload_success(self):
        payload = {
            "athlete_id": "rob",
            "source_file_name": "file.fit",
            "file_content_b64": base64.b64encode(b"data").decode("utf-8"),
        }

        mock_storage = MagicMock()
        mock_storage.get_ingestion_state.return_value = None
        mock_storage.store_workout.return_value = "workout-456"
        mock_context = MagicMock()
        mock_context.should_skip.return_value = False
        mock_context.existing_state = None
        mock_storage.get_ingestion_context.return_value = mock_context

        mock_parser = MagicMock()
        mock_parser.parse.return_value = {
            "sport": "Cycling",
            "duration_sec": 3600,
            "start_time_utc": "2026-01-01T10:00:00Z",
            "pwr_avg_watts": 220,
            "hr_avg_bpm": 150,
        }

        with patch("FitParser.handlers.fit_payload_handler.compute_file_hash", return_value="hash"):
            with _patch_dependency("storage", mock_storage):
                with patch("FitParser.handlers.ingestion_base_handler.FitParser", return_value=mock_parser):
                    body, status_code = function_app.dependencies.ingest_fit_payload(payload)

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
        req.get_json.return_value = {"days": 7, "athlete_id": "rob", "async": False}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"status": "success"}, 200)

        with _patch_dependency("onedrive_service", MagicMock()):
            with patch("function_app.OneDriveSyncHandler", return_value=mock_handler) as handler_cls:
                response = function_app.onedrive_sync_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        handler_cls.assert_called_once()
        mock_handler.handle.assert_called_once()

    def test_onedrive_sync_http_defaults_sync(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"days": 7, "athlete_id": "rob"}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"status": "success"}, 200)

        with _patch_dependency("onedrive_service", MagicMock()):
            with patch("function_app.OneDriveSyncHandler", return_value=mock_handler):
                response = function_app.onedrive_sync_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        mock_handler.handle.assert_called_once()

    def test_onedrive_sync_http_async_query_param(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"days": 7, "athlete_id": "rob"}
        req.params = {"async": "true"}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"status": "queued"}, 202)

        with _patch_dependency("onedrive_service", MagicMock()):
            with patch("function_app.OneDriveSyncHandler", return_value=mock_handler):
                response = function_app.onedrive_sync_http(req)

        assert response.status_code == 202
        mock_handler.handle.assert_called_once()

    def test_onedrive_authorize_returns_url(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob"}

        mock_service = MagicMock()
        mock_service.build_authorize_url.return_value = "https://login.example.com/auth"

        with _patch_dependency("onedrive_service", mock_service):
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
        req.params = {"code": "auth-code", "state": "rob|token"}

        mock_service = MagicMock()

        with _patch_dependency("onedrive_service", mock_service):
            response = function_app.onedrive_callback(req)

        assert response.status_code == 200
        mock_service.complete_authorization.assert_called_once_with(
            athlete_id="rob", code="auth-code"
        )
