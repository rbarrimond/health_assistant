"""Structured artifacts for intervals, climbs, and power curve."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class StructuredArtifactsModel(BaseModel):
    """Structured JSON artifacts for intervals, climbs, and power curve.
    
    Stores detailed structures as JSON/dict lists for:
    - intervals_json: Detected work/rest intervals with metrics
    - climbs_json: Detected climbs with gradient and VAM
    - power_curve_json: Full power-duration curve data
    
    Optional - presence depends on workout characteristics and data availability.
    """

    intervals: Optional[List[Dict[str, Any]]] = None
    climbs: Optional[List[Dict[str, Any]]] = None
    power_curve: Optional[List[Dict[str, Any]]] = None
