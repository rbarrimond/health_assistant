"""Domain models for parsed FIT workout data using pydantic."""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class DeviceInfo(BaseModel):
    """Device/manufacturer metadata."""

    manufacturer_name: Optional[str] = None


class WorkoutSession(BaseModel):
    """Session-level attributes and summaries."""

    sport: Optional[str] = None
    sub_sport: Optional[str] = None
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
