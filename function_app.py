"""Azure Functions app - HTTP adapter for FIT parsing and health analytics.

This module serves as the HTTP layer, delegating all business logic to handlers
in FitParser.handlers. All endpoints are thin wrappers that:
1. Parse HTTP request
2. Call appropriate handler
3. Return JSON response
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, cast

import azure.functions as func
from azure.core.exceptions import AzureError

from config.constants import (
    API_DOCS_DIR,
    ENV_PLUGIN_CONTACT_EMAIL,
    ENV_PLUGIN_LEGAL_URL,
    ENV_PLUGIN_LOGO_URL,
    ERR_INVALID_JSON,
    HTML_CONTENT_TYPE,
    INTERNAL_SERVER_ERROR,
    TEXT_PLAIN_CONTENT_TYPE,
)
from FitParser.backup_exporter import BackupExporter
from FitParser.http_utils import json_response, public_base_url
from FitParser.onedrive_sync import (
    OneDrivePersonalSyncService,
    OneDriveSyncConfig,
)
from FitParser.semantic_layer import SemanticLayer
from FitParser.table_storage import WorkoutTableStorage
from FitParser.withings_client import WithingsClient
from FitParser.handlers import (
    FitPayloadIngestionHandler,
    OneDriveSyncHandler,
    OneDriveSyncRequest,
    QueryHandler,
    PhysiometricsHandler,
    WithingsHandler,
    ConfigHandler,
    HealthHandler,
    AgentMemoryHandler,
)
from utils import endpoint, parse_ingest_payload

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

app = func.FunctionApp()

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
    # Payloads provide base64 content plus metadata; we reconstruct a temp FIT file
    # and pass its metadata into the ingestion pipeline for deterministic idempotency.
    handler = FitPayloadIngestionHandler(_get_storage())
    return handler.handle(payload)


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




def _build_onedrive_state(athlete_id: str) -> str:
    """Build a lightweight OAuth state payload."""
    return f"{athlete_id}|{int(time.time())}"


def _get_athlete_id_from_state(state: str | None) -> str | None:
    """Extract athlete_id from the OAuth state value."""
    if not state:
        return None
    return state.split("|", 1)[0] or None


# ============================================================================
# FIT File Upload Endpoints
# ============================================================================

@app.route(route="process_fit", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def process_fit_files(req: func.HttpRequest) -> func.HttpResponse:
    """Process FIT file upload from base64 content.

    Request body:
    {
        "file_content_b64": "base64encodedcontent",
        "source_file_name": "filename.fit",
        "athlete_id": "rob" (defaults to "rob"),
        "source_item_id": "optional-id",
        "source_file_path": "optional-path",
        "source_drive_id": "optional-drive-id",
        "source_etag": "optional-etag",
        "source_ctag": "optional-ctag",
        "source_quickxor_hash": "optional-quickxor-hash",
        "source_modified_at_utc": "optional-utc-timestamp",
        "file_sha256": "optional-sha256",
        "file_size_bytes": 12345
    }
    """
    body = parse_ingest_payload(req)

    handler = FitPayloadIngestionHandler(_get_storage())
    response, status = handler.handle(body)
    return json_response(cast(Dict[str, Any], response), status)


# ============================================================================
# OneDrive Sync Endpoints
# ============================================================================

@app.route(route="onedrive/authorize", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def onedrive_authorize(req: func.HttpRequest) -> func.HttpResponse:
    """Generate OneDrive OAuth authorization URL."""
    athlete_id = req.params.get("athlete_id", "rob")
    state = req.params.get("state") or _build_onedrive_state(athlete_id)
    service = _get_onedrive_service()

    return json_response(
        {
            "authorization_url": service.build_authorize_url(state=state),
            "athlete_id": athlete_id,
            "state": state,
        },
        200,
    )


@app.route(route="onedrive/callback", methods=["GET"])
@endpoint
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


@app.route(route="onedrive/sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def onedrive_sync_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered OneDrive sync."""
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}

    sync_req = OneDriveSyncRequest(body, dict(req.params))
    handler = OneDriveSyncHandler(_get_onedrive_service())
    response, status = handler.handle(sync_req)

    return json_response(response, status)


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
@endpoint
def planning_context(req: func.HttpRequest) -> func.HttpResponse:
    """Get planning context for training decisions."""
    athlete_id = req.params.get("athlete_id", "rob")
    days = int(req.params.get("days", "45"))
    days = max(1, min(days, 365))

    handler = QueryHandler(_get_semantic_layer())
    context, status = handler.query_planning_context(athlete_id, days)

    return json_response(context, status)


@app.route(route="workouts", methods=["GET"])
@endpoint
def list_workouts(req: func.HttpRequest) -> func.HttpResponse:
    """Query workouts with filters."""
    athlete_id = req.params.get("athlete_id", "rob")
    since = req.params.get("since")
    until = req.params.get("until")
    sport = req.params.get("sport")
    limit = int(req.params.get("limit", "50"))
    limit = max(1, min(limit, 200))

    handler = QueryHandler(_get_semantic_layer())
    workouts, status = handler.query_athlete_workouts(
        athlete_id,
        limit=limit,
        since=since,
        until=until,
        sport=sport,
    )

    return json_response({
        "athlete_id": athlete_id,
        "count": len(workouts),
        "workouts": workouts,
    }, status)


@app.route(route="workouts/{workout_id}", methods=["GET"])
@endpoint
def get_workout_detail(req: func.HttpRequest) -> func.HttpResponse:
    """Get detailed workout data including time series."""
    athlete_id = req.params.get("athlete_id", "rob")
    workout_id = req.route_params.get("workout_id")

    if not workout_id:
        return json_response({"error": "workout_id required in route"}, 400)

    handler = QueryHandler(_get_semantic_layer())
    workout, status = handler.query_workout_detail(athlete_id, workout_id)

    return json_response(workout, status)


@app.route(
    route="workouts/{workout_id}/recalculated",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION
)
@endpoint
def get_workout_recalculated(req: func.HttpRequest) -> func.HttpResponse:
    """Recalculate workout zones with override FTP/LTHR (placeholder endpoint)."""
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

    return json_response(response, 501)


@app.route(route="analysis/zones", methods=["GET"])
@endpoint
def zone_distribution(req: func.HttpRequest) -> func.HttpResponse:
    """Get time-in-zone distribution for planning."""
    athlete_id = req.params.get("athlete_id", "rob")
    days = int(req.params.get("days", "30"))
    days = max(1, min(days, 365))

    handler = QueryHandler(_get_semantic_layer())
    zones, status = handler.query_training_zones(athlete_id, days)

    return json_response(zones, status)


@app.route(route="analysis/efficiency", methods=["GET"])
@endpoint
def efficiency_trends(req: func.HttpRequest) -> func.HttpResponse:
    """Get aerobic efficiency and decoupling trends."""
    athlete_id = req.params.get("athlete_id", "rob")
    days = int(req.params.get("days", "90"))
    days = max(1, min(days, 365))

    handler = QueryHandler(_get_semantic_layer())
    trends, status = handler.query_efficiency_trends(athlete_id, days)

    return json_response(trends, status)


@app.route(route="rollups/weekly", methods=["GET"])
@endpoint
def weekly_rollups(req: func.HttpRequest) -> func.HttpResponse:
    """Get weekly rollup data."""
    athlete_id = req.params.get("athlete_id", "rob")
    weeks = int(req.params.get("weeks", "16"))
    weeks = max(1, min(weeks, 52))

    handler = QueryHandler(_get_semantic_layer())
    rollups, status = handler.query_weekly_rollups(athlete_id, weeks)

    return json_response(rollups, status)


# ============================================================================
# Health Check & Plugin Manifest Endpoints
# ============================================================================

@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
@endpoint(
    response_kind="json",
    error_status=503,
    error_body=lambda exc: {"status": "degraded", "error": "Health check failed"},
)
def health_check(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Health check endpoint with dependency verification."""
    handler = HealthHandler(_get_storage(), API_DOCS_DIR)
    result, status = handler.check_health()

    # Add timestamp
    result["timestamp"] = datetime.now(timezone.utc).isoformat()

    return json_response(result, status)


@app.route(route=".well-known/ai-plugin.json", methods=["GET"])
@endpoint(
    response_kind="json",
    error_body=lambda exc: {"error": "Failed to load plugin manifest"},
)
def serve_ai_plugin_manifest(req: func.HttpRequest) -> func.HttpResponse:
    """Serve ChatGPT Actions plugin manifest with dynamic OpenAPI URL."""
    base_url = public_base_url(req)

    env_overrides = {
        k: v for k, v in {
            "logo_url": os.getenv(ENV_PLUGIN_LOGO_URL),
            "contact_email": os.getenv(ENV_PLUGIN_CONTACT_EMAIL),
            "legal_info_url": os.getenv(ENV_PLUGIN_LEGAL_URL)
        }.items() if v is not None
    }

    handler = HealthHandler(_get_storage(), API_DOCS_DIR)
    result, status = handler.get_plugin_manifest(base_url, env_overrides)

    return json_response(result, status)


@app.route(route="openapi.yaml", methods=["GET"])
@endpoint(
    response_kind="text",
    error_body=lambda exc: INTERNAL_SERVER_ERROR,
)
def serve_openapi_spec(req: func.HttpRequest) -> func.HttpResponse:
    """Serve OpenAPI specification with dynamic server URL."""
    base_url = public_base_url(req)

    handler = HealthHandler(_get_storage(), API_DOCS_DIR)
    spec_body, status = handler.get_openapi_spec(base_url)

    return func.HttpResponse(spec_body, status_code=status, mimetype="application/x-yaml")


@app.route(route="logo.svg", methods=["GET"])
@endpoint(
    response_kind="text",
    error_body=lambda exc: "Error loading logo",
)
def serve_logo(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Serve the Health Assistant logo."""
    handler = HealthHandler(_get_storage(), API_DOCS_DIR)
    logo_body, status = handler.get_logo()

    return func.HttpResponse(logo_body, status_code=status, mimetype="image/svg+xml")


# ============================================================================
# Physiometrics Endpoints
# ============================================================================

@app.route(route="physiometrics/current", methods=["GET"])
@endpoint
def get_current_physiometrics(req: func.HttpRequest) -> func.HttpResponse:
    """Get current physiometric values for an athlete."""
    athlete_id = req.params.get("athlete_id", "rob")

    handler = PhysiometricsHandler(_get_semantic_layer())
    result, status = handler.get_current(athlete_id)

    return json_response(result, status)


@app.route(route="physiometrics/history", methods=["GET"])
@endpoint
def get_physiometrics_history(req: func.HttpRequest) -> func.HttpResponse:
    """Get time-series physiometrics data."""
    athlete_id = req.params.get("athlete_id", "rob")
    days = int(req.params.get("days", "90"))

    metrics_param = req.params.get("metrics")
    metrics = metrics_param.split(",") if metrics_param else None

    handler = PhysiometricsHandler(_get_semantic_layer())
    result, status = handler.get_history(athlete_id, days, metrics)

    return json_response(result, status)


@app.route(route="physiometrics/update", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def update_physiometrics(req: func.HttpRequest) -> func.HttpResponse:
    """Update physiometric values (single metric or bulk)."""
    try:
        req_body = req.get_json()
    except ValueError:
        return json_response({"error": ERR_INVALID_JSON}, 400)

    athlete_id = req_body.get("athlete_id")
    has_single_metric = "metric" in req_body and "value" in req_body
    has_bulk_metrics = "metrics" in req_body

    if not (has_single_metric or has_bulk_metrics):
        return json_response(
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

    return json_response(result, status)


# ============================================================================
# Agent Memory Endpoints
# ============================================================================

@app.route(route="agent/context", methods=["GET"])
@endpoint
def get_agent_context(req: func.HttpRequest) -> func.HttpResponse:
    """Get complete agent context (preferences + active observations).
    
    Use this at conversation start to provide context to the GPT agent.
    """
    athlete_id = req.params.get("athlete_id", "rob")

    handler = AgentMemoryHandler(_get_storage())
    result, status = handler.get_context(athlete_id)

    return json_response(result, status)


@app.route(route="agent/preferences", methods=["GET"])
@endpoint
def get_agent_preferences(req: func.HttpRequest) -> func.HttpResponse:
    """Get user preferences for the agent."""
    athlete_id = req.params.get("athlete_id", "rob")

    handler = AgentMemoryHandler(_get_storage())
    result, status = handler.get_preferences(athlete_id)

    return json_response(result, status)


@app.route(route="agent/preferences", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def update_agent_preferences(req: func.HttpRequest) -> func.HttpResponse:
    """Update user preferences for the agent."""
    try:
        req_body = req.get_json()
    except ValueError:
        return json_response({"error": ERR_INVALID_JSON}, 400)

    athlete_id = req_body.get("athlete_id", "rob")
    preferences = {k: v for k, v in req_body.items() if k != "athlete_id"}

    handler = AgentMemoryHandler(_get_storage())
    result, status = handler.update_preferences(athlete_id, preferences)

    return json_response(result, status)


@app.route(route="agent/observations", methods=["GET"])
@endpoint
def list_agent_observations(req: func.HttpRequest) -> func.HttpResponse:
    """List observations for an athlete."""
    athlete_id = req.params.get("athlete_id", "rob")
    status_filter = req.params.get("status", "active")
    limit = int(req.params.get("limit", "20"))

    handler = AgentMemoryHandler(_get_storage())
    result, status = handler.list_observations(athlete_id, status_filter, limit)

    return json_response(result, status)


@app.route(route="agent/observations", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def add_agent_observation(req: func.HttpRequest) -> func.HttpResponse:
    """Add a new observation for the agent."""
    try:
        req_body = req.get_json()
    except ValueError:
        return json_response({"error": ERR_INVALID_JSON}, 400)

    athlete_id = req_body.get("athlete_id", "rob")
    category = req_body.get("category")
    summary = req_body.get("summary")
    details = req_body.get("details")
    workout_ids = req_body.get("workout_ids", [])
    priority = req_body.get("priority", "normal")
    expires_days = req_body.get("expires_days")

    handler = AgentMemoryHandler(_get_storage())
    result, status = handler.add_observation(
        athlete_id=athlete_id,
        category=category,
        summary=summary,
        details=details,
        workout_ids=workout_ids,
        priority=priority,
        expires_days=expires_days
    )

    return json_response(result, status)


@app.route(route="agent/observations/{observation_id}", methods=["PATCH"],
           auth_level=func.AuthLevel.FUNCTION)
@endpoint
def update_agent_observation(req: func.HttpRequest) -> func.HttpResponse:
    """Update an observation's status."""
    observation_id = req.route_params.get("observation_id")
    if not observation_id:
        return json_response({"error": "observation_id required in route"}, 400)

    try:
        req_body = req.get_json()
    except ValueError:
        return json_response({"error": ERR_INVALID_JSON}, 400)

    athlete_id = req_body.get("athlete_id", "rob")
    status = req_body.get("status")

    handler = AgentMemoryHandler(_get_storage())
    result, status_code = handler.update_observation_status(
        athlete_id=athlete_id,
        observation_id=observation_id,
        status=status
    )

    return json_response(result, status_code)


# ============================================================================
# Withings OAuth & Webhook Endpoints
# ============================================================================

@app.route(route="withings/authorize", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def withings_authorize(req: func.HttpRequest) -> func.HttpResponse:
    """Get Withings OAuth authorization URL."""
    athlete_id = req.params.get("athlete_id", "rob")

    handler = WithingsHandler(_get_withings_client(), _get_storage())
    result, status = handler.get_authorization_url(athlete_id)

    return json_response(result, status)


@app.route(route="withings/callback", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
@endpoint(
    response_kind="html",
    error_body=lambda exc: (
        "<html><body><h1>Error</h1>"
        "<p>Failed to connect Withings account</p>"
        "</body></html>"
    ),
)
def withings_callback(req: func.HttpRequest) -> func.HttpResponse:
    """Handle Withings OAuth callback."""
    code = req.params.get("code", "")
    state = req.params.get("state", "")
    webhook_base_url = os.getenv("WITHINGS_WEBHOOK_URL",
                                 f"{req.url.split('/api/')[0]}/api/withings/webhook")

    handler = WithingsHandler(_get_withings_client(), _get_storage())
    html, status, content_type = handler.handle_oauth_callback(
        code, state, webhook_base_url)

    return func.HttpResponse(html, status_code=status, mimetype=content_type)


@app.route(route="withings/webhook", methods=["POST"])
@endpoint(
    response_kind="text",
    swallow_exceptions=True,
)
def withings_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """Receive Withings webhook notifications."""
    userid = req.form.get("userid", "")
    appli = req.form.get("appli", "")
    startdate = req.form.get("startdate", "")
    enddate = req.form.get("enddate", "")

    handler = WithingsHandler(_get_withings_client(), _get_storage())
    result, status = handler.process_webhook(
        userid, appli, startdate, enddate)

    return func.HttpResponse(result, status_code=status)


# ============================================================================
# Configuration Endpoints
# ============================================================================

@app.route(route="config/reload", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def reload_config(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Reload physiometrics configuration from disk."""
    handler = ConfigHandler()
    result, status = handler.reload_config()

    return json_response(result, status)


@app.route(route="config/update", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def update_config(req: func.HttpRequest) -> func.HttpResponse:
    """Update physiometrics configuration via HTTP POST."""
    try:
        req_body = req.get_json()
    except ValueError:
        return json_response({"error": ERR_INVALID_JSON}, 400)

    handler = ConfigHandler()
    result, status = handler.update_config(req_body)

    return json_response(result, status)


@app.route(route="config/history", methods=["GET"])
@endpoint
def config_history(req: func.HttpRequest) -> func.HttpResponse:
    """Get physiometrics configuration change history."""
    try:
        limit = int(req.params.get("limit", "10"))
    except ValueError:
        return json_response({"error": "Invalid limit parameter"}, 400)

    handler = ConfigHandler()
    result, status = handler.get_history(limit)

    return json_response(result, status)


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
