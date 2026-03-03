"""Canonical wellness domain models: PhysiometricsSnapshot and TrainingStateSnapshot.

These models define the contract for daily state aggregates from external sources
(Withings, Garmin, Intervals). All analytics are computed deterministically from
these canonical snapshots.
"""

import logging
from datetime import datetime
from typing import List, Optional

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
    resting_hr_bpm: Optional[float] = Field(
        None, ge=0, description="Resting heart rate in beats/minute"
    )
    sleep_duration_min: Optional[float] = Field(
        None, ge=0, description="Sleep duration in minutes"
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

    # Provenance and versioning
    data_sources: str = Field(
        default="", description="CSV of sources: withings,garmin,intervals"
    )
    canonical_version: str = Field(
        default="2.0.0", description="Schema version of this snapshot"
    )
    measured_at_utc: Optional[datetime] = Field(
        None, description="Most specific timestamp available from measurements"
    )
    last_updated_utc: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this snapshot was canonicalized",
    )

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
