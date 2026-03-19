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
from TrainingAnalyticsPlatform.models.async_ingestion import AsyncIngestionWorkItem
from TrainingAnalyticsPlatform.models.async_operation import AsyncIngestionOperationState
from TrainingAnalyticsPlatform.platform.dependencies import dependencies
from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.logging_setup import setup_logging
from TrainingAnalyticsPlatform.platform.http_utils import json_response, public_base_url
from TrainingAnalyticsPlatform.handlers import (
    FitPayloadIngestionHandler,
    OneDriveSyncRequest,
    OneDriveResetRequest,
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

ONEDRIVE_SYNC_TIMER_SCHEDULE = os.getenv("ONEDRIVE_SYNC_TIMER_SCHEDULE", "0 0 0 * * 1")
GARMIN_SYNC_TIMER_SCHEDULE = os.getenv("GARMIN_SYNC_TIMER_SCHEDULE", "0 0 3 * * 1")
GARMIN_PHYSIOMETRICS_SYNC_TIMER_SCHEDULE = os.getenv(
    "GARMIN_PHYSIOMETRICS_SYNC_TIMER_SCHEDULE",
    "0 30 3 * * 1",
)
INTERVALS_SYNC_TIMER_SCHEDULE = os.getenv("INTERVALS_SYNC_TIMER_SCHEDULE", "0 0 2 * * 1")
DEFERRED_RETRY_QUEUE_NAME = os.getenv("DEFERRED_RETRY_QUEUE_NAME", "rate-limit-deferrals")
ONEDRIVE_ASYNC_QUEUE_NAME = os.getenv("ONEDRIVE_ASYNC_QUEUE_NAME", "async-ingestion")

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


def _coerce_bool(value: Any, default: bool) -> bool:
    """Parse bool-like values with default fallback."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _run_weekly_presync_for_athletes(
    athlete_ids: list[str], *, enabled: bool
) -> Dict[str, Any]:
    """Run weekly pre-sync across target athletes with fail-fast semantics."""
    if not enabled:
        return {
            "enabled": False,
            "status": "skipped",
            "message": "Pre-sync disabled by request",
            "athletes": [],
        }

    unique_athletes = sorted(set(athlete_ids))
    athlete_results = []
    lookback_days = None
    for athlete_id in unique_athletes:
        outcome = dependencies.weekly_rollup_pre_sync_service.run(
            athlete_id=athlete_id,
            enabled=True,
        )
        if lookback_days is None:
            lookback_days = outcome.get("lookback_days")
        athlete_results.append(
            {
                "athlete_id": athlete_id,
                **outcome,
            }
        )
        if outcome.get("status") != "success":
            return {
                "enabled": True,
                "lookback_days": lookback_days,
                "status": "failed",
                "message": "Weekly rollup pre-sync failed; computation aborted",
                "athletes": athlete_results,
            }

    return {
        "enabled": True,
        "lookback_days": lookback_days,
        "status": "success",
        "message": "Weekly rollup pre-sync completed",
        "athletes": athlete_results,
    }


def _execute_deferred_retry_source(
    *, source: str, athlete_id: str, lookback_days: int
) -> tuple[Dict[str, Any], int]:
    """Replay a deferred source sync operation once due for retry."""
    if source == "onedrive_workouts":
        return dependencies.onedrive_service.handle(
            OneDriveSyncRequest(
                {
                    "athlete_id": athlete_id,
                    "days": lookback_days,
                    "async": False,
                },
                {},
            )
        )

    if source == "garmin_activities":
        return dependencies.garmin_service.handle(
            GarminSyncRequest(
                {
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "async": False,
                },
                {},
            )
        )

    if source == "garmin_physiometrics":
        return dependencies.garmin_physiometrics_service.handle(
            athlete_id,
            lookback_days,
            force=False,
        )

    if source == "intervals_physiometrics":
        intervals_athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
        if not intervals_athlete_id:
            return {"error": "INTERVALS_ATHLETE_ID is not configured"}, 424
        return dependencies.intervals_service.handle(
            intervals_athlete_id=intervals_athlete_id,
            athlete_id=athlete_id,
            lookback_days=lookback_days,
        )

    return {"error": f"Unsupported deferred retry source: {source}"}, 400


def _extract_retry_after_from_response(
    body: Dict[str, Any],
    headers: Dict[str, Any],
) -> str | None:
    """Extract Retry-After from response headers/body fallback."""
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == "retry-after":
            return None if value is None else str(value)

    for key in ("retry_after", "retryAfter"):
        value = body.get(key)
        if value is not None:
            return str(value)
    return None


def _normalize_source_response(
    response: Any,
) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
    """Normalize source responses to (body, status, headers)."""
    if isinstance(response, tuple) and len(response) == 2:
        body, status_code = response
        if isinstance(body, dict):
            return body, int(status_code), {}
    if isinstance(response, tuple) and len(response) == 3:
        body, status_code, headers = response
        if isinstance(body, dict):
            return body, int(status_code), headers if isinstance(headers, dict) else {}
    return {"error": "Invalid deferred retry response shape"}, 500, {}


def _process_deferred_retry_message(message_body: str) -> None:
    """Process one deferred retry message and update persisted retry state."""
    work_item = dependencies.deferred_retry_queue.decode_message(message_body)
    storage = dependencies.storage.retry_deferrals

    state = storage.get_state(
        athlete_id=work_item.athlete_id,
        operation_id=work_item.operation_id,
    )
    if state is None:
        logger.warning(
            "Deferred retry state not found; message ignored",
            extra={
                "athlete_id": work_item.athlete_id,
                "operation_id": work_item.operation_id,
                "source": work_item.source,
            },
        )
        return

    in_progress = storage.mark_status(
        athlete_id=work_item.athlete_id,
        operation_id=work_item.operation_id,
        status="retrying",
        etag=state.etag,
        increment_attempts=True,
    )

    source_response = _execute_deferred_retry_source(
        source=work_item.source,
        athlete_id=work_item.athlete_id,
        lookback_days=work_item.lookback_days,
    )
    body, status_code, headers = _normalize_source_response(source_response)

    if status_code == 200:
        storage.mark_status(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
            status="succeeded",
            etag=in_progress.etag,
            increment_attempts=False,
        )
        logger.info(
            "Deferred retry replay succeeded",
            extra={
                "athlete_id": work_item.athlete_id,
                "operation_id": work_item.operation_id,
                "source": work_item.source,
            },
        )
        return

    retry_after_raw = _extract_retry_after_from_response(body, headers)
    elapsed_sec = 0.0
    decision = dependencies.deferred_retry_coordinator.maybe_defer(
        athlete_id=work_item.athlete_id,
        source=work_item.source,
        lookback_days=work_item.lookback_days,
        retry_after_raw=retry_after_raw,
        elapsed_sec=elapsed_sec,
    )
    status = "deferred" if decision.deferred else "failed"
    storage.mark_status(
        athlete_id=work_item.athlete_id,
        operation_id=work_item.operation_id,
        status=status,
        etag=in_progress.etag,
        increment_attempts=False,
    )
    logger.warning(
        "Deferred retry replay did not succeed",
        extra={
            "athlete_id": work_item.athlete_id,
            "operation_id": work_item.operation_id,
            "source": work_item.source,
            "http_status": status_code,
            "deferred_again": decision.deferred,
            "safe_to_retry_at_utc": decision.safe_to_retry_at_utc,
        },
    )


def _process_async_ingestion_message(message_body: str) -> None:
    """Process one async ingestion work item from queue."""
    work_item = AsyncIngestionWorkItem.model_validate_json(message_body)
    force = bool(work_item.context.get("force", False))
    state_storage = dependencies.storage.async_operations

    state = state_storage.get_state(
        athlete_id=work_item.athlete_id,
        operation_id=work_item.operation_id,
    )
    if state is None:
        state_storage.upsert_state(
            AsyncIngestionOperationState.queued(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                source=work_item.source,
                lookback_days=work_item.lookback_days,
                mode="async_queue",
                queued_at_utc=work_item.queued_at_utc,
                request_id=work_item.request_id,
                correlation_id=work_item.correlation_id,
                context=work_item.context,
            )
        )
        state = state_storage.get_state(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
        )

    etag = state.etag if state else None

    logger.info(
        "Async ingestion worker started",
        extra={
            "operation_id": work_item.operation_id,
            "source": work_item.source,
            "athlete_id": work_item.athlete_id,
            "lookback_days": work_item.lookback_days,
            "force": force,
        },
    )

    try:
        state_storage.mark_status(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
            status="processing",
            etag=etag,
        )

        if work_item.source == "onedrive":
            result = dependencies.onedrive_service.sync(
                athlete_id=work_item.athlete_id,
                lookback_days=work_item.lookback_days,
            )
        elif work_item.source == "garmin":
            result = dependencies.garmin_service.sync(
                athlete_id=work_item.athlete_id,
                lookback_days=work_item.lookback_days,
                force=force,
            )
        else:
            logger.warning(
                "Unsupported async ingestion source",
                extra={
                    "operation_id": work_item.operation_id,
                    "source": work_item.source,
                    "athlete_id": work_item.athlete_id,
                },
            )
            return

        state_storage.mark_status(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
            status="succeeded",
            result={
                "status": result.get("status"),
                "found": result.get("found"),
                "ingested": result.get("ingested"),
                "skipped": result.get("skipped"),
                "failed": result.get("failed"),
            },
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        state_storage.mark_status(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
            status="failed",
            error=str(exc),
        )
        logger.error(
            "Async ingestion worker failed",
            extra={
                "operation_id": work_item.operation_id,
                "source": work_item.source,
                "athlete_id": work_item.athlete_id,
                "lookback_days": work_item.lookback_days,
                "force": force,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            exc_info=True,
        )
        raise

    logger.info(
        "Async ingestion worker completed",
        extra={
            "operation_id": work_item.operation_id,
            "source": work_item.source,
            "athlete_id": work_item.athlete_id,
            "lookback_days": work_item.lookback_days,
            "force": force,
            "result_status": result.get("status"),
            "ingested": result.get("ingested"),
            "skipped": result.get("skipped"),
            "failed": result.get("failed"),
        },
    )


@app.queue_trigger(
    arg_name="msg",
    queue_name=DEFERRED_RETRY_QUEUE_NAME,
    connection="AzureWebJobsStorage",
)
def process_deferred_retry(msg: func.QueueMessage) -> None:
    """Process deferred retry work items once they become visible in queue."""
    _process_deferred_retry_message(msg.get_body().decode("utf-8"))


@app.queue_trigger(
    arg_name="msg",
    queue_name=ONEDRIVE_ASYNC_QUEUE_NAME,
    connection="AzureWebJobsStorage",
)
def process_async_ingestion(msg: func.QueueMessage) -> None:
    """Process async ingestion queue work items."""
    _process_async_ingestion_message(msg.get_body().decode("utf-8"))


@app.route(
    route="async/operations/status",
    methods=["GET"],
    auth_level=func.AuthLevel.FUNCTION,
)
@endpoint
def get_async_operation_status(req: func.HttpRequest) -> func.HttpResponse:
    """Return async ingestion operation state by athlete and operation id."""
    athlete_id = req.params.get("athlete_id") or "rob"
    operation_id = req.params.get("operation_id")

    if not operation_id:
        return json_response({"error": "operation_id is required"}, 400)

    state = dependencies.storage.async_operations.get_state(
        athlete_id=athlete_id,
        operation_id=operation_id,
    )
    if state is None:
        return json_response(
            {
                "error": "Operation not found",
                "athlete_id": athlete_id,
                "operation_id": operation_id,
            },
            404,
        )

    return json_response(
        {
            "athlete_id": state.athlete_id,
            "operation_id": state.row_key,
            "source": state.source,
            "lookback_days": state.lookback_days,
            "status": state.status,
            "mode": state.mode,
            "queued_at_utc": state.queued_at_utc,
            "created_at_utc": state.created_at_utc,
            "updated_at_utc": state.updated_at_utc,
            "request_id": state.request_id,
            "correlation_id": state.correlation_id,
            "context": state.context,
            "result": state.result,
            "error": state.error,
        },
        200,
    )

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


@app.route(route="onedrive/sync/reset", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def onedrive_sync_reset_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered OneDrive delta reset."""
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}

    reset_req = OneDriveResetRequest(body, dict(req.params))
    handler = dependencies.onedrive_service
    response, status = handler.handle_reset(reset_req)

    return json_response(response, status)


@app.timer_trigger(arg_name="timer", schedule=ONEDRIVE_SYNC_TIMER_SCHEDULE)
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

    pre_sync = dependencies.planning_context_pre_sync_service.run(
        athlete_id=athlete_id, days=days
    )
    logger.info(
        "Planning context JIT pre-sync completed",
        extra={
            "athlete_id": athlete_id,
            "days": days,
            "pre_sync_status": pre_sync.get("status"),
        },
    )

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
# Training State Endpoints (On-Demand Projections)
# ============================================================================

@app.route(route="training-state/current", methods=["GET"])
@endpoint
def get_current_training_state(req: func.HttpRequest) -> func.HttpResponse:
    """Get current training state (computed on-demand from Workouts + Physiometrics).
    
    IMPORTANT: TrainingState is NOT stored - computed fresh for each request.
    
    Returns:
        - cts_rolling_7d, cts_rolling_28d (chronic training stress)
        - ats_rolling (acute training stress)
        - fatigue_index (ATS/CTS ratio)
        - readiness_score, garmin_readiness_score
    """
    athlete_id = req.params.get("athlete_id", "rob")

    handler = PhysiometricsHandler(dependencies.semantic_layer)
    result, status = handler.get_training_state_current(athlete_id)

    return json_response(result, status)


@app.route(route="training-state/history", methods=["GET"])
@endpoint
def get_training_state_history(req: func.HttpRequest) -> func.HttpResponse:
    """Get training state history (computed on-demand for date range).
    
    IMPORTANT: TrainingState is NOT stored - computed fresh for each request.
    
    Args:
        athlete_id: Athlete identifier (default: "rob")
        days: Number of days to look back (default: 45, max: 90)
    
    Returns:
        List of daily training state snapshots with rolling TSS and fatigue metrics.
    """
    athlete_id = req.params.get("athlete_id", "rob")
    days = int(req.params.get("days", "45"))

    handler = PhysiometricsHandler(dependencies.semantic_layer)
    result, status = handler.get_training_state_history(athlete_id, days)

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


@app.timer_trigger(arg_name="timer", schedule=GARMIN_SYNC_TIMER_SCHEDULE)
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


@app.route(
    route="garmin/physiometrics/sync",
    methods=["POST"],
    auth_level=func.AuthLevel.FUNCTION,
)
@endpoint
def garmin_physiometrics_sync_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered Garmin physiometrics sync (summary + training status)."""
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}

    athlete_id = (
        body.get("athlete_id")
        or req.params.get("athlete_id")
        or os.getenv("DEFAULT_ATHLETE_ID", "rob")
    )
    lookback_days = body.get("lookback_days")
    if lookback_days is None:
        lookback_days = req.params.get("lookback_days")
    force_raw = body.get("force")
    if force_raw is None:
        force_raw = req.params.get("force")
    force = False
    if isinstance(force_raw, bool):
        force = force_raw
    elif isinstance(force_raw, str):
        force = force_raw.lower() in ("true", "1", "yes")
    elif isinstance(force_raw, int):
        force = force_raw == 1

    handler = dependencies.garmin_physiometrics_service
    response, status = handler.handle(athlete_id, lookback_days, force=force)
    return json_response(response, status)


@app.timer_trigger(arg_name="timer", schedule=GARMIN_PHYSIOMETRICS_SYNC_TIMER_SCHEDULE)
def garmin_physiometrics_sync_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered Garmin physiometrics sync."""
    if timer.past_due:
        logger.warning("Garmin physiometrics sync timer is past due")

    try:
        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")
        handler = dependencies.garmin_physiometrics_service

        response, status = handler.handle(athlete_id)

        if status == 200:
            logger.info("Garmin physiometrics sync completed: %s", response)
        else:
            logger.warning("Garmin physiometrics sync failed: %s", response)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Garmin physiometrics timer failed: %s", exc, exc_info=True)
    finally:
        logger.debug("Garmin physiometrics timer trigger completed")


# ============================================================================
# Intervals.icu Sync Endpoints
# ============================================================================

@app.route(route="intervals/sync", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def intervals_sync_http(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered Intervals.icu physiometrics sync.
    
    Resolves two independent athlete identities:
    
    1. intervals_athlete_id (for Intervals API URL calls) - priority order:
       - Request body: {"intervals_athlete_id": "..."}
       - Query parameter: ?intervals_athlete_id=...
       - Environment: INTERVALS_ATHLETE_ID
       - Error (required for API fetch)
    
    2. athlete_id (for storage partition) - priority order:
       - Request body: {"athlete_id": "..."}
       - Query parameter: ?athlete_id=...
       - Environment: DEFAULT_ATHLETE_ID (default: "rob")
    
    Returns 400 if intervals_athlete_id cannot be resolved (API identity is required).
    Storage athlete_id has a safe default fallback.
    """
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}

    # Resolve intervals_athlete_id for API fetch (required)
    intervals_athlete_id = (
        body.get("intervals_athlete_id")
        or req.params.get("intervals_athlete_id")
        or os.getenv("INTERVALS_ATHLETE_ID")
    )
    
    # Resolve athlete_id for storage partition (has safe default)
    athlete_id = (
        body.get("athlete_id")
        or req.params.get("athlete_id")
        or os.getenv("DEFAULT_ATHLETE_ID", "rob")
    )
    
    lookback_days = body.get("lookback_days") or req.params.get("lookback_days")
    if lookback_days is not None:
        try:
            lookback_days = int(lookback_days)
        except (ValueError, TypeError):
            logger.warning("Invalid lookback_days, using default", extra={"lookback_days": lookback_days})
            lookback_days = None

    # Validate intervals_athlete_id (required for API)
    if not intervals_athlete_id:
        logger.warning("Missing intervals_athlete_id for Intervals sync")
        return json_response({"error": "intervals_athlete_id parameter required"}, 400)

    # Log resolved sources for auditability
    if body.get("intervals_athlete_id"):
        logger.info("Intervals sync: intervals_athlete_id from request body")
    elif req.params.get("intervals_athlete_id"):
        logger.info("Intervals sync: intervals_athlete_id from query parameter")
    else:
        logger.info("Intervals sync: intervals_athlete_id from INTERVALS_ATHLETE_ID env")
    
    if body.get("athlete_id"):
        logger.info("Intervals sync: athlete_id from request body")
    elif req.params.get("athlete_id"):
        logger.info("Intervals sync: athlete_id from query parameter")
    else:
        logger.info("Intervals sync: athlete_id from DEFAULT_ATHLETE_ID fallback")

    handler = dependencies.intervals_service
    response, status = handler.handle(
        intervals_athlete_id=intervals_athlete_id,
        athlete_id=athlete_id,
        lookback_days=lookback_days,
    )

    return json_response(response, status)


@app.timer_trigger(arg_name="timer", schedule=INTERVALS_SYNC_TIMER_SCHEDULE)
def intervals_sync_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered Intervals.icu physiometrics sync.
    
    Uses INTERVALS_ATHLETE_ID for API fetch and DEFAULT_ATHLETE_ID for storage.
    """
    if timer.past_due:
        logger.warning("Intervals sync timer is past due")

    try:
        intervals_athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
        athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")

        if not intervals_athlete_id:
            logger.warning(
                "Intervals sync timer missing INTERVALS_ATHLETE_ID; skipping sync"
            )
            return

        handler = dependencies.intervals_service

        response, status = handler.handle(
            intervals_athlete_id=intervals_athlete_id,
            athlete_id=athlete_id,
        )

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


@app.timer_trigger(arg_name="timer", schedule="0 0 5 * * 1")  # 5 AM UTC every Monday
def weekly_rollup_timer(timer: func.TimerRequest) -> None:
    """Timer-triggered weekly rollup persistence for the previous completed local week."""
    if timer.past_due:
        logger.warning("Weekly rollup timer is past due")

    athlete_id = os.getenv("DEFAULT_ATHLETE_ID", "rob")

    try:
        athletes = dependencies.semantic_layer.list_athletes_with_workouts()
        if not athletes:
            athletes = [athlete_id]

        pre_sync = _run_weekly_presync_for_athletes(athletes, enabled=True)
        if pre_sync.get("status") != "success":
            logger.error(
                "Weekly rollup timer pre-sync failed; rollup aborted",
                extra={
                    "athlete_id": athlete_id,
                    "pre_sync": pre_sync,
                },
            )
            return

        result = dependencies.semantic_layer.compute_and_persist_previous_week_rollups(
            athlete_ids=athletes,
        )
        athlete_results = result.get("results", [])
        succeeded_count = sum(1 for item in athlete_results if item.get("status") == "success")
        skipped_count = sum(1 for item in athlete_results if item.get("status") == "skipped")
        failed_count = sum(1 for item in athlete_results if item.get("status") in {"failed", "partial"})

        logger.info(
            "Weekly rollup timer succeeded",
            extra={
                "requested_athletes": len(athlete_results),
                "succeeded_count": succeeded_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
                "pre_sync": pre_sync,
            },
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error("Weekly rollup timer failed: %s", exc, exc_info=True)


@app.route(route="operations/rollups/weekly/compute", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@endpoint
def force_weekly_rollups(req: func.HttpRequest) -> func.HttpResponse:
    """Operational endpoint to force previous-week rollup computation and persistence."""
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}

    all_athletes = bool(body.get("all_athletes", False))
    requested_athlete_ids = body.get("athlete_ids")
    athlete_id = body.get("athlete_id") or req.params.get("athlete_id")
    raw_weeks = body.get("weeks", req.params.get("weeks", 1))

    try:
        weeks = int(raw_weeks)
    except (TypeError, ValueError):
        return json_response({"error": "weeks must be an integer >= 1"}, 400)

    if weeks < 1:
        return json_response({"error": "weeks must be >= 1"}, 400)

    athletes = []
    if isinstance(requested_athlete_ids, list):
        athletes = [str(item) for item in requested_athlete_ids if str(item).strip()]
    elif athlete_id:
        athletes = [str(athlete_id)]
    elif all_athletes:
        athletes = dependencies.semantic_layer.list_athletes_with_workouts()

    if not athletes:
        athletes = [os.getenv("DEFAULT_ATHLETE_ID", "rob")]

    result = dependencies.semantic_layer.compute_and_persist_previous_week_rollups(
        athlete_ids=athletes,
        weeks=weeks,
    )

    status = 207 if result.get("status") in {"partial", "failed"} else 200
    return json_response(result, status)
