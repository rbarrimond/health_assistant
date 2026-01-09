"""Azure Function to process FIT files from OneDrive."""

import base64
import json
import logging
import os
import tempfile
from typing import Dict, Optional

import azure.functions as func

from FitParser.fit_parser import FitParser, compute_file_hash
from FitParser.table_storage import WorkoutTableStorage

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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
    except ValueError:
        raise ValueError("Invalid JSON payload")

    required_fields = ["athlete_id", "source_file_name", "file_content_b64"]
    missing = [f for f in required_fields if f not in req_body]
    if missing:
        raise ValueError(f"Missing required fields: {missing}")

    return req_body


def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Main Azure Function handler - triggered by Power BI/OneDrive changes.
    
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
        except Exception as e:
            logger.error("Failed to decode base64 file content: %s", e)
            return func.HttpResponse(
                json.dumps({"error": "Invalid base64 encoding"}),
                status_code=400,
                mimetype="application/json"
            )

        # Write to temporary file
        with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        try:
            # Compute file hash for idempotency
            file_sha256 = compute_file_hash(tmp_path)
            logger.info("File SHA256: %s", file_sha256)

            # Initialize storage and check if already processed
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
                    mimetype="application/json"
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
                mimetype="application/json"
            )

        except Exception as e:
            logger.error("Error parsing or storing FIT file: %s", e, exc_info=True)
            
            # Record failed ingestion
            try:
                storage = WorkoutTableStorage()
                storage.record_ingestion_state(
                    athlete_id,
                    payload,
                    status="failed",
                    error=str(e)
                )
            except:
                pass

            return func.HttpResponse(
                json.dumps({"error": f"Failed to process FIT file: {str(e)}"}),
                status_code=500,
                mimetype="application/json"
            )

        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_path)
            except:
                pass

    except ValueError as e:
        logger.error("Validation error: %s", e)
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json"
        )
