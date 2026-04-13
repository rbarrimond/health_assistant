"""Consolidation handlers for wellness domain.

PhysiometricsConsolidationHandler: Merges multi-source daily snapshots per source precedence.
TrainingStateConsolidationHandler: Computes derived training state from workouts + physiometrics.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from TrainingAnalyticsPlatform.analytics.physiometrics_resolution import (
    BASELINE_SOURCE_PRECEDENCE,
    build_source_rows_by_source,
    resolve_latest_metric_across_sources,
)
from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer
from TrainingAnalyticsPlatform.models.wellness import (
    PhysiometricsSnapshot,
    TrainingStateSnapshot,
)
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator
from TrainingAnalyticsPlatform.storage.protocols import StorageInfrastructureProtocol

logger = logging.getLogger(__name__)


class SourcePrecedenceResolver:
    """Determines metric ownership by source precedence rules.
    
    Schema v4.2.0 field ownership (updated with training status + load focus):
    - Withings: exclusive for all body composition
    - Intervals: exclusive for resting_hr_bpm, steps, nutrition (Garmin values ignored)
    - Garmin: exclusive for training state and most performance metrics
    - FTP/LTHR: recency-aware across Garmin/manual/chatgpt with Garmin tie-break priority
    - Garmin: exclusive for training status labels and load focus percentages
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
        
        # Performance baselines (Garmin tie-break priority, recency-aware resolution)
        "ftp_watts": ["garmin", "chatgpt", "manual"],
        "cycling_vo2max_ml_kg_min": ["garmin"],
        "running_vo2max_ml_kg_min": ["garmin"],
        "hr_lthr_bpm": ["garmin", "chatgpt", "manual"],
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
        
        # Training status and load focus (Garmin exclusive, new in v4.2.0)
        "training_status_label": ["garmin"],
        "load_focus_low_aerobic_pct": ["garmin"],
        "load_focus_high_aerobic_pct": ["garmin"],
        "load_focus_anaerobic_pct": ["garmin"],
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

    CONSOLIDATED_VERSION = "4.2.0"
    METADATA_FIELDS = {"athlete_id", "effective_date", "data_sources", "canonical_version", "last_updated_utc"}
    STORAGE_FIELD_ALIASES = {
        # Legacy nested storage format aliases
        "ftp_watts": ["ftp_watts", "power_ftp_watts"],
        "hr_lthr_bpm": ["hr_lthr_bpm", "heart_rate_lthr_bpm", "lactate_threshold_hr_bpm"],
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
            hrv_sdnn_ms=None,
            sleep_duration_sec=None,
            resting_hr_bpm=None,
            # Activity (Intervals)
            steps=None,
            # Nutrition (Intervals)
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            # Extended body/recovery metrics
            spo2_pct=None,
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
            # Training status and load focus (Garmin)
            training_status_label=None,
            load_focus_low_aerobic_pct=None,
            load_focus_high_aerobic_pct=None,
            load_focus_anaerobic_pct=None,
            # Metadata
            data_sources="",
            canonical_version="4.2.0",
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

        if metric_name in BASELINE_SOURCE_PRECEDENCE:
            source_rows_by_source = build_source_rows_by_source(
                source_entities,
                tracked_sources=set(preferred_sources),
            )
            value, _, source = resolve_latest_metric_across_sources(
                metric_name,
                source_rows_by_source,
                field_aliases=self.STORAGE_FIELD_ALIASES,
                source_precedence=BASELINE_SOURCE_PRECEDENCE,
            )
            if value is not None and source is not None:
                setattr(consolidated, metric_name, value)
                used_sources.add(source)
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

    Delegates computation to the semantic layer so training-state projection
    uses the canonical workout analytics pipeline.
    """

    CONSOLIDATED_VERSION = "2.0.0"

    def __init__(
        self,
        storage_client: StorageInfrastructureProtocol,
        semantic_layer: Optional[SemanticLayer] = None,
    ):
        """Initialize training state consolidation handler.

        Args:
            storage_client: Azure Table Storage client
        """
        self.storage_client = storage_client
        self.semantic_layer = semantic_layer or self._build_semantic_layer(storage_client)

    @staticmethod
    def _build_semantic_layer(storage_client: StorageInfrastructureProtocol) -> SemanticLayer:
        """Create a semantic layer using shared storage when available."""
        if all(
            hasattr(storage_client, attribute)
            for attribute in ("infrastructure", "workouts", "physiometrics")
        ):
            return SemanticLayer(storage_client)
        return SemanticLayer(StorageCoordinator())

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
        date_obj = datetime.strptime(effective_date, "%Y-%m-%d").date()
        snapshot = self.semantic_layer._compute_training_state_for_date(
            athlete_id,
            date_obj,
        )

        logger.info(
            "Computed training state for athlete %s on %s; "
            "CTS_7d=%.1f, CTS_28d=%.1f, fatigue_idx=%.2f",
            athlete_id,
            effective_date,
            snapshot.cts_rolling_7d or 0,
            snapshot.cts_rolling_28d or 0,
            snapshot.fatigue_index or 0,
        )

        return snapshot

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
