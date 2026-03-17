"""Consolidation handlers for wellness domain.

PhysiometricsConsolidationHandler: Merges multi-source daily snapshots per source precedence.
TrainingStateConsolidationHandler: Computes derived training state from workouts + physiometrics.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from TrainingAnalyticsPlatform.models.wellness import (
    PhysiometricsSnapshot,
    TrainingStateSnapshot,
)
from TrainingAnalyticsPlatform.storage.protocols import StorageInfrastructureProtocol

logger = logging.getLogger(__name__)


class SourcePrecedenceResolver:
    """Determines metric ownership by source precedence rules.
    
    Schema v4.1.0 field ownership:
    - Withings: exclusive for all body composition
    - Intervals: exclusive for resting_hr_bpm, steps, nutrition (Garmin values ignored)
    - Garmin: exclusive for training state and performance metrics
    """

    METRIC_SOURCES = {
        # Body composition (Withings primary; Intervals fallback)
        "weight_kg": ["withings", "intervals"],
        "fat_mass_kg": ["withings"],
        "muscle_mass_kg": ["withings"],
        "bone_mass_kg": ["withings"],
        "body_fat_pct": ["withings", "intervals"],
        
        # Recovery metrics (Intervals exclusive)
        "hrv_ln_rmssd": ["intervals"],
        "hrv_sdnn_ms": ["intervals", "garmin"],
        "sleep_duration_sec": ["intervals"],
        "resting_hr_bpm": ["intervals"],  # Intervals exclusive; Garmin ignored
        "spo2_pct": ["intervals", "garmin"],
        
        # Activity (Intervals exclusive)
        "steps": ["intervals"],  # Intervals exclusive; Garmin ignored
        
        # Nutrition (Intervals exclusive)
        "calories_kcal": ["intervals"],
        "carbs_g": ["intervals"],
        "protein_g": ["intervals"],
        "fat_g": ["intervals"],
        
        # Performance baselines (Garmin exclusive)
        "ftp_watts": ["garmin"],
        "cycling_vo2max_ml_kg_min": ["garmin"],
        "running_vo2max_ml_kg_min": ["garmin"],
        "hr_lthr_bpm": ["garmin"],
        "hr_max_bpm": ["garmin"],
        
        # Training state (Garmin exclusive)
        "training_load": ["garmin"],
        "recovery_time_minutes": ["garmin"],
        "readiness_score": ["garmin"],
        
        # Extended training metrics (Garmin exclusive)
        "training_effect_aerobic": ["garmin"],
        "training_effect_anaerobic": ["garmin"],
        "training_stress_score": ["garmin"],
        "training_stress_balance": ["garmin"],
        "atp_probability": ["garmin"],
    }

    @staticmethod
    def get_preferred_source(metric_name: str) -> Optional[str]:
        """Return primary source for a metric, or None if no preference."""
        sources = SourcePrecedenceResolver.METRIC_SOURCES.get(metric_name)
        return sources[0] if sources else None


class PhysiometricsConsolidationHandler:
    """Consolidates multi-source daily physiometrics snapshots.

    Reads all source-keyed snapshots for an athlete on a given date,
    applies source precedence rules, and optionally writes consolidated view.
    """

    CONSOLIDATED_VERSION = "4.1.0"
    METADATA_FIELDS = {"athlete_id", "effective_date", "data_sources", "canonical_version", "last_updated_utc"}
    STORAGE_FIELD_ALIASES = {
        # Legacy nested storage format aliases
        "ftp_watts": ["ftp_watts", "power_ftp_watts"],
        "hr_lthr_bpm": ["hr_lthr_bpm", "heart_rate_lthr_bpm"],
        "hr_max_bpm": ["hr_max_bpm", "heart_rate_hr_max_bpm"],
        "resting_hr_bpm": ["resting_hr_bpm", "heart_rate_resting_bpm"],
        # Prefixed nutrition fields from older schemas
        "calories_kcal": ["calories_kcal", "nutrition_calories_kcal"],
        "carbs_g": ["carbs_g", "nutrition_carbs_g"],
        "protein_g": ["protein_g", "nutrition_protein_g"],
        "fat_g": ["fat_g", "nutrition_fat_g"],
        # Activity fields
        "steps": ["steps", "activity_steps"],
    }

    def __init__(self, storage_client: StorageInfrastructureProtocol):
        """Initialize consolidation handler.

        Args:
            storage_client: Azure Table Storage client
        """
        self.storage_client = storage_client

    def consolidate_day(
        self,
        athlete_id: str,
        effective_date: str,  # YYYY-MM-DD
        apply_precedence: bool = True,
    ) -> PhysiometricsSnapshot:
        """Consolidate all sources for a given athlete and date.

        Args:
            athlete_id: Athlete identifier
            effective_date: Date in YYYY-MM-DD
            apply_precedence: Whether to apply source precedence rules

        Returns:
            Consolidated PhysiometricsSnapshot
        """
        source_entities = self._fetch_source_entities(athlete_id, effective_date)

        if not source_entities:
            return self._create_empty_snapshot(athlete_id, effective_date)

        consolidated = self._create_empty_snapshot(athlete_id, effective_date)
        used_sources: Set[str] = set()

        if apply_precedence:
            self._apply_precedence_rules(consolidated, source_entities, used_sources)
        else:
            self._apply_latest_timestamp(consolidated, source_entities, used_sources)

        self._finalize_snapshot(consolidated, used_sources, athlete_id, effective_date)

        return consolidated

    def _fetch_source_entities(self, athlete_id: str, effective_date: str) -> List[Dict]:
        """Fetch all source entities for athlete and date.

        Args:
            athlete_id: Athlete identifier
            effective_date: Date in YYYY-MM-DD

        Returns:
            List of entity dictionaries
        """
        table_client = self.storage_client.get_table_client("Physiometrics")
        filter_str = f"PartitionKey eq '{athlete_id}' and effective_date eq '{effective_date}'"
        return list(table_client.query_entities(filter_str))

    def _create_empty_snapshot(
        self, athlete_id: str, effective_date: str
    ) -> PhysiometricsSnapshot:
        """Create an empty physiometrics snapshot.

        Args:
            athlete_id: Athlete identifier
            effective_date: Date in YYYY-MM-DD

        Returns:
            Empty PhysiometricsSnapshot with all optional fields as None
        """
        return PhysiometricsSnapshot(
            athlete_id=athlete_id,
            effective_date=effective_date,
            # Body composition (Withings)
            weight_kg=None,
            fat_mass_kg=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            body_fat_pct=None,
            # Recovery metrics (Intervals)
            hrv_ln_rmssd=None,
            sleep_duration_sec=None,
            resting_hr_bpm=None,
            # Activity (Intervals)
            steps=None,
            # Nutrition (Intervals)
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            # Performance baselines (Garmin)
            ftp_watts=None,
            cycling_vo2max_ml_kg_min=None,
            running_vo2max_ml_kg_min=None,
            hr_lthr_bpm=None,
            hr_max_bpm=None,
            # Training state (Garmin)
            training_load=None,
            recovery_time_minutes=None,
            readiness_score=None,
            # Extended training metrics (Garmin)
            training_effect_aerobic=None,
            training_effect_anaerobic=None,
            training_stress_score=None,
            training_stress_balance=None,
            atp_probability=None,
            # Metadata
            data_sources="",
            canonical_version="4.1.0",
        )

    def _apply_precedence_rules(
        self,
        consolidated: PhysiometricsSnapshot,
        source_entities: List[Dict],
        used_sources: Set[str],
    ) -> None:
        """Apply source precedence rules for each metric.

        Args:
            consolidated: Snapshot to populate
            source_entities: Source data entities
            used_sources: Set to track which sources contributed data
        """
        for metric_name in PhysiometricsSnapshot.model_fields.keys():
            if metric_name in self.METADATA_FIELDS:
                continue

            self._apply_metric_precedence(
                consolidated, metric_name, source_entities, used_sources
            )

    def _apply_metric_precedence(
        self,
        consolidated: PhysiometricsSnapshot,
        metric_name: str,
        source_entities: List[Dict],
        used_sources: Set[str],
    ) -> None:
        """Apply precedence rule for a single metric.

        Args:
            consolidated: Snapshot to populate
            metric_name: Name of metric field
            source_entities: Source data entities
            used_sources: Set to track which sources contributed data
        """
        preferred_sources = SourcePrecedenceResolver.METRIC_SOURCES.get(metric_name, [])
        if not preferred_sources:
            return

        for source in preferred_sources:
            value = self._find_metric_value(metric_name, source, source_entities)
            if value is not None:
                setattr(consolidated, metric_name, value)
                used_sources.add(source)
                break

    def _find_metric_value(
        self, metric_name: str, source: str, source_entities: List[Dict]
    ) -> Optional[Any]:
        """Find metric value from a specific source in entities.

        Args:
            metric_name: Name of metric field
            source: Source identifier (e.g., 'withings', 'garmin')
            source_entities: Source data entities

        Returns:
            Metric value or None if not found
        """
        for entity in source_entities:
            if self._entity_has_source(entity, source):
                value = self._get_entity_metric_value(entity, metric_name)
                if value is not None:
                    return value
        return None

    @classmethod
    def _entity_sources(cls, entity: Dict) -> Set[str]:
        """Return normalized source identifiers for an entity."""
        sources: Set[str] = set()
        data_source = entity.get("data_source")
        if isinstance(data_source, str) and data_source.strip():
            sources.add(data_source.strip().lower())

        data_sources = entity.get("data_sources")
        if isinstance(data_sources, str) and data_sources.strip():
            for value in data_sources.split(","):
                normalized = value.strip().lower()
                if normalized:
                    sources.add(normalized)

        return sources

    @classmethod
    def _entity_has_source(cls, entity: Dict, source: str) -> bool:
        """Check whether entity originated from a specific source."""
        return source.lower() in cls._entity_sources(entity)

    @classmethod
    def _get_entity_metric_value(cls, entity: Dict, metric_name: str) -> Optional[Any]:
        """Resolve a canonical metric from canonical/storage alias columns."""
        candidate_fields = cls.STORAGE_FIELD_ALIASES.get(metric_name, [metric_name])
        for field_name in candidate_fields:
            value = entity.get(field_name)
            if value is not None:
                return value
        return None

    def _apply_latest_timestamp(
        self,
        consolidated: PhysiometricsSnapshot,
        source_entities: List[Dict],
        used_sources: Set[str],
    ) -> None:
        """Apply latest timestamp strategy (no precedence).

        Args:
            consolidated: Snapshot to populate
            source_entities: Source data entities
            used_sources: Set to track which sources contributed data
        """
        for entity in source_entities:
            self._merge_entity_metrics(consolidated, entity)
            used_sources.update(self._entity_sources(entity))

    def _merge_entity_metrics(
        self, consolidated: PhysiometricsSnapshot, entity: Dict
    ) -> None:
        """Merge metrics from entity into consolidated snapshot.

        Args:
            consolidated: Snapshot to populate
            entity: Source entity dictionary
        """
        for metric_name in PhysiometricsSnapshot.__fields__.keys():
            if metric_name in self.METADATA_FIELDS:
                continue

            if getattr(consolidated, metric_name, None) is None:
                value = self._get_entity_metric_value(entity, metric_name)
                if value is not None:
                    setattr(consolidated, metric_name, value)

    def _finalize_snapshot(
        self,
        consolidated: PhysiometricsSnapshot,
        used_sources: Set[str],
        athlete_id: str,
        effective_date: str,
    ) -> None:
        """Set final metadata on consolidated snapshot.

        Args:
            consolidated: Snapshot to finalize
            used_sources: Set of sources that contributed data
            athlete_id: Athlete identifier
            effective_date: Date in YYYY-MM-DD
        """
        consolidated.data_sources = ",".join(sorted(src for src in used_sources if src))
        consolidated.canonical_version = self.CONSOLIDATED_VERSION
        consolidated.last_updated_utc = datetime.now(timezone.utc)

        logger.info(
            "Consolidated physiometrics for athlete %s on %s; sources: %s",
            athlete_id,
            effective_date,
            consolidated.data_sources,
        )

    def write_consolidated(
        self, consolidated: PhysiometricsSnapshot
    ) -> None:
        """Write consolidated snapshot to Physiometrics table.

        Args:
            consolidated: Consolidated snapshot
        """
        table_client = self.storage_client.get_table_client("Physiometrics")

        entity = {
            "PartitionKey": consolidated.athlete_id,
            "RowKey": consolidated.effective_date,
            **consolidated.dict(),
        }
        table_client.upsert_entity(entity)


class TrainingStateConsolidationHandler:
    """Computes daily training state from workouts and physiometrics.

    Computes rolling training stress (CTS, ATS) from Workouts table,
    integrates HRV and readiness from Physiometrics, and writes to
    TrainingState table.
    """

    CONSOLIDATED_VERSION = "2.0.0"
    TSS_SCALING_FACTOR = 10.0  # Standard TSS scaling

    def __init__(self, storage_client: StorageInfrastructureProtocol):
        """Initialize training state consolidation handler.

        Args:
            storage_client: Azure Table Storage client
        """
        self.storage_client = storage_client

    def compute_day(
        self, athlete_id: str, effective_date: str  # YYYY-MM-DD
    ) -> TrainingStateSnapshot:
        """Compute training state for a given athlete and date.

        Args:
            athlete_id: Athlete identifier
            effective_date: Date in YYYY-MM-DD

        Returns:
            Computed TrainingStateSnapshot
        """
        # Parse effective_date
        date_obj = datetime.strptime(effective_date, "%Y-%m-%d").date()

        workouts_table = self.storage_client.get_table_client("Workouts")
        phys_table = self.storage_client.get_table_client("Physiometrics")

        # Compute rolling TSS
        tss_7d, tss_28d = self._compute_rolling_tss(
            athlete_id, date_obj, workouts_table
        )

        # Compute CTS and ATS (Training Stress Balance model)
        cts_7d = tss_7d / 7.0  # Acute (7-day average)
        cts_28d = tss_28d / 28.0  # Chronic (28-day average)

        ats = cts_7d  # ATS = CTS over 7 days
        cts = cts_28d  # CTS = long-term load

        # Fatigue index = ATS / CTS; higher = more fatigued
        fatigue_index = None
        if cts and cts > 0:
            fatigue_index = ats / cts

        # Fetch latest Physiometrics for HRV and readiness
        physio_filter = f"PartitionKey eq '{athlete_id}'"
        physio_entities = list(phys_table.query_entities(physio_filter))
        physio_entities.sort(
            key=lambda e: e.get("effective_date", ""), reverse=True
        )
        latest_physio = physio_entities[0] if physio_entities else {}

        # Compute composite readiness (if not provided by Garmin)
        hrv_ln = latest_physio.get("hrv_ln_rmssd")
        garmin_readiness = latest_physio.get("readiness_score")
        composite_readiness = self._compute_composite_readiness(
            hrv_ln, fatigue_index, garmin_readiness
        )

        snapshot = TrainingStateSnapshot(
            athlete_id=athlete_id,
            effective_date=effective_date,
            cts_rolling_7d=cts_7d,
            cts_rolling_28d=cts_28d,
            ats_rolling=ats,
            fatigue_index=fatigue_index,
            readiness_score=composite_readiness or garmin_readiness,
            garmin_readiness_score=garmin_readiness,
            mood=None,
            soreness=None,
            pred_recovery_days=None,
            data_sources="workouts,physiometrics",
            canonical_version=self.CONSOLIDATED_VERSION,
        )

        logger.info(
            "Computed training state for athlete %s on %s; "
            "CTS_7d=%.1f, CTS_28d=%.1f, fatigue_idx=%.2f",
            athlete_id,
            effective_date,
            cts_7d or 0,
            cts_28d or 0,
            fatigue_index or 0,
        )

        return snapshot

    def _compute_rolling_tss(
        self,
        athlete_id: str,
        end_date: Any,  # datetime.date
        workouts_table: Any,
    ) -> tuple:
        """Compute rolling TSS for last 7 and 28 days.

        Args:
            athlete_id: Athlete identifier
            end_date: End date (datetime.date)
            workouts_table: Workouts table client

        Returns:
            Tuple of (tss_7d, tss_28d)
        """
        start_date_7 = end_date - timedelta(days=7)
        start_date_28 = end_date - timedelta(days=28)

        # Query workouts (simple filter; production would use PartitionKey + date range)
        # For now, iterate through entities and filter by date_start_utc
        filter_str = f"PartitionKey eq '{athlete_id}'"
        workout_entities = list(workouts_table.query_entities(filter_str))

        tss_7d = 0.0
        tss_28d = 0.0

        for entity in workout_entities:
            tss = entity.get("tss", 0)
            if not tss:
                continue

            # Parse start_time_utc
            start_str = entity.get("start_time_utc")
            if not start_str:
                continue

            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                start_date = start_dt.date()
            except (ValueError, AttributeError):
                continue

            # Accumulate TSS
            if start_date_28 <= start_date <= end_date:
                tss_28d += tss
            if start_date_7 <= start_date <= end_date:
                tss_7d += tss

        return tss_7d, tss_28d

    def _compute_composite_readiness(
        self,
        hrv_ln: Optional[float],
        fatigue_index: Optional[float],
        garmin_readiness: Optional[float],
    ) -> Optional[float]:
        """Compute composite readiness score (0-100).

        Simple model: weighted average of HRV (normalized) and
        inverse fatigue index.

        Args:
            hrv_ln: Natural log of RMSSD (typically 2.5-4.5)
            fatigue_index: ATS/CTS ratio (0-2+)
            garmin_readiness: Garmin native score (0-100)

        Returns:
            Composite readiness score (0-100), or None if insufficient data
        """
        if not any([hrv_ln, fatigue_index, garmin_readiness]):
            return None

        components = []

        if hrv_ln:
            # Normalize HRV to 0-100 (arbitrary bounds: ln 2.5 = 30, ln 4.5 = 90)
            hrv_score = max(0, min(100, (hrv_ln - 2.5) * 40))
            components.append(hrv_score)

        if fatigue_index:
            # Fatigue index: lower is better; invert to readiness
            # Index 1.0 = 50%, < 1.0 = better, > 1.0 = worse
            recovery_score = max(0, min(100, 50 + (1.0 - fatigue_index) * 50))
            components.append(recovery_score)

        if garmin_readiness:
            components.append(garmin_readiness)

        if components:
            return sum(components) / len(components)

        return None

    def write_training_state(self, snapshot: TrainingStateSnapshot) -> None:
        """Write training state snapshot to TrainingState table.

        Args:
            snapshot: Computed training state snapshot
        """
        table_client = self.storage_client.get_table_client("TrainingState")

        entity = {
            "PartitionKey": snapshot.athlete_id,
            "RowKey": snapshot.effective_date,
            **snapshot.dict(),
        }
        table_client.upsert_entity(entity)
