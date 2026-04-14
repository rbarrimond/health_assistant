"""Domain models for workout data analysis and storage.

This module provides a top-down, compositional model architecture for workout analytics:

**Main API Surface:**
- WorkoutMetricsModel: Compositional output model with typed submodels for all metric families

**Computation Engine:**
- CanonicalAnalyticsEngine: Vectorized analytics from 1 Hz canonical substrate

**Compositional Submodels:**
- SessionMetricsModel, SampleMetricsModel, DistanceMetricsModel: Core workout data
- HRZonesModel, PowerZonesModel: Zone distribution and boundaries
- TrainingLoadMetricsModel: Intensity Factor and TSS
- PowerDurationAnchorsModel: Peak power at standard durations
- EnvelopeScoresModel: Sprint/VO2/threshold capability scores
- VariabilityMetricsModel: Pacing and surge metrics
- DurabilityMetricsModel: Efficiency, decoupling, and fatigue
- StructuredArtifactsModel: JSON blobs for intervals, climbs, power curve

**Canonical Substrate:**
- CanonicalRecord: 1 Hz time-series record
- CanonicalLap: Lap summary

**Legacy Models:**
- Workout, WorkoutSession, DeviceInfo, RecordSample: Original parsed structures

All analytics follow the Canonical Analytics Surface specification (v1.1.0).
"""

# pylint: disable=line-too-long, missing-function-docstring, too-many-lines

from itertools import chain
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import (BaseModel, ConfigDict, Field, computed_field,
                      model_serializer, model_validator)

from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import ValidationError
from TrainingAnalyticsPlatform.models.constants import (
    CLIMB_GRADE_WINDOW_SEC, CLIMB_MAX_GAP_SEC, CLIMB_MIN_GRADE,
    CLIMB_MIN_SEC, DATETIME64_NS, INTERVAL_MIN_SEC,
    INTERVAL_THRESHOLD_FACTOR, ISO_8601_UTC_DESC, LAG_WINDOW_SEC,
    POWER_CURVE_SECONDS, RECOVERY_HR_WINDOW_SEC, SURGE_MIN_SEC,
    SURGE_THRESHOLD_FACTOR)
from TrainingAnalyticsPlatform.models.metrics import (
    DistanceMetricsModel, DurabilityMetricsModel, EnvelopeScoresModel,
    HRZonesModel, PowerDurationAnchorsModel, PowerZonesModel,
    SampleMetricsModel, SessionMetricsModel, StructuredArtifactsModel,
    TrainingLoadMetricsModel, VariabilityMetricsModel)

WORKOUT_ID_DESC = "Unique workout identifier"
ATHLETE_ID_DESC = "Athlete identifier"

# ============================================================================
# MAIN API: WorkoutMetricsModel
# ============================================================================


class WorkoutMetricsModel(BaseModel):
    """Main API surface for workout analytics - compositional model with typed metric families.
    
    This is the primary output model that composes all workout metrics into semantic groups.
    Construct from canonical substrate using `from_canonical()` for in-memory cached metrics.
    
    Structure:
    - session: Basic workout metadata (sport, start time, duration)
    - samples: Telemetry aggregates (HR/power/cadence averages, counts, missing data)
    - distance: GPS-based metrics (distance, elevation, speed, calories)
    - zones_hr: Heart rate zone distribution with boundaries (optional)
    - zones_power: Power zone distribution with boundaries (optional)
    - training_load: Intensity Factor and TSS (optional)
    - power_duration: Peak power anchors at standard durations (optional)
    - envelope: Sprint/VO2/threshold capability scores (optional)
    - variability: CV, surges, pacing evenness (optional)
    - durability: Efficiency factor, decoupling, drift, fatigue (optional)
    - artifacts: Structured JSON for intervals, climbs, power curve (optional)
    
    Example:
        >>> from CanonicalAnalyticsEngine import CanonicalAnalyticsEngine
        >>> df = load_canonical_records("workout.parquet")
        >>> metrics = WorkoutMetricsModel.from_canonical(df, metadata)
        >>> print(f"TSS: {metrics.training_load.tss if metrics.training_load else 'N/A'}")
        >>> print(f"20min power: {metrics.power_duration.peak_20min_watts if metrics.power_duration else 'N/A'}")
    """

    physiometrics_snapshot_timestamp: Optional[str] = Field(None, description=ISO_8601_UTC_DESC)
    session: SessionMetricsModel
    samples: SampleMetricsModel
    distance: DistanceMetricsModel
    zones_hr: Optional[HRZonesModel] = None
    zones_power: Optional[PowerZonesModel] = None
    hr_resting_bpm: Optional[float] = Field(None, ge=0, le=300)
    training_load: Optional[TrainingLoadMetricsModel] = None
    power_duration: Optional[PowerDurationAnchorsModel] = None
    envelope: Optional[EnvelopeScoresModel] = None
    variability: Optional[VariabilityMetricsModel] = None
    durability: Optional[DurabilityMetricsModel] = None
    artifacts: Optional[StructuredArtifactsModel] = None

    @classmethod
    def from_canonical_metrics(
        cls,
        metrics: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "WorkoutMetricsModel":
        """Build a typed metrics model from canonical analytics output plus metadata context."""
        return cls._from_metrics(metrics, metadata or {})

    @classmethod
    def from_canonical(
        cls,
        df: pd.DataFrame,
        metadata: Dict[str, Any],
        resample: bool = False,
    ) -> "WorkoutMetricsModel":
        canonical = CanonicalAnalyticsEngine.from_dataframe(df, metadata, resample=resample)
        metrics = canonical.to_metrics_dict()
        return cls._from_metrics(metrics, metadata)

    @classmethod
    def _from_metrics(
        cls,
        metrics: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> "WorkoutMetricsModel":
        session = cls._build_session(metrics, metadata)
        distance = cls._build_distance(metrics, metadata)
        samples = cls._build_samples(metrics)
        zones_hr = cls._build_hr_zones(metrics)
        zones_power = cls._build_power_zones(metrics)
        training_load = cls._build_training_load(metrics)
        power_duration = cls._build_power_duration(metrics)
        envelope = cls._build_envelope(metrics)
        variability = cls._build_variability(metrics)
        durability = cls._build_durability(metrics)
        artifacts = cls._build_artifacts(metrics)

        return cls(
            physiometrics_snapshot_timestamp=metadata.get("physiometrics_snapshot_timestamp"),
            session=session,
            samples=samples,
            distance=distance,
            zones_hr=zones_hr,
            zones_power=zones_power,
            hr_resting_bpm=metadata.get("hr_resting_bpm"),
            training_load=training_load,
            power_duration=power_duration,
            envelope=envelope,
            variability=variability,
            durability=durability,
            artifacts=artifacts,
        )

    @staticmethod
    def _has_any(values: List[Any]) -> bool:
        return any(value is not None for value in values)

    @staticmethod
    def _coalesce(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    @staticmethod
    def _metadata_section(metadata: Dict[str, Any], key: str) -> Dict[str, Any]:
        value = metadata.get(key)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _build_session(metrics: Dict[str, Any], metadata: Dict[str, Any]) -> SessionMetricsModel:
        identity = WorkoutMetricsModel._metadata_section(metadata, "identity")
        metadata_session = WorkoutMetricsModel._metadata_section(metadata, "metadata_session")
        activity_metadata = WorkoutMetricsModel._metadata_section(metadata, "activity_metadata")
        enrichment = WorkoutMetricsModel._metadata_section(metadata, "enrichment")
        coalesce = WorkoutMetricsModel._coalesce
        local_tz_offset = coalesce(
            metadata.get("local_tz_offset"),
            activity_metadata.get("local_tz_offset"),
        )
        timezone_value = coalesce(
            metadata.get("timezone"),
            activity_metadata.get("timezone"),
            local_tz_offset,
        )
        return SessionMetricsModel(
            sport=coalesce(metadata.get("sport"), identity.get("sport")),
            sub_sport=coalesce(metadata.get("sub_sport"), identity.get("sub_sport")),
            apple_workout_type=coalesce(
                metadata.get("apple_workout_type"),
                enrichment.get("apple_workout_type"),
            ),
            workout_name=coalesce(metadata.get("workout_name"), enrichment.get("workout_name")),
            device_name=coalesce(metadata.get("device_name"), identity.get("device_name")),
            is_indoor=coalesce(metadata.get("is_indoor"), enrichment.get("is_indoor")),
            start_time_utc=coalesce(
                metadata.get("start_time_utc"),
                metrics.get("start_time_utc"),
                identity.get("start_time_utc"),
            ),
            local_tz_offset=local_tz_offset,
            timezone=timezone_value,
            duration_sec=coalesce(metadata.get("duration_sec"), metrics.get("duration_sec")),
            moving_time_sec=coalesce(
                metadata.get("moving_time_sec"),
                metrics.get("moving_time_sec"),
                metadata_session.get("moving_time_sec"),
            ),
            enrichment=enrichment or None,
        )

    @staticmethod
    def _build_distance(metrics: Dict[str, Any], metadata: Dict[str, Any]) -> DistanceMetricsModel:
        return DistanceMetricsModel(
            has_gps=bool(metadata.get("has_gps")) if metadata.get("has_gps") is not None else False,
            distance_m=metrics.get("distance_m"),
            elevation_gain_m=metrics.get("elevation_gain_m"),
            elevation_loss_m=metrics.get("elevation_loss_m"),
            avg_speed_mps=metrics.get("avg_speed_mps"),
            max_speed_mps=metrics.get("max_speed_mps"),
            calories_kcal=metrics.get("calories_kcal"),
        )

    @staticmethod
    def _build_samples(metrics: Dict[str, Any]) -> SampleMetricsModel:
        return SampleMetricsModel(
            hr_avg_bpm=metrics.get("hr_avg_bpm"),
            hr_max_bpm=metrics.get("hr_max_bpm"),
            hr_min_bpm=metrics.get("hr_min_bpm"),
            hr_samples_count=metrics.get("hr_samples_count") or 0,
            hr_missing_pct=metrics.get("hr_missing_pct"),
            pwr_avg_watts=metrics.get("pwr_avg_watts"),
            pwr_max_watts=metrics.get("pwr_max_watts"),
            pwr_normalized_watts=metrics.get("pwr_normalized_watts"),
            pwr_variability_index=metrics.get("pwr_variability_index"),
            pwr_samples_count=metrics.get("pwr_samples_count") or 0,
            pwr_missing_pct=metrics.get("pwr_missing_pct"),
            cad_avg_rpm=metrics.get("cad_avg_rpm"),
            cad_max_rpm=metrics.get("cad_max_rpm"),
            cad_samples_count=metrics.get("cad_samples_count") or 0,
        )

    @classmethod
    def _build_hr_zones(cls, metrics: Dict[str, Any]) -> Optional[HRZonesModel]:
        hr_zone_basis = metrics.get("hr_zone_basis")
        hr_zone_reference = metrics.get("hr_zone_reference_bpm")
        if not hr_zone_basis or hr_zone_reference is None:
            return None
        return HRZonesModel(
            hr_zone_model=metrics.get("hr_zone_model"),
            hr_zone_basis=str(hr_zone_basis),
            hr_zone_reference_bpm=float(hr_zone_reference),
            hr_z1_sec=metrics.get("hr_z1_sec") or 0,
            hr_z2_sec=metrics.get("hr_z2_sec") or 0,
            hr_z3_sec=metrics.get("hr_z3_sec") or 0,
            hr_z4_sec=metrics.get("hr_z4_sec") or 0,
            hr_z5_sec=metrics.get("hr_z5_sec") or 0,
            hr_z1_low_bpm=metrics.get("hr_z1_low_bpm"),
            hr_z1_high_bpm=metrics.get("hr_z1_high_bpm"),
            hr_z2_low_bpm=metrics.get("hr_z2_low_bpm"),
            hr_z2_high_bpm=metrics.get("hr_z2_high_bpm"),
            hr_z3_low_bpm=metrics.get("hr_z3_low_bpm"),
            hr_z3_high_bpm=metrics.get("hr_z3_high_bpm"),
            hr_z4_low_bpm=metrics.get("hr_z4_low_bpm"),
            hr_z4_high_bpm=metrics.get("hr_z4_high_bpm"),
            hr_z5_low_bpm=metrics.get("hr_z5_low_bpm"),
            hr_z5_high_bpm=metrics.get("hr_z5_high_bpm"),
            hr_zone_total_sec=metrics.get("hr_zone_total_sec") or 0,
        )

    @classmethod
    def _build_power_zones(cls, metrics: Dict[str, Any]) -> Optional[PowerZonesModel]:
        ftp_watts = metrics.get("ftp_watts")
        if ftp_watts is None or ftp_watts <= 0:
            return None
        return PowerZonesModel(
            pwr_zone_model=metrics.get("pwr_zone_model") or "coggan_7",
            ftp_watts=float(ftp_watts),
            pwr_z1_sec=metrics.get("pwr_z1_sec") or 0,
            pwr_z2_sec=metrics.get("pwr_z2_sec") or 0,
            pwr_z3_sec=metrics.get("pwr_z3_sec") or 0,
            pwr_z4_sec=metrics.get("pwr_z4_sec") or 0,
            pwr_z5_sec=metrics.get("pwr_z5_sec") or 0,
            pwr_z6_sec=metrics.get("pwr_z6_sec") or 0,
            pwr_z7_sec=metrics.get("pwr_z7_sec") or 0,
            pwr_z1_low_w=metrics.get("pwr_z1_low_w"),
            pwr_z1_high_w=metrics.get("pwr_z1_high_w"),
            pwr_z2_low_w=metrics.get("pwr_z2_low_w"),
            pwr_z2_high_w=metrics.get("pwr_z2_high_w"),
            pwr_z3_low_w=metrics.get("pwr_z3_low_w"),
            pwr_z3_high_w=metrics.get("pwr_z3_high_w"),
            pwr_z4_low_w=metrics.get("pwr_z4_low_w"),
            pwr_z4_high_w=metrics.get("pwr_z4_high_w"),
            pwr_z5_low_w=metrics.get("pwr_z5_low_w"),
            pwr_z5_high_w=metrics.get("pwr_z5_high_w"),
            pwr_z6_low_w=metrics.get("pwr_z6_low_w"),
            pwr_z6_high_w=metrics.get("pwr_z6_high_w"),
            pwr_z7_low_w=metrics.get("pwr_z7_low_w"),
            pwr_z7_high_w=metrics.get("pwr_z7_high_w"),
            pwr_zone_total_sec=metrics.get("pwr_zone_total_sec"),
            low_aerobic_sec=metrics.get("low_aerobic_sec"),
            intensity_sec=metrics.get("intensity_sec"),
        )

    @classmethod
    def _build_training_load(cls, metrics: Dict[str, Any]) -> Optional[TrainingLoadMetricsModel]:
        if not cls._has_any([metrics.get("intensity_factor"), metrics.get("tss")]):
            return None
        return TrainingLoadMetricsModel(
            intensity_factor=metrics.get("intensity_factor"),
            tss=metrics.get("tss"),
        )

    @classmethod
    def _build_power_duration(cls, metrics: Dict[str, Any]) -> Optional[PowerDurationAnchorsModel]:
        if not cls._has_any([
            metrics.get("peak_5s_watts"),
            metrics.get("peak_30s_watts"),
            metrics.get("peak_3min_watts"),
            metrics.get("peak_5min_watts"),
            metrics.get("peak_8min_watts"),
            metrics.get("peak_20min_watts"),
            metrics.get("peak_60min_watts"),
        ]):
            return None
        return PowerDurationAnchorsModel(
            peak_5s_watts=metrics.get("peak_5s_watts"),
            peak_30s_watts=metrics.get("peak_30s_watts"),
            peak_3min_watts=metrics.get("peak_3min_watts"),
            peak_5min_watts=metrics.get("peak_5min_watts"),
            peak_8min_watts=metrics.get("peak_8min_watts"),
            peak_20min_watts=metrics.get("peak_20min_watts"),
            peak_60min_watts=metrics.get("peak_60min_watts"),
            power_curve_watts=metrics.get("power_curve_watts") or None,
        )

    @classmethod
    def _build_envelope(cls, metrics: Dict[str, Any]) -> Optional[EnvelopeScoresModel]:
        if not cls._has_any([
            metrics.get("sprint_envelope_score"),
            metrics.get("vo2_envelope_score"),
            metrics.get("threshold_envelope_score"),
        ]):
            return None
        return EnvelopeScoresModel(
            sprint_envelope_score=metrics.get("sprint_envelope_score"),
            vo2_envelope_score=metrics.get("vo2_envelope_score"),
            threshold_envelope_score=metrics.get("threshold_envelope_score"),
        )

    @classmethod
    def _build_variability(cls, metrics: Dict[str, Any]) -> Optional[VariabilityMetricsModel]:
        if not cls._has_any([
            metrics.get("cv_power"),
            metrics.get("cv_hr"),
            metrics.get("surge_count"),
            metrics.get("surge_density_per_hr"),
            metrics.get("pacing_evenness_score"),
        ]):
            return None
        return VariabilityMetricsModel(
            cv_power=metrics.get("cv_power"),
            cv_hr=metrics.get("cv_hr"),
            surge_count=metrics.get("surge_count"),
            surge_density_per_hr=metrics.get("surge_density_per_hr"),
            pacing_evenness_score=metrics.get("pacing_evenness_score"),
        )

    @classmethod
    def _build_durability(cls, metrics: Dict[str, Any]) -> Optional[DurabilityMetricsModel]:
        if not cls._has_any([
            metrics.get("efficiency_factor_avg"),
            metrics.get("decoupling_pct"),
            metrics.get("durability_slope"),
            metrics.get("fatigue_rate_power"),
            metrics.get("hr_power_lag_sec"),
            metrics.get("ef_first_half"),
            metrics.get("ef_second_half"),
            metrics.get("ef_overall"),
            metrics.get("hr_drift_bpm"),
        ]):
            return None
        return DurabilityMetricsModel(
            efficiency_factor_avg=metrics.get("efficiency_factor_avg"),
            decoupling_pct=metrics.get("decoupling_pct"),
            durability_slope=metrics.get("durability_slope"),
            fatigue_rate_power=metrics.get("fatigue_rate_power"),
            hr_power_lag_sec=metrics.get("hr_power_lag_sec"),
            ef_first_half=metrics.get("ef_first_half"),
            ef_second_half=metrics.get("ef_second_half"),
            ef_overall=metrics.get("ef_overall"),
            hr_drift_bpm=metrics.get("hr_drift_bpm"),
        )

    @classmethod
    def _build_artifacts(cls, metrics: Dict[str, Any]) -> Optional[StructuredArtifactsModel]:
        if not cls._has_any([
            metrics.get("intervals"),
            metrics.get("climbs"),
            metrics.get("power_curve"),
        ]):
            return None
        return StructuredArtifactsModel(
            intervals=metrics.get("intervals"),
            climbs=metrics.get("climbs"),
            power_curve=metrics.get("power_curve"),
        )


# ============================================================================
# PLANNING API: WorkoutProjection
# ============================================================================


class WorkoutProjection(BaseModel):
    """Lightweight projection of workout for efficient planning context pulls.
    
    Built from Workouts table + metadata.json at read-time, this projection optimizes
    for batch queries where clients need summary information for training decisions
    (TSS, readiness, workload analysis) without full metric computation overhead.
    
    Contains only:
    - Identity fields (workout_id, sport, device, timestamps)
    - Session summary (duration, distance, elevation, calories)
    - Data availability flags (has_power, has_hr, has_gps)
    - Sport-specific peaks (HR/power/cadence averages and maximums)
    - Status flags (indoor, race, commute)
    - Provenance metadata (ingestion version, timestamp)
    
    Base fields are extracted directly from WorkoutEntity + metadata.json.
    Read-time hydration automatically fills missing capability-dependent metrics from
    CanonicalAnalyticsEngine when `has_hr`/`has_power` are true, without overwriting
    metadata-provided values.
    Capability-dependent fields (HR/power metrics) are Optional based on has_hr/has_power.
    
    Use this for:
    - Batch planning context queries (/api/planning/context)
    - Efficient workout list responses (/api/workouts?limit=50)
    
    For full metrics including zones, efficiency, duration curves, duration curves, duration curve analysis:
    call /api/workouts/{workout_id} (returns WorkoutDetail).
    
    Example:
        >>> projection = build_workout_projection(workout_entity, metadata_dict)
        >>> print(f"{projection.sport} - {projection.duration_sec}s - HR avg: {projection.hr_avg_bpm}")
    """
    
    model_config = ConfigDict(extra="forbid")
    
    # Identity
    workout_id: str = Field(..., description="Unique workout identifier")
    athlete_id: str = Field(..., description="Athlete identifier")
    sport: str = Field(..., description="Primary sport/activity type (cycling, running, etc.)")
    sub_sport: Optional[str] = Field(None, description="Sub-sport (road_cycling, trail_running, etc.)")
    workout_name: Optional[str] = Field(None, description="User-provided workout name")
    device_name: Optional[str] = Field(None, description="Device name (Robert's Apple Watch, Garmin Edge, etc.)")
    device_manufacturer: Optional[str] = Field(None, description="Device manufacturer (Apple, Garmin, Wahoo, etc.)")
    
    # Timing
    start_time_utc: str = Field(..., description=ISO_8601_UTC_DESC)
    local_tz_offset: Optional[str] = Field(None, description="Local timezone offset (e.g., '-05:00')")
    timezone: Optional[str] = Field(None, description="IANA timezone name (e.g., 'America/New_York')")
    duration_sec: float = Field(..., ge=0, description="Total elapsed time in seconds")
    moving_time_sec: Optional[float] = Field(None, ge=0, description="Active moving time in seconds")
    
    # Distance & Elevation
    distance_m: Optional[float] = Field(None, ge=0, description="GPS distance in meters")
    elevation_gain_m: Optional[float] = Field(None, ge=0, description="Elevation gain in meters")
    elevation_loss_m: Optional[float] = Field(None, ge=0, description="Elevation loss in meters")
    calories_kcal: Optional[float] = Field(None, ge=0, description="Total energy expenditure in kilocalories")
    
    # Data Availability Flags
    has_power: bool = Field(..., description="Workout contains power meter data")
    has_hr: bool = Field(..., description="Workout contains heart rate data")
    has_gps: bool = Field(..., description="Workout contains GPS data")
    
    # Sport-Specific Peaks (capability-dependent, Optional)
    hr_avg_bpm: Optional[float] = Field(None, ge=30, le=240, description="Average heart rate (bpm) - populated if has_hr=True")
    hr_max_bpm: Optional[float] = Field(None, ge=30, le=240, description="Max heart rate (bpm) - populated if has_hr=True")
    pwr_avg_watts: Optional[float] = Field(None, ge=0, description="Average power (watts) - populated if has_power=True")
    pwr_max_watts: Optional[float] = Field(None, ge=0, description="Max power (watts) - populated if has_power=True")
    pwr_normalized_watts: Optional[float] = Field(None, ge=0, description="Normalized power (watts) - populated if has_power=True")
    cad_avg_rpm: Optional[float] = Field(None, ge=0, description="Average cadence (rpm)")
    cad_max_rpm: Optional[float] = Field(None, ge=0, description="Max cadence (rpm)")
    
    # Status Flags
    is_indoor: bool = Field(default=False, description="Workout was performed indoors")
    race_flag: bool = Field(default=False, description="Marked as race/competitive event")
    commute_flag: bool = Field(default=False, description="Marked as commute workout")
    
    # Provenance
    ingestion_version: Optional[str] = Field(None, description="Ingestion pipeline version")
    ingestion_timestamp_utc: Optional[str] = Field(None, description=ISO_8601_UTC_DESC)


class WorkoutDetailResponse(BaseModel):
    """Typed response contract for deep-dive single-workout queries."""

    model_config = ConfigDict(extra="forbid")

    workout_id: str = Field(..., description=WORKOUT_ID_DESC)
    athlete_id: str = Field(..., description=ATHLETE_ID_DESC)
    source_system: Optional[str] = Field(default=None, description="Source provider for workout ingestion")
    metrics: WorkoutMetricsModel
    laps_count: Optional[int] = Field(default=None, ge=0, description="Number of lap summaries included")
    laps: Optional[List["LapSummaryResponse"]] = Field(
        default=None,
        description="Lap summary payloads when laps=true",
    )
    lap_errors: Optional[Dict[str, str]] = Field(
        default=None,
        description="Lap loading/parsing errors when lap data cannot be fully resolved",
    )
    developer_fields_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional developer field summary extracted from metadata payload",
    )
    developer_fields_error: Optional[str] = Field(
        default=None,
        description="Developer field processing error when include_developer_fields=true",
    )


class LapSummaryResponse(BaseModel):
    """Typed lap summary payload for workout detail and lap detail endpoints."""

    model_config = ConfigDict(extra="forbid")

    lap_index: int = Field(..., ge=0, description="Zero-based lap index")
    message_index: Optional[int] = Field(default=None, ge=0, description="FIT message_index when present")
    start_time: Optional[str] = Field(default=None, description=ISO_8601_UTC_DESC)
    end_time: Optional[str] = Field(default=None, description=ISO_8601_UTC_DESC)
    total_elapsed_time: Optional[float] = Field(default=None, ge=0, description="Lap elapsed duration in seconds")
    total_timer_time: Optional[float] = Field(default=None, ge=0, description="Lap active timer duration in seconds")
    total_distance: Optional[float] = Field(default=None, ge=0, description="Lap distance in meters")
    total_calories: Optional[float] = Field(default=None, ge=0, description="Lap calories in kilocalories")
    avg_heart_rate: Optional[float] = Field(default=None, ge=0, description="Average heart rate during lap")
    max_heart_rate: Optional[float] = Field(default=None, ge=0, description="Maximum heart rate during lap")
    avg_power: Optional[float] = Field(default=None, ge=0, description="Average power during lap")
    max_power: Optional[float] = Field(default=None, ge=0, description="Maximum power during lap")
    avg_cadence: Optional[float] = Field(default=None, ge=0, description="Average cadence during lap")
    max_cadence: Optional[float] = Field(default=None, ge=0, description="Maximum cadence during lap")
    avg_speed: Optional[float] = Field(default=None, ge=0, description="Average speed during lap")
    max_speed: Optional[float] = Field(default=None, ge=0, description="Maximum speed during lap")
    intensity: Optional[str] = Field(default=None, description="FIT lap intensity label")
    lap_trigger: Optional[str] = Field(default=None, description="FIT lap trigger type")
    sport: Optional[str] = Field(default=None, description="Lap sport")
    sub_sport: Optional[str] = Field(default=None, description="Lap sub-sport")
    extra_fields: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional lap fields not promoted into top-level lap summary attributes",
    )


class WorkoutLapDetailResponse(BaseModel):
    """Typed response contract for workout lap detail queries."""

    model_config = ConfigDict(extra="forbid")

    workout_id: str = Field(..., description=WORKOUT_ID_DESC)
    athlete_id: str = Field(..., description=ATHLETE_ID_DESC)
    lap: LapSummaryResponse


class CanonicalAnalyticsEngine(BaseModel):  # pylint: disable=too-many-public-methods
    """Computation engine for deriving workout analytics from canonical 1 Hz substrate.
    
    This is an internal computation engine that calculates all workout metrics from a 1 Hz
    canonical DataFrame. It enforces 1 Hz sampling and provides computed fields for all
    metrics defined in the Canonical Analytics Surface specification.
    
    The engine uses vectorized pandas operations for efficient computation and exposes
    metrics as @computed_field properties. All computations are lazy and cached.
    
    Usage:
        >>> engine = CanonicalAnalyticsEngine.from_dataframe(df, metadata, resample=True)
        >>> metrics_dict = engine.to_metrics_dict()
        >>> # Or use WorkoutMetricsModel.from_canonical() for typed output
    
    Validation:
    - By default, raises ValidationError (422) if input DataFrame is not 1 Hz sampled
    - Set resample=True to automatically resample non-1Hz data
    - Requires 'timestamp_utc' or 'elapsed_sec' column for temporal index
    
    Architecture:
    - df: pandas DataFrame with 1 Hz canonical records (schema: CanonicalRecord)
    - metadata: Dict with workout context (sport, FTP, HR zones, etc.)
    - @computed_field properties: Lazy-evaluated metrics with caching
    - to_metrics_dict(): Exports all computed metrics as flat dictionary
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    df: pd.DataFrame = Field(default_factory=pd.DataFrame)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    resample: bool = Field(
        default=False,
        description="If True, resample input DataFrame to 1 Hz; if False, validate input is already 1 Hz"
    )

    @model_serializer(mode="plain")
    def _serialize_metrics(self) -> Dict[str, Any]:
        return self.to_metrics_dict()

    @model_validator(mode='after')
    def _validate_and_resample_to_1hz(self) -> 'CanonicalAnalyticsEngine':
        """Validate input is 1 Hz or resample if explicitly requested."""
        df = self.__dict__.get("df")
        if not isinstance(df, pd.DataFrame) or df.empty:
            return self

        working = self._establish_temporal_index(df)
        is_1hz = self._is_1hz_frequency(working)

        if is_1hz:
            working = self._add_elapsed_sec_column(working)
            object.__setattr__(self, "df", working)
            return self

        # Not 1 Hz - check if resampling is allowed
        if not self.__dict__.get("resample", False):
            diffs = working.index.to_series().diff().dt.total_seconds().dropna()
            median_interval_sec = round(float(diffs.median()), 3) if not diffs.empty else None
            min_interval_sec = round(float(diffs.min()), 3) if not diffs.empty else None
            max_interval_sec = round(float(diffs.max()), 3) if not diffs.empty else None
            raise ValidationError(
                "Canonical validation failed: input DataFrame is not 1 Hz sampled "
                f"(rows={len(working)}, median_interval_sec={median_interval_sec}, "
                f"min_interval_sec={min_interval_sec}, max_interval_sec={max_interval_sec}). "
                "Set resample=True to enable automatic resampling, or provide pre-resampled 1 Hz data.",
                status_code=422,
            )

        resampled = self._resample_to_1hz(working)
        object.__setattr__(self, "df", resampled)
        return self

    def _establish_temporal_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """Establish temporal index from timestamp_utc or elapsed_sec columns."""
        working = df.copy()
        index = None

        if "timestamp_utc" in working:
            timestamps = pd.to_datetime(working["timestamp_utc"], errors="coerce", utc=True)
            valid = timestamps.notna()
            if valid.any():
                working = working.loc[valid].copy()
                index = timestamps[valid]

        if index is None and "elapsed_sec" in working:
            elapsed = pd.to_numeric(working["elapsed_sec"], errors="coerce")
            valid = elapsed.notna()
            if valid.any():
                working = working.loc[valid].copy()
                index = pd.to_timedelta(elapsed[valid], unit="s")

        if index is None:
            raise ValueError(
                "Cannot establish temporal index for CanonicalRecord validation. "
                "DataFrame must have either 'timestamp_utc' or 'elapsed_sec' column."
            )

        working.index = index
        return working.sort_index()

    def _add_elapsed_sec_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add elapsed_sec column if not present."""
        if "elapsed_sec" in df:
            return df

        if isinstance(df.index, pd.DatetimeIndex):
            df["elapsed_sec"] = (df.index - df.index[0]).total_seconds()
        else:
            df["elapsed_sec"] = pd.to_timedelta(df.index).total_seconds()
        return df

    def _resample_to_1hz(self, df: pd.DataFrame) -> pd.DataFrame:
        """Resample DataFrame to 1 Hz.
        
        Handles different aggregation strategies:
        - mean_cols: Average values across resampling window
        - last_cols: Forward-fill last value from previous record
        - rr_intervals_sec: Concatenate all interval tuples in window (order-preserving)
        """
        mean_cols = [
            col
            for col in [
                "power_watts",
                "heart_rate_bpm",
                "cadence_rpm",
                "speed_mps",
                "temperature_c",
                "respiration_rate_brpm",
                "lr_balance_pct",
            ]
            if col in df
        ]
        last_cols = [col for col in ["distance_m", "elevation_m"] if col in df]
        rr_col = "rr_intervals_sec" if "rr_intervals_sec" in df else None

        mean_frame = (
            df[mean_cols].apply(pd.to_numeric, errors="coerce").resample("1s").mean()
            if mean_cols
            else pd.DataFrame(index=df.resample("1s").mean().index)
        )
        last_frame = (
            df[last_cols].apply(pd.to_numeric, errors="coerce").resample("1s").last().ffill()
            if last_cols
            else pd.DataFrame(index=mean_frame.index)
        )

        # Handle RR intervals: concatenate tuples while preserving order
        rr_frame = pd.DataFrame(index=mean_frame.index)
        if rr_col:
            def concatenate_rr_tuples(group):
                """Flatten and concatenate all RR interval tuples in resample window."""
                # Filter out None/NaN values and concatenate tuples
                tuples = [v for v in group if isinstance(v, tuple) and len(v) > 0]
                if not tuples:
                    return ()
                return tuple(chain.from_iterable(tuples))

            rr_frame[rr_col] = df[[rr_col]].resample("1s").apply(
                lambda x: concatenate_rr_tuples(x[rr_col].values)  # type: ignore[arg-type]
            )

        resampled = pd.concat([mean_frame, last_frame, rr_frame], axis=1)
        return self._add_elapsed_sec_column(resampled)

    def _is_1hz_frequency(self, df: pd.DataFrame) -> bool:
        """Check if DataFrame index represents 1 Hz sampling (1 second intervals)."""
        if len(df) < 2:
            return True  # Too few samples to determine frequency

        # Calculate time differences between consecutive samples
        if isinstance(df.index, pd.DatetimeIndex):
            diffs = df.index.to_series().diff().dt.total_seconds()
        elif isinstance(df.index, pd.TimedeltaIndex):
            diffs = df.index.to_series().diff().dt.total_seconds()
        else:
            return False  # Cannot determine frequency without time-based index

        # Check if all diffs are approximately 1 second (allowing small floating point tolerance)
        diffs = diffs.dropna()
        if diffs.empty:
            return False

        # Allow 10ms tolerance for 1 Hz (floating point comparisons)
        return bool(np.all(np.abs(diffs - 1.0) < 0.01))

    @classmethod
    def from_canonical(
        cls,
        df: pd.DataFrame,
        metadata: Dict[str, Any],
        resample: bool = False,
    ) -> "CanonicalAnalyticsEngine":
        return cls.from_dataframe(df, metadata, resample=resample)

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        metadata: Dict[str, Any],
        resample: bool = False,
    ) -> "CanonicalAnalyticsEngine":
        return cls(df=df, metadata=metadata, resample=resample)

    @property
    def metrics(self) -> Dict[str, Any]:
        return self.to_metrics_dict()

    def to_metrics_dict(self) -> Dict[str, Any]:
        values = {
            "start_time_utc": self.start_time_utc,
            "duration_sec": self.duration_sec,
            "moving_time_sec": self.moving_time_sec,
            "distance_m": self.distance_m,
            "elevation_gain_m": self.elevation_gain_m,
            "elevation_loss_m": self.elevation_loss_m,
            "avg_speed_mps": self.avg_speed_mps,
            "max_speed_mps": self.max_speed_mps,
            "calories_kcal": self.calories_kcal,
            "hr_avg_bpm": self.hr_avg_bpm,
            "hr_max_bpm": self.hr_max_bpm,
            "hr_min_bpm": self.hr_min_bpm,
            "hr_samples_count": self.hr_samples_count,
            "hr_missing_pct": self.hr_missing_pct,
            "pwr_avg_watts": self.pwr_avg_watts,
            "pwr_max_watts": self.pwr_max_watts,
            "pwr_normalized_watts": self.pwr_normalized_watts,
            "pwr_variability_index": self.pwr_variability_index,
            "pwr_samples_count": self.pwr_samples_count,
            "pwr_missing_pct": self.pwr_missing_pct,
            "cad_avg_rpm": self.cad_avg_rpm,
            "cad_max_rpm": self.cad_max_rpm,
            "cad_samples_count": self.cad_samples_count,
            "hr_zone_basis": self.hr_zone_basis,
            "hr_zone_reference_bpm": self.hr_zone_reference_bpm,
            "hr_zone_model": self.hr_zone_model,
            "hr_z1_sec": self.hr_z1_sec,
            "hr_z2_sec": self.hr_z2_sec,
            "hr_z3_sec": self.hr_z3_sec,
            "hr_z4_sec": self.hr_z4_sec,
            "hr_z5_sec": self.hr_z5_sec,
            "hr_z1_low_bpm": self.hr_z1_low_bpm,
            "hr_z1_high_bpm": self.hr_z1_high_bpm,
            "hr_z2_low_bpm": self.hr_z2_low_bpm,
            "hr_z2_high_bpm": self.hr_z2_high_bpm,
            "hr_z3_low_bpm": self.hr_z3_low_bpm,
            "hr_z3_high_bpm": self.hr_z3_high_bpm,
            "hr_z4_low_bpm": self.hr_z4_low_bpm,
            "hr_z4_high_bpm": self.hr_z4_high_bpm,
            "hr_z5_low_bpm": self.hr_z5_low_bpm,
            "hr_z5_high_bpm": self.hr_z5_high_bpm,
            "hr_zone_total_sec": self.hr_zone_total_sec,
            "pwr_zone_model": self.pwr_zone_model,
            "ftp_watts": self.ftp_watts,
            "pwr_z1_sec": self.pwr_z1_sec,
            "pwr_z2_sec": self.pwr_z2_sec,
            "pwr_z3_sec": self.pwr_z3_sec,
            "pwr_z4_sec": self.pwr_z4_sec,
            "pwr_z5_sec": self.pwr_z5_sec,
            "pwr_z6_sec": self.pwr_z6_sec,
            "pwr_z7_sec": self.pwr_z7_sec,
            "pwr_z1_low_w": self.pwr_z1_low_w,
            "pwr_z1_high_w": self.pwr_z1_high_w,
            "pwr_z2_low_w": self.pwr_z2_low_w,
            "pwr_z2_high_w": self.pwr_z2_high_w,
            "pwr_z3_low_w": self.pwr_z3_low_w,
            "pwr_z3_high_w": self.pwr_z3_high_w,
            "pwr_z4_low_w": self.pwr_z4_low_w,
            "pwr_z4_high_w": self.pwr_z4_high_w,
            "pwr_z5_low_w": self.pwr_z5_low_w,
            "pwr_z5_high_w": self.pwr_z5_high_w,
            "pwr_z6_low_w": self.pwr_z6_low_w,
            "pwr_z6_high_w": self.pwr_z6_high_w,
            "pwr_z7_low_w": self.pwr_z7_low_w,
            "pwr_z7_high_w": self.pwr_z7_high_w,
            "pwr_zone_total_sec": self.pwr_zone_total_sec,
            "low_aerobic_sec": self.low_aerobic_sec,
            "intensity_sec": self.intensity_sec,
            "intensity_factor": self.intensity_factor,
            "tss": self.tss,
            "ef_first_half": self.ef_first_half,
            "ef_second_half": self.ef_second_half,
            "ef_overall": self.ef_overall,
            "hr_drift_bpm": self.hr_drift_bpm,
            "decoupling_pct": self.decoupling_pct,
            "efficiency_factor_avg": self.efficiency_factor_avg,
            "peak_5s_watts": self.peak_5s_watts,
            "peak_30s_watts": self.peak_30s_watts,
            "peak_3min_watts": self.peak_3min_watts,
            "peak_5min_watts": self.peak_5min_watts,
            "peak_8min_watts": self.peak_8min_watts,
            "peak_20min_watts": self.peak_20min_watts,
            "peak_60min_watts": self.peak_60min_watts,
            "sprint_envelope_score": self.sprint_envelope_score,
            "vo2_envelope_score": self.vo2_envelope_score,
            "threshold_envelope_score": self.threshold_envelope_score,
            "cv_power": self.cv_power,
            "cv_hr": self.cv_hr,
            "surge_count": self.surge_count,
            "surge_density_per_hr": self.surge_density_per_hr,
            "pacing_evenness_score": self.pacing_evenness_score,
            "durability_slope": self.durability_slope,
            "fatigue_rate_power": self.fatigue_rate_power,
            "hr_power_lag_sec": self.hr_power_lag_sec,
            "power_curve_watts": self.power_curve_watts,
            "intervals": self.intervals,
            "climbs": self.climbs,
            "power_curve": self.power_curve,
        }
        return {key: value for key, value in values.items() if value is not None}

    @computed_field
    @property
    def start_time_utc(self) -> Optional[str]:
        metadata = self.metadata or {}
        metadata_value = metadata.get("start_time_utc")
        if metadata_value:
            return str(metadata_value)
        timestamps = self._timestamps()
        return timestamps.min().isoformat() if not timestamps.empty else None

    @computed_field
    @property
    def duration_sec(self) -> Optional[float]:
        metadata = self.metadata or {}
        metadata_value = metadata.get("duration_sec")
        if metadata_value is not None:
            return self._as_float(metadata_value)
        elapsed = self._numeric_series(self.df, "elapsed_sec")
        if not elapsed.empty:
            return float(elapsed.max())
        timestamps = self._timestamps()
        if timestamps.size >= 2:
            return float((timestamps.max() - timestamps.min()).total_seconds())
        return None

    @computed_field
    @property
    def moving_time_sec(self) -> Optional[float]:
        metadata = self.metadata or {}
        metadata_value = metadata.get("moving_time_sec")
        if metadata_value is not None:
            return self._as_float(metadata_value)
        return self.duration_sec

    @computed_field
    @property
    def distance_m(self) -> Optional[float]:
        metadata = self.metadata or {}
        metadata_value = metadata.get("distance_m")
        if metadata_value is not None:
            return self._as_float(metadata_value)
        distance = self._numeric_series(self.df, "distance_m")
        return float(distance.max()) if not distance.empty else None

    @computed_field
    @property
    def elevation_gain_m(self) -> Optional[float]:
        elevation = self._numeric_series(self.df, "elevation_m")
        if elevation.size < 2:
            return None
        diffs = elevation.diff()
        return float(diffs[diffs > 0].sum())

    @computed_field
    @property
    def elevation_loss_m(self) -> Optional[float]:
        elevation = self._numeric_series(self.df, "elevation_m")
        if elevation.size < 2:
            return None
        diffs = elevation.diff()
        return float(diffs[diffs < 0].abs().sum())

    @computed_field
    @property
    def avg_speed_mps(self) -> Optional[float]:
        speed = self._numeric_series(self.df, "speed_mps")
        return float(np.round(speed.mean(), 2)) if not speed.empty else None

    @computed_field
    @property
    def max_speed_mps(self) -> Optional[float]:
        speed = self._numeric_series(self.df, "speed_mps")
        return float(speed.max()) if not speed.empty else None

    @computed_field
    @property
    def calories_kcal(self) -> Optional[float]:
        metadata = self.metadata or {}
        metadata_value = metadata.get("calories_kcal")
        if metadata_value is not None:
            return self._as_float(metadata_value)
        return None

    @computed_field
    @property
    def hr_avg_bpm(self) -> Optional[float]:
        hr = self._numeric_series(self.df, "heart_rate_bpm")
        return float(np.round(hr.mean(), 1)) if not hr.empty else None

    @computed_field
    @property
    def hr_max_bpm(self) -> Optional[float]:
        hr = self._numeric_series(self.df, "heart_rate_bpm")
        return float(hr.max()) if not hr.empty else None

    @computed_field
    @property
    def hr_min_bpm(self) -> Optional[float]:
        hr = self._numeric_series(self.df, "heart_rate_bpm")
        return float(hr.min()) if not hr.empty else None

    @computed_field
    @property
    def hr_samples_count(self) -> Optional[int]:
        hr = self._numeric_series(self.df, "heart_rate_bpm")
        return int(hr.size) if not hr.empty else None

    @staticmethod
    def _missing_pct(duration: Optional[float], samples: Optional[int]) -> Optional[float]:
        if not duration or duration <= 0:
            return None
        if not samples:
            return None
        missing_pct = (1 - samples / duration) * 100
        bounded_missing_pct = min(max(missing_pct, 0.0), 100.0)
        return round(bounded_missing_pct, 1)

    @computed_field
    @property
    def hr_missing_pct(self) -> Optional[float]:
        duration = self.duration_sec
        if not duration or duration <= 0:
            return None
        samples = self.hr_samples_count
        if not samples:
            return None
        return self._missing_pct(self.duration_sec, self.hr_samples_count)

    @computed_field
    @property
    def pwr_avg_watts(self) -> Optional[float]:
        power = self._numeric_series(self.df, "power_watts")
        return float(np.round(power.mean(), 1)) if not power.empty else None

    @computed_field
    @property
    def pwr_max_watts(self) -> Optional[float]:
        power = self._numeric_series(self.df, "power_watts")
        return float(power.max()) if not power.empty else None

    @computed_field
    @property
    def pwr_normalized_watts(self) -> Optional[float]:
        power = self._numeric_series(self.df, "power_watts")
        return self._normalized_power(power)

    @computed_field
    @property
    def pwr_variability_index(self) -> Optional[float]:
        avg_power = self.pwr_avg_watts
        normalized = self.pwr_normalized_watts
        if not avg_power or not normalized or avg_power <= 0:
            return None
        return round(normalized / avg_power, 2)

    @computed_field
    @property
    def pwr_samples_count(self) -> Optional[int]:
        power = self._numeric_series(self.df, "power_watts")
        return int(power.size) if not power.empty else None

    @computed_field
    @property
    def pwr_missing_pct(self) -> Optional[float]:
        duration = self.duration_sec
        if not duration or duration <= 0:
            return None
        samples = self.pwr_samples_count
        if not samples:
            return None
        return self._missing_pct(self.duration_sec, self.pwr_samples_count)

    @computed_field
    @property
    def cad_avg_rpm(self) -> Optional[float]:
        cadence = self._numeric_series(self.df, "cadence_rpm")
        return float(np.round(cadence.mean(), 1)) if not cadence.empty else None

    @computed_field
    @property
    def cad_max_rpm(self) -> Optional[float]:
        cadence = self._numeric_series(self.df, "cadence_rpm")
        return float(cadence.max()) if not cadence.empty else None

    @computed_field
    @property
    def cad_samples_count(self) -> Optional[int]:
        cadence = self._numeric_series(self.df, "cadence_rpm")
        return int(cadence.size) if not cadence.empty else None

    @computed_field
    @property
    def hr_zone_basis(self) -> Optional[str]:
        return self._hr_zone_summary().get("hr_zone_basis")

    @computed_field
    @property
    def hr_zone_reference_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_zone_reference_bpm")

    @computed_field
    @property
    def hr_zone_model(self) -> Optional[str]:
        return self._hr_zone_summary().get("hr_zone_model")

    @computed_field
    @property
    def hr_z1_sec(self) -> Optional[int]:
        return self._hr_zone_summary().get("hr_z1_sec")

    @computed_field
    @property
    def hr_z2_sec(self) -> Optional[int]:
        return self._hr_zone_summary().get("hr_z2_sec")

    @computed_field
    @property
    def hr_z3_sec(self) -> Optional[int]:
        return self._hr_zone_summary().get("hr_z3_sec")

    @computed_field
    @property
    def hr_z4_sec(self) -> Optional[int]:
        return self._hr_zone_summary().get("hr_z4_sec")

    @computed_field
    @property
    def hr_z5_sec(self) -> Optional[int]:
        return self._hr_zone_summary().get("hr_z5_sec")

    @computed_field
    @property
    def hr_z1_low_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z1_low_bpm")

    @computed_field
    @property
    def hr_z1_high_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z1_high_bpm")

    @computed_field
    @property
    def hr_z2_low_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z2_low_bpm")

    @computed_field
    @property
    def hr_z2_high_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z2_high_bpm")

    @computed_field
    @property
    def hr_z3_low_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z3_low_bpm")

    @computed_field
    @property
    def hr_z3_high_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z3_high_bpm")

    @computed_field
    @property
    def hr_z4_low_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z4_low_bpm")

    @computed_field
    @property
    def hr_z4_high_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z4_high_bpm")

    @computed_field
    @property
    def hr_z5_low_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z5_low_bpm")

    @computed_field
    @property
    def hr_z5_high_bpm(self) -> Optional[float]:
        return self._hr_zone_summary().get("hr_z5_high_bpm")

    @computed_field
    @property
    def hr_zone_total_sec(self) -> Optional[int]:
        return self._hr_zone_summary().get("hr_zone_total_sec")

    @computed_field
    @property
    def pwr_zone_model(self) -> Optional[str]:
        return self._power_zone_summary().get("pwr_zone_model")

    @computed_field
    @property
    def ftp_watts(self) -> Optional[float]:
        return self._resolve_ftp_watts()

    @computed_field
    @property
    def pwr_z1_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_z1_sec")

    @computed_field
    @property
    def pwr_z2_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_z2_sec")

    @computed_field
    @property
    def pwr_z3_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_z3_sec")

    @computed_field
    @property
    def pwr_z4_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_z4_sec")

    @computed_field
    @property
    def pwr_z5_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_z5_sec")

    @computed_field
    @property
    def pwr_z6_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_z6_sec")

    @computed_field
    @property
    def pwr_z7_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_z7_sec")

    @computed_field
    @property
    def pwr_z1_low_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z1_low_w")

    @computed_field
    @property
    def pwr_z1_high_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z1_high_w")

    @computed_field
    @property
    def pwr_z2_low_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z2_low_w")

    @computed_field
    @property
    def pwr_z2_high_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z2_high_w")

    @computed_field
    @property
    def pwr_z3_low_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z3_low_w")

    @computed_field
    @property
    def pwr_z3_high_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z3_high_w")

    @computed_field
    @property
    def pwr_z4_low_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z4_low_w")

    @computed_field
    @property
    def pwr_z4_high_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z4_high_w")

    @computed_field
    @property
    def pwr_z5_low_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z5_low_w")

    @computed_field
    @property
    def pwr_z5_high_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z5_high_w")

    @computed_field
    @property
    def pwr_z6_low_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z6_low_w")

    @computed_field
    @property
    def pwr_z6_high_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z6_high_w")

    @computed_field
    @property
    def pwr_z7_low_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z7_low_w")

    @computed_field
    @property
    def pwr_z7_high_w(self) -> Optional[float]:
        return self._power_zone_summary().get("pwr_z7_high_w")

    @computed_field
    @property
    def pwr_zone_total_sec(self) -> Optional[int]:
        return self._power_zone_summary().get("pwr_zone_total_sec")

    @computed_field
    @property
    def low_aerobic_sec(self) -> Optional[float]:
        return self._power_zone_summary().get("low_aerobic_sec")

    @computed_field
    @property
    def intensity_sec(self) -> Optional[float]:
        return self._power_zone_summary().get("intensity_sec")

    @computed_field
    @property
    def intensity_factor(self) -> Optional[float]:
        normalized = self.pwr_normalized_watts
        ftp = self.ftp_watts
        if not normalized or not ftp or ftp <= 0:
            return None
        return round(normalized / ftp, 3)

    @computed_field
    @property
    def tss(self) -> Optional[float]:
        duration = self.duration_sec
        intensity = self.intensity_factor
        if not duration or not intensity:
            return None
        return round((duration / 3600) * (intensity ** 2) * 100, 1)

    @computed_field
    @property
    def ef_first_half(self) -> Optional[float]:
        return self._efficiency_summary().get("ef_first_half")

    @computed_field
    @property
    def ef_second_half(self) -> Optional[float]:
        return self._efficiency_summary().get("ef_second_half")

    @computed_field
    @property
    def ef_overall(self) -> Optional[float]:
        return self._efficiency_summary().get("ef_overall")

    @computed_field
    @property
    def hr_drift_bpm(self) -> Optional[float]:
        return self._efficiency_summary().get("hr_drift_bpm")

    @computed_field
    @property
    def decoupling_pct(self) -> Optional[float]:
        return self._efficiency_summary().get("decoupling_pct")

    @computed_field
    @property
    def efficiency_factor_avg(self) -> Optional[float]:
        return self._efficiency_summary().get("efficiency_factor_avg")

    @computed_field
    @property
    def peak_5s_watts(self) -> Optional[float]:
        return self._best_avg_power(5)

    @computed_field
    @property
    def peak_30s_watts(self) -> Optional[float]:
        return self._best_avg_power(30)

    @computed_field
    @property
    def peak_3min_watts(self) -> Optional[float]:
        return self._best_avg_power(180)

    @computed_field
    @property
    def peak_5min_watts(self) -> Optional[float]:
        return self._best_avg_power(300)

    @computed_field
    @property
    def peak_8min_watts(self) -> Optional[float]:
        return self._best_avg_power(480)

    @computed_field
    @property
    def peak_20min_watts(self) -> Optional[float]:
        return self._best_avg_power(1200)

    @computed_field
    @property
    def peak_60min_watts(self) -> Optional[float]:
        return self._best_avg_power(3600)

    @computed_field
    @property
    def sprint_envelope_score(self) -> Optional[float]:
        ftp = self.ftp_watts
        if not ftp or ftp <= 0:
            return None
        p5 = self.peak_5s_watts
        p30 = self.peak_30s_watts
        if p5 is None or p30 is None:
            return None
        sprint_raw = 0.6 * p5 + 0.4 * p30
        return round(sprint_raw / ftp, 3)

    @computed_field
    @property
    def vo2_envelope_score(self) -> Optional[float]:
        ftp = self.ftp_watts
        if not ftp or ftp <= 0:
            return None
        values = [self.peak_3min_watts, self.peak_5min_watts, self.peak_8min_watts]
        if any(value is None for value in values):
            return None
        vo2_values = np.array([float(value) for value in values if value is not None])
        vo2_raw = float(np.mean(vo2_values))
        return round(vo2_raw / ftp, 3)

    @computed_field
    @property
    def threshold_envelope_score(self) -> Optional[float]:
        ftp = self.ftp_watts
        if not ftp or ftp <= 0:
            return None
        values = [self.peak_20min_watts, self.peak_60min_watts]
        if any(value is None for value in values):
            return None
        threshold_values = np.array([float(value) for value in values if value is not None])
        threshold_raw = float(np.mean(threshold_values))
        return round(threshold_raw / ftp, 3)

    @computed_field
    @property
    def cv_power(self) -> Optional[float]:
        power = self._numeric_series(self.df, "power_watts")
        if power.empty:
            return None
        mean_power = float(power.mean())
        if mean_power <= 0:
            return None
        return round(float(power.std()) / mean_power, 3)

    @computed_field
    @property
    def cv_hr(self) -> Optional[float]:
        hr = self._numeric_series(self.df, "heart_rate_bpm")
        if hr.empty:
            return None
        mean_hr = float(hr.mean())
        if mean_hr <= 0:
            return None
        return round(float(hr.std()) / mean_hr, 3)

    @computed_field
    @property
    def surge_count(self) -> Optional[int]:
        power = self._numeric_series(self.df, "power_watts")
        ftp = self.ftp_watts
        if power.empty or not ftp or ftp <= 0:
            return None
        mask = (power > (ftp * SURGE_THRESHOLD_FACTOR)).to_numpy()
        return self._count_segments(mask, SURGE_MIN_SEC)

    @computed_field
    @property
    def surge_density_per_hr(self) -> Optional[float]:
        duration = self.duration_sec
        count = self.surge_count
        if not duration or not count:
            return None
        return round(count / (duration / 3600), 3)

    @computed_field
    @property
    def pacing_evenness_score(self) -> Optional[float]:
        variability = self.pwr_variability_index
        if not variability or variability <= 0:
            return None
        return round(1 / variability, 3)

    @computed_field
    @property
    def durability_slope(self) -> Optional[float]:
        arrays = self._durability_arrays()
        if arrays is None:
            return None
        elapsed, power, _ = arrays
        slope = self._linear_regression_slope(elapsed, power)
        return round(slope, 5) if slope is not None else None

    @computed_field
    @property
    def fatigue_rate_power(self) -> Optional[float]:
        arrays = self._durability_arrays()
        if arrays is None:
            return None
        _, power, _ = arrays
        duration = self.duration_sec
        rate = self._fatigue_rate_power(power, duration)
        return round(rate, 6) if rate is not None else None

    @computed_field
    @property
    def hr_power_lag_sec(self) -> Optional[int]:
        """Signed cross-correlation lag of HR response to power, τ ∈ [-60, +60] seconds.

        Positive value: HR lags behind power changes (normal physiological response).
        Negative value: HR leads power (e.g., elevated HR before a power drop).
        None if insufficient data (< 10 aligned samples).

        See CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT.md — "HR–Power Lag".
        No abs() is applied; the signed value is contractually correct.
        """
        arrays = self._durability_arrays()
        if arrays is None:
            return None
        _, power, hr_values = arrays
        return self._hr_power_lag_sec(pd.Series(power), pd.Series(hr_values))

    @computed_field
    @property
    def power_curve_watts(self) -> Dict[int, float]:
        power = self._numeric_series(self.df, "power_watts")
        if power.empty:
            return {}
        metrics: Dict[int, float] = {}
        for minutes in [1, 5, 20, 60]:
            best = self._compute_best_avg_power(power, minutes * 60)
            if best is not None:
                metrics[minutes] = best
        return metrics

    @computed_field
    @property
    def intervals(self) -> List[Dict[str, Any]]:
        return self._intervals()

    @computed_field
    @property
    def climbs(self) -> List[Dict[str, Any]]:
        return self._climbs()

    @computed_field
    @property
    def power_curve(self) -> List[Dict[str, Any]]:
        return self._power_curve()

    # ========== Private Helper Methods ==========
    # pylint: disable=missing-function-docstring

    def _timestamps(self) -> pd.Series:
        raw_df = self.__dict__.get("df")
        df = raw_df if isinstance(raw_df, pd.DataFrame) else pd.DataFrame()
        return pd.to_datetime(
            self._timestamp_series(df),
            errors="coerce",
            utc=True,
        ).dropna()

    def _resolve_ftp_watts(self) -> Optional[float]:
        return self._as_float(Config.power_config().ftp_watts)

    def _normalized_power(self, power: pd.Series) -> Optional[float]:
        if power.size < 30:
            return None
        p30 = power.rolling(window=30, min_periods=30).mean().dropna()
        if p30.empty:
            return None
        np_sum = p30.pow(4).mean()
        if np_sum <= 0:
            return None
        return float(np.round(np_sum ** 0.25, 1))

    def _best_avg_power(self, window_sec: int) -> Optional[float]:
        power = self._numeric_series(self.df, "power_watts")
        if power.empty:
            return None
        return self._compute_best_avg_power(power, window_sec)

    def _compute_best_avg_power(self, power: pd.Series, window_sec: int) -> Optional[float]:
        window = int(window_sec)
        if window <= 0 or power.size < window:
            return None
        cumsum = power.cumsum().to_numpy()
        window_sums = cumsum[window - 1 :] - np.concatenate(([0.0], cumsum[:-window]))
        best_avg = float(np.max(window_sums) / window) if window_sums.size else None
        return round(best_avg, 1) if best_avg is not None else None

    def _hr_zone_summary(self) -> Dict[str, Any]:
        hr = self._numeric_series(self.df, "heart_rate_bpm")
        return self._compute_hr_zones_from_series(hr) if not hr.empty else {}

    def _power_zone_summary(self) -> Dict[str, Any]:
        power = self._numeric_series(self.df, "power_watts")
        ftp = self.ftp_watts
        return self._compute_power_zones_from_series(power, ftp_watts=ftp) if not power.empty else {}

    def _efficiency_summary(self) -> Dict[str, Any]:
        duration = self.duration_sec
        if not duration or duration < 1800:
            return {}
        hr = self._numeric_series(self.df, "heart_rate_bpm")
        power = self._numeric_series(self.df, "power_watts")
        if hr.empty or power.empty or len(hr) < 30 or len(power) < 30:
            return {}

        min_len = min(len(hr), len(power))
        hrs = hr.iloc[:min_len]
        pwr = power.iloc[:min_len]
        mid = min_len // 2
        avg_hr_first = float(hrs.iloc[:mid].mean())
        avg_hr_second = float(hrs.iloc[mid:].mean())
        avg_hr_overall = float(hrs.mean())

        if avg_hr_first <= 0 or avg_hr_second <= 0 or avg_hr_overall <= 0:
            return {}

        np_first = self._normalized_power(pwr.iloc[:mid])
        np_second = self._normalized_power(pwr.iloc[mid:])
        np_overall = self._normalized_power(pd.Series(pwr))
        if np_first is None or np_second is None or np_overall is None:
            return {}

        ef_first = np_first / avg_hr_first
        ef_second = np_second / avg_hr_second
        ef_overall = np_overall / avg_hr_overall
        hr_drift = avg_hr_second - avg_hr_first

        metrics = {
            "ef_first_half": round(ef_first, 3),
            "ef_second_half": round(ef_second, 3),
            "ef_overall": round(ef_overall, 3),
            "efficiency_factor_avg": round(ef_overall, 3),
            "hr_drift_bpm": round(hr_drift, 1),
        }
        # Aerobic decoupling: positive = efficiency decline (fatigue), negative = efficiency improvement
        # Formula: ((EF_first / EF_second) - 1) × 100
        if ef_first > 0:
            metrics["decoupling_pct"] = round(((ef_first / ef_second) - 1) * 100, 2)
        return metrics

    def _durability_arrays(self) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        df = self.__dict__.get("df", pd.DataFrame())
        power_col = df.get("power_watts")
        elapsed_col = df.get("elapsed_sec")
        hr_col = df.get("heart_rate_bpm")

        power_raw = pd.to_numeric(power_col, errors="coerce") if power_col is not None else None
        elapsed_raw = pd.to_numeric(elapsed_col, errors="coerce") if elapsed_col is not None else None
        hr_raw = pd.to_numeric(hr_col, errors="coerce") if hr_col is not None else None

        if power_raw is None or elapsed_raw is None:
            return None

        base_mask = power_raw.notna() & elapsed_raw.notna()
        if not base_mask.any():
            return None

        power = power_raw[base_mask].to_numpy(dtype=float)
        elapsed = elapsed_raw[base_mask].to_numpy(dtype=float)
        hr_values = hr_raw[base_mask].to_numpy(dtype=float) if hr_raw is not None else np.array([])
        return elapsed, power, hr_values

    def _intervals(self) -> List[Dict[str, Any]]:
        ftp = self.ftp_watts
        return self._compute_intervals_artifact(self.df, ftp) if ftp else []

    def _climbs(self) -> List[Dict[str, Any]]:
        return self._compute_climbs_artifact(self.df)

    def _power_curve(self) -> List[Dict[str, Any]]:
        power = self._numeric_series(self.df, "power_watts")
        return self._compute_power_curve_artifact(power)

    def _durability_slope(self, elapsed: np.ndarray, power: np.ndarray) -> Optional[float]:
        if elapsed.size < 2 or power.size < 2:
            return None
        return self._linear_regression_slope(elapsed, power)

    def _fatigue_rate_power(self, power: np.ndarray, duration_sec: Optional[float]) -> Optional[float]:
        if not duration_sec or duration_sec <= 0 or power.size < 4:
            return None
        quartile = power.size // 4
        if quartile <= 0:
            return None
        p1 = float(np.mean(power[:quartile]))
        p4 = float(np.mean(power[-quartile:]))
        return (p4 - p1) / duration_sec

    def _as_float(self, value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    def _numeric_series(self, df: pd.DataFrame, column: str) -> pd.Series:
        if column in df:
            return pd.to_numeric(df[column], errors="coerce").dropna()
        return pd.Series(dtype=float)

    def _timestamp_series(self, df: pd.DataFrame) -> pd.Series:
        if "timestamp_utc" in df:
            return df["timestamp_utc"]
        return pd.Series(dtype=DATETIME64_NS)

    @classmethod
    def _compute_hr_zones_from_series(
        cls,
        hr: pd.Series,
    ) -> Dict[str, float | int | str]:
        hr_cfg = Config.hr_config()
        zone_basis = hr_cfg.basis
        hr_rest = hr_cfg.resting_hr_bpm

        if zone_basis == "LTHR":
            ref_bpm = hr_cfg.lthr_bpm
        elif zone_basis == "HRR":
            ref_bpm = hr_cfg.hr_max_bpm
        else:
            ref_bpm = hr_cfg.hr_max_bpm

        if not ref_bpm:
            ref_bpm = float(hr.max()) if not hr.empty else None
        if not ref_bpm:
            return {}

        zones = cls._get_hr_zones(zone_basis, ref_bpm, hr_rest)
        if not zones:
            return {}

        hrs_array = hr.to_numpy(dtype=float)
        zone_bounds = list(zones.values())
        lows = np.array([low for low, _ in zone_bounds], dtype=float)
        highs = np.array([high for _, high in zone_bounds], dtype=float)
        hrs_clamped = np.clip(hrs_array, lows[0], highs[-1])
        bin_indices = np.digitize(hrs_clamped, highs, right=True)
        counts = np.bincount(bin_indices, minlength=len(highs))[:len(highs)]

        metrics: Dict[str, float | int | str] = {}
        total_sec = 0
        for i, (zone_name, (low, high)) in enumerate(zones.items(), 1):
            count = int(counts[i - 1])
            metrics[f"{zone_name}_sec"] = count
            metrics[f"hr_z{i}_low_bpm"] = float(low)
            metrics[f"hr_z{i}_high_bpm"] = float(high)
            total_sec += count

        metrics["hr_zone_total_sec"] = total_sec
        metrics["hr_zone_basis"] = zone_basis
        metrics["hr_zone_reference_bpm"] = float(ref_bpm)
        metrics["hr_zone_model"] = (
            "coggan" if zone_basis == "LTHR" else "karvonen"
        )
        return metrics

    @staticmethod
    def _get_hr_zones(
        zone_basis: str,
        reference_bpm: float,
        hr_rest: Optional[float] = None,
    ) -> Dict[str, tuple]:
        if zone_basis == "HRmax":
            return {
                "hr_z1": (int(reference_bpm * 0.50), int(reference_bpm * 0.60)),
                "hr_z2": (int(reference_bpm * 0.60), int(reference_bpm * 0.70)),
                "hr_z3": (int(reference_bpm * 0.70), int(reference_bpm * 0.80)),
                "hr_z4": (int(reference_bpm * 0.80), int(reference_bpm * 0.90)),
                "hr_z5": (int(reference_bpm * 0.90), int(reference_bpm * 1.00)),
            }
        if zone_basis == "LTHR":
            return {
                "hr_z1": (int(reference_bpm * 0.01), int(reference_bpm * 0.68999)),
                "hr_z2": (int(reference_bpm * 0.69), int(reference_bpm * 0.83999)),
                "hr_z3": (int(reference_bpm * 0.84), int(reference_bpm * 0.94999)),
                "hr_z4": (int(reference_bpm * 0.95), int(reference_bpm * 1.05999)),
                "hr_z5": (int(reference_bpm * 1.06), int(reference_bpm * 2.00)),
            }
        if zone_basis == "HRR":
            rest_hr = hr_rest if hr_rest else 60
            hr_reserve = reference_bpm - rest_hr
            return {
                "hr_z1": (int(hr_reserve * 0.50 + rest_hr), int(hr_reserve * 0.60 + rest_hr)),
                "hr_z2": (int(hr_reserve * 0.60 + rest_hr), int(hr_reserve * 0.70 + rest_hr)),
                "hr_z3": (int(hr_reserve * 0.70 + rest_hr), int(hr_reserve * 0.80 + rest_hr)),
                "hr_z4": (int(hr_reserve * 0.80 + rest_hr), int(hr_reserve * 0.90 + rest_hr)),
                "hr_z5": (int(hr_reserve * 0.90 + rest_hr), int(hr_reserve * 1.00 + rest_hr)),
            }
        return {}

    @classmethod
    def _compute_power_zones_from_series(
        cls,
        power: pd.Series,
        ftp_watts: Optional[float] = None,
    ) -> Dict[str, float | int | str]:
        pwr_cfg = Config.power_config()
        ftp = ftp_watts or pwr_cfg.ftp_watts or 250
        zones = {
            "pwr_z1": (0, int(ftp * 0.55)),
            "pwr_z2": (int(ftp * 0.55), int(ftp * 0.75)),
            "pwr_z3": (int(ftp * 0.75), int(ftp * 0.90)),
            "pwr_z4": (int(ftp * 0.90), int(ftp * 1.05)),
            "pwr_z5": (int(ftp * 1.05), int(ftp * 1.20)),
            "pwr_z6": (int(ftp * 1.20), int(ftp * 1.50)),
            "pwr_z7": (int(ftp * 1.50), 99999),
        }

        powers_array = power.to_numpy(dtype=float)
        zone_bounds = list(zones.values())
        lows = np.array([low for low, _ in zone_bounds], dtype=float)
        highs = np.array([high for _, high in zone_bounds], dtype=float)
        in_range = (powers_array >= lows[0]) & (powers_array <= highs[-1])
        powers_valid = powers_array[in_range]
        if powers_valid.size:
            bin_indices = np.digitize(powers_valid, highs, right=False)
            counts = np.bincount(bin_indices, minlength=len(highs))[:len(highs)]
        else:
            counts = np.zeros(len(highs), dtype=int)

        metrics: Dict[str, float | int | str] = {}
        total_sec = 0
        for i, (zone_name, (low, high)) in enumerate(zones.items(), 1):
            count = int(counts[i - 1])
            metrics[f"{zone_name}_sec"] = count
            metrics[f"pwr_z{i}_low_w"] = float(low)
            metrics[f"pwr_z{i}_high_w"] = float(high if high != 99999 else ftp * 2)
            total_sec += count

        def _num(value: object) -> float:
            return float(value) if isinstance(value, (int, float)) else 0.0

        metrics["pwr_zone_total_sec"] = total_sec
        metrics["low_aerobic_sec"] = (
            _num(metrics.get("pwr_z1_sec")) + _num(metrics.get("pwr_z2_sec"))
        )
        metrics["intensity_sec"] = sum(
            _num(metrics.get(f"pwr_z{i}_sec")) for i in range(4, 8)
        )
        metrics["pwr_zone_model"] = "coggan_7"
        metrics["ftp_watts"] = ftp
        return metrics

    def _find_segments(self, mask: np.ndarray, min_len: int) -> List[tuple[int, int]]:
        if min_len <= 0:
            return []
        true_indices = np.nonzero(mask)[0]
        if true_indices.size == 0:
            return []
        segments: List[tuple[int, int]] = []
        start = int(true_indices[0])
        prev = int(true_indices[0])
        for idx in true_indices[1:]:
            idx = int(idx)
            if idx == prev + 1:
                prev = idx
                continue
            if prev - start + 1 >= min_len:
                segments.append((start, prev))
            start = idx
            prev = idx
        if prev - start + 1 >= min_len:
            segments.append((start, prev))
        return segments

    def _count_segments(self, mask: np.ndarray, min_len: int) -> int:
        return len(self._find_segments(mask, min_len))

    def _linear_regression_slope(self, x_values: np.ndarray, y_values: np.ndarray) -> Optional[float]:
        if x_values.size < 2 or y_values.size < 2:
            return None
        if x_values.size != y_values.size:
            min_len = min(x_values.size, y_values.size)
            x_values = x_values[:min_len]
            y_values = y_values[:min_len]
        if np.all(np.isnan(x_values)) or np.all(np.isnan(y_values)):
            return None
        try:
            slope = np.polyfit(x_values, y_values, 1)[0]
        except (TypeError, ValueError):
            return None
        return float(slope)

    def _hr_power_lag_sec(self, power: pd.Series, hr: pd.Series) -> Optional[int]:
        """Return signed lag τ in seconds that maximises correlation(power_t, shift(hr_t, τ)).

        Searches τ in [-LAG_WINDOW_SEC, +LAG_WINDOW_SEC] (currently [-60, +60]).
        Returns signed int; negative values are valid and must not be suppressed.
        Returns None when fewer than 10 aligned samples are available.
        """
        if power.empty or hr.empty:
            return None
        min_len = min(len(power), len(hr))
        if min_len < 10:
            return None
        power_values = power.to_numpy(dtype=float)[:min_len]
        hr_values = hr.to_numpy(dtype=float)[:min_len]

        power_values = power_values - np.mean(power_values)
        hr_values = hr_values - np.mean(hr_values)

        best_lag = None
        best_corr = -np.inf
        for lag in range(-LAG_WINDOW_SEC, LAG_WINDOW_SEC + 1):
            p_slice, h_slice = self._lagged_slices(
                power_values,
                hr_values,
                lag,
            )
            if p_slice.size < 2 or h_slice.size < 2:
                continue
            corr = np.corrcoef(p_slice, h_slice)[0, 1]
            if np.isnan(corr):
                continue
            if corr > best_corr:
                best_corr = corr
                best_lag = lag
        return int(best_lag) if best_lag is not None else None

    def _lagged_slices(
        self,
        power_values: np.ndarray,
        hr_values: np.ndarray,
        lag: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if lag < 0:
            return power_values[:lag], hr_values[-lag:]
        if lag > 0:
            return power_values[lag:], hr_values[:-lag]
        return power_values, hr_values

    def _compute_intervals_artifact(
        self,
        resampled: pd.DataFrame,
        ftp_watts: Optional[float],
    ) -> List[Dict[str, Any]]:
        if not ftp_watts or ftp_watts <= 0:
            return []

        series = self._interval_series(resampled)
        if series is None:
            return []

        power_arr, hr_arr, elapsed_arr = series
        segments = self._interval_segments(power_arr, ftp_watts)
        return [
            self._interval_summary(power_arr, hr_arr, elapsed_arr, start_idx, end_idx)
            for start_idx, end_idx in segments
        ]

    def _compute_climbs_artifact(
        self,
        resampled: pd.DataFrame,
    ) -> List[Dict[str, Any]]:
        series = self._climb_series(resampled)
        if series is None:
            return []

        grade, power_values, hr_values = series
        segments = self._climb_segments(grade)
        return [
            self._climb_summary(grade, power_values, hr_values, start_idx, end_idx)
            for start_idx, end_idx in segments
        ]

    def _interval_series(
        self,
        resampled: pd.DataFrame,
    ) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        power_col = resampled.get("power_watts")
        elapsed_col = resampled.get("elapsed_sec")
        if power_col is None or elapsed_col is None:
            return None

        power_values = pd.to_numeric(power_col, errors="coerce").to_numpy(dtype=float)
        elapsed_values = pd.to_numeric(elapsed_col, errors="coerce").to_numpy(dtype=float)
        hr_col = resampled.get("heart_rate_bpm")
        hr_values = (
            pd.to_numeric(hr_col, errors="coerce").to_numpy(dtype=float)
            if hr_col is not None
            else np.array([])
        )
        if power_values.size == 0 or elapsed_values.size == 0:
            return None
        return power_values, hr_values, elapsed_values

    def _interval_segments(
        self,
        power_values: np.ndarray,
        ftp_watts: float,
    ) -> List[tuple[int, int]]:
        threshold = ftp_watts * INTERVAL_THRESHOLD_FACTOR
        mask = power_values >= threshold
        return self._find_segments(mask, INTERVAL_MIN_SEC)

    def _interval_summary(
        self,
        power_values: np.ndarray,
        hr_values: np.ndarray,
        elapsed_values: np.ndarray,
        start_idx: int,
        end_idx: int,
    ) -> Dict[str, Any]:
        start_sec = float(elapsed_values[start_idx]) if start_idx < elapsed_values.size else None
        end_sec = float(elapsed_values[end_idx]) if end_idx < elapsed_values.size else None
        duration_sec = int(round(end_sec - start_sec + 1)) if start_sec is not None and end_sec is not None else 0
        power_slice = power_values[start_idx : end_idx + 1]
        peak_power = float(np.nanmax(power_slice)) if power_slice.size else None
        avg_power = float(np.nanmean(power_slice)) if power_slice.size else None
        recovery_slope = self._interval_recovery_slope(hr_values, end_idx)
        return {
            "start_sec": round(start_sec, 1) if start_sec is not None else None,
            "end_sec": round(end_sec, 1) if end_sec is not None else None,
            "duration_sec": duration_sec,
            "avg_power": round(avg_power, 1) if avg_power is not None else None,
            "peak_power": round(peak_power, 1) if peak_power is not None else None,
            "recovery_hr_slope": round(recovery_slope, 4) if recovery_slope is not None else None,
        }

    def _interval_recovery_slope(self, hr_values: np.ndarray, end_idx: int) -> Optional[float]:
        if hr_values.size == 0:
            return None
        recovery_start = end_idx + 1
        recovery_end = min(recovery_start + RECOVERY_HR_WINDOW_SEC, hr_values.size)
        if recovery_end - recovery_start < 2:
            return None
        x_vals = np.arange(recovery_end - recovery_start, dtype=float)
        y_vals = hr_values[recovery_start:recovery_end]
        return self._linear_regression_slope(x_vals, y_vals)

    def _climb_series(
        self,
        resampled: pd.DataFrame,
    ) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        if "distance_m" not in resampled or "elevation_m" not in resampled:
            return None
        distance = pd.to_numeric(resampled["distance_m"], errors="coerce")
        elevation = pd.to_numeric(resampled["elevation_m"], errors="coerce")
        if distance.dropna().size < 2 or elevation.dropna().size < 2:
            return None

        dist_values = distance.to_numpy(dtype=float)
        elev_values = elevation.to_numpy(dtype=float)
        delta_dist = pd.Series(np.diff(dist_values), dtype=float)
        delta_elev = pd.Series(np.diff(elev_values), dtype=float)

        window = max(3, min(CLIMB_GRADE_WINDOW_SEC, len(delta_dist)))
        smooth_dist = delta_dist.rolling(window=window, min_periods=3, center=True).sum()
        smooth_elev = delta_elev.rolling(window=window, min_periods=3, center=True).sum()
        with np.errstate(divide="ignore", invalid="ignore"):
            grade = np.where(smooth_dist.to_numpy(dtype=float) > 0,
                             smooth_elev.to_numpy(dtype=float) / smooth_dist.to_numpy(dtype=float),
                             np.nan)

        power_col = resampled.get("power_watts")
        hr_col = resampled.get("heart_rate_bpm")
        power_values = (
            pd.to_numeric(power_col, errors="coerce").to_numpy(dtype=float)
            if power_col is not None
            else np.array([])
        )
        hr_values = (
            pd.to_numeric(hr_col, errors="coerce").to_numpy(dtype=float)
            if hr_col is not None
            else np.array([])
        )
        return grade, power_values, hr_values

    def _climb_segments(self, grade: np.ndarray) -> List[tuple[int, int]]:
        mask = np.isfinite(grade) & (grade >= CLIMB_MIN_GRADE)
        mask = self._bridge_short_false_gaps(mask, CLIMB_MAX_GAP_SEC)
        return self._find_segments(mask, CLIMB_MIN_SEC)

    def _bridge_short_false_gaps(self, mask: np.ndarray, max_gap: int) -> np.ndarray:
        if max_gap <= 0 or mask.size == 0:
            return mask

        bridged = mask.copy()
        false_indices = np.nonzero(~bridged)[0]
        if false_indices.size == 0:
            return bridged

        gap_start = int(false_indices[0])
        gap_prev = int(false_indices[0])
        for idx in false_indices[1:]:
            idx = int(idx)
            if idx == gap_prev + 1:
                gap_prev = idx
                continue
            self._fill_gap_if_supported(bridged, gap_start, gap_prev, max_gap)
            gap_start = idx
            gap_prev = idx
        self._fill_gap_if_supported(bridged, gap_start, gap_prev, max_gap)
        return bridged

    def _fill_gap_if_supported(
        self,
        mask: np.ndarray,
        start_idx: int,
        end_idx: int,
        max_gap: int,
    ) -> None:
        if start_idx == 0 or end_idx == mask.size - 1:
            return
        if end_idx - start_idx + 1 > max_gap:
            return
        if mask[start_idx - 1] and mask[end_idx + 1]:
            mask[start_idx : end_idx + 1] = True

    def _climb_summary(
        self,
        grade: np.ndarray,
        power_values: np.ndarray,
        hr_values: np.ndarray,
        start_idx: int,
        end_idx: int,
    ) -> Dict[str, Any]:
        segment_grade = grade[start_idx : end_idx + 1]
        avg_grade = float(np.nanmean(segment_grade)) * 100
        power_slice = power_values[start_idx : end_idx + 1]
        avg_power = float(np.nanmean(power_slice)) if power_slice.size else None
        efficiency = self._climb_efficiency(avg_power, hr_values, start_idx, end_idx)
        return {
            "duration": int(end_idx - start_idx + 1),
            "avg_grade": round(avg_grade, 2),
            "avg_power": round(avg_power, 1) if avg_power is not None else None,
            "efficiency_factor": round(efficiency, 3) if efficiency is not None else None,
        }

    def _climb_efficiency(
        self,
        avg_power: Optional[float],
        hr_values: np.ndarray,
        start_idx: int,
        end_idx: int,
    ) -> Optional[float]:
        if avg_power is None or hr_values.size == 0:
            return None
        hr_slice = hr_values[start_idx : end_idx + 1]
        avg_hr = float(np.nanmean(hr_slice)) if hr_slice.size else None
        if avg_hr and avg_hr > 0:
            return avg_power / avg_hr
        return None

    def _compute_power_curve_artifact(self, power: pd.Series) -> List[Dict[str, Any]]:
        if power.empty:
            return []
        curve: List[Dict[str, Any]] = []
        for duration_sec in POWER_CURVE_SECONDS:
            best = self._compute_best_avg_power(power, duration_sec)
            if best is not None:
                curve.append(
                    {
                        "duration_sec": duration_sec,
                        "avg_power_watts": best,
                    }
                )
        return curve
