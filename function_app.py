"""Azure Functions app - Process FIT files from external sources."""

import base64
import json
import logging
import os
import secrets
import threading
import tempfile
from datetime import datetime, timezone
from typing import Dict
from urllib.parse import urlparse

import azure.functions as func
from azure.core.exceptions import AzureError

from FitParser.config import Config
from FitParser.fit_parser import FitParser, compute_file_hash
from FitParser.table_storage import WorkoutTableStorage
from FitParser.semantic_layer import SemanticLayer
from FitParser.onedrive_client import OneDriveGraphError
from FitParser.onedrive_sync import OneDrivePersonalSyncService, OneDriveSyncConfig
from FitParser.withings_client import WithingsClient
from FitParser.backup_exporter import BackupExporter


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# pylint: disable=too-many-lines

JSON_CONTENT_TYPE = "application/json"
HTML_CONTENT_TYPE = "text/html"
ERR_VALIDATION = "Validation error: %s"
ERR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"
ERR_ATHLETE_ID_REQUIRED = "athlete_id parameter required"
ERR_INVALID_JSON = "Invalid JSON payload"

app = func.FunctionApp()

# Environment variable names and defaults for plugin metadata
ENV_API_DOCS_DIR = "API_DOCS_DIR"
ENV_PUBLIC_BASE_URL = "PUBLIC_BASE_URL"
ENV_PLUGIN_LOGO_URL = "PLUGIN_LOGO_URL"
ENV_PLUGIN_CONTACT_EMAIL = "PLUGIN_CONTACT_EMAIL"
ENV_PLUGIN_LEGAL_URL = "PLUGIN_LEGAL_URL"

API_DOCS_DIR = os.getenv(ENV_API_DOCS_DIR, os.path.join(
    os.path.dirname(__file__), "api_docs"))
PLUGIN_MANIFEST_PATH = os.path.join(API_DOCS_DIR, "ai-plugin.json")
OPENAPI_SPEC_PATH = os.path.join(API_DOCS_DIR, "openapi.yaml")

DEFAULT_LOGO_URL = "https://via.placeholder.com/128.png?text=Health+Assistant"
DEFAULT_CONTACT_EMAIL = "rbarrimond+health-assistant@users.noreply.github.com"
DEFAULT_LEGAL_URL = "https://github.com/rbarrimond/health_assistant/blob/main/README.md"

# Initialize and warm up table storage on host start (idempotent table creation).
# pylint: disable=invalid-name  # These are mutable singletons, not constants
_storage_singleton = None
_semantic_layer_singleton = None

try:
    _storage_singleton = WorkoutTableStorage()
    _semantic_layer_singleton = SemanticLayer(_storage_singleton)
    logger.info("Table storage and semantic layer initialized on startup")
except (ValueError, AzureError, OSError) as _e:
    # Don't crash host; function will attempt again on first request.
    logger.warning("Table storage init deferred: %s", _e)


def _public_base_url(req: func.HttpRequest) -> str:
    """Return the externally reachable base URL, overridable via env."""
    override = os.getenv(ENV_PUBLIC_BASE_URL)
    if override:
        return override.rstrip("/")

    parsed = urlparse(req.url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _read_text_file(path: str) -> str:
    """Read a text file with utf-8 encoding."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _response_missing_file(name: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": f"{name} not found"}),
        status_code=500,
        mimetype=JSON_CONTENT_TYPE,
    )


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """
    Health check endpoint with dependency verification.

    Returns 200 OK if all critical dependencies are operational.
    Returns 503 Service Unavailable if any dependency check fails.
    """
    checks = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    status_code = 200

    # Check table storage connectivity (non-blocking)
    try:
        storage = _get_storage_instance()
        # Lightweight operation to verify connectivity
        # List tables to confirm service client is operational
        list(storage.service_client.list_tables(results_per_page=1))
        checks["storage"] = "ok"
    except Exception:  # pylint: disable=broad-except
        # Storage unavailable but don't expose details
        checks["storage"] = "degraded"
        checks["status"] = "degraded"
        status_code = 503

    return func.HttpResponse(
        json.dumps(checks),
        status_code=status_code,
        mimetype=JSON_CONTENT_TYPE
    )


@app.route(route=".well-known/ai-plugin.json", methods=["GET"])
def serve_ai_plugin_manifest(req: func.HttpRequest) -> func.HttpResponse:
    """Serve ChatGPT Actions plugin manifest with dynamic OpenAPI URL."""
    try:
        manifest = json.loads(_read_text_file(PLUGIN_MANIFEST_PATH))
    except FileNotFoundError:
        return _response_missing_file("ai-plugin.json")
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        logger.error("ai-plugin.json invalid: %s", exc)
        return func.HttpResponse(
            json.dumps({"error": "ai-plugin.json invalid"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE,
        )

    base_url = _public_base_url(req)

    # Populate dynamic metadata from environment or defaults
    manifest.setdefault("api", {})["url"] = f"{base_url}/openapi.yaml"
    manifest["logo_url"] = os.getenv(
        ENV_PLUGIN_LOGO_URL, manifest.get("logo_url", DEFAULT_LOGO_URL)
    )
    manifest["contact_email"] = os.getenv(
        ENV_PLUGIN_CONTACT_EMAIL,
        manifest.get("contact_email", DEFAULT_CONTACT_EMAIL)
    )
    manifest["legal_info_url"] = os.getenv(
        ENV_PLUGIN_LEGAL_URL,
        manifest.get("legal_info_url", DEFAULT_LEGAL_URL)
    )

    return func.HttpResponse(
        json.dumps(manifest),
        status_code=200,
        mimetype=JSON_CONTENT_TYPE,
    )


@app.route(route="openapi.yaml", methods=["GET"])
def serve_openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    """Serve OpenAPI specification with dynamic server URL."""
    try:
        spec_body = _read_text_file(OPENAPI_SPEC_PATH)
    except FileNotFoundError:
        return _response_missing_file("openapi.yaml")

    # Replace placeholder server URL with actual public base URL
    base_url = _public_base_url(req)
    spec_body = spec_body.replace(
        "https://health-assistant.azurewebsites.net",
        base_url
    )

    return func.HttpResponse(
        spec_body,
        status_code=200,
        mimetype="application/x-yaml",
    )


# =============================================================================
# Physiometrics Endpoints
# =============================================================================

@app.route(route="physiometrics/current", methods=["GET"])
def get_current_physiometrics(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get current physiometric values for an athlete.

    GET /api/physiometrics/current?athlete_id=rob

    Returns:
        - 200 OK with current physiometric snapshot
        - 400 Bad Request if athlete_id missing
        - 500 Internal Error on failure
    """
    athlete_id = req.params.get("athlete_id")

    if not athlete_id:
        return func.HttpResponse(
            json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    try:
        layer = SemanticLayer()
        result = layer.get_current_physiometrics(athlete_id)

        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error getting current physiometrics: %s",
                     e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to retrieve physiometrics"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="physiometrics/history", methods=["GET"])
def get_physiometrics_history(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get time-series physiometrics data.

    GET /api/physiometrics/history?athlete_id=rob&metrics=weight_kg,cycling_vo2max_ml_kg_min&days=90

    Query parameters:
        athlete_id (required): Athlete identifier
        days (optional): Number of days to look back (default 90, max 365)
        metrics (optional): Comma-separated list of metrics (default: all)

    Returns:
        - 200 OK with time-series data
        - 400 Bad Request if athlete_id missing
        - 500 Internal Error on failure
    """
    athlete_id = req.params.get("athlete_id")

    if not athlete_id:
        return func.HttpResponse(
            json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    try:
        days = int(req.params.get("days", "90"))
        days = min(days, 365)  # Cap at 365

        metrics_param = req.params.get("metrics")
        metrics = metrics_param.split(",") if metrics_param else None

        layer = SemanticLayer()
        result = layer.get_physiometrics_trends(
            athlete_id=athlete_id,
            days=days,
            metrics=metrics
        )

        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error getting physiometrics history: %s",
                     e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to retrieve physiometrics history"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="physiometrics/update", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def update_physiometrics(req: func.HttpRequest) -> func.HttpResponse:
    """
    Update physiometric values (single metric or bulk partial update).

    POST /api/physiometrics/update
    Content-Type: application/json

    Single metric update:
    {
        "athlete_id": "rob",
        "metric": "cycling_vo2max_ml_kg_min",
        "value": 52.3,
        "effective_date": "2026-01-19",
        "source": "chatgpt"
    }

    Bulk partial update:
    {
        "athlete_id": "rob",
        "metrics": {
            "weight_kg": 75.2,
            "cycling_vo2max_ml_kg_min": 52.3
        },
        "effective_date": "2026-01-19",
        "source": "chatgpt"
    }

    Returns:
        - 200 OK with update confirmation
        - 400 Bad Request if payload invalid
        - 500 Internal Error on failure
    """
    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": ERR_INVALID_JSON}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    athlete_id = req_body.get("athlete_id")
    if not athlete_id:
        return func.HttpResponse(
            json.dumps({"error": "athlete_id required"}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    # Validate payload shape before initializing downstream dependencies.
    has_single_metric = "metric" in req_body and "value" in req_body
    has_bulk_metrics = "metrics" in req_body

    if not (has_single_metric or has_bulk_metrics):
        return func.HttpResponse(
            json.dumps(
                {"error": "Either 'metric'+'value' or 'metrics' dict required"}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    try:
        layer = SemanticLayer()
        effective_date = req_body.get("effective_date")
        source = req_body.get("source", "chatgpt")
        result: Dict = {"status": "error"}

        # Check if single metric update or bulk
        if has_single_metric:
            # Single metric update
            result = layer.update_physiometric_value(
                athlete_id=athlete_id,
                metric=req_body["metric"],
                value=req_body["value"],
                effective_date=effective_date,
                source=source
            )
        elif has_bulk_metrics:
            # Bulk update (update each metric individually)
            results = []
            for metric, value in req_body["metrics"].items():
                result = layer.update_physiometric_value(
                    athlete_id=athlete_id,
                    metric=metric,
                    value=value,
                    effective_date=effective_date,
                    source=source
                )
                results.append(result)
            result = {
                "status": "success",
                "updates": results
            }

        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error updating physiometrics: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to update physiometrics"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


# =============================================================================
# Withings OAuth & Webhook Endpoints
# =============================================================================

@app.route(route="withings/authorize", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def withings_authorize(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get Withings OAuth authorization URL.

    GET /api/withings/authorize?athlete_id=rob

    Returns:
        - 200 OK with authorization URL for user to open in browser
        - 400 Bad Request if athlete_id missing
        - 500 Internal Error on failure
    """
    athlete_id = req.params.get("athlete_id")

    if not athlete_id:
        return func.HttpResponse(
            json.dumps({"error": ERR_ATHLETE_ID_REQUIRED}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    try:
        client = WithingsClient()
        auth_url, _ = client.get_authorization_url(athlete_id)

        return func.HttpResponse(
            json.dumps({
                "authorization_url": auth_url,
                "instructions": "Open this URL in your browser to authorize Withings access",
                "athlete_id": athlete_id
            }),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error generating Withings auth URL: %s",
                     e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to generate authorization URL"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="withings/callback", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def withings_callback(req: func.HttpRequest) -> func.HttpResponse:
    """
    Handle Withings OAuth callback.

    GET /api/withings/callback?code=...&state=...

    Returns:
        - 200 OK with success HTML page
        - 400 Bad Request if code/state missing or invalid
        - 500 Internal Error on failure
    """
    code = req.params.get("code")
    state = req.params.get("state")

    if not code or not state:
        return func.HttpResponse(
            "<html><body><h1>Error</h1><p>Missing authorization code or state</p></body></html>",
            status_code=400,
            mimetype=HTML_CONTENT_TYPE
        )

    try:
        client = WithingsClient()
        storage = WorkoutTableStorage()

        # Exchange code for tokens
        token_data = client.exchange_auth_code(code, state)

        # Store tokens
        storage.store_withings_tokens(
            athlete_id=token_data["athlete_id"],
            withings_userid=str(token_data["userid"]),
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_in=token_data["expires_in"],
            scope=token_data["scope"]
        )

        # Subscribe to webhook notifications
        callback_url = os.getenv("WITHINGS_WEBHOOK_URL",
                                 f"{req.url.split('/api/')[0]}/api/withings/webhook")
        client.subscribe_to_notifications(
            access_token=token_data["access_token"],
            callback_url=callback_url
        )

        logger.info(
            "Successfully connected Withings for athlete %s (userid: %s)",
            token_data["athlete_id"], token_data["userid"]
        )

        success_html = f"""<html>
            <body>
                <h1>Success!</h1>
                <p>Withings connected for athlete {token_data['athlete_id']}.</p>
                <p>Weight measurements will now sync automatically.</p>
                <p>You can close this window and return to the chat.</p>
            </body>
            </html>"""

        return func.HttpResponse(
            success_html,
            status_code=200,
            mimetype=HTML_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error in Withings callback: %s", e, exc_info=True)
        error_html = (
            "<html><body><h1>Error</h1>"
            f"<p>Failed to connect Withings account: {e}</p>"
            "</body></html>"
        )
        return func.HttpResponse(
            error_html,
            status_code=500,
            mimetype=HTML_CONTENT_TYPE
        )


@app.route(route="withings/webhook", methods=["POST"])
def withings_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """
    Receive Withings webhook notifications.

    POST /api/withings/webhook
    Content-Type: application/x-www-form-urlencoded

    Form parameters:
        userid: Withings user ID
        appli: Notification type (1 = weight)
        startdate: Unix timestamp
        enddate: Unix timestamp

    Returns:
        - 200 OK (acknowledges webhook immediately)
        - 400 Bad Request if invalid payload
    """
    try:
        # Parse form data
        userid = req.form.get("userid")
        appli = req.form.get("appli")
        startdate = req.form.get("startdate")
        enddate = req.form.get("enddate")

        if not all([userid, appli, startdate, enddate]):
            logger.warning("Invalid Withings webhook payload: missing fields")
            return func.HttpResponse("Missing required fields", status_code=400)

        # Only process weight notifications (appli=1)
        if appli != "1":
            logger.info("Ignoring non-weight notification (appli=%s)", appli)
            return func.HttpResponse("OK", status_code=200)

        logger.info(
            "Received Withings webhook: userid=%s, startdate=%s, enddate=%s",
            userid, startdate, enddate
        )

        # Queue for async processing (Azure Queue integration pending); acknowledge now

        return func.HttpResponse("OK", status_code=200)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error processing Withings webhook: %s", e, exc_info=True)
        # Still return 200 to avoid Withings retry flood
        return func.HttpResponse("OK", status_code=200)


@app.route(route="workouts/{workout_id}/recalculated", methods=["GET"])
def get_workout_recalculated(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get workout with retroactively recalculated zones (read-only view).

    GET /api/workouts/{workout_id}/recalculated?ftp_watts=300&lthr_bpm=175

    Query parameters:
        ftp_watts (optional): Override FTP value
        lthr_bpm (optional): Override LTHR value

    Returns:
        - 200 OK with recalculated zone data (not implemented yet)
        - 404 Not Found if workout doesn't exist
        - 501 Not Implemented (placeholder)
    """
    workout_id = req.route_params.get("workout_id")

    if not workout_id:
        return func.HttpResponse(
            json.dumps({"error": "workout_id required"}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    try:
        # Extract override parameters
        ftp_watts = req.params.get("ftp_watts")
        lthr_bpm = req.params.get("lthr_bpm")

        override = {}
        if ftp_watts:
            override["ftp_watts"] = float(ftp_watts)
        if lthr_bpm:
            override["lthr_bpm"] = float(lthr_bpm)

        layer = SemanticLayer()
        result = layer.recalculate_workout_zones(
            workout_id=workout_id,
            physiometrics_override=override
        )

        return func.HttpResponse(
            json.dumps(result),
            status_code=501,  # Not Implemented
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error recalculating zones: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to recalculate zones"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="config/reload", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def reload_config(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Reload physiometrics configuration from disk.

    POST /config/reload

    Returns:
        - 200 OK with config details if reload succeeds
        - 404 Not Found if physiometrics.json does not exist
        - 500 Internal Error if JSON parsing fails
    """
    try:
        # Force reload from disk
        config_data = Config.load_physiometrics(force_reload=True)

        if config_data is None:
            logger.warning("Physiometrics file not found at %s",
                           Config.physiometrics_file())
            return func.HttpResponse(
                json.dumps({
                    "error": "Physiometrics file not found",
                    "path": str(Config.physiometrics_file())
                }),
                status_code=404,
                mimetype=JSON_CONTENT_TYPE
            )

        # Return current configuration
        hr_cfg = Config.hr_config()
        pwr_cfg = Config.power_config()

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "message": "Configuration reloaded from disk",
                "heart_rate": {
                    "basis": hr_cfg.basis,
                    "lthr_bpm": hr_cfg.lthr_bpm,
                    "hr_max_bpm": hr_cfg.hr_max_bpm,
                    "resting_hr_bpm": hr_cfg.resting_hr_bpm,
                },
                "power": {
                    "ftp_watts": pwr_cfg.ftp_watts,
                }
            }),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except json.JSONDecodeError as e:
        logger.error("JSON parsing error in physiometrics file: %s", e)
        return func.HttpResponse(
            json.dumps({
                "error": "Invalid JSON in physiometrics file",
                "details": str(e)
            }),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )
    except (OSError, IOError, ValueError, KeyError) as e:
        logger.error("Error reloading config: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Failed to reload configuration",
                "details": str(e)
            }),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="config/update", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def update_config(req: func.HttpRequest) -> func.HttpResponse:
    """Update physiometrics configuration via HTTP POST.

    POST /config/update
    Content-Type: application/json

    Request body:
    {
        "heart_rate": {
            "basis": "HRmax",
            "lthr_bpm": 175,
            "hr_max_bpm": 195,
            "resting_hr_bpm": 52,
            "zones": { ... }
        },
        "power": {
            "ftp_watts": 285,
            "zones": { ... }
        }
    }

    Returns:
        - 200 OK with saved config and timestamp on success
        - 400 Bad Request if JSON is invalid or missing fields
        - 500 Internal Error if save fails
    """
    try:
        req_body = req.get_json()
    except ValueError as e:
        logger.error("Invalid JSON in update request: %s", e)
        return func.HttpResponse(
            json.dumps({"error": ERR_INVALID_JSON}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    # Validate required sections
    if not isinstance(req_body, dict):
        return func.HttpResponse(
            json.dumps({"error": "Payload must be a JSON object"}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )

    try:
        # Save to Azure Table Storage
        timestamp = Config.save_physiometrics(req_body)

        # Load and return updated config
        hr_cfg = Config.hr_config()
        pwr_cfg = Config.power_config()

        logger.info("Configuration updated at %s", timestamp)

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "message": "Configuration saved to Azure Table Storage",
                "updated_at_utc": timestamp,
                "heart_rate": {
                    "basis": hr_cfg.basis,
                    "lthr_bpm": hr_cfg.lthr_bpm,
                    "hr_max_bpm": hr_cfg.hr_max_bpm,
                    "resting_hr_bpm": hr_cfg.resting_hr_bpm,
                },
                "power": {
                    "ftp_watts": pwr_cfg.ftp_watts,
                }
            }),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error("Validation error updating config: %s", e)
        return func.HttpResponse(
            json.dumps({
                "error": "Failed to update configuration",
                "details": str(e)
            }),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )
    except (OSError, IOError, KeyError) as e:
        logger.error("Error updating config: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Unexpected error updating configuration",
                "details": str(e)
            }),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="config/history", methods=["GET"])
def config_history(req: func.HttpRequest) -> func.HttpResponse:
    """Get physiometrics configuration change history.

    GET /config/history?limit=10

    Query parameters:
        limit: Maximum number of entries to return (default 10, max 50)

    Returns:
        - 200 OK with list of config changes (newest first)
        - 500 Error if retrieval fails
    """
    try:
        limit = req.params.get("limit", "10")
        try:
            limit = min(int(limit), 50)  # Cap at 50
        except ValueError:
            limit = 10

        history = Config.get_physiometrics_history(limit=limit)

        # Transform for readability
        result = []
        for entry in history:
            result.append({
                "updated_at_utc": entry.get("RowKey"),
                "heart_rate": {
                    "basis": entry.get("heart_rate_basis"),
                    "lthr_bpm": entry.get("heart_rate_lthr_bpm"),
                    "hr_max_bpm": entry.get("heart_rate_hr_max_bpm"),
                    "resting_hr_bpm": entry.get("heart_rate_resting_bpm"),
                },
                "power": {
                    "ftp_watts": entry.get("power_ftp_watts"),
                }
            })

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "count": len(result),
                "history": result
            }),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except (ValueError, OSError, KeyError) as e:
        logger.error("Error retrieving config history: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({
                "error": "Failed to retrieve configuration history",
                "details": str(e)
            }),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


def parse_ingest_payload(req: func.HttpRequest) -> Dict:
    """
    Parse ingestion payload from an external file source.

    Expected format:
    {
        "athlete_id": "rob",
        "source_item_id": "onedrive_item_id",
        "source_file_name": "2026-01-07-xyz.fit",
        "source_file_path": "/Apps/HealthFit/2026-01-07-xyz.fit",
        "source_drive_id": "drive_id",
        "file_content_b64": "base64_encoded_fit_file_content",
        "file_size_bytes": 12345
    }
    """
    try:
        req_body = req.get_json()
    except ValueError as exc:
        raise ValueError(ERR_INVALID_JSON) from exc

    required_fields = ["athlete_id", "source_file_name", "file_content_b64"]
    missing = [f for f in required_fields if f not in req_body]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    return req_body


def _decode_fit_file_content(file_content_b64: str) -> bytes:
    """Decode base64 FIT file content.

    Args:
        file_content_b64: Base64-encoded file content

    Returns:
        Decoded file bytes

    Raises:
        ValueError: If base64 decoding fails
    """
    try:
        return base64.b64decode(file_content_b64)
    except (TypeError, ValueError) as e:
        logger.error("Failed to decode base64 file content: %s", e)
        raise ValueError("Invalid base64 encoding") from e


def _get_storage_instance():
    """Get storage singleton or create new instance."""
    if '_storage_singleton' in globals() and _storage_singleton:
        return _storage_singleton
    return WorkoutTableStorage()


def _build_source_info(payload: Dict, file_sha256: str, file_size: int) -> Dict:
    """Build source information dictionary from payload."""
    return {
        "source_system": "HealthFit",
        "source_file_name": payload.get("source_file_name"),
        "source_file_path": payload.get("source_file_path", ""),
        "source_item_id": payload.get("source_item_id"),
        "source_drive_id": payload.get("source_drive_id"),
        "source_etag": payload.get("source_etag"),
        "file_size_bytes": payload.get("file_size_bytes", file_size),
        "file_sha256": file_sha256,
    }


def _build_success_body(workout_id: str, athlete_id: str, metrics: Dict) -> Dict:
    """Build success response body for ingested workout."""
    return {
        "status": "success",
        "workout_id": workout_id,
        "athlete_id": athlete_id,
        "sport": metrics.get("sport"),
        "duration_sec": metrics.get("duration_sec"),
        "metrics": {
            "distance_m": metrics.get("distance_m"),
            "avg_power_watts": metrics.get("pwr_avg_watts"),
            "avg_hr_bpm": metrics.get("hr_avg_bpm"),
        }
    }


def _validate_ingest_payload(payload: Dict) -> Dict:
    """Validate ingestion payload and return it back."""
    required_fields = ["athlete_id", "source_file_name", "file_content_b64"]
    missing = [f for f in required_fields if f not in payload]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")
    return payload


def _ingest_fit_payload(payload: Dict) -> tuple[Dict, int]:
    """Ingest a FIT payload and return (response_body, status_code)."""
    # pylint: disable=too-many-locals
    payload = _validate_ingest_payload(payload)
    logger.info("Processing file: %s", payload.get("source_file_name"))

    athlete_id = payload["athlete_id"]

    # Decode and write to temp file
    try:
        file_content = _decode_fit_file_content(payload["file_content_b64"])
    except ValueError as e:
        return {"error": str(e)}, 400

    with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        # Check for duplicate
        file_sha256 = compute_file_hash(tmp_path)
        logger.info("File SHA256: %s", file_sha256)

        storage = _get_storage_instance()
        file_key = payload.get("source_item_id") or file_sha256
        existing = storage.get_ingestion_state(athlete_id, file_key)

        if existing and existing.get("status") == "ingested":
            logger.info("File already ingested: %s", file_key)
            return {
                "status": "skipped",
                "reason": "File already processed",
                "workout_id": existing.get("workout_id")
            }, 200

        # Parse and store
        metrics = FitParser(tmp_path).parse()
        logger.info("Parsed metrics: %s", list(metrics.keys()))

        source_info = _build_source_info(
            payload, file_sha256, len(file_content))
        workout_id = storage.store_workout(athlete_id, metrics, source_info)

        storage.record_ingestion_state(
            athlete_id,
            {**source_info,
                "first_seen_at_utc": metrics.get("start_time_utc")},
            status="ingested",
            workout_id=workout_id
        )

        logger.info("Successfully ingested workout %s", workout_id)
        return _build_success_body(workout_id, athlete_id, metrics), 200

    except (ValueError, OSError, IOError) as e:
        logger.error("Error parsing or storing FIT file: %s", e, exc_info=True)
        _record_failed_ingestion(athlete_id, payload, str(e))
        return {"error": f"Failed to process FIT file: {str(e)}"}, 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _record_failed_ingestion(athlete_id: str, payload: Dict, error: str):
    """Record failed ingestion state (best effort)."""
    try:
        storage = _get_storage_instance()
        storage.record_ingestion_state(
            athlete_id,
            payload,
            status="failed",
            error=error
        )
    except (ValueError, OSError, IOError):
        pass  # Already logging main error


@app.function_name("ProcessFitFiles")
@app.route(route="process_fit", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def process_fit_files(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered function to process FIT files from external sources.

    Process flow:
    1. Parse incoming file payload
    2. Save file temporarily
    3. Parse FIT file for metrics
    4. Store workout data in Azure Tables
    5. Record ingestion state for idempotency
    """
    logger.info("FIT file ingestion function triggered")

    try:
        payload = parse_ingest_payload(req)
        body, status_code = _ingest_fit_payload(payload)
        return func.HttpResponse(
            json.dumps(body),
            status_code=status_code,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error(ERR_VALIDATION, e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )
    except (OSError, IOError) as e:
        logger.error("System error: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "System error processing request"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


# =============================================================================
# OneDrive Personal Sync (Timer + HTTP)
# =============================================================================

def _get_onedrive_sync_service() -> OneDrivePersonalSyncService:
    config = OneDriveSyncConfig.from_env()
    storage = _get_storage_instance()
    return OneDrivePersonalSyncService(
        config=config,
        storage=storage,
        ingest_payload_fn=_ingest_fit_payload,
    )


@app.route(route="onedrive/authorize", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def onedrive_authorize(req: func.HttpRequest) -> func.HttpResponse:
    """Generate OneDrive OAuth authorization URL."""
    athlete_id = req.params.get("athlete_id") or os.getenv(
        "DEFAULT_ATHLETE_ID", "rob")
    state = f"{athlete_id}:{secrets.token_urlsafe(16)}"
    service = _get_onedrive_sync_service()
    authorization_url = service.build_authorize_url(state=state)
    return func.HttpResponse(
        json.dumps({
            "authorization_url": authorization_url,
            "athlete_id": athlete_id,
            "state": state,
        }),
        status_code=200,
        mimetype=JSON_CONTENT_TYPE,
    )


@app.route(route="onedrive/callback", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def onedrive_callback(req: func.HttpRequest) -> func.HttpResponse:
    """OAuth callback endpoint for OneDrive authorization."""
    code = req.params.get("code")
    state = req.params.get("state", "")
    athlete_id = state.split(":", 1)[0] if state else os.getenv(
        "DEFAULT_ATHLETE_ID", "rob")

    if not code:
        return func.HttpResponse(
            "Missing authorization code.",
            status_code=400,
            mimetype="text/plain",
        )

    try:
        service = _get_onedrive_sync_service()
        service.complete_authorization(athlete_id=athlete_id, code=code)
        html = f"""
        <html>
          <body>
            <h2>OneDrive Connected</h2>
            <p>Authorization complete for athlete {athlete_id}.</p>
          </body>
        </html>
        """
        return func.HttpResponse(html, status_code=200, mimetype="text/html")
    except (ValueError, OneDriveGraphError) as exc:
        logger.error("OneDrive auth failed: %s", exc)
        return func.HttpResponse(
            json.dumps({"error": str(exc)}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE,
        )


@app.route(route="onedrive/sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def onedrive_sync_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered OneDrive sync."""
    try:
        req_body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        req_body = {}

    async_flag = req.params.get("async")
    async_flag = async_flag or (req_body.get("async") if isinstance(req_body, dict) else None)
    if async_flag is None:
        async_flag = False
    else:
        async_flag = str(async_flag).lower() in {"1", "true", "yes", "y"}

    athlete_id = req_body.get("athlete_id") if isinstance(
        req_body, dict) else None
    athlete_id = athlete_id or os.getenv("DEFAULT_ATHLETE_ID", "rob")

    lookback_days = req_body.get(
        "days") if isinstance(req_body, dict) else None
    service = _get_onedrive_sync_service()
    try:
        lookback_days = int(
            lookback_days) if lookback_days is not None else service.config.lookback_days
    except ValueError:
        lookback_days = service.config.lookback_days

    if async_flag:
        def _run_sync() -> None:
            try:
                result = service.sync(
                    athlete_id=athlete_id, lookback_days=lookback_days)
                logger.info("OneDrive async sync result: %s", result)
            except (ValueError, OneDriveGraphError) as exc:
                logger.error("OneDrive async sync failed: %s", exc, exc_info=True)

        threading.Thread(target=_run_sync, daemon=True).start()
        return func.HttpResponse(
            json.dumps({
                "status": "queued",
                "athlete_id": athlete_id,
                "lookback_days": lookback_days,
                "folder_path": service.config.folder_path,
                "mode": "async",
                "queued_at_utc": datetime.now(timezone.utc).isoformat()
            }),
            status_code=202,
            mimetype=JSON_CONTENT_TYPE
        )

    try:
        result = service.sync(athlete_id=athlete_id,
                              lookback_days=lookback_days)
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )
    except (ValueError, OneDriveGraphError) as exc:
        logger.error("OneDrive sync failed: %s", exc)
        return func.HttpResponse(
            json.dumps({"status": "error", "error": str(exc)}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.timer_trigger(arg_name="timer", schedule="0 0 * * * *")  # hourly
def onedrive_sync_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered OneDrive sync."""
    if timer.past_due:
        logger.warning("OneDrive sync timer is past due")

    athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
    try:
        service = _get_onedrive_sync_service()
        result = service.sync(athlete_id=athlete_id,
                              lookback_days=service.config.lookback_days)
        logger.info("OneDrive sync result: %s", result)
    except (ValueError, OneDriveGraphError) as exc:
        logger.error("OneDrive sync failed: %s", exc, exc_info=True)


# =============================================================================
# Semantic Access Layer Endpoints
# =============================================================================


@app.route(route="planning/context", methods=["GET"])
def planning_context(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get planning context for training decisions.

    The single most important endpoint - answers:
    "Given what I've actually done, what does tomorrow look like?"

    GET /api/planning/context?athlete_id=rob&days=45

    Query parameters:
        athlete_id: Athlete identifier (required)
        days: Number of days to look back (default 45)

    Returns:
        - 200 OK with planning context payload
        - 400 Bad Request if athlete_id missing
        - 500 Error if retrieval fails
    """
    try:
        athlete_id = req.params.get("athlete_id")
        if not athlete_id:
            return func.HttpResponse(
                json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        days = int(req.params.get("days", "45"))
        days = max(1, min(days, 365))  # Cap between 1-365 days

        # Get semantic layer instance
        if '_semantic_layer_singleton' in globals() and _semantic_layer_singleton:
            semantic = _semantic_layer_singleton
        else:
            semantic = SemanticLayer()

        context = semantic.get_planning_context(athlete_id, days)

        return func.HttpResponse(
            json.dumps(context, default=str),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error(ERR_VALIDATION, e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error retrieving planning context: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to retrieve planning context"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="workouts", methods=["GET"])
def list_workouts(req: func.HttpRequest) -> func.HttpResponse:
    """
    Query workouts with filters.

    GET /api/workouts?athlete_id=rob&since=2026-01-01&limit=50&sport=Cycling

    Query parameters:
        athlete_id: Athlete identifier (required)
        since: ISO date string (start of range, optional)
        until: ISO date string (end of range, optional)
        limit: Maximum workouts to return (default 50, max 200)
        sport: Filter by sport type (optional)

    Returns:
        - 200 OK with list of workout summaries
        - 400 Bad Request if athlete_id missing
        - 500 Error if retrieval fails
    """
    try:
        athlete_id = req.params.get("athlete_id")
        if not athlete_id:
            return func.HttpResponse(
                json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        since = req.params.get("since")
        until = req.params.get("until")
        limit = int(req.params.get("limit", "50"))
        limit = max(1, min(limit, 200))  # Cap between 1-200
        sport = req.params.get("sport")

        # Get semantic layer instance
        if '_semantic_layer_singleton' in globals() and _semantic_layer_singleton:
            semantic = _semantic_layer_singleton
        else:
            semantic = SemanticLayer()

        workouts = semantic.get_workouts(
            athlete_id, since=since, until=until, limit=limit, sport=sport
        )

        return func.HttpResponse(
            json.dumps({
                "athlete_id": athlete_id,
                "count": len(workouts),
                "workouts": workouts
            }, default=str),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error(ERR_VALIDATION, e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error listing workouts: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to list workouts"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="workouts/{workout_id}", methods=["GET"])
def get_workout(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get detailed workout data including time series.

    GET /api/workouts/{workout_id}?athlete_id=rob

    Route parameters:
        workout_id: Unique workout identifier

    Query parameters:
        athlete_id: Athlete identifier (required)

    Returns:
        - 200 OK with full workout data
        - 400 Bad Request if athlete_id missing
        - 404 Not Found if workout doesn't exist
        - 500 Error if retrieval fails
    """
    try:
        athlete_id = req.params.get("athlete_id")
        if not athlete_id:
            return func.HttpResponse(
                json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        workout_id = req.route_params.get("workout_id")
        if not workout_id:
            return func.HttpResponse(
                json.dumps({"error": "Missing workout_id in route"}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        # Get semantic layer instance
        if '_semantic_layer_singleton' in globals() and _semantic_layer_singleton:
            semantic = _semantic_layer_singleton
        else:
            semantic = SemanticLayer()

        workout = semantic.get_workout_detail(athlete_id, workout_id)

        if not workout:
            return func.HttpResponse(
                json.dumps({"error": "Workout not found"}),
                status_code=404,
                mimetype=JSON_CONTENT_TYPE
            )

        return func.HttpResponse(
            json.dumps(workout, default=str),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error(ERR_VALIDATION, e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error retrieving workout: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to retrieve workout"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="rollups/weekly", methods=["GET"])
def weekly_rollups(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get weekly rollup data.

    GET /api/rollups/weekly?athlete_id=rob&weeks=16

    Query parameters:
        athlete_id: Athlete identifier (required)
        weeks: Number of weeks to retrieve (default 16, max 52)

    Returns:
        - 200 OK with weekly rollup data
        - 400 Bad Request if athlete_id missing
        - 500 Error if retrieval fails
    """
    try:
        athlete_id = req.params.get("athlete_id")
        if not athlete_id:
            return func.HttpResponse(
                json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        weeks = int(req.params.get("weeks", "16"))
        weeks = max(1, min(weeks, 52))  # Cap between 1-52 weeks

        # Get semantic layer instance
        if '_semantic_layer_singleton' in globals() and _semantic_layer_singleton:
            semantic = _semantic_layer_singleton
        else:
            semantic = SemanticLayer()

        rollups = semantic.get_weekly_rollups(athlete_id, weeks)

        return func.HttpResponse(
            json.dumps({
                "athlete_id": athlete_id,
                "weeks": weeks,
                "count": len(rollups),
                "rollups": rollups
            }, default=str),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error(ERR_VALIDATION, e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error retrieving weekly rollups: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to retrieve weekly rollups"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="analysis/zones", methods=["GET"])
def zone_distribution(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get time-in-zone distribution for planning.

    GET /api/analysis/zones?athlete_id=rob&days=30

    Query parameters:
        athlete_id: Athlete identifier (required)
        days: Number of days to analyze (default 30, max 365)

    Returns:
        - 200 OK with zone distribution data
        - 400 Bad Request if athlete_id missing
        - 500 Error if retrieval fails
    """
    try:
        athlete_id = req.params.get("athlete_id")
        if not athlete_id:
            return func.HttpResponse(
                json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        days = int(req.params.get("days", "30"))
        days = max(1, min(days, 365))  # Cap between 1-365 days

        # Get semantic layer instance
        if '_semantic_layer_singleton' in globals() and _semantic_layer_singleton:
            semantic = _semantic_layer_singleton
        else:
            semantic = SemanticLayer()

        distribution = semantic.get_zone_distribution(athlete_id, days)

        return func.HttpResponse(
            json.dumps(distribution, default=str),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error(ERR_VALIDATION, e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error analyzing zones: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to analyze zone distribution"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="analysis/efficiency", methods=["GET"])
def efficiency_trends(req: func.HttpRequest) -> func.HttpResponse:
    """
    Get aerobic efficiency and decoupling trends.

    GET /api/analysis/efficiency?athlete_id=rob&days=90

    Query parameters:
        athlete_id: Athlete identifier (required)
        days: Number of days to analyze (default 90, max 365)

    Returns:
        - 200 OK with efficiency trend data
        - 400 Bad Request if athlete_id missing
        - 500 Error if retrieval fails
    """
    try:
        athlete_id = req.params.get("athlete_id")
        if not athlete_id:
            return func.HttpResponse(
                json.dumps({"error": ERR_MISSING_ATHLETE_ID}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        days = int(req.params.get("days", "90"))
        days = max(1, min(days, 365))  # Cap between 1-365 days

        # Get semantic layer instance
        if '_semantic_layer_singleton' in globals() and _semantic_layer_singleton:
            semantic = _semantic_layer_singleton
        else:
            semantic = SemanticLayer()

        trends = semantic.get_efficiency_trends(athlete_id, days)

        return func.HttpResponse(
            json.dumps(trends, default=str),
            status_code=200,
            mimetype=JSON_CONTENT_TYPE
        )

    except ValueError as e:
        logger.error(ERR_VALIDATION, e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype=JSON_CONTENT_TYPE
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error analyzing efficiency: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to analyze efficiency trends"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


# =============================================================================
# Daily Backup Export (Timer Trigger)
# =============================================================================

@app.timer_trigger(arg_name="timer", schedule="0 2 * * *")  # 2 AM UTC daily
def backup_export_timer(timer: func.TimerRequest) -> None:
    """Daily timer-triggered backup export to read-only blob storage.

    Schedule: 0 2 * * * = 2 AM UTC every day
    Output: JSON blobs in backups/ container, organized by date
    Lifecycle: Move to cool tier after 30 days, delete after 90 days
    """
    if timer.past_due:
        logger.warning("Backup export timer is past due")

    try:
        logger.info("Starting daily backup export at %s",
                    datetime.now(timezone.utc).isoformat())

        # Ensure storage is initialized
        if _storage_singleton is None:
            logger.error("Storage singleton not initialized")
            return

        # Perform export
        exporter = BackupExporter(_storage_singleton)
        result = exporter.export_all_tables()

        if result.get("status") == "success":
            logger.info("Backup export completed successfully: %s", result)
        else:
            logger.error("Backup export failed: %s", result.get("error"))

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Timer trigger backup export failed: %s",
                     e, exc_info=True)
