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

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

JSON_CONTENT_TYPE = "application/json"

app = func.FunctionApp()

# Initialize and warm up table storage on host start (idempotent table creation).
try:
    _storage_singleton = WorkoutTableStorage()
    logger.info("Table storage initialized on startup")
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
    logger.info("FIT file ingestion function triggered")

    try:
        # Parse request payload
        payload = parse_onedrive_payload(req)
        logger.info("Processing file: %s", payload.get("source_file_name"))

        athlete_id = payload["athlete_id"]
        file_content_b64 = payload["file_content_b64"]

        # Decode base64 file content
        try:
            file_content = base64.b64decode(file_content_b64)
        except (TypeError, ValueError) as e:
            logger.error("Failed to decode base64 file content: %s", e)
            return func.HttpResponse(
                json.dumps({"error": "Invalid base64 encoding"}),
                status_code=400,
                mimetype=JSON_CONTENT_TYPE
            )

        # Write to temporary file
        with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            # Compute file hash for idempotency
            file_sha256 = compute_file_hash(tmp_path)
            logger.info("File SHA256: %s", file_sha256)

            # Use singleton storage if available; else initialize.
            if '_storage_singleton' in globals() and _storage_singleton:
                storage = _storage_singleton
            else:
                storage = WorkoutTableStorage()

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

            # Parse FIT file
            parser = FitParser(tmp_path)
            metrics = parser.parse()
            logger.info("Parsed metrics: %s", list(metrics.keys()))

            # Build source info
            source_info = {
                "source_system": "HealthFit",
                "source_file_name": payload.get("source_file_name"),
                "source_file_path": payload.get("source_file_path", ""),
                "source_item_id": payload.get("source_item_id"),
                "source_drive_id": payload.get("source_drive_id"),
                "source_etag": payload.get("source_etag"),
                "file_size_bytes": payload.get("file_size_bytes", len(file_content)),
                "file_sha256": file_sha256,
            }

            # Store in Azure Tables
            workout_id = storage.store_workout(athlete_id, metrics, source_info)

            # Record successful ingestion
            storage.record_ingestion_state(
                athlete_id,
                {**source_info, "first_seen_at_utc": metrics.get("start_time_utc")},
                status="ingested",
                workout_id=workout_id
            )

            logger.info("Successfully ingested workout %s", workout_id)

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

        except (ValueError, OSError, IOError) as e:
            logger.error("Error parsing or storing FIT file: %s", e, exc_info=True)

            # Record failed ingestion
            try:
                if '_storage_singleton' in globals() and _storage_singleton:
                    storage = _storage_singleton
                else:
                    storage = WorkoutTableStorage()
                storage.record_ingestion_state(
                    athlete_id,
                    payload,
                    status="failed",
                    error=str(e)
                )
            except (ValueError, OSError, IOError):
                pass

            return func.HttpResponse(
                json.dumps({"error": f"Failed to process FIT file: {str(e)}"}),
                status_code=500,
                mimetype=JSON_CONTENT_TYPE
            )

        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except ValueError as e:
        logger.error("Validation error: %s", e)
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
