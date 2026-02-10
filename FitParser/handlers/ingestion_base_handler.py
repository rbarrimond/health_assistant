"""Shared ingestion helper logic for FIT processing."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from FitParser.fit_parser import FitParser
from FitParser.table_storage import WorkoutTableStorage

logger = logging.getLogger(__name__)


class FitIngestionBaseHandler(ABC):
    """Abstract base for FIT ingestion handlers (payload + sync)."""

    def __init__(self, storage: WorkoutTableStorage):
        self.storage = storage

    @abstractmethod
    def handle(self, *args, **kwargs) -> Tuple[Dict[str, Any], int]:
        """Process a FIT ingestion request and return (response, status)."""
        raise NotImplementedError

    def _skip_if_unchanged(
        self,
        athlete_id: str,
        source_info: Dict[str, Any],
        *,
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str]]:
        context = self.storage.get_ingestion_context(
            athlete_id,
            source_info,
            ingestion_key=ingestion_key,
            existing_state=existing_state,
        )
        if not context.should_skip():
            return False, None

        workout_id = (
            context.existing_state.get("workout_id")
            if context.existing_state
            else None
        )
        self.storage.record_ingestion_state(
            athlete_id,
            source_info,
            status="skipped",
            workout_id=workout_id,
            ingestion_key=context.ingestion_key,
            existing_state=context.existing_state,
        )
        return True, workout_id

    def ingest_bytes(
        self,
        athlete_id: str,
        source_info: Dict[str, Any],
        file_bytes: bytes,
        *,
        file_path: Optional[str] = None,
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        # Derived handlers normalize input then call this to run shared ingestion.
        """Ingest a FIT file already available as bytes."""
        skipped, workout_id = self._skip_if_unchanged(
            athlete_id,
            source_info,
            ingestion_key=ingestion_key,
            existing_state=existing_state,
        )
        if skipped:
            return {"status": "skipped", "workout_id": workout_id}, 200

        _, workout_id = self._parse_and_store(
            athlete_id,
            source_info,
            file_bytes=file_bytes,
            file_path=file_path,
        )
        return {"status": "success", "workout_id": workout_id}, 200

    def _parse_and_store(
        self,
        athlete_id: str,
        source_info: Dict[str, Any],
        *,
        file_path: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
    ) -> Tuple[Dict[str, Any], str]:
        parser = FitParser(
            file_path=file_path,
            file_bytes=file_bytes,
            source_file_name=source_info.get("source_file_name"),
        )
        metrics = parser.parse()
        workout_id = self.storage.store_workout(
            athlete_id, metrics, source_info
        )
        lap_records = parser.extract_lap_records()
        if lap_records:
            self.storage.store_workout_laps(
                athlete_id,
                workout_id,
                lap_records,
            )
        self.storage.record_ingestion_state(
            athlete_id,
            source_info,
            status="ingested",
            workout_id=workout_id,
        )
        return metrics, workout_id

    def _record_failure(
        self,
        athlete_id: str,
        source_info: Optional[Dict[str, Any]],
        error_message: str,
    ) -> None:
        if not source_info:
            return
        self.storage.record_ingestion_state(
            athlete_id,
            source_info,
            status="failed",
            error=error_message,
        )
