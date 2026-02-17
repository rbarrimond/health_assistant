"""GPS-based distance and elevation metrics."""

from typing import Optional

from pydantic import BaseModel, Field


class DistanceMetricsModel(BaseModel):
    """GPS-based distance and elevation metrics.
    
    Includes distance, elevation gain/loss, speed, and energy expenditure.
    Always present; GPS-dependent fields may be None for indoor workouts.
    """

    has_gps: bool = Field(default=False, description="Contains GPS coordinates")
    distance_m: Optional[float] = Field(None, ge=0, description="Total distance meters")
    elevation_gain_m: Optional[float] = Field(None, ge=0, description="Total climbing meters")
    elevation_loss_m: Optional[float] = Field(None, ge=0, description="Total descending meters")
    avg_speed_mps: Optional[float] = Field(None, ge=0, description="Average speed m/s")
    max_speed_mps: Optional[float] = Field(None, ge=0, description="Maximum speed m/s")
    calories_kcal: Optional[float] = Field(None, ge=0, description="Total calories burned")
