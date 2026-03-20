"""Additional coverage for function_app helpers and endpoints."""

# pyright: reportPrivateUsage=false, reportPrivateImportUsage=false
# pylint: disable=line-too-long,protected-access,missing-function-docstring,missing-class-docstring,no-member

import base64
import json
import os
from unittest.mock import MagicMock, PropertyMock, call, patch

import azure.functions as func

import function_app
from config.constants import ENV_PUBLIC_BASE_URL
from TrainingAnalyticsPlatform.platform.dependencies import FunctionAppDependencies
from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import (
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
        monkeypatch.setenv(function_app.ENV_PLUGIN_LOGO_URL,
                           "https://logo.example.com")
        monkeypatch.setenv(
            function_app.ENV_PLUGIN_CONTACT_EMAIL, "support@example.com")
        monkeypatch.setenv(function_app.ENV_PLUGIN_LEGAL_URL,
                           "https://legal.example.com")

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
        mock_handler.get_openapi_spec.assert_called_once_with(
            "https://api.example.com")

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
        req.get_body.return_value = json.dumps({"athlete_id": "rob"}).encode("utf-8")
        req.headers = {
            "Content-Type": "application/json",
            "x-correlation-id": "corr-update-1",
        }
        req.params = {}
        req.route_params = {}

        response = function_app.update_physiometrics(req)

        assert response.status_code == 400
        body = json.loads(response.get_body())
        assert body["error_code"] == "BAD_REQUEST"
        assert body["correlation_id"] == "corr-update-1"
        assert body["operation"] == "update_physiometrics"
        assert body["athlete_id"] == "rob"
        assert "Either 'metric'+'value' or 'metrics' dict required" in body["error"]


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


class TestWeeklyRollupOperations:
    def test_weekly_rollup_timer_uses_all_detected_athletes(self):
        timer = MagicMock(spec=func.TimerRequest)
        timer.past_due = False

        mock_semantic = MagicMock()
        mock_semantic.list_athletes_with_workouts.return_value = ["rob", "sam"]
        mock_semantic.compute_and_persist_previous_week_rollups.return_value = {
            "status": "success",
            "message": "Weekly rollup persistence completed successfully",
            "results": [
                {"athlete_id": "rob", "status": "success", "message": "ok", "weeks": []},
                {"athlete_id": "sam", "status": "success", "message": "ok", "weeks": []},
            ],
        }
        mock_presync = MagicMock()
        mock_presync.run.return_value = {
            "enabled": True,
            "lookback_days": 8,
            "status": "success",
            "message": "Weekly rollup pre-sync completed",
            "sources": [],
        }

        with _patch_dependency("semantic_layer", mock_semantic):
            with _patch_dependency("weekly_rollup_pre_sync_service", mock_presync):
                function_app.weekly_rollup_timer(timer)

        mock_semantic.compute_and_persist_previous_week_rollups.assert_called_once_with(
            athlete_ids=["rob", "sam"]
        )
        mock_presync.run.assert_has_calls(
            [
                call(athlete_id="rob", enabled=True),
                call(athlete_id="sam", enabled=True),
            ]
        )

    def test_force_weekly_rollups_endpoint_single_athlete(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"athlete_id": "rob", "weeks": 4}
        req.params = {}

        mock_semantic = MagicMock()
        mock_semantic.compute_and_persist_previous_week_rollups.return_value = {
            "status": "success",
            "message": "Weekly rollup persistence completed successfully",
            "results": [
                {
                    "athlete_id": "rob",
                    "status": "success",
                    "message": "All requested week rollups persisted successfully",
                    "weeks": [
                        {
                            "weeks_ago": 1,
                            "status": "success",
                            "message": "Weekly rollup persisted",
                        }
                    ],
                }
            ],
        }

        with _patch_dependency("semantic_layer", mock_semantic):
            response = function_app.force_weekly_rollups(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        assert len(body["results"]) == 1
        mock_semantic.compute_and_persist_previous_week_rollups.assert_called_once_with(
            athlete_ids=["rob"],
            weeks=4,
        )

    def test_force_weekly_rollups_endpoint_all_athletes(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"all_athletes": True}
        req.params = {}

        mock_semantic = MagicMock()
        mock_semantic.list_athletes_with_workouts.return_value = ["rob", "sam"]
        mock_semantic.compute_and_persist_previous_week_rollups.return_value = {
            "status": "partial",
            "message": "Some requested week rollups failed",
            "results": [
                {"athlete_id": "rob", "status": "success", "message": "ok", "weeks": []},
                {"athlete_id": "sam", "status": "partial", "message": "partial", "weeks": []},
            ],
        }

        with _patch_dependency("semantic_layer", mock_semantic):
            response = function_app.force_weekly_rollups(req)

        assert response.status_code == 207
        body = json.loads(response.get_body())
        assert body["status"] == "partial"
        mock_semantic.compute_and_persist_previous_week_rollups.assert_called_once_with(
            athlete_ids=["rob", "sam"],
            weeks=1,
        )

    def test_force_weekly_rollups_endpoint_invalid_weeks(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"athlete_id": "rob", "weeks": 0}
        req.params = {}

        response = function_app.force_weekly_rollups(req)

        assert response.status_code == 400
        body = json.loads(response.get_body())
        assert "weeks" in body["error"]


class TestPlanningContextEndpoint:
    def test_planning_context_endpoint_calls_presync(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob", "days": "30"}

        mock_semantic = MagicMock()
        mock_semantic.query_planning_context = MagicMock(
            return_value=({"athlete_id": "rob"}, 200)
        )
        mock_presync = MagicMock()
        mock_presync.run.return_value = {
            "lookback_days": 30,
            "status": "all_succeeded",
            "message": "Planning context pre-sync completed successfully",
            "sources": [],
        }

        with _patch_dependency("semantic_layer", mock_semantic):
            with _patch_dependency("planning_context_pre_sync_service", mock_presync):
                with patch("function_app.QueryHandler") as handler_cls:
                    mock_handler = MagicMock()
                    mock_handler.query_planning_context.return_value = (
                        {"athlete_id": "rob"},
                        200,
                    )
                    handler_cls.return_value = mock_handler
                    response = function_app.planning_context(req)

        assert response.status_code == 200
        mock_presync.run.assert_called_once_with(athlete_id="rob", days=30)
        mock_handler.query_planning_context.assert_called_once_with("rob", 30)

    def test_planning_context_endpoint_continues_on_presync_failure(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob", "days": "45"}

        mock_presync = MagicMock()
        mock_presync.run.return_value = {
            "lookback_days": 45,
            "status": "failed",
            "message": "Planning context pre-sync failed for all sources",
            "sources": [
                {
                    "source": "garmin_activities",
                    "status": "failed",
                    "http_status": 429,
                    "message": "Rate limited",
                    "attempts": 3,
                    "duration_ms": 1200,
                }
            ],
        }

        with _patch_dependency("planning_context_pre_sync_service", mock_presync):
            with _patch_dependency("semantic_layer", MagicMock()):
                with patch("function_app.QueryHandler") as handler_cls:
                    mock_handler = MagicMock()
                    mock_handler.query_planning_context.return_value = (
                        {"athlete_id": "rob", "recent_workouts": []},
                        200,
                    )
                    handler_cls.return_value = mock_handler
                    response = function_app.planning_context(req)

        # Endpoint must return 200 regardless of pre-sync failure (best-available)
        assert response.status_code == 200
        mock_presync.run.assert_called_once_with(athlete_id="rob", days=45)
        mock_handler.query_planning_context.assert_called_once_with("rob", 45)


class TestDeferredRetryQueueProcessing:
    def test_process_deferred_retry_message_delegates_to_executor(self):
        mock_executor = MagicMock()

        with _patch_dependency("deferred_retry_executor", mock_executor):
            function_app._process_deferred_retry_message("{}")

        mock_executor.process_message.assert_called_once_with("{}")

    def test_process_deferred_retry_message_propagates_executor_failure(self):
        mock_executor = MagicMock()
        mock_executor.process_message.side_effect = RuntimeError("boom")

        with _patch_dependency("deferred_retry_executor", mock_executor):
            try:
                function_app._process_deferred_retry_message("{}")
                assert False, "Expected RuntimeError"
            except RuntimeError as exc:
                assert str(exc) == "boom"

    def test_queue_trigger_calls_processor(self):
        msg = MagicMock(spec=func.QueueMessage)
        msg.get_body.return_value = b'{"operation_id":"op-3"}'

        with patch("function_app._process_deferred_retry_message") as process_mock:
            function_app.process_deferred_retry(msg)

        process_mock.assert_called_once_with('{"operation_id":"op-3"}')

    def test_queue_trigger_propagates_processor_failure_for_host_retry(self):
        msg = MagicMock(spec=func.QueueMessage)
        msg.get_body.return_value = b'{"operation_id":"op-3"}'

        with patch(
            "function_app._process_deferred_retry_message",
            side_effect=RuntimeError("deferred-processing-failed"),
        ):
            with pytest.raises(RuntimeError, match="deferred-processing-failed"):
                function_app.process_deferred_retry(msg)


class TestAsyncIngestionQueueProcessing:
    def test_process_async_ingestion_message_delegates_to_executor(self):
        mock_executor = MagicMock()
        message = {
            "operation_id": "op-async-1",
            "source": "onedrive",
            "athlete_id": "rob",
            "lookback_days": 14,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
        }

        with _patch_dependency("async_ingestion_executor", mock_executor):
            function_app._process_async_ingestion_message(json.dumps(message))

        mock_executor.process_message.assert_called_once_with(json.dumps(message))

    def test_process_async_ingestion_message_propagates_executor_failure(self):
        mock_executor = MagicMock()
        mock_executor.process_message.side_effect = RuntimeError("boom")
        message = {
            "operation_id": "op-async-garmin-1",
            "source": "garmin",
            "athlete_id": "rob",
            "lookback_days": 21,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
            "context": {"force": True},
        }

        with _patch_dependency("async_ingestion_executor", mock_executor):
            try:
                function_app._process_async_ingestion_message(json.dumps(message))
                assert False, "Expected RuntimeError"
            except RuntimeError as exc:
                assert str(exc) == "boom"

    def test_process_async_ingestion_message_delegates_unsupported_source(self):
        mock_executor = MagicMock()
        message = {
            "operation_id": "op-async-2",
            "source": "polar",
            "athlete_id": "rob",
            "lookback_days": 14,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
        }

        with _patch_dependency("async_ingestion_executor", mock_executor):
            function_app._process_async_ingestion_message(json.dumps(message))

        mock_executor.process_message.assert_called_once_with(json.dumps(message))

    def test_async_ingestion_queue_trigger_calls_processor(self):
        msg = MagicMock(spec=func.QueueMessage)
        msg.get_body.return_value = b'{"operation_id":"op-async-3"}'

        with patch("function_app._process_async_ingestion_message") as process_mock:
            function_app.process_async_ingestion(msg)

        process_mock.assert_called_once_with('{"operation_id":"op-async-3"}')

    def test_async_ingestion_queue_trigger_propagates_processor_failure_for_host_retry(self):
        msg = MagicMock(spec=func.QueueMessage)
        msg.get_body.return_value = b'{"operation_id":"op-async-3"}'

        with patch(
            "function_app._process_async_ingestion_message",
            side_effect=RuntimeError("async-processing-failed"),
        ):
            with pytest.raises(RuntimeError, match="async-processing-failed"):
                function_app.process_async_ingestion(msg)

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
            body, status_code = function_app.dependencies.ingest_fit_payload(
                payload)

        assert status_code == 400
        assert body["error"] == "No file content"


class TestAsyncOperationStatusEndpoint:
    def test_get_async_operation_status_requires_operation_id(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob"}

        response = function_app.get_async_operation_status(req)

        assert response.status_code == 400

    def test_get_async_operation_status_returns_not_found(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob", "operation_id": "op-missing"}

        mock_storage = MagicMock()
        mock_async_ops = MagicMock()
        mock_storage.async_operations = mock_async_ops
        mock_async_ops.get_state.return_value = None

        with _patch_dependency("storage", mock_storage):
            response = function_app.get_async_operation_status(req)

        assert response.status_code == 404

    def test_get_async_operation_status_returns_state(self):
        req = MagicMock(spec=func.HttpRequest)
        req.params = {"athlete_id": "rob", "operation_id": "op-1"}

        mock_state = MagicMock()
        mock_state.athlete_id = "rob"
        mock_state.row_key = "op-1"
        mock_state.source = "onedrive"
        mock_state.lookback_days = 14
        mock_state.status = "succeeded"
        mock_state.mode = "async_queue"
        mock_state.queued_at_utc = "2026-03-19T00:00:00+00:00"
        mock_state.created_at_utc = "2026-03-19T00:00:01+00:00"
        mock_state.updated_at_utc = "2026-03-19T00:01:00+00:00"
        mock_state.request_id = None
        mock_state.correlation_id = None
        mock_state.context = {"source_system": "onedrive"}
        mock_state.result = {"ingested": 2}
        mock_state.error = None

        mock_storage = MagicMock()
        mock_async_ops = MagicMock()
        mock_storage.async_operations = mock_async_ops
        mock_async_ops.get_state.return_value = mock_state

        with _patch_dependency("storage", mock_storage):
            response = function_app.get_async_operation_status(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["operation_id"] == "op-1"
        assert body["status"] == "succeeded"

    def test_ingest_fit_payload_success(self):
        payload = {
            "athlete_id": "rob",
            "source_file_name": "file.fit",
            "file_content_b64": base64.b64encode(b"data").decode("utf-8"),
        }

        mock_storage = MagicMock()
        mock_storage.workouts = MagicMock()
        mock_storage.workouts.get_ingestion_state.return_value = None
        mock_storage.workouts.store_workout.return_value = "workout-456"
        mock_storage.workouts.store_canonical_records.return_value = "records.parquet"
        mock_context = MagicMock()
        mock_context.should_skip.return_value = False
        mock_context.existing_state = None
        mock_storage.workouts.get_ingestion_context.return_value = mock_context

        mock_model = MagicMock()
        from TrainingAnalyticsPlatform.models import CanonicalRecordSet
        
        mock_model.device_name = "Apple Watch"
        mock_model.device_manufacturer_code = None
        mock_model.device_product_code = None
        mock_model.validate_semantic_contract.return_value = None
        # Return structured metadata with semantic zones (schema 2.0.0)
        mock_model.build_canonical_metadata.return_value = {
            "identity": {
                "sport": "Cycling",
                "start_time_utc": "2026-01-01T10:00:00+00:00",
                "sub_sport": None,
                "duration_sec": 3600,
                "distance_m": 25000.0,
                "device_name": "Apple Watch",
                "device_source": "apple_watch",
            },
            "capabilities": {
                "has_power": True,
                "has_hr": True,
                "has_gps": True,
            },
            "session": {
                "avg_speed_mps": 6.94,
                "pwr_avg_watts": 220,
                "hr_avg_bpm": 150,
            },
            "file_metadata": {},
            "activity_metadata": {},
            "enrichment": {},
            "llm_analysis": {},
        }
        mock_model.build_canonical_records.return_value = CanonicalRecordSet(messages=[], start_dt=None)
        mock_model.build_laps_json.return_value = {"laps": []}
        mock_model.build_metadata_messages.return_value = {"metadata_schema_version": "1.0"}
        mock_model.build_fit_analysis.return_value = {"analysis": "data"}
        mock_model.raw_frames.return_value = '[]'  # JSON string of empty frames list
        mock_model.semantic_workout_id = "workout-456"

        with patch("TrainingAnalyticsPlatform.handlers.fit_payload_handler.compute_bytes_hash", return_value="hash"):
            with _patch_dependency("storage", mock_storage):
                with patch("TrainingAnalyticsPlatform.handlers.ingestion_base_handler.create_fit_model", return_value=mock_model):
                    body, status_code = function_app.dependencies.ingest_fit_payload(
                        payload)

        assert status_code == 200
        assert body["status"] == "success"
        mock_storage.workouts.record_ingestion_state.assert_called_once()


class TestOneDriveHelpersAndEndpoints:
    def test_onedrive_default_lookback_invalid(self, monkeypatch):
        monkeypatch.setenv(ONEDRIVE_CLIENT_ID, "client-id")
        monkeypatch.setenv(ONEDRIVE_CLIENT_SECRET, "client-secret")
        monkeypatch.setenv(ONEDRIVE_REDIRECT_URI,
                           "https://example.com/callback")
        monkeypatch.setenv(ONEDRIVE_SYNC_LOOKBACK_DAYS, "invalid")
        assert OneDriveSyncConfig.from_env().lookback_days == 30

    def test_onedrive_default_lookback_minimum(self, monkeypatch):
        monkeypatch.setenv(ONEDRIVE_CLIENT_ID, "client-id")
        monkeypatch.setenv(ONEDRIVE_CLIENT_SECRET, "client-secret")
        monkeypatch.setenv(ONEDRIVE_REDIRECT_URI,
                           "https://example.com/callback")
        monkeypatch.setenv(ONEDRIVE_SYNC_LOOKBACK_DAYS, "0")
        assert OneDriveSyncConfig.from_env().lookback_days == 1

    def test_onedrive_sync_http_calls_sync(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"days": 7,
                                     "athlete_id": "rob", "async": False}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"status": "success"}, 200)

        with _patch_dependency("onedrive_service", mock_handler):
            response = function_app.onedrive_sync_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        mock_handler.handle.assert_called_once()

    def test_onedrive_sync_http_defaults_sync(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"days": 7, "athlete_id": "rob"}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"status": "success"}, 200)

        with _patch_dependency("onedrive_service", mock_handler):
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

        with _patch_dependency("onedrive_service", mock_handler):
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

    def test_onedrive_sync_reset_http_single(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"athlete_id": "rob"}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle_reset.return_value = (
            {
                "status": "success",
                "scope": "single",
                "athlete_id": "rob",
                "reset_count": 1,
            },
            200,
        )

        with _patch_dependency("onedrive_service", mock_handler):
            response = function_app.onedrive_sync_reset_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        assert body["scope"] == "single"
        mock_handler.handle_reset.assert_called_once()

    def test_onedrive_sync_reset_http_bulk(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"all": True}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle_reset.return_value = (
            {
                "status": "success",
                "scope": "bulk",
                "reset_count": 2,
            },
            200,
        )

        with _patch_dependency("onedrive_service", mock_handler):
            response = function_app.onedrive_sync_reset_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["scope"] == "bulk"
        assert body["reset_count"] == 2
        mock_handler.handle_reset.assert_called_once()


class TestGarminEndpointHandlers:
    def test_garmin_sync_uses_lookback_days_from_body(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {
            "lookback_days": 30,
            "athlete_id": "rob",
            "async": False,
        }
        req.params = {}

        mock_handler = MagicMock()

        def _handle(sync_req):
            assert sync_req.lookback_days == 30
            assert sync_req.athlete_id == "rob"
            assert sync_req.async_mode is False
            return {"status": "success", "lookback_days": 30}, 200

        mock_handler.handle.side_effect = _handle

        with _patch_dependency("garmin_service", mock_handler):
            response = function_app.garmin_sync_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["lookback_days"] == 30
        mock_handler.handle.assert_called_once()

    def test_garmin_sync_uses_lookback_days_from_query_param(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"athlete_id": "rob"}
        req.params = {"lookback_days": "60", "async": "false"}

        mock_handler = MagicMock()

        def _handle(sync_req):
            assert sync_req.lookback_days == 60
            assert sync_req.athlete_id == "rob"
            assert sync_req.async_mode is False
            return {"status": "success", "lookback_days": 60}, 200

        mock_handler.handle.side_effect = _handle

        with _patch_dependency("garmin_service", mock_handler):
            response = function_app.garmin_sync_http(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["lookback_days"] == 60
        mock_handler.handle.assert_called_once()

    def test_garmin_sync_error_response_includes_operational_context(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {
            "athlete_id": "rob",
            "lookback_days": 14,
            "async": False,
        }
        req.get_body.return_value = json.dumps({
            "athlete_id": "rob",
            "lookback_days": 14,
            "async": False,
        }).encode("utf-8")
        req.headers = {
            "Content-Type": "application/json",
            "x-correlation-id": "corr-garmin-1",
        }
        req.params = {}
        req.route_params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"error": "Garmin API unavailable"}, 500)

        with _patch_dependency("garmin_service", mock_handler):
            response = function_app.garmin_sync_http(req)

        assert response.status_code == 500
        body = json.loads(response.get_body())
        assert body["error"] == "Garmin API unavailable"
        assert body["error_code"] == "INTERNAL_SERVER_ERROR"
        assert body["correlation_id"] == "corr-garmin-1"
        assert body["operation"] == "garmin_sync_http"
        assert body["source"] == "garmin"
        assert body["provider"] == "garmin"
        assert body["athlete_id"] == "rob"

    def test_garmin_physiometrics_partial_errors_include_error_details(self):
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {
            "athlete_id": "rob",
            "lookback_days": 1,
        }
        req.get_body.return_value = json.dumps({
            "athlete_id": "rob",
            "lookback_days": 1,
        }).encode("utf-8")
        req.headers = {
            "Content-Type": "application/json",
            "x-correlation-id": "corr-garmin-phys-1",
        }
        req.params = {}
        req.route_params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = (
            {
                "message": "Synced 0 Garmin physiometrics records",
                "count": 0,
                "records_fetched": 0,
                "records_processed": 0,
                "records_skipped": 0,
                "records_failed": 1,
                "errors": ["2026-03-03: garmin unavailable"],
            },
            207,
        )

        with _patch_dependency("garmin_physiometrics_service", mock_handler):
            response = function_app.garmin_physiometrics_sync_http(req)

        assert response.status_code == 207
        body = json.loads(response.get_body())
        assert body["correlation_id"] == "corr-garmin-phys-1"
        assert body["operation"] == "garmin_physiometrics_sync_http"
        assert body["source"] == "garmin"
        assert body["provider"] == "garmin"
        assert body["athlete_id"] == "rob"
        assert body["errors"] == ["2026-03-03: garmin unavailable"]
        assert len(body["error_details"]) == 1
        assert body["error_details"][0]["error"] == "2026-03-03: garmin unavailable"
        assert body["error_details"][0]["error_code"] == "OPERATIONAL_ERROR"
        assert body["error_details"][0]["correlation_id"] == "corr-garmin-phys-1"
        assert body["error_details"][0]["operation"] == "garmin_physiometrics_sync_http"


class TestIntervalsEndpointHandlers:
    """Tests for Intervals.icu sync endpoint ID splitting."""

    def test_intervals_sync_requires_intervals_athlete_id(self, monkeypatch):
        """Test that missing intervals_athlete_id returns 400."""
        monkeypatch.setenv("DEFAULT_ATHLETE_ID", "rob")
        monkeypatch.delenv("INTERVALS_ATHLETE_ID", raising=False)

        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"athlete_id": "rob"}
        req.params = {}

        response = function_app.intervals_sync_http(req)

        assert response.status_code == 400
        assert "intervals_athlete_id" in response.get_body().decode().lower()

    def test_intervals_sync_intervals_athlete_id_from_body(self, monkeypatch):
        """Test intervals_athlete_id from request body takes precedence."""
        monkeypatch.setenv("INTERVALS_ATHLETE_ID", "env_intervals")
        monkeypatch.setenv("DEFAULT_ATHLETE_ID", "default_storage")

        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {
            "intervals_athlete_id": "body_intervals",
            "athlete_id": "body_storage",
            "lookback_days": 30,
        }
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"count": 10}, 200)

        with _patch_dependency("intervals_service", mock_handler):
            response = function_app.intervals_sync_http(req)

        assert response.status_code == 200
        mock_handler.handle.assert_called_once()
        call_kwargs = mock_handler.handle.call_args[1]
        assert call_kwargs["intervals_athlete_id"] == "body_intervals"
        assert call_kwargs["athlete_id"] == "body_storage"
        assert call_kwargs["lookback_days"] == 30

    def test_intervals_sync_intervals_athlete_id_from_query_param(self, monkeypatch):
        """Test intervals_athlete_id from query param when body absent."""
        monkeypatch.setenv("INTERVALS_ATHLETE_ID", "env_intervals")
        monkeypatch.setenv("DEFAULT_ATHLETE_ID", "default_storage")

        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {}
        req.params = {
            "intervals_athlete_id": "query_intervals",
            "athlete_id": "query_storage",
            "lookback_days": "7",
        }

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"count": 5}, 200)

        with _patch_dependency("intervals_service", mock_handler):
            response = function_app.intervals_sync_http(req)

        assert response.status_code == 200
        call_kwargs = mock_handler.handle.call_args[1]
        assert call_kwargs["intervals_athlete_id"] == "query_intervals"
        assert call_kwargs["athlete_id"] == "query_storage"
        assert call_kwargs["lookback_days"] == 7

    def test_intervals_sync_intervals_athlete_id_from_env(self, monkeypatch):
        """Test intervals_athlete_id from env INTERVALS_ATHLETE_ID fallback."""
        monkeypatch.setenv("INTERVALS_ATHLETE_ID", "env_intervals")
        monkeypatch.setenv("DEFAULT_ATHLETE_ID", "default_storage")

        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"athlete_id": "custom_storage"}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"count": 1}, 200)

        with _patch_dependency("intervals_service", mock_handler):
            response = function_app.intervals_sync_http(req)

        assert response.status_code == 200
        call_kwargs = mock_handler.handle.call_args[1]
        assert call_kwargs["intervals_athlete_id"] == "env_intervals"
        assert call_kwargs["athlete_id"] == "custom_storage"

    def test_intervals_sync_athlete_id_defaults_to_default_athlete_id(
        self, monkeypatch
    ):
        """Test storage athlete_id defaults to DEFAULT_ATHLETE_ID."""
        monkeypatch.setenv("INTERVALS_ATHLETE_ID", "env_intervals")
        monkeypatch.setenv("DEFAULT_ATHLETE_ID", "default_storage")

        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"intervals_athlete_id": "i508584"}
        req.params = {}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"count": 0}, 200)

        with _patch_dependency("intervals_service", mock_handler):
            response = function_app.intervals_sync_http(req)

        assert response.status_code == 200
        call_kwargs = mock_handler.handle.call_args[1]
        assert call_kwargs["intervals_athlete_id"] == "i508584"
        assert call_kwargs["athlete_id"] == "default_storage"

    def test_intervals_sync_lookback_days_from_query_param(self, monkeypatch):
        """Test that lookback_days can come from query parameter."""
        monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i508584")
        monkeypatch.setenv("DEFAULT_ATHLETE_ID", "rob")

        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {}
        req.params = {"lookback_days": "60"}

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"count": 20}, 200)

        with _patch_dependency("intervals_service", mock_handler):
            response = function_app.intervals_sync_http(req)

        assert response.status_code == 200
        call_kwargs = mock_handler.handle.call_args[1]
        assert call_kwargs["intervals_athlete_id"] == "i508584"
        assert call_kwargs["athlete_id"] == "rob"
        assert call_kwargs["lookback_days"] == 60


class TestIntervalsTimerHandlers:
    def test_intervals_timer_uses_intervals_and_default_athlete_ids(self, monkeypatch):
        monkeypatch.setenv("INTERVALS_ATHLETE_ID", "env_intervals")
        monkeypatch.setenv("DEFAULT_ATHLETE_ID", "default_storage")

        timer = MagicMock(spec=func.TimerRequest)
        timer.past_due = False

        mock_handler = MagicMock()
        mock_handler.handle.return_value = ({"count": 0}, 200)

        with _patch_dependency("intervals_service", mock_handler):
            function_app.intervals_sync_timer(timer)

        mock_handler.handle.assert_called_once_with(
            intervals_athlete_id="env_intervals",
            athlete_id="default_storage",
        )

