"""Training load and power-duration metrics."""

from typing import Dict, Optional

from pydantic import BaseModel, Field


class TrainingLoadMetricsModel(BaseModel):
    """Training load metrics: Intensity Factor and TSS.
    
    - intensity_factor: Normalized Power / FTP
    - tss: Training Stress Score (Coggan formula)
    
    Optional - only present if power data and FTP available.
    """

    intensity_factor: Optional[float] = Field(None, ge=0)
    tss: Optional[float] = Field(None, ge=0)


class PowerDurationAnchorsModel(BaseModel):
    """Peak power at standard durations for power curve analysis.
    
    Captures maximum sustained power for key durations: 5s (sprint), 30s (anaerobic),
    3/5/8min (VO2max), 20/60min (threshold/FTP). Optional power_curve_watts provides
    full curve at 1-second resolution up to workout duration.
    
    Optional - only present if power data available.
    """

    peak_5s_watts: Optional[float] = Field(None, ge=0)
    peak_30s_watts: Optional[float] = Field(None, ge=0)
    peak_3min_watts: Optional[float] = Field(None, ge=0)
    peak_5min_watts: Optional[float] = Field(None, ge=0)
    peak_8min_watts: Optional[float] = Field(None, ge=0)
    peak_20min_watts: Optional[float] = Field(None, ge=0)
    peak_60min_watts: Optional[float] = Field(None, ge=0)
    power_curve_watts: Optional[Dict[int, float]] = None


class EnvelopeScoresModel(BaseModel):
    """Physiological envelope capability scores across energy systems.
    
    Scores workout load distribution across:
    - sprint_envelope_score: Anaerobic/neuromuscular (5-30s efforts)
    - vo2_envelope_score: VO2max system (3-8min efforts)
    - threshold_envelope_score: Lactate threshold (20-60min efforts)
    
    Higher scores indicate more stress in that energy system.
    Optional - only present if power data available.
    """

    sprint_envelope_score: Optional[float] = Field(None, ge=0)
    vo2_envelope_score: Optional[float] = Field(None, ge=0)
    threshold_envelope_score: Optional[float] = Field(None, ge=0)
