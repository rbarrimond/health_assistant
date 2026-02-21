"""Canonical substrate models for 1 Hz time-series and lap data.

These models define the schema for Parquet-stored canonical workout data.
All analytics are computed from this substrate by CanonicalAnalyticsEngine.
"""

from typing import Optional

from pydantic import BaseModel, Field

from .constants import ISO_8601_UTC_DESC


class CanonicalRecord(BaseModel):
    """1 Hz time-series record for canonical substrate.

    This is the primary storage format for workout telemetry at 1 Hz resolution.
    Stored in Parquet format for efficient querying. All analytics are computed
    from this canonical substrate by CanonicalAnalyticsEngine.

    Core telemetry: power_watts, heart_rate_bpm, cadence_rpm, speed_mps
    Extended telemetry: distance_m, elevation_m, temperature_c,
    respiration_rate_brpm, lr_balance_pct, rr_interval_sec
    """

    timestamp_utc: str = Field(description=ISO_8601_UTC_DESC)
    elapsed_sec: Optional[float] = Field(None, ge=0)
    power_watts: Optional[float] = Field(None, ge=0)
    heart_rate_bpm: Optional[float] = Field(None, ge=0)
    cadence_rpm: Optional[float] = Field(None, ge=0)
    speed_mps: Optional[float] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)
    elevation_m: Optional[float] = Field(None)
    temperature_c: Optional[float] = Field(None)
    respiration_rate_brpm: Optional[float] = Field(None, ge=0)
    lr_balance_pct: Optional[float] = Field(None, ge=0, le=100)
    rr_interval_sec: Optional[float] = Field(None, ge=0)


class CanonicalLap(BaseModel):
    """Lap-level summary record for canonical substrate.

    Deprecated: prefer laps.json artifacts for lap payloads.
    Stores lap summaries in Parquet format for querying multi-lap workouts.
    Complements CanonicalRecord time-series data with segment-level aggregates.
    """

    lap_index: int = Field(ge=0)
    start_time_utc: Optional[str] = Field(None, description=ISO_8601_UTC_DESC)
    elapsed_sec: Optional[float] = Field(None, ge=0)
    moving_time_sec: Optional[float] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)
    calories_kcal: Optional[float] = Field(None, ge=0)
    avg_heart_rate_bpm: Optional[float] = Field(None, ge=0)
    max_heart_rate_bpm: Optional[float] = Field(None, ge=0)
    avg_power_watts: Optional[float] = Field(None, ge=0)
    max_power_watts: Optional[float] = Field(None, ge=0)
    avg_cadence_rpm: Optional[float] = Field(None, ge=0)
    max_cadence_rpm: Optional[float] = Field(None, ge=0)
