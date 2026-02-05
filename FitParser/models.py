"""Domain models for parsed FIT workout data using pydantic."""

# pylint: disable=line-too-long

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class DeviceInfo(BaseModel):
    """Device/manufacturer metadata."""

    manufacturer_name: Optional[str] = None


class WorkoutSession(BaseModel):
    """Session-level attributes and summaries."""

    sport: Optional[str] = None
    sub_sport: Optional[str] = None
    apple_workout_type: Optional[str] = None
    workout_name: Optional[str] = None
    is_indoor: Optional[bool] = None

    start_time_utc: Optional[str] = None
    end_time_utc: Optional[str] = None
    timezone: str = "UTC"

    duration_sec: Optional[int] = None
    moving_time_sec: Optional[int] = None

    distance_m: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    elevation_loss_m: Optional[float] = None

    avg_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None

    calories_kcal: Optional[float] = None

    @field_validator("start_time_utc", mode="before")
    @classmethod
    def ensure_utc_suffix(cls, v: Optional[str]) -> Optional[str]:
        """Guarantee ISO timestamps are suffixed with Z for UTC."""
        if v is None:
            return v
        if not v.endswith("Z"):
            return f"{v}Z"
        return v


class RecordSample(BaseModel):
    """Per-sample data points from FIT records."""

    heart_rate: Optional[int] = None
    power: Optional[int] = None
    cadence: Optional[int] = None
    position_lat: Optional[float] = None
    position_long: Optional[float] = None


class Workout(BaseModel):
    """Aggregated workout consisting of session summary, device, and samples."""

    session: WorkoutSession
    device: DeviceInfo = Field(default_factory=DeviceInfo)
    records: List[RecordSample] = Field(default_factory=list)


# ============================================================================
# METRICS MODELS - For parsed FIT file output
# ============================================================================


class SessionMetricsModel(BaseModel):
    """Session-level metrics (duration, distance, sport type)."""

    sport: Optional[str] = Field(None, description="Sport type (e.g., 'cycling', 'running')")
    sub_sport: Optional[str] = Field(None, description="Sub-sport variant")
    apple_workout_type: Optional[str] = Field(None, description="Apple Watch workout type (e.g., 'Functional Strength Training')")
    workout_name: Optional[str] = Field(None, description="User-defined workout name")
    device_name: Optional[str] = Field(None, description="Device manufacturer")
    is_indoor: Optional[bool] = Field(None, description="Indoor vs outdoor")
    start_time_utc: Optional[str] = Field(None, description="ISO 8601 UTC start time")
    end_time_utc: Optional[str] = Field(None, description="ISO 8601 UTC end time")
    timezone: str = Field(default="UTC", description="Timezone of workout")
    duration_sec: Optional[float] = Field(None, ge=0, description="Total elapsed time seconds")
    moving_time_sec: Optional[float] = Field(None, ge=0, description="Active movement seconds")


class SampleMetricsModel(BaseModel):
    """Sample-based metrics (HR, power, cadence aggregates)."""

    # Heart rate
    hr_avg_bpm: Optional[float] = Field(None, ge=0, le=300, description="Average HR")
    hr_max_bpm: Optional[float] = Field(None, ge=0, le=300, description="Maximum HR")
    hr_samples_count: int = Field(
        default=0, ge=0, description="Valid HR samples"
    )
    hr_missing_pct: Optional[float] = Field(
        None, ge=0, le=100, description="Percent missing HR data"
    )

    # Power
    pwr_avg_watts: Optional[float] = Field(None, ge=0, description="Average power")
    pwr_max_watts: Optional[float] = Field(None, ge=0, description="Maximum power")
    pwr_normalized_watts: Optional[float] = Field(None, ge=0, description="Normalized power (NP)")
    pwr_variability_index: Optional[float] = Field(None, ge=1.0, description="VI = NP / avg (≥1.0)")
    pwr_samples_count: int = Field(default=0, ge=0, description="Valid power samples")
    pwr_missing_pct: Optional[float] = Field(None, ge=0, le=100, description="Percent missing power data")

    # Cadence
    cad_avg_rpm: Optional[float] = Field(None, ge=0, description="Average cadence")
    cad_max_rpm: Optional[float] = Field(None, ge=0, description="Maximum cadence")
    cad_samples_count: int = Field(default=0, ge=0, description="Valid cadence samples")


class DistanceMetricsModel(BaseModel):
    """Distance and elevation metrics."""

    has_gps: bool = Field(default=False, description="Contains GPS coordinates")
    distance_m: Optional[float] = Field(None, ge=0, description="Total distance meters")
    elevation_gain_m: Optional[float] = Field(None, ge=0, description="Total climbing meters")
    elevation_loss_m: Optional[float] = Field(None, ge=0, description="Total descending meters")
    avg_speed_ms: Optional[float] = Field(None, ge=0, description="Average speed m/s")
    max_speed_ms: Optional[float] = Field(None, ge=0, description="Maximum speed m/s")
    calories: Optional[float] = Field(None, ge=0, description="Total calories burned")


class HRZonesModel(BaseModel):
    """Heart rate zone metrics."""

    hr_zone_basis: str = Field(description="Zone calculation method (max|lthr|hrr)")
    hr_zone_reference_bpm: float = Field(gt=0, description="Reference BPM for zone calc")
    hr_z1_sec: float = Field(default=0, ge=0)
    hr_z1_min: float = Field(default=0, ge=0)
    hr_z2_sec: float = Field(default=0, ge=0)
    hr_z2_min: float = Field(default=0, ge=0)
    hr_z3_sec: float = Field(default=0, ge=0)
    hr_z3_min: float = Field(default=0, ge=0)
    hr_z4_sec: float = Field(default=0, ge=0)
    hr_z4_min: float = Field(default=0, ge=0)
    hr_z5_sec: float = Field(default=0, ge=0)
    hr_z5_min: float = Field(default=0, ge=0)
    hr_zone_total_sec: float = Field(default=0, ge=0)


class PowerZonesModel(BaseModel):
    """Power zone metrics (Coggan 7-zone)."""

    pwr_zone_model: str = Field(default="coggan_7")
    ftp_watts: float = Field(gt=0, description="Functional threshold power")
    pwr_z1_sec: float = Field(default=0, ge=0)
    pwr_z1_min: float = Field(default=0, ge=0)
    pwr_z2_sec: float = Field(default=0, ge=0)
    pwr_z2_min: float = Field(default=0, ge=0)
    pwr_z3_sec: float = Field(default=0, ge=0)
    pwr_z3_min: float = Field(default=0, ge=0)
    pwr_z4_sec: float = Field(default=0, ge=0)
    pwr_z4_min: float = Field(default=0, ge=0)
    pwr_z5_sec: float = Field(default=0, ge=0)
    pwr_z5_min: float = Field(default=0, ge=0)
    pwr_z6_sec: float = Field(default=0, ge=0)
    pwr_z6_min: float = Field(default=0, ge=0)
    pwr_z7_sec: float = Field(default=0, ge=0)
    pwr_z7_min: float = Field(default=0, ge=0)
    low_aerobic_min: float = Field(default=0, ge=0)
    intensity_min: float = Field(default=0, ge=0)


class WorkoutMetricsModel(BaseModel):
    """Complete workout metrics output."""

    physiometrics_snapshot_timestamp: str = Field(description="ISO 8601 UTC timestamp")
    session: SessionMetricsModel
    samples: SampleMetricsModel
    distance: DistanceMetricsModel
    zones_hr: Optional[HRZonesModel] = None
    zones_power: Optional[PowerZonesModel] = None
    aerobic_efficiency_mphb: Optional[float] = Field(None, ge=0)
    hr_resting_bpm: Optional[float] = Field(None, ge=0, le=300)


# ============================================================================
# AGENT MEMORY MODELS - For external memory storage
# ============================================================================


class AgentPreferences(BaseModel):
    """User preferences and training context for the agent."""

    athlete_id: str = Field(description="Athlete identifier")
    current_goal: Optional[str] = Field(
        None, description="Current training goal or race target"
    )
    training_phase: Optional[str] = Field(
        None, description="Current training phase (e.g., 'base-building', 'build', 'peak', 'recovery')"
    )
    preferred_sports: List[str] = Field(
        default_factory=list, description="Preferred sports in priority order"
    )
    ftp_test_frequency_weeks: Optional[int] = Field(
        None, description="How often to prompt for FTP testing"
    )
    last_ftp_test_date: Optional[str] = Field(
        None, description="ISO 8601 date of last FTP test"
    )
    notes: Optional[str] = Field(
        None, description="Free-form context notes"
    )
    updated_at: Optional[str] = Field(
        None, description="ISO 8601 UTC timestamp of last update"
    )


class AgentObservation(BaseModel):
    """Agent observations and flags for future reference."""

    athlete_id: str = Field(description="Athlete identifier")
    observation_id: str = Field(description="Unique observation identifier")
    category: str = Field(
        description="Observation category (e.g., 'pattern', 'flag', 'insight')"
    )
    summary: str = Field(description="Brief observation summary")
    details: Optional[str] = Field(None, description="Detailed observation context")
    referenced_workout_ids: List[str] = Field(
        default_factory=list, description="Related workout IDs"
    )
    priority: str = Field(
        default="normal", description="Priority level: low, normal, high"
    )
    status: str = Field(
        default="active", description="Status: active, resolved, archived"
    )
    created_at: str = Field(description="ISO 8601 UTC timestamp")
    expires_at: Optional[str] = Field(
        None, description="ISO 8601 UTC timestamp when observation expires"
    )
