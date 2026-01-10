from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, field_validator


class DeviceInfo(BaseModel):
    manufacturer_name: Optional[str] = None


class WorkoutSession(BaseModel):
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
        if v is None:
            return v
        # Ensure we return an ISO string with trailing Z for UTC
        if not v.endswith("Z"):
            return f"{v}Z"
        return v


class RecordSample(BaseModel):
    heart_rate: Optional[int] = None
    power: Optional[int] = None
    cadence: Optional[int] = None
    position_lat: Optional[float] = None
    position_long: Optional[float] = None


class Workout(BaseModel):
    session: WorkoutSession
    device: DeviceInfo = DeviceInfo()
    records: List[RecordSample] = []
