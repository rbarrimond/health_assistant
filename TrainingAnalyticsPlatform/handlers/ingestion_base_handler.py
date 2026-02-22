"""Shared ingestion helper logic for FIT processing."""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.ingestion.fit_models import create_fit_model
from TrainingAnalyticsPlatform.ingestion.fit_parser import compute_workout_id
from TrainingAnalyticsPlatform.storage.table_storage import (
    CANONICAL_SCHEMA_VERSION,
    WorkoutTableStorage,
)

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
        file_path: Optional[str] = None,  # pylint: disable=unused-argument
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
        )
        return {"status": "success", "workout_id": workout_id}, 200

    def _parse_and_store(
        self,
        athlete_id: str,
        source_info: Dict[str, Any],
        *,
        file_bytes: bytes,
    ) -> Tuple[Dict[str, Any], str]:
        model = create_fit_model(
            source_metadata=source_info,
            file_bytes=file_bytes,
        )
        metadata = model.build_canonical_metadata()
        source_info["normalized_source_system"] = self._normalize_source_system(
            source_info, metadata
        )
        workout_id = compute_workout_id(
            source_item_id=source_info.get("source_item_id"),
            file_sha256=source_info.get("file_sha256"),
            file_path=source_info.get("source_file_path"),
            file_name=source_info.get("source_file_name"),
            start_time=metadata.get("start_time_utc"),
        )
        semantic_workout_id = model.semantic_workout_id

        raw_fit_payload = model.build_raw_fit(return_dict=True, return_json=False)
        metadata_payload = model.build_metadata_messages()
        laps_payload = model.build_laps_json()
        analysis_payload = model.build_fit_analysis()

        records = model.build_canonical_records()
        records_blob = self.storage.store_canonical_records(workout_id, records)
        self.storage.store_raw_fit_json(workout_id, raw_fit_payload)
        self.storage.store_metadata_json(workout_id, metadata_payload)
        self.storage.store_laps_json(workout_id, laps_payload)
        self.storage.store_fit_analysis(workout_id, analysis_payload)
        laps_count = len(laps_payload.get("laps", []))

        self.storage.store_workout(
            athlete_id,
            metadata,
            source_info,
            workout_id=workout_id,
            semantic_workout_id=semantic_workout_id,
            canonical_schema_version=CANONICAL_SCHEMA_VERSION,
            canonical_records_blob=records_blob,
            records_count=len(records),
            laps_count=laps_count,
        )
        self.storage.record_ingestion_state(
            athlete_id,
            source_info,
            status="ingested",
            workout_id=workout_id,
        )
        return metadata, workout_id

    @staticmethod
    def _normalize_source_system(
        source_info: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> str:
        """Normalize source classification for downstream processing.

        Rule: Apple Watch generated FITs normalize to ONEDRIVE_SOURCE_SYSTEM, all others to Garmin.
        """
        manufacturer = str(metadata.get("file_manufacturer") or "").lower()
        device_name = str(metadata.get("device_name") or "").lower()
        if "apple" in manufacturer or "apple" in device_name or "watch" in device_name:
            return Config.ONEDRIVE_SOURCE_SYSTEM
        if source_info.get("source_system"):
            return "Garmin"
        return "Garmin"

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
