"""Variability and durability performance metrics."""

from typing import Optional

from pydantic import BaseModel, Field


class VariabilityMetricsModel(BaseModel):
    """Pacing variability and surge analysis.
    
    Measures workout intensity stability:
    - cv_power, cv_hr: Coefficient of variation for power and heart rate
    - surge_count, surge_density_per_hr: Hard effort detection
    - pacing_evenness_score: Overall pacing consistency (0-1, higher = more even)
    
    Optional - requires power and/or heart rate data.
    """

    cv_power: Optional[float] = Field(None, ge=0)
    cv_hr: Optional[float] = Field(None, ge=0)
    surge_count: Optional[int] = Field(None, ge=0)
    surge_density_per_hr: Optional[float] = Field(None, ge=0)
    pacing_evenness_score: Optional[float] = Field(None, ge=0)


class DurabilityMetricsModel(BaseModel):
    """Durability and fatigue metrics over workout duration.
    
    Measures ability to sustain effort:
    - efficiency_factor_avg: Power/HR ratio (overall metabolic efficiency)
    - decoupling_pct: HR-power decoupling between first and second half
    - durability_slope: Power output trend over time
    - fatigue_rate_power: Rate of power decline
    - hr_drift_bpm: Heart rate drift over workout
    - ef_first_half, ef_second_half, ef_overall: Efficiency factor by period
    - hr_power_lag_sec: Signed HR-to-power lag in seconds, τ ∈ [-60, +60].
      Positive = HR lags behind power (normal physiological response).
      Negative = HR leads power (e.g., HR elevated before power drops).
      Search range and sign semantics defined in CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT.md.
    
    Optional - requires both power and heart rate data.
    """

    efficiency_factor_avg: Optional[float] = Field(None, ge=0)
    decoupling_pct: Optional[float] = None
    durability_slope: Optional[float] = None
    fatigue_rate_power: Optional[float] = None
    hr_power_lag_sec: Optional[int] = Field(None, ge=-60, le=60)
    ef_first_half: Optional[float] = Field(None, ge=0)
    ef_second_half: Optional[float] = Field(None, ge=0)
    ef_overall: Optional[float] = Field(None, ge=0)
    hr_drift_bpm: Optional[float] = Field(None, ge=0)
