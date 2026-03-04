"""Handle FIT payload ingestion from base64 content."""

import base64
import logging
from typing import Any, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import (
    DeviceFilteredError,
    FitParsingError,
    IngestionIdResolutionError,
    WorkoutIdCalculationError,
    WorkoutTypeResolutionError,
)
from TrainingAnalyticsPlatform.handlers.ingestion_hashing import compute_bytes_hash
from TrainingAnalyticsPlatform.handlers.ingestion_base_handler import FitIngestionBaseHandler

logger = logging.getLogger(__name__)


class FitPayloadIngestionHandler(FitIngestionBaseHandler):
    """Ingest FIT payloads encoded as base64 plus metadata."""

    _WORKOUT_TYPE_RESOLUTION_ERROR_MESSAGE = "Workout type resolution failed"

    def handle(self, *args, **kwargs) -> Tuple[Dict[str, Any], int]:
        """Handle ingestion requests (HTTP payloads)."""
        payload = self._extract_payload(args, kwargs)
        return self.handle_payload(payload)

    def handle_payload(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """Process a payload containing base64 FIT file content and metadata."""
        athlete_id = payload.get("athlete_id", "rob")
        source_info: Optional[Dict[str, Any]] = None
        try:
            source_info, response = self._process_payload_ingestion(payload, athlete_id)
            return response
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return self._handle_payload_exception(athlete_id, source_info, exc)

    def _process_payload_ingestion(
        self,
        payload: Dict[str, Any],
        athlete_id: str,
    ) -> Tuple[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        file_bytes = self._extract_payload_bytes(payload)
        source_info = self._build_payload_source_info(payload, file_bytes)
        response = self.ingest_bytes(
            athlete_id,
            source_info,
            file_bytes,
            file_path=source_info.get("source_file_path"),
        )
        return source_info, response

    def _handle_payload_exception(
        self,
        athlete_id: str,
        source_info: Optional[Dict[str, Any]],
        exc: Exception,
    ) -> Tuple[Dict[str, Any], int]:
        if isinstance(exc, IngestionIdResolutionError):
            logger.error(
                "FIT payload ingestion_id resolution failed",
                extra=self._payload_log_extra(athlete_id, source_info, exc),
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response()

        if isinstance(exc, WorkoutIdCalculationError):
            logger.error(
                "FIT payload workout_id calculation failed",
                extra=self._payload_log_extra(athlete_id, source_info, exc),
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response()

        if isinstance(exc, FitParsingError):
            logger.error(
                "FIT payload parse failed",
                extra=self._payload_log_extra(athlete_id, source_info, exc),
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response()

        if isinstance(exc, DeviceFilteredError):
            logger.warning(
                "FIT payload filtered by device classification",
                extra=self._payload_log_extra(athlete_id, source_info, exc, include_reason=True),
            )
            return exc.to_response()

        if isinstance(exc, (ValueError, TypeError)):
            logger.warning(
                "FIT payload ingestion validation failed",
                extra=self._payload_log_extra(athlete_id, source_info, exc, include_ingestion_id=False),
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return {"status": "error", "error": str(exc)}, 400

        if isinstance(exc, WorkoutTypeResolutionError):
            logger.error(
                self._WORKOUT_TYPE_RESOLUTION_ERROR_MESSAGE,
                extra=self._payload_log_extra(athlete_id, source_info, exc),
                exc_info=True,
            )
            self._record_failure(
                athlete_id,
                source_info,
                self._WORKOUT_TYPE_RESOLUTION_ERROR_MESSAGE,
            )
            return {"status": "error", "error": self._WORKOUT_TYPE_RESOLUTION_ERROR_MESSAGE}, 500

        logger.error(
            "FIT payload ingestion failed",
            extra=self._payload_log_extra(athlete_id, source_info, exc),
            exc_info=True,
        )
        self._record_failure(athlete_id, source_info, "Internal server error")
        return {"status": "error", "error": "Internal server error"}, 500

    @staticmethod
    def _payload_log_extra(
        athlete_id: str,
        source_info: Optional[Dict[str, Any]],
        exc: Exception,
        include_ingestion_id: bool = True,
        include_reason: bool = False,
    ) -> Dict[str, Any]:
        extra = {
            "athlete_id": athlete_id,
            "source_system": source_info.get("source_system") if source_info else None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if include_ingestion_id:
            extra["ingestion_id"] = source_info.get("ingestion_id") if source_info else None
        if include_reason:
            extra["reason"] = str(exc)
        return extra

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
        source_info = {
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
        source_info["ingestion_id"] = self._resolve_ingestion_id(source_info)
        return source_info

    @staticmethod
    def _resolve_ingestion_id(source_info: Dict[str, Any]) -> str:
        source_item_id = source_info.get("source_item_id")
        if source_item_id:
            return str(source_item_id)

        file_sha256 = source_info.get("file_sha256")
        if file_sha256:
            return str(file_sha256)

        raise IngestionIdResolutionError(
            "Cannot compute ingestion_id without source_item_id or file_sha256"
        )
