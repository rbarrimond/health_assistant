"""Handle FIT payload ingestion from base64 content."""

import base64
import logging
from typing import Any, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import (
    WorkoutTypeResolutionError,
)
from TrainingAnalyticsPlatform.ingestion.fit_parser import compute_bytes_hash
from TrainingAnalyticsPlatform.handlers.ingestion_base_handler import FitIngestionBaseHandler

logger = logging.getLogger(__name__)


class FitPayloadIngestionHandler(FitIngestionBaseHandler):
    """Ingest FIT payloads encoded as base64 plus metadata."""

    def handle(self, *args, **kwargs) -> Tuple[Dict[str, Any], int]:
        """Handle ingestion requests (HTTP payloads)."""
        payload = self._extract_payload(args, kwargs)
        return self.handle_payload(payload)

    def handle_payload(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """Process a payload containing base64 FIT file content and metadata."""
        athlete_id = payload.get("athlete_id", "rob")
        source_info: Optional[Dict[str, Any]] = None
        file_bytes: Optional[bytes] = None

        try:
            file_bytes = self._extract_payload_bytes(payload)
            source_info = self._build_payload_source_info(payload, file_bytes)
            return self.ingest_bytes(
                athlete_id,
                source_info,
                file_bytes,
                file_path=source_info.get("source_file_path"),
            )

        except (ValueError, TypeError) as exc:
            logger.warning("FIT payload ingestion validation failed: %s", exc)
            self._record_failure(athlete_id, source_info, str(exc))
            return {"status": "error", "error": str(exc)}, 400
        except WorkoutTypeResolutionError as exc:
            logger.error("Workout type resolution failed: %s", exc)
            self._record_failure(athlete_id, source_info, "Workout type resolution failed")
            return {"status": "error", "error": "Workout type resolution failed"}, 500
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("FIT payload ingestion failed: %s", exc, exc_info=True)
            self._record_failure(athlete_id, source_info, "Internal server error")
            return {"status": "error", "error": "Internal server error"}, 500

    def _extract_payload(self, args: tuple, kwargs: dict) -> Dict[str, Any]:
        payload = kwargs.get("payload")
        if payload is None and args:
            payload = args[0]
        if not isinstance(payload, dict):
            raise TypeError("payload must be provided as a dict")
        return payload

    def _extract_payload_bytes(self, payload: Dict[str, Any]) -> bytes:
        file_content_b64 = payload.get("file_content_b64")
        if not file_content_b64:
            raise ValueError("No file content")

        try:
            return base64.b64decode(file_content_b64)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError("Invalid base64 content") from exc

    def _build_payload_source_info(
        self,
        payload: Dict[str, Any],
        file_bytes: bytes,
    ) -> Dict[str, Any]:
        return {
            "source_system": payload.get("source_system", Config.ONEDRIVE_SOURCE_SYSTEM),
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
            or compute_bytes_hash(file_bytes),
        }
