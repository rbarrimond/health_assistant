"""Azure Functions app - Process FIT files from OneDrive."""

import base64
import json
import logging
import os
import tempfile
from typing import Dict

import azure.functions as func
from azure.core.exceptions import AzureError

from FitParser.config import Config
from FitParser.fit_parser import FitParser, compute_file_hash
from FitParser.table_storage import WorkoutTableStorage
from FitParser.semantic_layer import SemanticLayer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

JSON_CONTENT_TYPE = "application/json"
ERR_VALIDATION = "Validation error: %s"
ERR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"

app = func.FunctionApp()

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


@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:  # pylint: disable=unused-argument
    """Health check endpoint."""
    return func.HttpResponse(
        json.dumps({"status": "healthy"}),
        status_code=200,
        mimetype=JSON_CONTENT_TYPE
    )


@app.route(route="config/reload", methods=["POST"])
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


@app.route(route="config/update", methods=["POST"])
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
            json.dumps({"error": "Invalid JSON payload"}),
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


def parse_onedrive_payload(req: func.HttpRequest) -> Dict:
    """
    Parse OneDrive change notification or direct file payload.

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
        raise ValueError("Invalid JSON payload") from exc

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


def _build_success_response(workout_id: str, athlete_id: str, metrics: Dict) -> func.HttpResponse:
    """Build success response for ingested workout."""
    return func.HttpResponse(
        json.dumps({
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
        }),
        status_code=200,
        mimetype=JSON_CONTENT_TYPE
    )


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
@app.route(route="process_fit", methods=["POST"])
def process_fit_files(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP-triggered function to process FIT files from OneDrive.

    Process flow:
    1. Parse incoming OneDrive file payload
    2. Save file temporarily
    3. Parse FIT file for metrics
    4. Store workout data in Azure Tables
    5. Record ingestion state for idempotency
    """
    # pylint: disable=too-many-locals
    logger.info("FIT file ingestion function triggered")

    try:
        payload = parse_onedrive_payload(req)
        logger.info("Processing file: %s", payload.get("source_file_name"))

        athlete_id = payload["athlete_id"]
  
        # Decode and write to temp file
        try:
            file_content = _decode_fit_file_content(payload["file_content_b64"])
        except ValueError as e:
            return func.HttpResponse(
                json.dumps({"error": str(e)}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

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
                return func.HttpResponse(
                    json.dumps({
                        "status": "skipped",
                        "reason": "File already processed",
                        "workout_id": existing.get("workout_id")
                    }),
                    status_code=200,
                    mimetype=JSON_CONTENT_TYPE
                )

            # Parse and store
            metrics = FitParser(tmp_path).parse()
            logger.info("Parsed metrics: %s", list(metrics.keys()))

            source_info = _build_source_info(payload, file_sha256, len(file_content))
            workout_id = storage.store_workout(athlete_id, metrics, source_info)

            storage.record_ingestion_state(
                athlete_id,
                {**source_info, "first_seen_at_utc": metrics.get("start_time_utc")},
                status="ingested",
                workout_id=workout_id
            )

            logger.info("Successfully ingested workout %s", workout_id)
            return _build_success_response(workout_id, athlete_id, metrics)

        except (ValueError, OSError, IOError) as e:
            logger.error("Error parsing or storing FIT file: %s", e, exc_info=True)
            _record_failed_ingestion(athlete_id, payload, str(e))
            return func.HttpResponse(
                json.dumps({"error": f"Failed to process FIT file: {str(e)}"}),
                status_code=500,
                mimetype=JSON_CONTENT_TYPE
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

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
# Semantic Access Layer Endpoints
# =============================================================================


@app.route(route="api/planning/context", methods=["GET"])
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
    except Exception as e:  # pylint: disable=broad-exception-caught  # pylint: disable=broad-exception-caught
        logger.error("Error retrieving planning context: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Failed to retrieve planning context"}),
            status_code=500,
            mimetype=JSON_CONTENT_TYPE
        )


@app.route(route="api/workouts", methods=["GET"])
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


@app.route(route="api/workouts/{workout_id}", methods=["GET"])
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


@app.route(route="api/rollups/weekly", methods=["GET"])
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


@app.route(route="api/analysis/zones", methods=["GET"])
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


@app.route(route="api/analysis/efficiency", methods=["GET"])
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
