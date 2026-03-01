"""Shared ingestion helper logic for FIT processing."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import (
    DeviceFilteredError,
    IngestionIdResolutionError,
    WorkoutIdCalculationError,
)
from TrainingAnalyticsPlatform.ingestion.code_mappings import (
    GARMIN_API_ALLOWED_MANUFACTURERS,
)
from TrainingAnalyticsPlatform.ingestion.device_classifier import FitDevice
from TrainingAnalyticsPlatform.ingestion.fit_models import create_fit_model
from TrainingAnalyticsPlatform.storage.storage_infrastructure import CANONICAL_SCHEMA_VERSION

logger = logging.getLogger(__name__)


class FitIngestionBaseHandler(ABC):
    """Abstract base for FIT ingestion handlers (payload + sync)."""

    def __init__(self, storage):
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
        context = self.storage.workouts.get_ingestion_context(
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
        self.storage.workouts.record_ingestion_state(
            athlete_id,
            source_info,
            status="skipped",
            workout_id=workout_id,
            ingestion_id=source_info.get("ingestion_id"),
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
        ingestion_id = source_info.get("ingestion_id")
        if not ingestion_id:
            raise IngestionIdResolutionError(
                "ingestion_id is required and must be computed by concrete handlers"
            )

        skipped, workout_id = self._skip_if_unchanged(
            athlete_id,
            source_info,
            ingestion_key=ingestion_key or ingestion_id,
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
        model.validate_semantic_contract()
        
        # Apply device-source filtration rules
        self._apply_device_source_filtration(athlete_id, model, source_info)
        
        # Build structured canonical metadata with semantic zones
        structured_metadata = model.build_canonical_metadata()
        
        # Extract ingestion context for provenance zone
        ingestion_id = source_info.get("ingestion_id")
        if not ingestion_id:
            raise IngestionIdResolutionError(
                "ingestion_id is required and must be computed by concrete handlers"
            )
        source_info["ingestion_id"] = ingestion_id
        
        # Add provenance zone (zone 8)
        from datetime import datetime, timezone
        structured_metadata["provenance"] = {
            "ingestion_version": source_info.get("ingestion_version", "1.0.0"),
            "ingestion_id": ingestion_id,
            "ingestion_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment": source_info.get("environment", "production"),
        }
        
        # Flatten metadata for backward compatibility with _normalize_source_system
        flat_metadata = self._flatten_structured_metadata(structured_metadata)
        
        source_info["normalized_source_system"] = self._normalize_source_system(
            source_info, flat_metadata
        )

        workout_id = model.semantic_workout_id
        if not workout_id:
            raise WorkoutIdCalculationError(
                "Unable to compute workout_id from precise start time + sport code"
            )

        raw_fit_frames = model.raw_frames(as_json=True)
        assert isinstance(raw_fit_frames, str), "raw_frames with as_json=True must return JSON string"
        raw_fit_payload = json.loads(raw_fit_frames)
        metadata_payload = model.build_metadata_messages()
        laps_payload = model.build_laps_json()
        analysis_payload = model.build_fit_analysis()

        record_set = model.build_canonical_records()
        records_blob = self.storage.workouts.store_canonical_records(ingestion_id, record_set)
        self.storage.workouts.store_raw_fit_json(ingestion_id, raw_fit_payload)
        self.storage.workouts.store_metadata_json(ingestion_id, metadata_payload)
        self.storage.workouts.store_laps_json(ingestion_id, laps_payload)
        self.storage.workouts.store_fit_analysis(ingestion_id, analysis_payload)
        laps_count = len(laps_payload.get("laps", []))

        # Store structured metadata (all 8 semantic zones) to blob
        self.storage.workouts.store_canonical_metadata_blob(ingestion_id, structured_metadata)

        self.storage.workouts.store_workout(
            athlete_id,
            structured_metadata,
            source_info,
            workout_id=workout_id,
            ingestion_id=ingestion_id,
            canonical_schema_version=CANONICAL_SCHEMA_VERSION,
            canonical_records_blob=records_blob,
            records_count=len(record_set.to_dataframe),
            laps_count=laps_count,
        )
        self.storage.workouts.record_ingestion_state(
            athlete_id,
            source_info,
            status="ingested",
            workout_id=workout_id,
            ingestion_id=ingestion_id,
            ingestion_key=ingestion_id,
        )
        return flat_metadata, workout_id

    @staticmethod
    def _flatten_structured_metadata(structured_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten semantic zones back to flat dict for backward compatibility.
        
        Args:
            structured_metadata: Metadata with semantic zones (identity, capabilities, session, etc.)
            
        Returns:
            Flattened dict with all fields at top level
        """
        flat = {}
        for zone_name, zone_data in structured_metadata.items():
            if isinstance(zone_data, dict):
                flat.update(zone_data)
        return flat

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
        self.storage.workouts.record_ingestion_state(
            athlete_id,
            source_info,
            status="failed",
            error=error_message,
            ingestion_id=source_info.get("ingestion_id") if source_info else None,
        )

    def _apply_device_source_filtration(
        self,
        athlete_id: str,
        model: Any,
        source_info: Dict[str, Any],
    ) -> None:
        """Apply device-source classification and filtration rules during ingestion.
        
        This method classifies the device source (Apple Watch vs. HealthKit synced)
        and enriches source_info for downstream processing. Currently a checkpoint
        for future filtration logic (exclusion, normalization, flagging).
        
        Args:
            model: Instantiated FIT model (BaseFitModel and subclasses)
            source_info: Ingestion source metadata dict (mutated with device classification)
        """
        device_name = model.device_name
        device_manufacturer_code = model.device_manufacturer_code
        device_product_code = model.device_product_code

        # Classify device source
        device_source_type = FitDevice.device_source_type(
            device_name=device_name,
            device_manufacturer_code=device_manufacturer_code,
            device_product_code=device_product_code,
        )
        
        is_healthkit_synced = FitDevice.is_healthkit_synced(
            device_name=device_name,
            device_manufacturer_code=device_manufacturer_code,
            device_product_code=device_product_code,
        )

        # Enrich source_info with device classification for logging/tracking
        source_info["device_source_type"] = device_source_type
        source_info["is_healthkit_synced"] = is_healthkit_synced

        # Log device classification for monitoring
        logger.info(
            "Device source classification: device_source_type=%s, "
            "is_healthkit_synced=%s, device_name=%r",
            device_source_type,
            is_healthkit_synced,
            device_name,
        )

        handler_name = self.__class__.__name__
        if handler_name == "FitPayloadIngestionHandler":
            return

        if handler_name == "OneDriveSyncIngestionHandler" and is_healthkit_synced:
            reason = "healthkit_synced"
            message = "Filtered HealthKit-synced workout (iPhone sentinel)"
            self._record_filtered_ingestion(
                athlete_id,
                source_info,
                message=message,
                reason=reason,
            )
            raise DeviceFilteredError(
                message,
                device_name=device_name,
                device_source_type=device_source_type,
                manufacturer_code=device_manufacturer_code,
                reason=reason,
            )

        if handler_name == "GarminSyncIngestionHandler":
            if device_manufacturer_code not in GARMIN_API_ALLOWED_MANUFACTURERS:
                reason = "manufacturer_not_allowed"
                allowed = sorted(GARMIN_API_ALLOWED_MANUFACTURERS)
                message = (
                    "Filtered Garmin API workout: manufacturer_code "
                    f"{device_manufacturer_code} not in allowlist {allowed}"
                )
                self._record_filtered_ingestion(
                    athlete_id,
                    source_info,
                    message=message,
                    reason=reason,
                )
                raise DeviceFilteredError(
                    message,
                    device_name=device_name,
                    device_source_type=device_source_type,
                    manufacturer_code=device_manufacturer_code,
                    reason=reason,
                )

    def _record_filtered_ingestion(
        self,
        athlete_id: str,
        source_info: Dict[str, Any],
        *,
        message: str,
        reason: str,
    ) -> None:
        logger.warning(
            "Device filtration rejected file: reason=%s, message=%s, source_info=%s",
            reason,
            message,
            source_info,
        )
        self.storage.workouts.record_ingestion_state(
            athlete_id,
            source_info,
            status="filtered",
            error=f"{reason}:{message}",
            ingestion_id=source_info.get("ingestion_id"),
            ingestion_key=source_info.get("ingestion_id"),
        )

