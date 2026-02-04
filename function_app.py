"""Azure Functions app - HTTP adapter for FIT parsing and health analytics.

This module serves as the HTTP layer, delegating all business logic to handlers
in FitParser.handlers. All endpoints are thin wrappers that:
1. Parse HTTP request
2. Call appropriate handler
3. Return JSON response
"""

import base64
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast
from urllib.parse import urlparse

import azure.functions as func
from azure.core.exceptions import AzureError

from FitParser.backup_exporter import BackupExporter
from FitParser.onedrive_sync import (
    OneDrivePersonalSyncService,
    OneDriveSyncConfig,
)
from FitParser.fit_parser import FitParser, compute_file_hash
from FitParser.semantic_layer import SemanticLayer
from FitParser.table_storage import WorkoutTableStorage
from FitParser.withings_client import WithingsClient
from FitParser.handlers import (
    FitUploadHandler,
    OneDriveSyncHandler,
    OneDriveSyncRequest,
    QueryHandler,
    PhysiometricsHandler,
    WithingsHandler,
    ConfigHandler,
    HealthHandler,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

app = func.FunctionApp()

# ============================================================================
# Constants & Configuration
# ============================================================================

JSON_CONTENT_TYPE = "application/json"
HTML_CONTENT_TYPE = "text/html"
TEXT_PLAIN_CONTENT_TYPE = "text/plain"
INTERNAL_SERVER_ERROR = "Internal server error"

# Error messages
ERR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"
ERR_ATHLETE_ID_REQUIRED = "athlete_id parameter required"
ERR_INVALID_JSON = "Invalid JSON payload"
ERR_VALIDATION = "Validation error: %s"

# Plugin metadata environment variables
ENV_API_DOCS_DIR = "API_DOCS_DIR"
ENV_PUBLIC_BASE_URL = "PUBLIC_BASE_URL"
ENV_PLUGIN_LOGO_URL = "PLUGIN_LOGO_URL"
ENV_PLUGIN_CONTACT_EMAIL = "PLUGIN_CONTACT_EMAIL"
ENV_PLUGIN_LEGAL_URL = "PLUGIN_LEGAL_URL"

# Plugin metadata defaults
DEFAULT_LOGO_URL = "https://via.placeholder.com/128.png?text=Health+Assistant"
DEFAULT_CONTACT_EMAIL = "rbarrimond+health-assistant@users.noreply.github.com"
DEFAULT_LEGAL_URL = "https://github.com/rbarrimond/health_assistant/blob/main/README.md"

# API documentation paths
API_DOCS_DIR = os.getenv(ENV_API_DOCS_DIR, os.path.join(
    os.path.dirname(__file__), "api_docs"))
PLUGIN_MANIFEST_PATH = os.path.join(API_DOCS_DIR, "ai-plugin.json")
OPENAPI_SPEC_PATH = os.path.join(API_DOCS_DIR, "openapi.yaml")

# ============================================================================
# Utility Functions
# ============================================================================


def parse_ingest_payload(req: func.HttpRequest) -> Dict[str, Any]:
    """Parse FIT file ingestion payload from HTTP request.

    Extracts and validates required fields from the JSON request body.

    Args:
        req: Azure HttpRequest object

    Returns:
        Parsed payload dictionary with required fields

    Raises:
        ValueError: If required fields are missing
    """
    try:
        payload = req.get_json()

        # Validate required fields
        required_fields = ["athlete_id",
                           "source_file_name", "file_content_b64"]
        for field in required_fields:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")

        return payload
    except (ValueError, TypeError) as e:
        msg = f"Invalid payload: {str(e)}"
        raise ValueError(msg) from e

# ============================================================================
# Dependency Singletons
# ============================================================================


_storage_singleton: Optional[WorkoutTableStorage] = None
_semantic_layer_singleton: Optional[SemanticLayer] = None
_onedrive_service_singleton: Optional[OneDrivePersonalSyncService] = None

try:
    _storage_singleton = WorkoutTableStorage()
    _semantic_layer_singleton = SemanticLayer(_storage_singleton)
    logger.info("Storage and semantic layer initialized on startup")
except (ValueError, AzureError, OSError) as exc:
    logger.warning("Deferred initialization: %s", exc)


def _get_storage() -> WorkoutTableStorage:
    """Get storage singleton or create instance."""
    global _storage_singleton  # pylint: disable=global-statement
    if _storage_singleton is None:
        _storage_singleton = WorkoutTableStorage()
    return _storage_singleton


def _get_semantic_layer() -> SemanticLayer:
    """Get semantic layer singleton or create instance."""
    global _semantic_layer_singleton  # pylint: disable=global-statement
    if _semantic_layer_singleton is None:
        _semantic_layer_singleton = SemanticLayer(_get_storage())
    return _semantic_layer_singleton


def _ingest_fit_payload(payload: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
    """
    Ingest a FIT file payload from OneDrive sync.

    Args:
        payload: Dict with athlete_id, source_file_name, file_content_b64, etc.

    Returns:
        (response_dict, HTTP status_code)
    """
    athlete_id = payload.get("athlete_id", "rob")
    storage = _get_storage()
    source_info = None
    try:
        file_content_b64 = payload.get("file_content_b64")

        if not file_content_b64:
            return {"status": "error", "error": "No file content"}, 400

        # Decode base64 content
        file_content = base64.b64decode(file_content_b64)

        # Write temp file for processing
        with tempfile.NamedTemporaryFile(delete=False, suffix=".fit") as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            source_info = {
                "source_system": payload.get("source_system", "HealthFit"),
                "source_file_name": payload.get("source_file_name"),
                "source_file_path": payload.get("source_file_path"),
                "source_item_id": payload.get("source_item_id"),
                "source_drive_id": payload.get("source_drive_id"),
                "source_etag": payload.get("source_etag"),
                "file_size_bytes": payload.get("file_size_bytes"),
                "file_sha256": payload.get("file_sha256")
                or compute_file_hash(tmp_path),
            }

            # Parse and store with source info from payload
            parser = FitParser(tmp_path, source_file_name=source_info.get("source_file_name"))
            metrics = parser.parse()

            workout_id = storage.store_workout(
                athlete_id, metrics, source_info
            )
            storage.record_ingestion_state(
                athlete_id,
                source_info,
                status="ingested",
                workout_id=workout_id,
            )

            return {
                "status": "success",
                "workout_id": workout_id,
            }, 200
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except (ValueError, TypeError) as exc:
        logger.warning("FIT payload ingestion validation failed: %s", exc)
        if source_info:
            storage.record_ingestion_state(
                athlete_id,
                source_info,
                status="failed",
                error=str(exc),
            )
        return {"status": "error", "error": str(exc)}, 400
    except OSError as exc:
        logger.error("FIT payload file operation failed: %s", exc)
        if source_info:
            storage.record_ingestion_state(
                athlete_id,
                source_info,
                status="failed",
                error="File operation failed",
            )
        return {"status": "error", "error": "File operation failed"}, 500


def _get_onedrive_service() -> OneDrivePersonalSyncService:
    """Get OneDrive service singleton or create instance."""
    global _onedrive_service_singleton  # pylint: disable=global-statement
    if _onedrive_service_singleton is None:
        config = OneDriveSyncConfig.from_env()
        storage = _get_storage()
        _onedrive_service_singleton = OneDrivePersonalSyncService(
            config=config,
            storage=storage,
            ingest_payload_fn=_ingest_fit_payload
        )
    return _onedrive_service_singleton


def _get_withings_client() -> WithingsClient:
    """Get Withings client instance."""
    return WithingsClient()


def _json_response(data: Dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    """Create JSON HTTP response."""
    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status_code,
        mimetype=JSON_CONTENT_TYPE,
    )


def _public_base_url(req: func.HttpRequest) -> str:
    """Return the externally reachable base URL, overridable via env."""
    override = os.getenv(ENV_PUBLIC_BASE_URL)
    if override:
        return override.rstrip("/")

    parsed = urlparse(req.url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_onedrive_state(athlete_id: str) -> str:
    """Build a lightweight OAuth state payload."""
    return f"{athlete_id}|{int(time.time())}"


def _get_athlete_id_from_state(state: str | None) -> str | None:
    """Extract athlete_id from the OAuth state value."""
    if not state:
        return None
    return state.split("|", 1)[0] or None


def _read_text_file(path: str) -> str:
    """Read a text file with utf-8 encoding."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _response_missing_file(name: str) -> func.HttpResponse:
    """Return 500 error for missing file."""
    return func.HttpResponse(
        json.dumps({"error": f"{name} not found"}),
        status_code=500,
        mimetype=JSON_CONTENT_TYPE,
    )


# ============================================================================
# FIT File Upload Endpoints
# ============================================================================

@app.route(route="process_fit", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def process_fit_files(req: func.HttpRequest) -> func.HttpResponse:
    """Process FIT file upload."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        file_path = req.params.get("file_path")

        if not file_path:
            return _json_response({"error": "file_path parameter required"}, 400)

        handler = FitUploadHandler(_get_storage())
        metrics, status = handler.handle(file_path, athlete_id)

        if status == 201 and metrics:
            payload = metrics
            if hasattr(metrics, "model_dump"):
                payload = metrics.model_dump()  # type: ignore[attr-defined]
            return _json_response(cast(Dict[str, Any], payload), status)
        else:
            error_msg = {
                404: "File not found",
                400: "Invalid FIT file",
                500: "Upload failed",
            }.get(status, "Unknown error")
            return _json_response({"error": error_msg}, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Upload endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


# ============================================================================
# OneDrive Sync Endpoints
# ============================================================================

@app.route(route="onedrive/authorize", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def onedrive_authorize(req: func.HttpRequest) -> func.HttpResponse:
    """Generate OneDrive OAuth authorization URL."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        state = req.params.get("state") or _build_onedrive_state(athlete_id)
        service = _get_onedrive_service()

        return _json_response(
            {
                "authorization_url": service.build_authorize_url(state=state),
                "athlete_id": athlete_id,
                "state": state,
            },
            200,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("OneDrive authorize endpoint failed: %s",
                     exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="onedrive/callback", methods=["GET"])
def onedrive_callback(req: func.HttpRequest) -> func.HttpResponse:
    """Handle OneDrive OAuth callback and persist tokens."""
    code = req.params.get("code")
    state = req.params.get("state")

    if not code:
        return func.HttpResponse(
            "Missing authorization code",
            status_code=400,
            mimetype=TEXT_PLAIN_CONTENT_TYPE,
        )

    athlete_id = (
        req.params.get("athlete_id")
        or _get_athlete_id_from_state(state)
        or "rob"
    )

    try:
        service = _get_onedrive_service()
        service.complete_authorization(athlete_id=athlete_id, code=code)

        success_html = (
            "<html><body><h1>Success!</h1>"
            f"<p>OneDrive connected for athlete {athlete_id}.</p>"
            "<p>You can close this window and return to the app.</p>"
            "</body></html>"
        )
        return func.HttpResponse(
            success_html,
            status_code=200,
            mimetype=HTML_CONTENT_TYPE,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("OneDrive callback failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="onedrive/sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def onedrive_sync_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered OneDrive sync."""
    try:
        try:
            body = req.get_json() if req.method == "POST" else {}
        except ValueError:
            body = {}

        sync_req = OneDriveSyncRequest(body, dict(req.params))
        handler = OneDriveSyncHandler(_get_onedrive_service())
        response, status = handler.handle(sync_req)

        return _json_response(response, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Sync endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.timer_trigger(arg_name="timer", schedule="0 0 * * * *")  # hourly
def onedrive_sync_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered OneDrive sync."""
    if timer.past_due:
        logger.warning("OneDrive sync timer is past due")

    try:
        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        service = _get_onedrive_service()

        # Use handler with sync mode (async=False) to prevent thread leaks
        # Timer triggers must complete synchronously and return cleanly
        sync_req = OneDriveSyncRequest({"athlete_id": athlete_id}, {})
        handler = OneDriveSyncHandler(service)
        response, status = handler.handle(sync_req)

        if status == 200:
            logger.info("OneDrive sync completed: %s", response)
        else:
            logger.warning("OneDrive sync failed: %s", response)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("OneDrive timer failed: %s", exc, exc_info=True)
    finally:
        # Ensure function returns cleanly
        logger.debug("OneDrive timer trigger completed")


# ============================================================================
# Planning & Semantic Analysis Endpoints
# ============================================================================

@app.route(route="planning/context", methods=["GET"])
def planning_context(req: func.HttpRequest) -> func.HttpResponse:
    """Get planning context for training decisions."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        days = int(req.params.get("days", "45"))
        days = max(1, min(days, 365))

        handler = QueryHandler(_get_semantic_layer())
        context, status = handler.query_planning_context(athlete_id, days)

        return _json_response(context, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Planning endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="workouts", methods=["GET"])
def list_workouts(req: func.HttpRequest) -> func.HttpResponse:
    """Query workouts with filters."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        limit = int(req.params.get("limit", "50"))
        limit = max(1, min(limit, 200))

        handler = QueryHandler(_get_semantic_layer())
        workouts, status = handler.query_athlete_workouts(athlete_id, limit)

        return _json_response({
            "athlete_id": athlete_id,
            "count": len(workouts),
            "workouts": workouts,
        }, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("List workouts endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="workouts/{workout_id}", methods=["GET"])
def get_workout_detail(req: func.HttpRequest) -> func.HttpResponse:
    """Get detailed workout data including time series."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        workout_id = req.route_params.get("workout_id")

        if not workout_id:
            return _json_response({"error": "workout_id required in route"}, 400)

        handler = QueryHandler(_get_semantic_layer())
        workout, status = handler.query_workout_detail(athlete_id, workout_id)

        return _json_response(workout, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Workout detail endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(
    route="workouts/{workout_id}/recalculated",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
def get_workout_recalculated(req: func.HttpRequest) -> func.HttpResponse:
    """Recalculate workout zones with override FTP/LTHR (placeholder endpoint)."""
    try:
        workout_id = req.route_params.get("workout_id")
        ftp_watts = req.params.get("ftp_watts")
        lthr_bpm = req.params.get("lthr_bpm")

        # Placeholder response - endpoint not yet implemented
        response = {
            "message": "Not implemented",
            "workout_id": workout_id,
            "physiometrics_override": {
                "ftp_watts": float(ftp_watts) if ftp_watts else None,
                "lthr_bpm": float(lthr_bpm) if lthr_bpm else None
            }
        }

        return _json_response(response, 501)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Recalculated workout endpoint failed: %s",
                     exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="analysis/zones", methods=["GET"])
def zone_distribution(req: func.HttpRequest) -> func.HttpResponse:
    """Get time-in-zone distribution for planning."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        days = int(req.params.get("days", "30"))
        days = max(1, min(days, 365))

        handler = QueryHandler(_get_semantic_layer())
        zones, status = handler.query_training_zones(athlete_id, days)

        return _json_response(zones, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Zone analysis endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="analysis/efficiency", methods=["GET"])
def efficiency_trends(req: func.HttpRequest) -> func.HttpResponse:
    """Get aerobic efficiency and decoupling trends."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        days = int(req.params.get("days", "90"))
        days = max(1, min(days, 365))

        handler = QueryHandler(_get_semantic_layer())
        trends, status = handler.query_efficiency_trends(athlete_id, days)

        return _json_response(trends, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Efficiency endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="rollups/weekly", methods=["GET"])
def weekly_rollups(req: func.HttpRequest) -> func.HttpResponse:
    """Get weekly rollup data."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        weeks = int(req.params.get("weeks", "16"))
        weeks = max(1, min(weeks, 52))

        handler = QueryHandler(_get_semantic_layer())
        rollups, status = handler.query_weekly_rollups(athlete_id, weeks)

        return _json_response(rollups, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Rollups endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


# ============================================================================
# Health Check & Plugin Manifest Endpoints
# ============================================================================

@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Health check endpoint with dependency verification."""
    try:
        handler = HealthHandler(_get_storage(), API_DOCS_DIR)
        result, status = handler.check_health()

        # Add timestamp
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Health check endpoint failed: %s", exc, exc_info=True)
        return _json_response({
            "status": "degraded",
            "error": "Health check failed"
        }, 503)


@app.route(route=".well-known/ai-plugin.json", methods=["GET"])
def serve_ai_plugin_manifest(req: func.HttpRequest) -> func.HttpResponse:
    """Serve ChatGPT Actions plugin manifest with dynamic OpenAPI URL."""
    try:
        base_url = _public_base_url(req)

        env_overrides = {
            k: v for k, v in {
                "logo_url": os.getenv(ENV_PLUGIN_LOGO_URL),
                "contact_email": os.getenv(ENV_PLUGIN_CONTACT_EMAIL),
                "legal_info_url": os.getenv(ENV_PLUGIN_LEGAL_URL)
            }.items() if v is not None
        }

        handler = HealthHandler(_get_storage(), API_DOCS_DIR)
        result, status = handler.get_plugin_manifest(base_url, env_overrides)

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Plugin manifest endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": "Failed to load plugin manifest"}, 500)


@app.route(route="openapi.yaml", methods=["GET"])
def serve_openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    """Serve OpenAPI specification with dynamic server URL."""
    try:
        base_url = _public_base_url(req)

        handler = HealthHandler(_get_storage(), API_DOCS_DIR)
        spec_body, status = handler.get_openapi_spec(base_url)

        return func.HttpResponse(spec_body, status_code=status, mimetype="application/x-yaml")

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("OpenAPI spec endpoint failed: %s", exc, exc_info=True)
        return func.HttpResponse(
            INTERNAL_SERVER_ERROR, status_code=500, mimetype=TEXT_PLAIN_CONTENT_TYPE
        )


@app.route(route="logo.svg", methods=["GET"])
def serve_logo(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Serve the Health Assistant logo."""
    try:
        handler = HealthHandler(_get_storage(), API_DOCS_DIR)
        logo_body, status = handler.get_logo()

        return func.HttpResponse(logo_body, status_code=status, mimetype="image/svg+xml")

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Logo endpoint failed: %s", exc, exc_info=True)
        return func.HttpResponse(
            "Error loading logo",
            status_code=500,
            mimetype=TEXT_PLAIN_CONTENT_TYPE,
        )


# ============================================================================
# Physiometrics Endpoints
# ============================================================================

@app.route(route="physiometrics/current", methods=["GET"])
def get_current_physiometrics(req: func.HttpRequest) -> func.HttpResponse:
    """Get current physiometric values for an athlete."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")

        handler = PhysiometricsHandler(_get_semantic_layer())
        result, status = handler.get_current(athlete_id)

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Physiometrics current endpoint failed: %s",
                     exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="physiometrics/history", methods=["GET"])
def get_physiometrics_history(req: func.HttpRequest) -> func.HttpResponse:
    """Get time-series physiometrics data."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")
        days = int(req.params.get("days", "90"))

        metrics_param = req.params.get("metrics")
        metrics = metrics_param.split(",") if metrics_param else None

        handler = PhysiometricsHandler(_get_semantic_layer())
        result, status = handler.get_history(athlete_id, days, metrics)

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Physiometrics history endpoint failed: %s",
                     exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="physiometrics/update", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def update_physiometrics(req: func.HttpRequest) -> func.HttpResponse:
    """Update physiometric values (single metric or bulk)."""
    try:
        try:
            req_body = req.get_json()
        except ValueError:
            return _json_response({"error": ERR_INVALID_JSON}, 400)

        athlete_id = req_body.get("athlete_id")
        has_single_metric = "metric" in req_body and "value" in req_body
        has_bulk_metrics = "metrics" in req_body

        if not (has_single_metric or has_bulk_metrics):
            return _json_response(
                {"error": "Either 'metric'+'value' or 'metrics' dict required"}, 400)

        handler = PhysiometricsHandler(_get_semantic_layer())
        effective_date = req_body.get("effective_date")
        source = req_body.get("source", "chatgpt")

        if has_single_metric:
            result, status = handler.update_metric(
                athlete_id=athlete_id,
                metric=req_body["metric"],
                value=req_body["value"],
                effective_date=effective_date,
                source=source
            )
        else:
            result, status = handler.update_metrics(
                athlete_id=athlete_id,
                metrics=req_body["metrics"],
                effective_date=effective_date,
                source=source
            )

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Physiometrics update endpoint failed: %s",
                     exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


# ============================================================================
# Withings OAuth & Webhook Endpoints
# ============================================================================

@app.route(route="withings/authorize", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
def withings_authorize(req: func.HttpRequest) -> func.HttpResponse:
    """Get Withings OAuth authorization URL."""
    try:
        athlete_id = req.params.get("athlete_id", "rob")

        handler = WithingsHandler(_get_withings_client(), _get_storage())
        result, status = handler.get_authorization_url(athlete_id)

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Withings authorize endpoint failed: %s",
                     exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="withings/callback", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def withings_callback(req: func.HttpRequest) -> func.HttpResponse:
    """Handle Withings OAuth callback."""
    try:
        code = req.params.get("code", "")
        state = req.params.get("state", "")
        webhook_base_url = os.getenv("WITHINGS_WEBHOOK_URL",
                                     f"{req.url.split('/api/')[0]}/api/withings/webhook")

        handler = WithingsHandler(_get_withings_client(), _get_storage())
        html, status, content_type = handler.handle_oauth_callback(
            code, state, webhook_base_url)

        return func.HttpResponse(html, status_code=status, mimetype=content_type)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Withings callback endpoint failed: %s",
                     exc, exc_info=True)
        error_html = (
            "<html><body><h1>Error</h1>"
            "<p>Failed to connect Withings account</p>"
            "</body></html>"
        )
        return func.HttpResponse(error_html, status_code=500, mimetype=HTML_CONTENT_TYPE)


@app.route(route="withings/webhook", methods=["POST"])
def withings_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """Receive Withings webhook notifications."""
    try:
        userid = req.form.get("userid", "")
        appli = req.form.get("appli", "")
        startdate = req.form.get("startdate", "")
        enddate = req.form.get("enddate", "")

        handler = WithingsHandler(_get_withings_client(), _get_storage())
        result, status = handler.process_webhook(
            userid, appli, startdate, enddate)

        return func.HttpResponse(result, status_code=status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Withings webhook endpoint failed: %s",
                     exc, exc_info=True)
        return func.HttpResponse("OK", status_code=200)


# ============================================================================
# Configuration Endpoints
# ============================================================================

@app.route(route="config/reload", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def reload_config(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Reload physiometrics configuration from disk."""
    try:
        handler = ConfigHandler()
        result, status = handler.reload_config()

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Config reload endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="config/update", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def update_config(req: func.HttpRequest) -> func.HttpResponse:
    """Update physiometrics configuration via HTTP POST."""
    try:
        try:
            req_body = req.get_json()
        except ValueError:
            return _json_response({"error": ERR_INVALID_JSON}, 400)

        handler = ConfigHandler()
        result, status = handler.update_config(req_body)

        return _json_response(result, status)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Config update endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


@app.route(route="config/history", methods=["GET"])
def config_history(req: func.HttpRequest) -> func.HttpResponse:
    """Get physiometrics configuration change history."""
    try:
        limit = int(req.params.get("limit", "10"))

        handler = ConfigHandler()
        result, status = handler.get_history(limit)

        return _json_response(result, status)

    except ValueError:
        return _json_response({"error": "Invalid limit parameter"}, 400)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Config history endpoint failed: %s", exc, exc_info=True)
        return _json_response({"error": INTERNAL_SERVER_ERROR}, 500)


# ============================================================================
# Daily Backup Export (Timer Trigger)
# ============================================================================

@app.timer_trigger(arg_name="timer", schedule="0 2 * * *")  # 2 AM UTC daily
def backup_export_timer(timer: func.TimerRequest) -> None:
    """Daily timer-triggered backup export to read-only blob storage."""
    if timer.past_due:
        logger.warning("Backup export timer is past due")

    try:
        logger.info("Starting daily backup export at %s",
                    datetime.now(timezone.utc).isoformat())

        storage = _get_storage()
        if storage is None:
            logger.error("Storage not initialized")
            return

        exporter = BackupExporter(storage)
        result = exporter.export_all_tables()

        if result.get("status") == "success":
            logger.info("Backup export completed successfully: %s", result)
        else:
            logger.error("Backup export failed: %s", result.get("error"))

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Backup export timer failed: %s", exc, exc_info=True)
