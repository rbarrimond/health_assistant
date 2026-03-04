"""Canonical wellness domain models: PhysiometricsSnapshot and TrainingStateSnapshot.

These models define the contract for daily state aggregates from external sources
(Withings, Garmin, Intervals). All analytics are computed deterministically from
these canonical snapshots.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PhysiometricsSnapshot(BaseModel):
    """Daily physiometrics snapshot aggregating body state from all sources.

    PartitionKey: athlete_id
    RowKey: YYYY-MM-DD (effective_date, local athlete timezone)

    This snapshot represents the canonical view of an athlete's daily body state,
    integrating measurements from Withings (weight, body composition), Intervals
    (HRV, RHR, sleep), and Garmin training state (FTP, VO2Max, LTHR).

    Nullable fields support sparse data (not all sources report all metrics daily).
    """

    athlete_id: str = Field(description="Athlete identifier (partition key)")
    effective_date: str = Field(
        description="YYYY-MM-DD in athlete's local timezone (row key)"
    )

    # Withings body composition metrics
    weight_kg: Optional[float] = Field(None, ge=0, description="Body weight in kg")
    fat_mass_kg: Optional[float] = Field(None, ge=0, description="Fat mass in kg")
    muscle_mass_kg: Optional[float] = Field(None, ge=0, description="Muscle mass in kg")
    bone_mass_kg: Optional[float] = Field(None, ge=0, description="Bone mass in kg")
    body_fat_pct: Optional[float] = Field(
        None, ge=0, le=100, description="Body fat percentage"
    )
    visceral_fat_index: Optional[float] = Field(
        None, ge=0, description="Withings visceral fat index"
    )
    metabolic_age_years: Optional[int] = Field(
        None, ge=0, description="Estimated metabolic age in years"
    )

    # Intervals wellness metrics
    hrv_ln_rmssd: Optional[float] = Field(
        None, description="HRV (natural log of RMSSD) for modeling"
    )
    hrv_sdnn_ms: Optional[float] = Field(
        None, ge=0, description="HRV SDNN in milliseconds (Intervals)"
    )
    resting_hr_bpm: Optional[float] = Field(
        None, ge=0, description="Resting heart rate in beats/minute"
    )
    sleep_duration_sec: Optional[float] = Field(
        None, ge=0, description="Sleep duration in seconds"
    )

    # Garmin training state snapshot
    ftp_watts: Optional[float] = Field(None, ge=0, description="Functional threshold power in watts")
    cycling_vo2max_ml_kg_min: Optional[float] = Field(
        None, ge=0, description="Estimated VO2Max in ml/kg/min"
    )
    hr_lthr_bpm: Optional[float] = Field(
        None, ge=0, description="Lactate threshold heart rate in beats/minute"
    )
    hr_max_bpm: Optional[float] = Field(
        None, ge=0, description="Maximum heart rate in beats/minute"
    )
    load: Optional[float] = Field(None, ge=0, description="Garmin training load proxy")
    readiness_score: Optional[float] = Field(
        None, ge=0, le=100, description="Garmin readiness score (0-100)"
    )

    # Subjective wellness scores (Intervals.icu self-reported metrics)
    soreness: Optional[int] = Field(None, ge=0, le=10, description="Muscle soreness (0-10)")
    fatigue: Optional[int] = Field(None, ge=0, le=10, description="Overall fatigue (0-10)")
    stress: Optional[int] = Field(None, ge=0, le=10, description="Stress level (0-10)")
    mood: Optional[int] = Field(None, ge=0, le=10, description="Mood state (0-10)")
    motivation: Optional[int] = Field(None, ge=0, le=10, description="Training motivation (0-10)")
    injury: Optional[int] = Field(None, ge=0, le=10, description="Injury severity (0-10)")

    # Nutrition tracking (Intervals.icu dietary log)
    calories_kcal: Optional[float] = Field(None, ge=0, description="Daily calorie intake in kcal")
    carbs_g: Optional[float] = Field(None, ge=0, description="Carbohydrate intake in grams")
    protein_g: Optional[float] = Field(None, ge=0, description="Protein intake in grams")
    fat_g: Optional[float] = Field(None, ge=0, description="Fat intake in grams")

    # Activity and body metrics
    steps: Optional[int] = Field(None, ge=0, description="Daily step count")
    abdomen_cm: Optional[float] = Field(None, ge=0, description="Abdominal circumference in cm")
    spo2_pct: Optional[float] = Field(None, ge=0, le=100, description="Blood oxygen saturation percentage")
    systolic_bp: Optional[float] = Field(None, ge=0, description="Systolic blood pressure")
    diastolic_bp: Optional[float] = Field(None, ge=0, description="Diastolic blood pressure")
    vo2max_ml_kg_min: Optional[float] = Field(None, ge=0, description="VO2max in ml/kg/min")
    menstrual_phase: Optional[str] = Field(None, description="Menstrual cycle phase (Intervals)")
    menstrual_phase_predicted: Optional[str] = Field(
        None, description="Predicted menstrual phase (Intervals)"
    )

    # Nested sport-specific training metrics from Intervals.icu
    sport_info: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Per-sport metrics array: [{'type', 'eftp', 'wPrime', 'pMax'}, ...]"
    )

    # Provenance and versioning
    data_sources: str = Field(
        default="", description="CSV of sources: withings,garmin,intervals"
    )
    canonical_version: str = Field(
        default="2.4.0", description="Schema version of this snapshot"
    )
    measured_at_utc: Optional[datetime] = Field(
        None, description="Most specific timestamp available from measurements"
    )
    source_updated_at_utc: Optional[str] = Field(
        None, description="Source-reported update timestamp (ISO 8601)"
    )
    raw_intervals_icu_json: Optional[str] = Field(
        None, description="Full unmodified Intervals.icu day payload JSON"
    )
    ext_json: Optional[str] = Field(
        None, description="Canonical extended fields JSON blob for non-queryable metrics"
    )
    last_updated_utc: datetime = Field(
        default_factory=datetime.utcnow,
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
        sport_info_json = (
            json.dumps(self.sport_info) if self.sport_info is not None else None
        )
        ext_payload = {
            "hrv_sdnn_ms": self.hrv_sdnn_ms,
            "soreness": self.soreness,
            "fatigue": self.fatigue,
            "stress": self.stress,
            "mood": self.mood,
            "motivation": self.motivation,
            "injury": self.injury,
            "calories_kcal": self.calories_kcal,
            "carbs_g": self.carbs_g,
            "protein_g": self.protein_g,
            "fat_g": self.fat_g,
            "abdomen_cm": self.abdomen_cm,
            "spo2_pct": self.spo2_pct,
            "systolic_bp": self.systolic_bp,
            "diastolic_bp": self.diastolic_bp,
            "vo2max_ml_kg_min": self.vo2max_ml_kg_min,
            "menstrual_phase": self.menstrual_phase,
            "menstrual_phase_predicted": self.menstrual_phase_predicted,
            "sport_info_json": sport_info_json,
            "source_updated_at_utc": self.source_updated_at_utc,
        }

        return {
            # Body composition (Withings)
            "weight_kg": self.weight_kg,
            "fat_mass_kg": self.fat_mass_kg,
            "muscle_mass_kg": self.muscle_mass_kg,
            "bone_mass_kg": self.bone_mass_kg,
            "body_fat_pct": self.body_fat_pct,
            "visceral_fat_index": self.visceral_fat_index,
            "metabolic_age_years": self.metabolic_age_years,
            
            # Heart rate metrics (nested for legacy compatibility)
            "heart_rate": {
                "basis": "LTHR",  # Default basis for Intervals/Garmin data
                "lthr_bpm": self.hr_lthr_bpm,
                "hr_max_bpm": self.hr_max_bpm,
                "resting_hr_bpm": self.resting_hr_bpm,
            },
            
            # Wellness metrics (Intervals)
            "hrv_ln_rmssd": self.hrv_ln_rmssd,
            "hrv_sdnn_ms": self.hrv_sdnn_ms,
            "sleep_duration_sec": self.sleep_duration_sec,
            "readiness_score": self.readiness_score,
            
            # Power metrics (nested for legacy compatibility)
            "power": {
                "ftp_watts": self.ftp_watts,
            },
            
            # Aerobic capacity
            "cycling_vo2max_ml_kg_min": self.cycling_vo2max_ml_kg_min,
            
            # Subjective wellness
            "soreness": self.soreness,
            "fatigue": self.fatigue,
            "stress": self.stress,
            "mood": self.mood,
            "motivation": self.motivation,
            "injury": self.injury,
            
            # Nutrition
            "calories_kcal": self.calories_kcal,
            "carbs_g": self.carbs_g,
            "protein_g": self.protein_g,
            "fat_g": self.fat_g,
            
            # Activity & body
            "steps": self.steps,
            "abdomen_cm": self.abdomen_cm,
            "spo2_pct": self.spo2_pct,
            "systolic_bp": self.systolic_bp,
            "diastolic_bp": self.diastolic_bp,
            "vo2max_ml_kg_min": self.vo2max_ml_kg_min,
            "menstrual_phase": self.menstrual_phase,
            "menstrual_phase_predicted": self.menstrual_phase_predicted,
            
            # Nested sport data (serialize to JSON string)
            "sport_info_json": sport_info_json,

            # Raw source preservation (zero-loss ingestion)
            "source_updated_at_utc": self.source_updated_at_utc,
            "raw_intervals_icu_json": self.raw_intervals_icu_json,
            "ext_json": self.ext_json if self.ext_json is not None else json.dumps(ext_payload),
        }

    class Config:
        """Pydantic config for serialization."""
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


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
        default="2.0.0", description="Schema version of this snapshot"
    )
    last_updated_utc: datetime = Field(
        default_factory=datetime.utcnow, description="When snapshot was computed"
    )

    class Config:
        """Pydantic config for serialization."""
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


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

    class Config:
        """Pydantic config for serialization."""
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}
