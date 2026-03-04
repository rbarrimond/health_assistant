"""Azure Functions app - HTTP adapter for FIT parsing and health analytics.

This module serves as the HTTP layer, delegating all business logic to handlers
in TrainingAnalyticsPlatform.handlers. All endpoints are thin wrappers that:
1. Parse HTTP request
2. Call appropriate handler
3. Return JSON response
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, cast

import azure.functions as func

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
from TrainingAnalyticsPlatform.storage.backup_exporter import BackupExporter
from TrainingAnalyticsPlatform.platform.dependencies import dependencies
from TrainingAnalyticsPlatform.platform.logging_setup import setup_logging
from TrainingAnalyticsPlatform.platform.http_utils import json_response, public_base_url
from TrainingAnalyticsPlatform.handlers import (
    FitPayloadIngestionHandler,
    OneDriveSyncRequest,
    QueryHandler,
    PhysiometricsHandler,
    WithingsHandler,
    ConfigHandler,
    HealthHandler,
    AgentMemoryHandler,
)
from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import GarminSyncRequest
from utils import endpoint, parse_ingest_payload

logger = logging.getLogger(__name__)
setup_logging()

app = func.FunctionApp()

if "PYTEST_CURRENT_TEST" not in os.environ and os.getenv("SKIP_FUNCTION_APP_WARMUP") != "1":
    dependencies.warmup()

# ============================================================================
# OneDrive OAuth Helpers (local to this module)
# ============================================================================

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

    handler = FitPayloadIngestionHandler(dependencies.storage)
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
    service = dependencies.onedrive_service

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

    service = dependencies.onedrive_service
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
    handler = dependencies.onedrive_service
    response, status = handler.handle(sync_req)

    return json_response(response, status)


@app.timer_trigger(arg_name="timer", schedule="0 */10 * * * *")  # every 10 minutes
def onedrive_sync_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered OneDrive sync."""
    if timer.past_due:
        logger.warning(
            "timer_event",
            extra={
                "event_name": "timer.past_due",
                "timer_name": "onedrive_sync_timer",
            },
        )

    try:
        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        handler = dependencies.onedrive_service

        # Use handler with sync mode (async=False) to prevent thread leaks
        # Timer triggers must complete synchronously and return cleanly
        sync_req = OneDriveSyncRequest({"athlete_id": athlete_id}, {})
        response, status = handler.handle(sync_req)

        if status == 200:
            logger.info(
                "timer_event",
                extra={
                    "event_name": "timer.success",
                    "timer_name": "onedrive_sync_timer",
                    "status_code": status,
                },
            )
        else:
            logger.warning(
                "timer_event",
                extra={
                    "event_name": "timer.warning",
                    "timer_name": "onedrive_sync_timer",
                    "status_code": status,
                    "response": response,
                },
            )

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception(
            "timer_event",
            extra={
                "event_name": "timer.error",
                "timer_name": "onedrive_sync_timer",
                "error": str(exc),
            },
        )
    finally:
        logger.debug(
            "timer_event",
            extra={
                "event_name": "timer.completed",
                "timer_name": "onedrive_sync_timer",
            },
        )


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

    handler = QueryHandler(dependencies.semantic_layer)
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

    handler = QueryHandler(dependencies.semantic_layer)
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
    """Get detailed workout data with optional lap summaries."""
    athlete_id = req.params.get("athlete_id", "rob")
    workout_id = req.route_params.get("workout_id")
    include_laps = req.params.get("laps", "false").lower() in {"1", "true", "yes", "y"}
    include_developer_fields = req.params.get("developer_fields", "false").lower() in {
        "1", "true", "yes", "y"
    }

    if not workout_id:
        return json_response({"error": "workout_id required in route"}, 400)

    handler = QueryHandler(dependencies.semantic_layer)
    workout, status = handler.query_workout_detail(
        athlete_id,
        workout_id,
        include_laps=include_laps,
        include_developer_fields=include_developer_fields,
    )

    return json_response(workout, status, req=req)


@app.route(route="workouts/{workout_id}/laps/{lap_index}", methods=["GET"])
@endpoint
def get_workout_lap_detail(req: func.HttpRequest) -> func.HttpResponse:
    """Get lap summary and records for a specific workout lap."""
    athlete_id = req.params.get("athlete_id", "rob")
    workout_id = req.route_params.get("workout_id")
    lap_index = req.route_params.get("lap_index")

    if not workout_id:
        return json_response({"error": "workout_id required in route"}, 400)

    if lap_index is None:
        return json_response({"error": "lap_index required in route"}, 400)

    try:
        lap_index_int = int(lap_index)
    except ValueError:
        return json_response({"error": "lap_index must be an integer"}, 400)

    handler = QueryHandler(dependencies.semantic_layer)
    lap, status = handler.query_workout_lap_detail(
        athlete_id,
        workout_id,
        lap_index_int,
    )

    return json_response(lap, status, req=req)


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

    handler = QueryHandler(dependencies.semantic_layer)
    zones, status = handler.query_training_zones(athlete_id, days)

    return json_response(zones, status)


@app.route(route="analysis/efficiency", methods=["GET"])
@endpoint
def efficiency_trends(req: func.HttpRequest) -> func.HttpResponse:
    """Get aerobic efficiency and decoupling trends."""
    athlete_id = req.params.get("athlete_id", "rob")
    days = int(req.params.get("days", "90"))
    days = max(1, min(days, 365))

    handler = QueryHandler(dependencies.semantic_layer)
    trends, status = handler.query_efficiency_trends(athlete_id, days)

    return json_response(trends, status)


@app.route(route="rollups/weekly", methods=["GET"])
@endpoint
def weekly_rollups(req: func.HttpRequest) -> func.HttpResponse:
    """Get weekly rollup data."""
    athlete_id = req.params.get("athlete_id", "rob")
    weeks = int(req.params.get("weeks", "16"))
    weeks = max(1, min(weeks, 52))

    handler = QueryHandler(dependencies.semantic_layer)
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
    handler = HealthHandler(dependencies.storage, API_DOCS_DIR)
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

    handler = HealthHandler(dependencies.storage, API_DOCS_DIR)
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

    handler = HealthHandler(dependencies.storage, API_DOCS_DIR)
    spec_body, status = handler.get_openapi_spec(base_url)

    return func.HttpResponse(spec_body, status_code=status, mimetype="application/x-yaml")


@app.route(route="logo.svg", methods=["GET"])
@endpoint(
    response_kind="text",
    error_body=lambda exc: "Error loading logo",
)
def serve_logo(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Serve the Health Assistant logo."""
    handler = HealthHandler(dependencies.storage, API_DOCS_DIR)
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

    handler = PhysiometricsHandler(dependencies.semantic_layer)
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

    handler = PhysiometricsHandler(dependencies.semantic_layer)
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

    handler = PhysiometricsHandler(dependencies.semantic_layer)
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

@app.route(route="agent/context", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def get_agent_context(req: func.HttpRequest) -> func.HttpResponse:
    """Get complete agent context (preferences + active observations).
    
    Use this at conversation start to provide context to the GPT agent.
    """
    athlete_id = req.params.get("athlete_id", "rob")

    handler = AgentMemoryHandler(dependencies.storage)
    result, status = handler.get_context(athlete_id)

    return json_response(result, status)


@app.route(route="agent/preferences", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def get_agent_preferences(req: func.HttpRequest) -> func.HttpResponse:
    """Get user preferences for the agent."""
    athlete_id = req.params.get("athlete_id", "rob")
    status_filter = req.params.get("status", "active")
    limit = int(req.params.get("limit", "20"))

    handler = AgentMemoryHandler(dependencies.storage)
    result, status = handler.get_preferences(athlete_id, status_filter, limit)

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
    category = req_body.get("category")
    summary = req_body.get("summary")
    details = req_body.get("details")
    priority = req_body.get("priority", "normal")
    status = req_body.get("status", "active")

    handler = AgentMemoryHandler(dependencies.storage)
    result, status = handler.add_preference(
        athlete_id=athlete_id,
        category=category,
        summary=summary,
        details=details,
        priority=priority,
        status=status
    )

    return json_response(result, status)


@app.route(route="agent/preferences/{preference_id}", methods=["PATCH"],
           auth_level=func.AuthLevel.FUNCTION)
@endpoint
def update_agent_preference(req: func.HttpRequest) -> func.HttpResponse:
    """Update a preference (status, summary, details, etc.)."""
    preference_id = req.route_params.get("preference_id")
    if not preference_id:
        return json_response({"error": "preference_id required in route"}, 400)

    try:
        req_body = req.get_json()
    except ValueError:
        return json_response({"error": ERR_INVALID_JSON}, 400)

    athlete_id = req_body.get("athlete_id", "rob")

    handler = AgentMemoryHandler(dependencies.storage)
    result, status_code = handler.update_preference(
        athlete_id=athlete_id,
        preference_id=preference_id,
        updates=req_body
    )

    return json_response(result, status_code)


@app.route(route="agent/observations", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def list_agent_observations(req: func.HttpRequest) -> func.HttpResponse:
    """List observations for an athlete."""
    athlete_id = req.params.get("athlete_id", "rob")
    status_filter = req.params.get("status", "active")
    limit = int(req.params.get("limit", "20"))

    handler = AgentMemoryHandler(dependencies.storage)
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

    handler = AgentMemoryHandler(dependencies.storage)
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

    handler = AgentMemoryHandler(dependencies.storage)
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

    handler = WithingsHandler(dependencies.withings_client, dependencies.storage)
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

    handler = WithingsHandler(dependencies.withings_client, dependencies.storage)
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

    handler = WithingsHandler(dependencies.withings_client, dependencies.storage)
    result, status = handler.process_webhook(
        userid, appli, startdate, enddate)

    return func.HttpResponse(result, status_code=status)


# ============================================================================
# Garmin Connect Sync Endpoints
# ============================================================================

@app.route(route="garmin/sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def garmin_sync_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered Garmin Connect sync."""
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}

    sync_req = GarminSyncRequest(body, dict(req.params))
    handler = dependencies.garmin_service
    response, status = handler.handle(sync_req)

    return json_response(response, status)


@app.timer_trigger(arg_name="timer", schedule="0 3 * * *")  # 3 AM UTC daily
def garmin_sync_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered Garmin Connect sync."""
    if timer.past_due:
        logger.warning("Garmin sync timer is past due")

    try:
        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        handler = dependencies.garmin_service

        # Use handler with sync mode (async=False) to prevent thread leaks
        sync_req = GarminSyncRequest({"athlete_id": athlete_id}, {})
        response, status = handler.handle(sync_req)

        if status == 200:
            logger.info("Garmin sync completed: %s", response)
        else:
            logger.warning("Garmin sync failed: %s", response)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Garmin timer failed: %s", exc, exc_info=True)
    finally:
        logger.debug("Garmin timer trigger completed")


# ============================================================================
# Intervals.icu Sync Endpoints
# ============================================================================

@app.route(route="intervals/sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def intervals_sync_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered Intervals.icu physiometrics sync."""
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}

    athlete_id = body.get("athlete_id", os.getenv("DEFAULT_ATHLETE_ID", "rob"))
    lookback_days = body.get("lookback_days")

    handler = dependencies.intervals_service
    response, status = handler.handle(athlete_id, lookback_days)

    return json_response(response, status)


@app.timer_trigger(arg_name="timer", schedule="0 2 * * *")  # 2 AM UTC daily
def intervals_sync_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered Intervals.icu physiometrics sync."""
    if timer.past_due:
        logger.warning("Intervals sync timer is past due")

    try:
        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        handler = dependencies.intervals_service

        response, status = handler.handle(athlete_id)

        if status == 200:
            logger.info("Intervals sync completed: %s", response)
        else:
            logger.warning("Intervals sync failed: %s", response)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Intervals timer failed: %s", exc, exc_info=True)
    finally:
        logger.debug("Intervals timer trigger completed")


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

        storage = dependencies.storage
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
