"""Heart rate and power zone distribution models."""

from typing import Optional

from pydantic import BaseModel, Field


class HRZonesModel(BaseModel):
    """Heart rate zone distribution with boundaries and aggregates.
    
    Provides time-in-zone for 5 zones, zone boundaries (low/high BPM), and the
    reference model (e.g., 'lthr', 'max_hr'). Optional - only present if HR data available.
    """

    hr_zone_model: Optional[str] = Field(None, description="Zone model name")
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
    hr_z1_low_bpm: Optional[float] = Field(None, ge=0)
    hr_z1_high_bpm: Optional[float] = Field(None, ge=0)
    hr_z2_low_bpm: Optional[float] = Field(None, ge=0)
    hr_z2_high_bpm: Optional[float] = Field(None, ge=0)
    hr_z3_low_bpm: Optional[float] = Field(None, ge=0)
    hr_z3_high_bpm: Optional[float] = Field(None, ge=0)
    hr_z4_low_bpm: Optional[float] = Field(None, ge=0)
    hr_z4_high_bpm: Optional[float] = Field(None, ge=0)
    hr_z5_low_bpm: Optional[float] = Field(None, ge=0)
    hr_z5_high_bpm: Optional[float] = Field(None, ge=0)
    hr_zone_total_sec: float = Field(default=0, ge=0)


class PowerZonesModel(BaseModel):
    """Power zone distribution with boundaries and aggregates.
    
    Provides time-in-zone for 7 zones (Coggan model), zone boundaries (low/high watts),
    and derived aggregates (low aerobic time, intensity time). Optional - only present
    if power data and FTP available.
    """

    pwr_zone_model: str = Field(default="coggan_7")
    ftp_watts: float = Field(gt=0, description="Functional threshold power")
    pwr_z1_sec: float = Field(default=0, ge=0)
    pwr_z2_sec: float = Field(default=0, ge=0)
    pwr_z3_sec: float = Field(default=0, ge=0)
    pwr_z4_sec: float = Field(default=0, ge=0)
    pwr_z5_sec: float = Field(default=0, ge=0)
    pwr_z6_sec: float = Field(default=0, ge=0)
    pwr_z7_sec: float = Field(default=0, ge=0)
    pwr_z1_low_w: Optional[float] = Field(None, ge=0)
    pwr_z1_high_w: Optional[float] = Field(None, ge=0)
    pwr_z2_low_w: Optional[float] = Field(None, ge=0)
    pwr_z2_high_w: Optional[float] = Field(None, ge=0)
    pwr_z3_low_w: Optional[float] = Field(None, ge=0)
    pwr_z3_high_w: Optional[float] = Field(None, ge=0)
    pwr_z4_low_w: Optional[float] = Field(None, ge=0)
    pwr_z4_high_w: Optional[float] = Field(None, ge=0)
    pwr_z5_low_w: Optional[float] = Field(None, ge=0)
    pwr_z5_high_w: Optional[float] = Field(None, ge=0)
    pwr_z6_low_w: Optional[float] = Field(None, ge=0)
    pwr_z6_high_w: Optional[float] = Field(None, ge=0)
    pwr_z7_low_w: Optional[float] = Field(None, ge=0)
    pwr_z7_high_w: Optional[float] = Field(None, ge=0)
    pwr_zone_total_sec: Optional[float] = Field(None, ge=0)
    low_aerobic_sec: Optional[float] = Field(None, ge=0)
    intensity_sec: Optional[float] = Field(None, ge=0)
