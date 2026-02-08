"""Handle FIT payload ingestion from base64 content."""

import base64
import logging
import os
import tempfile
from typing import Any, Dict, Optional, Tuple

from FitParser.exceptions import FitAdapterError, WorkoutTypeResolutionError
from FitParser.fit_parser import compute_file_hash
from FitParser.handlers.ingestion_base import IngestionHandlerBase

logger = logging.getLogger(__name__)


class FitPayloadIngestionHandler(IngestionHandlerBase):
    """Ingest FIT payloads encoded as base64 plus metadata."""

    def handle_payload(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """Process a payload containing base64 FIT file content and metadata."""
        athlete_id = payload.get("athlete_id", "rob")
        source_info: Optional[Dict[str, Any]] = None
        tmp_path: Optional[str] = None

        try:
            file_bytes = self._extract_payload_bytes(payload)
            tmp_path = self._write_temp_fit(file_bytes)
            source_info = self._build_payload_source_info(payload, tmp_path)

            skipped, workout_id = self._skip_if_unchanged(athlete_id, source_info)
            if skipped:
                return {"status": "skipped", "workout_id": workout_id}, 200

            _, workout_id = self._parse_and_store(athlete_id, tmp_path, source_info)
            return {"status": "success", "workout_id": workout_id}, 200

        except (ValueError, TypeError, FitAdapterError) as exc:
            logger.warning("FIT payload ingestion validation failed: %s", exc)
            self._record_failure(athlete_id, source_info, str(exc))
            return {"status": "error", "error": str(exc)}, 400
        except WorkoutTypeResolutionError as exc:
            logger.error("Workout type resolution failed: %s", exc)
            self._record_failure(athlete_id, source_info, "Workout type resolution failed")
            return {"status": "error", "error": "Workout type resolution failed"}, 500
        except OSError as exc:
            logger.error("FIT payload file operation failed: %s", exc)
            self._record_failure(athlete_id, source_info, "File operation failed")
            return {"status": "error", "error": "File operation failed"}, 500
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("FIT payload ingestion failed: %s", exc, exc_info=True)
            self._record_failure(athlete_id, source_info, "Internal server error")
            return {"status": "error", "error": "Internal server error"}, 500
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _extract_payload_bytes(self, payload: Dict[str, Any]) -> bytes:
        file_content_b64 = payload.get("file_content_b64")
        if not file_content_b64:
            raise ValueError("No file content")

        try:
            return base64.b64decode(file_content_b64)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError("Invalid base64 content") from exc

    def _write_temp_fit(self, file_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".fit") as tmp:
            tmp.write(file_bytes)
            return tmp.name

    def _build_payload_source_info(
        self,
        payload: Dict[str, Any],
        tmp_path: str,
    ) -> Dict[str, Any]:
        return {
            "source_system": payload.get("source_system", "HealthFit"),
            "source_file_name": payload.get("source_file_name"),
            "source_file_path": payload.get("source_file_path"),
            "source_item_id": payload.get("source_item_id"),
            "source_drive_id": payload.get("source_drive_id"),
            "source_etag": payload.get("source_etag"),
            "source_ctag": payload.get("source_ctag"),
            "source_quickxor_hash": payload.get("source_quickxor_hash"),
            "source_modified_at_utc": payload.get("source_modified_at_utc"),
            "file_size_bytes": payload.get("file_size_bytes"),
            "file_sha256": payload.get("file_sha256")
            or compute_file_hash(tmp_path),
        }
