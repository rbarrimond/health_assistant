"""Telemetry sample aggregates for heart rate, power, and cadence."""

from typing import Optional

from pydantic import BaseModel, Field


class SampleMetricsModel(BaseModel):
    """Telemetry sample aggregates for heart rate, power, and cadence.
    
    Provides averages, maximums, sample counts, and data quality metrics.
    Always present; individual fields may be None if telemetry unavailable.
    """

    # Heart rate
    hr_avg_bpm: Optional[float] = Field(None, ge=0, le=300, description="Average HR")
    hr_max_bpm: Optional[float] = Field(None, ge=0, le=300, description="Maximum HR")
    hr_min_bpm: Optional[float] = Field(None, ge=0, le=300, description="Minimum HR")
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
