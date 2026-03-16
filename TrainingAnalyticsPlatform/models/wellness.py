"""Canonical wellness domain models: PhysiometricsSnapshot and TrainingStateSnapshot.

These models define the contract for daily state aggregates from external sources
(Withings, Garmin, Intervals). All analytics are computed deterministically from
these canonical snapshots.
"""

import json
import logging
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PhysiometricsSnapshot(BaseModel):
    """Daily physiometrics snapshot aggregating body state from all sources.

    PartitionKey: athlete_id
    RowKey: YYYY-MM-DD|source (effective_date + source-qualified daily identity)

    This snapshot represents the canonical view of an athlete's daily body state,
    integrating measurements from:
    - Withings: body composition (weight, fat/muscle/bone mass, body fat %)
    - Intervals: recovery metrics (HRV, sleep, resting HR), activity (steps), nutrition
    - Garmin: performance baselines (FTP, VO2Max, LTHR), training state (load, readiness)

    Field ownership and precedence:
    - Withings: exclusive for all body composition
    - Intervals: exclusive for resting_hr_bpm, steps (Garmin values ignored as inaccurate)
    - Garmin: exclusive for training state and performance metrics

    Nullable fields support sparse data (not all sources report all metrics daily).
    Multiple sources may persist distinct snapshots for the same effective_date.
    """

    athlete_id: str = Field(description="Athlete identifier (partition key)")
    effective_date: str = Field(
        description="YYYY-MM-DD in athlete's local timezone (row key)"
    )

    # Body composition (Withings exclusive)
    weight_kg: Optional[float] = Field(None, ge=0, description="Body weight in kg")
    fat_mass_kg: Optional[float] = Field(None, ge=0, description="Fat mass in kg")
    muscle_mass_kg: Optional[float] = Field(None, ge=0, description="Muscle mass in kg")
    bone_mass_kg: Optional[float] = Field(None, ge=0, description="Bone mass in kg")
    body_fat_pct: Optional[float] = Field(
        None, ge=0, le=100, description="Body fat percentage"
    )

    # Recovery metrics (Intervals exclusive)
    hrv_ln_rmssd: Optional[float] = Field(
        None, description="HRV (natural log of RMSSD) for modeling"
    )
    hrv_sdnn_ms: Optional[float] = Field(
        None, ge=0, description="HRV SDNN in milliseconds"
    )
    sleep_duration_sec: Optional[float] = Field(
        None, ge=0, description="Sleep duration in seconds"
    )
    resting_hr_bpm: Optional[float] = Field(
        None, ge=0, description="Resting heart rate (Intervals exclusive; Garmin ignored)"
    )

    # Activity (Intervals exclusive)
    steps: Optional[int] = Field(
        None, ge=0, description="Daily step count (Intervals exclusive; Garmin ignored)"
    )

    # Nutrition (Intervals exclusive)
    calories_kcal: Optional[float] = Field(None, ge=0, description="Daily calorie intake in kcal")
    carbs_g: Optional[float] = Field(None, ge=0, description="Carbohydrate intake in grams")
    protein_g: Optional[float] = Field(None, ge=0, description="Protein intake in grams")
    fat_g: Optional[float] = Field(None, ge=0, description="Fat intake in grams")

    # Extended body/recovery metrics
    spo2_pct: Optional[float] = Field(None, ge=0, le=100, description="Blood oxygen saturation percentage")

    # Performance baselines (Garmin exclusive)
    ftp_watts: Optional[float] = Field(None, ge=0, description="Functional threshold power in watts")
    cycling_vo2max_ml_kg_min: Optional[float] = Field(
        None, ge=0, description="Estimated cycling VO2Max in ml/kg/min"
    )
    hr_lthr_bpm: Optional[float] = Field(
        None, ge=0, description="Lactate threshold heart rate in beats/minute"
    )
    hr_max_bpm: Optional[float] = Field(
        None, ge=0, description="Maximum heart rate in beats/minute"
    )

    # Training state (Garmin exclusive)
    training_load: Optional[float] = Field(
        None, ge=0, description="Garmin cumulative training load"
    )
    recovery_time_minutes: Optional[int] = Field(
        None, ge=0, description="Garmin estimated recovery time in minutes"
    )
    readiness_score: Optional[float] = Field(
        None, ge=0, le=100, description="Garmin readiness score (0-100)"
    )

    # Extended training metrics (Garmin exclusive)
    training_effect_aerobic: Optional[float] = Field(
        None, ge=0, le=5, description="Garmin aerobic training effect (0-5)"
    )
    training_effect_anaerobic: Optional[float] = Field(
        None, ge=0, le=5, description="Garmin anaerobic training effect (0-5)"
    )
    training_stress_score: Optional[float] = Field(
        None, ge=0, description="Garmin training stress score"
    )
    training_stress_balance: Optional[float] = Field(
        None, description="Garmin training stress balance"
    )
    atp_probability: Optional[float] = Field(
        None, ge=0, le=100, description="Garmin ATP/energy availability percentage"
    )

    # Provenance and versioning
    data_sources: str = Field(
        default="", description="CSV of sources: withings,garmin,intervals"
    )
    canonical_version: str = Field(
        default="4.0.0", description="Schema version (4.0.0 = SDNN/SpO2 promotion, Intervals body fallback, load-field removal)"
    )
    last_updated_utc: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this snapshot was canonicalized",
    )

    def to_storage_dict(self) -> dict:
        """Convert snapshot to storage layer format.
        
        Storage layer uses nested dicts for heart_rate and power to maintain
        backward compatibility with legacy Garmin ingestion format.
        
        This method ensures all canonical fields are explicitly mapped,
        preventing silent field loss during schema evolution.
        
        Returns:
            Dict matching physiometrics_storage.py entity schema
        """
        return {
            # Body composition (Withings exclusive)
            "weight_kg": self.weight_kg,
            "fat_mass_kg": self.fat_mass_kg,
            "muscle_mass_kg": self.muscle_mass_kg,
            "bone_mass_kg": self.bone_mass_kg,
            "body_fat_pct": self.body_fat_pct,
            
            # Recovery metrics (Intervals exclusive)
            "hrv_ln_rmssd": self.hrv_ln_rmssd,
            "hrv_sdnn_ms": self.hrv_sdnn_ms,
            "sleep_duration_sec": self.sleep_duration_sec,
            "resting_hr_bpm": self.resting_hr_bpm,
            
            # Activity (Intervals exclusive)
            "steps": self.steps,
            
            # Nutrition (Intervals exclusive)
            "calories_kcal": self.calories_kcal,
            "carbs_g": self.carbs_g,
            "protein_g": self.protein_g,
            "fat_g": self.fat_g,

            # Extended body/recovery metrics
            "spo2_pct": self.spo2_pct,
            
            # Performance baselines (Garmin exclusive)
            "ftp_watts": self.ftp_watts,
            "cycling_vo2max_ml_kg_min": self.cycling_vo2max_ml_kg_min,
            "hr_lthr_bpm": self.hr_lthr_bpm,
            "hr_max_bpm": self.hr_max_bpm,
            
            # Training state (Garmin exclusive)
            "training_load": self.training_load,
            "recovery_time_minutes": self.recovery_time_minutes,
            "readiness_score": self.readiness_score,
            
            # Extended training metrics (Garmin exclusive)
            "training_effect_aerobic": self.training_effect_aerobic,
            "training_effect_anaerobic": self.training_effect_anaerobic,
            "training_stress_score": self.training_stress_score,
            "training_stress_balance": self.training_stress_balance,
            "atp_probability": self.atp_probability,
        }


class TrainingStateSnapshot(BaseModel):
    """Daily training state snapshot computed from workouts and physiometrics.

    PartitionKey: athlete_id
    RowKey: YYYY-MM-DD (effective_date)

    This snapshot represents the canonical view of an athlete's daily training
    and recovery state, computed deterministically from:
    - Workouts table (historical TSS for last 7 and 28 days)
    - Physiometrics table (HRV, readiness, Garmin training state)

    All metrics are derived and idempotent; safe to recompute any time.
    """

    athlete_id: str = Field(description="Athlete identifier (partition key)")
    effective_date: str = Field(description="YYYY-MM-DD (row key)")

    # Rolling training stress
    cts_rolling_7d: Optional[float] = Field(
        None, ge=0, description="Chronic training stress (7 days)"
    )
    cts_rolling_28d: Optional[float] = Field(
        None, ge=0, description="Chronic training stress (28 days)"
    )
    ats_rolling: Optional[float] = Field(
        None, ge=0, description="Acute training stress (7 days)"
    )
    fatigue_index: Optional[float] = Field(
        None, description="Fatigue index (ATS / CTS; higher = more fatigued)"
    )

    # Readiness and recovery
    readiness_score: Optional[float] = Field(
        None, ge=0, le=100, description="Composite readiness (HRV + load + HR)"
    )
    garmin_readiness_score: Optional[float] = Field(
        None, ge=0, le=100, description="Garmin native readiness score"
    )
    mood: Optional[int] = Field(
        None, ge=1, le=5, description="User-reported mood (1-5)"
    )
    soreness: Optional[int] = Field(
        None, ge=1, le=5, description="User-reported soreness (1-5)"
    )

    # Recovery prediction
    pred_recovery_days: Optional[int] = Field(
        None, ge=0, description="Predicted days to full recovery"
    )

    # Provenance and versioning
    data_sources: str = Field(
        default="", description="CSV of sources: workouts,physiometrics,garmin"
    )
    canonical_version: str = Field(
        default="4.0.0", description="Schema version of this snapshot"
    )
    last_updated_utc: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When snapshot was computed"
    )


class MetricProvenance(BaseModel):
    """Provenance metadata for a single metric within a snapshot.

    Tracks source identity, measurement time, and confidence for audit trails
    and conflict resolution.
    """

    source_system: str = Field(description="Source: withings, garmin, intervals, computed")
    source_record_id: Optional[str] = Field(
        None, description="Source-specific ID (e.g., Withings measureid)"
    )
    observed_at_utc: datetime = Field(
        description="When metric was actually measured (source time)"
    )
    ingested_at_utc: datetime = Field(
        description="When metric was fetched and stored in blob"
    )
    confidence: Optional[float] = Field(
        None, ge=0, le=1, description="Confidence or quality score (0-1)"
    )
