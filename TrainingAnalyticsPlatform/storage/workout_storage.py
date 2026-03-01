"""Workout artifact and metadata storage."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from TrainingAnalyticsPlatform.models import CanonicalRecordSet, WorkoutMetricsModel
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import (
    IngestionContext,
    StorageInfrastructure,
    WorkoutEntity,
)

logger = logging.getLogger(__name__)


class WorkoutStorage:
    """Handle workout metadata, artifacts, and ingestion state."""

    def __init__(self, infrastructure: StorageInfrastructure):
        """Initialize with storage infrastructure."""
        self.infra = infrastructure

    def store_workout(
        self,
        athlete_id: str,
        metadata: Dict,
        source_info: Dict,
        *,
        workout_id: Optional[str] = None,
        ingestion_id: Optional[str] = None,
        canonical_schema_version: Optional[str] = None,
        canonical_records_blob: Optional[str] = None,
        records_count: Optional[int] = None,
        laps_count: Optional[int] = None,
    ) -> str:
        """
        Store canonical workout metadata and parquet pointers in Workouts table.

        Args:
            athlete_id: Athlete identifier (e.g., 'rob')
            metadata: Canonical metadata (semantic zones dict OR flat dict for backward compatibility)
            source_info: OneDrive/source file info
            workout_id: Unique workout identifier
            ingestion_id: Ingestion tracking identifier
            canonical_schema_version: Version of canonical schema
            canonical_records_blob: Blob path for canonical substrate parquet
            records_count: Number of canonical records
            laps_count: Number of canonical laps

        Returns:
            workout_id of stored entity
        """
        if not ingestion_id:
            raise ValueError("ingestion_id is required to store a workout")
        if not workout_id:
            raise ValueError("workout_id is required to store a workout")

        # Extract identity and capability fields from metadata
        # Handle both structured (zones) and flat dict formats
        identity = metadata.get("identity", {}) if "identity" in metadata else {}
        capabilities = metadata.get("capabilities", {}) if "capabilities" in metadata else {}
        provenance = metadata.get("provenance", {}) if "provenance" in metadata else {}
        
        # For backward compatibility, also check flat dict
        if not identity:
            identity = metadata
        
        # Flatten structured metadata for metrics field (semantic layer compatibility)
        flat_metadata = self._flatten_structured_metadata(metadata)
        
        # Build partition and row keys from identity zone
        start_time = identity.get("start_time_utc", metadata.get("start_time_utc", ""))
        if start_time:
            # Extract YYYY-MM for partition (Azure Tables forbid '/', '\\', '#', '?')
            partition_key = f"{athlete_id}|{start_time[:7]}"
            # Format: YYYYMMDDTHHMMSSZ|workout_id
            row_key_time = start_time.replace("-", "").replace(":", "").replace("+", "")
            row_key = f"{row_key_time}|{workout_id[:12]}"
        else:
            # Fallback if no start time
            partition_key = f"{athlete_id}|unknown"
            row_key = workout_id[:20]

        # Extract queryable fields from semantic zones
        entity = WorkoutEntity(
            partition_key=partition_key,
            row_key=row_key,
            workout_id=workout_id,
            ingestion_id=ingestion_id,
            athlete_id=athlete_id,
            canonical_schema_version=canonical_schema_version,
            canonical_records_blob=canonical_records_blob,
            records_count=records_count,
            laps_count=laps_count,
            # Identity zone fields (queryable)
            start_time_utc=identity.get("start_time_utc"),
            sport=identity.get("sport"),
            sub_sport=identity.get("sub_sport"),
            duration_sec=identity.get("duration_sec"),
            distance_m=identity.get("distance_m"),
            device_manufacturer=identity.get("device_manufacturer"),
            device_model=identity.get("device_model"),
            # Capabilities zone fields (queryable)
            has_power=capabilities.get("has_power", False),
            has_hr=capabilities.get("has_hr", False),
            has_gps=capabilities.get("has_gps", False),
            # Metrics dict for flexible enrichment (flattened for semantic layer compatibility)
            metrics=flat_metadata,  # Flattened zones for backward compatibility with semantic layer
        ).to_entity()

        # Store in table
        try:
            table_client = self.infra.get_table_client("Workouts")
            table_client.upsert_entity(entity)
            logger.info("Stored workout %s for %s", workout_id, athlete_id)
            return workout_id
        except HttpResponseError as e:
            logger.error("Error storing workout %s: %s", workout_id, e)
            raise StorageError("Failed to store workout") from e

    @staticmethod
    def _flatten_structured_metadata(metadata: Dict) -> Dict:
        """Flatten semantic zones back to flat dict for backward compatibility.
        
        Args:
            metadata: Metadata with semantic zones (identity, capabilities, session, etc.) OR flat dict
            
        Returns:
            Flattened dict with all fields at top level
        """
        # If already flat (no zones), return as-is
        if "identity" not in metadata:
            return metadata
        
        flat = {}
        for zone_name, zone_data in metadata.items():
            if isinstance(zone_data, dict):
                flat.update(zone_data)
        return flat

    def record_ingestion_state(
        self,
        athlete_id: str,
        file_info: Dict,
        status: str,
        error: Optional[str] = None,
        workout_id: Optional[str] = None,
        ingestion_id: Optional[str] = None,
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict] = None,
    ) -> None:
        """Record ingestion state for idempotency tracking."""
        context = IngestionContext(
            athlete_id=athlete_id,
            file_info=file_info,
            workout_id=workout_id,
            storage=self,
            ingestion_id=ingestion_id,
            ingestion_key=ingestion_key,
            existing_state=existing_state,
        )

        entity = context.build_state_entity(status=status, error=error).to_entity()

        try:
            table_client = self.infra.get_table_client("IngestionState")
            table_client.upsert_entity(entity)
            logger.info("Recorded ingestion state for %s: %s", athlete_id, status)
        except HttpResponseError as e:
            logger.error("Error recording ingestion state for %s: %s", athlete_id, e)
            raise StorageError("Failed to record ingestion state") from e

    def get_ingestion_state(
        self,
        athlete_id: str,
        ingestion_key: str,
    ) -> Optional[Dict]:
        """Retrieve ingestion state for a file by athlete and ingestion key."""
        try:
            table_client = self.infra.get_table_client("IngestionState")
            entity = table_client.get_entity(partition_key=athlete_id, row_key=ingestion_key)
            return entity
        except ResourceNotFoundError:
            # Entity doesn't exist yet - not an error
            return None
        except HttpResponseError as e:
            logger.warning("Error checking ingestion state for %s: %s", ingestion_key, e)
            return None

    def get_ingestion_context(
        self,
        athlete_id: str,
        file_info: Dict,
        workout_id: Optional[str] = None,
        ingestion_id: Optional[str] = None,
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict] = None,
    ) -> IngestionContext:
        """Create an IngestionContext instance for idempotency checks."""
        return IngestionContext(
            athlete_id=athlete_id,
            file_info=file_info,
            workout_id=workout_id,
            storage=self,
            ingestion_id=ingestion_id,
            ingestion_key=ingestion_key,
            existing_state=existing_state,
        )

    def store_canonical_records(
        self,
        workout_id: str,
        records: CanonicalRecordSet,
    ) -> Optional[str]:
        """Store canonical workout records to blob as parquet."""
        return self.infra.upload_parquet_blob(workout_id, records)

    def load_canonical_records(self, blob_name: str) -> pd.DataFrame:
        """Load canonical workout records from blob (parquet)."""
        return self.infra.load_parquet_blob(blob_name)

    def store_raw_fit_json(
        self,
        workout_id: str,
        raw_fit_json: Dict,
    ) -> str:
        """Store raw FIT JSON (gzip compressed) to blob."""
        blob_name = self.infra.raw_fit_blob_name(workout_id)
        return self.infra.upload_json_gzip(blob_name, raw_fit_json)

    def store_fit_analysis(
        self,
        workout_id: str,
        fit_analysis: Dict,
    ) -> str:
        """Store FIT analysis JSON to blob."""
        blob_name = self.infra.fit_analysis_blob_name(workout_id)
        return self.infra.upload_json_blob(blob_name, fit_analysis)

    def store_metadata_json(
        self,
        workout_id: str,
        metadata: Dict,
    ) -> str:
        """Store FIT metadata messages JSON to blob."""
        blob_name = self.infra.metadata_blob_name(workout_id)
        return self.infra.upload_json_blob(blob_name, metadata)

    def load_metadata_json(self, workout_id: str) -> Dict:
        """Load FIT metadata messages from blob."""
        blob_name = self.infra.metadata_blob_name(workout_id)
        return self.infra.load_json_blob(blob_name)

    def store_canonical_metadata_blob(
        self,
        workout_id: str,
        canonical_metadata: Dict,
    ) -> str:
        """Store canonical metadata (all 8 semantic zones) to blob.
        
        This is the source of truth for all workout metadata including identity,
        capabilities, session aggregates, enrichment fields, and LLM analysis placeholders.
        """
        # Use same blob path as metadata.json for now (overwrite is acceptable)
        blob_name = self.infra.metadata_blob_name(workout_id)
        return self.infra.upload_json_blob(blob_name, canonical_metadata)

    def store_laps_json(
        self,
        workout_id: str,
        laps: Dict,
    ) -> str:
        """Store lap records JSON to blob."""
        blob_name = self.infra.laps_blob_name(workout_id)
        return self.infra.upload_json_blob(blob_name, laps)

    def load_laps_json(self, workout_id: str) -> Dict:
        """Load lap records from blob."""
        blob_name = self.infra.laps_blob_name(workout_id)
        return self.infra.load_json_blob(blob_name)

    def upsert_metrics(
        self,
        athlete_id: str,
        metrics: WorkoutMetricsModel,
    ) -> str:
        """Store parsed workout metrics, returning the workout_id."""
        # If parser returns a raw dict, store directly
        if isinstance(metrics, dict):
            flat_metrics = metrics
        else:
            # Extract flat metrics dict from nested model structure
            flat_metrics = self._flatten_workout_metrics(metrics)

        # Source info defaults
        source_info = {"source_system": "HealthFit"}

        payload = json.dumps(flat_metrics, separators=(",", ":"), default=str, sort_keys=True)
        ingestion_id = hashlib.sha256(payload.encode()).hexdigest()

        # Call store_workout with the flat metrics dict
        return self.store_workout(
            athlete_id,
            flat_metrics,
            source_info,
            ingestion_id=ingestion_id,
        )

    def _flatten_workout_metrics(self, metrics_model: WorkoutMetricsModel) -> Dict:
        """Flatten nested WorkoutMetricsModel into flat dictionary for storage."""
        metrics = {}

        # Session metrics
        if metrics_model.session:
            metrics.update({
                "sport": metrics_model.session.sport,
                "sub_sport": metrics_model.session.sub_sport,
                "apple_workout_type": metrics_model.session.apple_workout_type,
                "workout_name": metrics_model.session.workout_name,
                "device_name": metrics_model.session.device_name,
                "is_indoor": metrics_model.session.is_indoor,
                "start_time_utc": metrics_model.session.start_time_utc,
                "timezone": metrics_model.session.timezone,
                "duration_sec": metrics_model.session.duration_sec,
                "moving_time_sec": metrics_model.session.moving_time_sec,
            })

        # Distance and elevation metrics
        if metrics_model.distance:
            metrics.update({
                "has_gps": metrics_model.distance.has_gps,
                "distance_m": metrics_model.distance.distance_m,
                "elevation_gain_m": metrics_model.distance.elevation_gain_m,
                "elevation_loss_m": metrics_model.distance.elevation_loss_m,
                "avg_speed_mps": metrics_model.distance.avg_speed_mps,
                "max_speed_mps": metrics_model.distance.max_speed_mps,
                "calories_kcal": metrics_model.distance.calories_kcal,
            })

        # Sample metrics
        if metrics_model.samples:
            metrics.update({
                "hr_avg_bpm": metrics_model.samples.hr_avg_bpm,
                "hr_max_bpm": metrics_model.samples.hr_max_bpm,
                "hr_min_bpm": metrics_model.samples.hr_min_bpm,
                "hr_samples_count": metrics_model.samples.hr_samples_count,
                "hr_missing_pct": metrics_model.samples.hr_missing_pct,
                "pwr_avg_watts": metrics_model.samples.pwr_avg_watts,
                "pwr_max_watts": metrics_model.samples.pwr_max_watts,
                "pwr_normalized_watts": metrics_model.samples.pwr_normalized_watts,
                "pwr_variability_index": metrics_model.samples.pwr_variability_index,
                "pwr_samples_count": metrics_model.samples.pwr_samples_count,
                "pwr_missing_pct": metrics_model.samples.pwr_missing_pct,
                "cad_avg_rpm": metrics_model.samples.cad_avg_rpm,
                "cad_max_rpm": metrics_model.samples.cad_max_rpm,
                "cad_samples_count": metrics_model.samples.cad_samples_count,
            })

        # HR zones
        if metrics_model.zones_hr:
            metrics.update({
                "hr_z1_sec": metrics_model.zones_hr.hr_z1_sec,
                "hr_z2_sec": metrics_model.zones_hr.hr_z2_sec,
                "hr_z3_sec": metrics_model.zones_hr.hr_z3_sec,
                "hr_z4_sec": metrics_model.zones_hr.hr_z4_sec,
                "hr_z5_sec": metrics_model.zones_hr.hr_z5_sec,
                "hr_z1_low_bpm": metrics_model.zones_hr.hr_z1_low_bpm,
                "hr_z1_high_bpm": metrics_model.zones_hr.hr_z1_high_bpm,
                "hr_z2_low_bpm": metrics_model.zones_hr.hr_z2_low_bpm,
                "hr_z2_high_bpm": metrics_model.zones_hr.hr_z2_high_bpm,
                "hr_z3_low_bpm": metrics_model.zones_hr.hr_z3_low_bpm,
                "hr_z3_high_bpm": metrics_model.zones_hr.hr_z3_high_bpm,
                "hr_z4_low_bpm": metrics_model.zones_hr.hr_z4_low_bpm,
                "hr_z4_high_bpm": metrics_model.zones_hr.hr_z4_high_bpm,
                "hr_z5_low_bpm": metrics_model.zones_hr.hr_z5_low_bpm,
                "hr_z5_high_bpm": metrics_model.zones_hr.hr_z5_high_bpm,
                "hr_zone_model": metrics_model.zones_hr.hr_zone_model,
                "hr_zone_basis": metrics_model.zones_hr.hr_zone_basis,
                "hr_zone_reference_bpm": metrics_model.zones_hr.hr_zone_reference_bpm,
                "hr_zone_total_sec": metrics_model.zones_hr.hr_zone_total_sec,
            })

        # Power zones
        if metrics_model.zones_power:
            metrics.update({
                "pwr_z1_sec": metrics_model.zones_power.pwr_z1_sec,
                "pwr_z2_sec": metrics_model.zones_power.pwr_z2_sec,
                "pwr_z3_sec": metrics_model.zones_power.pwr_z3_sec,
                "pwr_z4_sec": metrics_model.zones_power.pwr_z4_sec,
                "pwr_z5_sec": metrics_model.zones_power.pwr_z5_sec,
                "pwr_z6_sec": metrics_model.zones_power.pwr_z6_sec,
                "pwr_z7_sec": metrics_model.zones_power.pwr_z7_sec,
                "pwr_z1_low_w": metrics_model.zones_power.pwr_z1_low_w,
                "pwr_z1_high_w": metrics_model.zones_power.pwr_z1_high_w,
                "pwr_z2_low_w": metrics_model.zones_power.pwr_z2_low_w,
                "pwr_z2_high_w": metrics_model.zones_power.pwr_z2_high_w,
                "pwr_z3_low_w": metrics_model.zones_power.pwr_z3_low_w,
                "pwr_z3_high_w": metrics_model.zones_power.pwr_z3_high_w,
                "pwr_z4_low_w": metrics_model.zones_power.pwr_z4_low_w,
                "pwr_z4_high_w": metrics_model.zones_power.pwr_z4_high_w,
                "pwr_z5_low_w": metrics_model.zones_power.pwr_z5_low_w,
                "pwr_z5_high_w": metrics_model.zones_power.pwr_z5_high_w,
                "pwr_z6_low_w": metrics_model.zones_power.pwr_z6_low_w,
                "pwr_z6_high_w": metrics_model.zones_power.pwr_z6_high_w,
                "pwr_z7_low_w": metrics_model.zones_power.pwr_z7_low_w,
                "pwr_z7_high_w": metrics_model.zones_power.pwr_z7_high_w,
                "pwr_zone_total_sec": metrics_model.zones_power.pwr_zone_total_sec,
                "low_aerobic_sec": metrics_model.zones_power.low_aerobic_sec,
                "intensity_sec": metrics_model.zones_power.intensity_sec,
                "ftp_watts": metrics_model.zones_power.ftp_watts,
                "pwr_zone_model": metrics_model.zones_power.pwr_zone_model,
            })

        if metrics_model.training_load:
            metrics.update({
                "intensity_factor": metrics_model.training_load.intensity_factor,
                "tss": metrics_model.training_load.tss,
            })

        if metrics_model.power_duration:
            metrics.update({
                "peak_5s_watts": metrics_model.power_duration.peak_5s_watts,
                "peak_30s_watts": metrics_model.power_duration.peak_30s_watts,
                "peak_3min_watts": metrics_model.power_duration.peak_3min_watts,
                "peak_5min_watts": metrics_model.power_duration.peak_5min_watts,
                "peak_8min_watts": metrics_model.power_duration.peak_8min_watts,
                "peak_20min_watts": metrics_model.power_duration.peak_20min_watts,
                "peak_60min_watts": metrics_model.power_duration.peak_60min_watts,
            })

        if metrics_model.envelope:
            metrics.update({
                "sprint_envelope_score": metrics_model.envelope.sprint_envelope_score,
                "vo2_envelope_score": metrics_model.envelope.vo2_envelope_score,
                "threshold_envelope_score": metrics_model.envelope.threshold_envelope_score,
            })

        if metrics_model.variability:
            metrics.update({
                "cv_power": metrics_model.variability.cv_power,
                "cv_hr": metrics_model.variability.cv_hr,
                "surge_count": metrics_model.variability.surge_count,
                "surge_density_per_hr": metrics_model.variability.surge_density_per_hr,
                "pacing_evenness_score": metrics_model.variability.pacing_evenness_score,
            })

        if metrics_model.durability:
            metrics.update({
                "efficiency_factor_avg": metrics_model.durability.efficiency_factor_avg,
                "decoupling_pct": metrics_model.durability.decoupling_pct,
                "durability_slope": metrics_model.durability.durability_slope,
                "fatigue_rate_power": metrics_model.durability.fatigue_rate_power,
                "hr_power_lag_sec": metrics_model.durability.hr_power_lag_sec,
                "ef_first_half": metrics_model.durability.ef_first_half,
                "ef_second_half": metrics_model.durability.ef_second_half,
                "ef_overall": metrics_model.durability.ef_overall,
                "hr_drift_bpm": metrics_model.durability.hr_drift_bpm,
            })

        # Physiometrics
        metrics.update({
            "hr_resting_bpm": metrics_model.hr_resting_bpm,
            "physiometrics_snapshot_timestamp": metrics_model.physiometrics_snapshot_timestamp,
        })

        return metrics


