"""Session-level metadata for workouts."""
# pylint: disable=line-too-long

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SessionMetricsModel(BaseModel):
    """Core workout session metadata.
    
    Basic identification and timing information for a workout. Always present
    in WorkoutMetricsModel output.
    """

    sport: Optional[str] = Field(None, description="Sport type (e.g., 'cycling', 'running')")
    sub_sport: Optional[str] = Field(None, description="Sub-sport variant")
    apple_workout_type: Optional[str] = Field(None, description="Apple Watch workout type (e.g., 'Functional Strength Training')")
    workout_name: Optional[str] = Field(None, description="User-defined workout name")
    device_name: Optional[str] = Field(None, description="Device manufacturer")
    is_indoor: Optional[bool] = Field(None, description="Indoor vs outdoor")
    start_time_utc: Optional[str] = Field(None, description="ISO 8601 UTC start time")
    local_tz_offset: Optional[str] = Field(
        None,
        description="Local wall-clock UTC offset (for example, 'UTC-05:00')",
    )
    timezone: Optional[str] = Field(
        None,
        description="Canonical timezone (IANA preferred, falls back to local_tz_offset when unresolved)",
    )
    duration_sec: Optional[float] = Field(None, ge=0, description="Total elapsed time seconds")
    moving_time_sec: Optional[float] = Field(None, ge=0, description="Active movement seconds")
    enrichment: Optional[Dict[str, Any]] = Field(
        None,
        description="Raw `metadata.json.enrichment` payload for direct workout inspection",
    )
