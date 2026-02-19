"""Original parsed workout structures (Legacy API).

Deprecated: these models are retained for backward compatibility during the
fitdecode migration and artifact-first ingestion refactor. Prefer canonical
substrate models and artifact payloads.
"""

# pylint: disable=arguments-differ

from datetime import datetime, timezone
import warnings
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class DeviceInfo(BaseModel):
    """Device/manufacturer metadata."""

    def model_post_init(self, __context) -> None:
        warnings.warn(
            "DeviceInfo is deprecated; prefer canonical substrate metadata.",
            DeprecationWarning,
            stacklevel=2,
        )

    manufacturer_name: Optional[str] = None


class WorkoutSession(BaseModel):
    """Session-level attributes and summaries."""

    def model_post_init(self, __context) -> None:
        warnings.warn(
            "WorkoutSession is deprecated; prefer canonical metadata artifacts.",
            DeprecationWarning,
            stacklevel=2,
        )

    sport: Optional[str] = None
    sub_sport: Optional[str] = None
    apple_workout_type: Optional[str] = None
    workout_name: Optional[str] = None
    is_indoor: Optional[bool] = None

    start_time_utc: Optional[str] = None
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
        """Normalize ISO timestamps to use UTC offsets instead of Z."""
        if v is None:
            return v
        value = str(v)
        if value.endswith("Z"):
            return f"{value[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc).isoformat()
        return value


class RecordSample(BaseModel):
    """Per-sample data points from FIT records."""

    def model_post_init(self, __context) -> None:
        warnings.warn(
            "RecordSample is deprecated; prefer canonical record substrate.",
            DeprecationWarning,
            stacklevel=2,
        )

    heart_rate: Optional[int] = None
    power: Optional[int] = None
    cadence: Optional[int] = None
    position_lat: Optional[float] = None
    position_long: Optional[float] = None


class Workout(BaseModel):
    """Aggregated workout consisting of session summary, device, and samples."""

    def model_post_init(self, __context) -> None:
        warnings.warn(
            "Workout is deprecated; prefer canonical substrate and artifacts.",
            DeprecationWarning,
            stacklevel=2,
        )

    session: WorkoutSession
    device: DeviceInfo = Field(default_factory=DeviceInfo)
    records: List[RecordSample] = Field(default_factory=list)
