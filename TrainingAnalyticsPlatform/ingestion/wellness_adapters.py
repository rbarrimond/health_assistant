"""Source adapters for wellness data ingestion.

Base classes and protocols for converting raw API responses to canonical
PhysiometricsSnapshot. Follows the BaseFitModel pattern for extensibility.
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from pydantic import ValidationError

from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot

logger = logging.getLogger(__name__)


class AdapterError(Exception):
    """Base exception for adapter errors."""

    pass


class BaseWellnessSourceAdapter(ABC):
    """Abstract base for wellness source adapters (Withings, Garmin, Intervals)."""

    @abstractmethod
    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse raw API response to intermediate dict.
        
        Args:
            raw_data: Raw API response
            
        Returns:
            Parsed intermediate dict
        """
        pass

    @abstractmethod
    def validate_semantic_contract(self, parsed: Dict[str, Any]) -> None:
        """Validate parsed data against source-specific contracts.
        
        Args:
            parsed: Parsed intermediate dict
            
        Raises:
            AdapterError: If contract violations found
        """
        pass

    @abstractmethod
    def map_to_canonical(
        self, parsed: Dict[str, Any], athlete_id: str
    ) -> PhysiometricsSnapshot:
        """Map parsed data to canonical physiometrics snapshot.
        
        Args:
            parsed: Parsed intermediate dict
            athlete_id: Athlete identifier
            
        Returns:
            PhysiometricsSnapshot
        """
        pass

    def adapt(
        self, raw_data: Dict[str, Any], athlete_id: str
    ) -> PhysiometricsSnapshot:
        """Full pipeline: parse → validate → map.
        
        Args:
            raw_data: Raw API response
            athlete_id: Athlete identifier
            
        Returns:
            Canonical snapshot
        """
        try:
            parsed = self._do_parse(raw_data)
            self.validate_semantic_contract(parsed)
            return self.map_to_canonical(parsed, athlete_id)
        except ValidationError as e:
            raise AdapterError(f"Validation failed: {e}") from e


class WithingsPhysiometricsAdapter(BaseWellnessSourceAdapter):
    """Converts Withings OpenAPI measure.get_meas responses."""

    REQUIRED_FIELDS = ["date", "measures"]

    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract measuregrps and measures."""
        body = raw_data.get("body", {})
        measuregrps = body.get("measuregrps", [])

        if not measuregrps:
            raise AdapterError("No measuregrps in Withings response")

        # Use first measurement group
        grp = measuregrps[0]
        date_unix = grp.get("date")
        measures = grp.get("measures", [])

        return {"date": date_unix, "measures": measures}

    def validate_semantic_contract(self, parsed: Dict[str, Any]) -> None:
        """Validate contract: require date and measures."""
        for field in self.REQUIRED_FIELDS:
            if field not in parsed:
                raise AdapterError(f"Missing required field: {field}")

        # Validate weight is reasonable (> 20 kg)
        for measure in parsed.get("measures", []):
            if measure.get("type") == 1:  # Weight
                value = measure.get("value", 0)
                unit = measure.get("unit", 0)
                # unit=-3 means divide by 10^3 (kg)
                weight_kg = value / (10 ** abs(unit)) if unit else value
                if weight_kg < 20 or weight_kg > 300:
                    raise AdapterError(f"Weight sanity check failed: {weight_kg} kg")

    def map_to_canonical(
        self, parsed: Dict[str, Any], athlete_id: str
    ) -> PhysiometricsSnapshot:
        """Map Withings measures to PhysiometricsSnapshot."""
        # Extract date
        date_unix = parsed.get("date")
        if date_unix:
            date_obj = datetime.fromtimestamp(date_unix, tz=timezone.utc)
        else:
            date_obj = datetime.now(timezone.utc)

        effective_date = date_obj.date().isoformat()

        # Map measures by type
        weight_kg = None
        fat_mass_kg = None
        body_fat_pct = None
        muscle_mass_kg = None
        bone_mass_kg = None

        for measure in parsed.get("measures", []):
            mtype = measure.get("type")
            value = measure.get("value", 0)
            unit = measure.get("unit", 0)

            # Apply unit scaling
            if unit < 0:
                scaled_value = value / (10 ** abs(unit))
            else:
                scaled_value = value

            if mtype == 1:  # Weight
                weight_kg = scaled_value
            elif mtype == 5:  # Fat mass
                fat_mass_kg = scaled_value
            elif mtype == 6:  # Body fat
                body_fat_pct = scaled_value
            elif mtype == 7:  # Muscle mass
                muscle_mass_kg = scaled_value
            elif mtype == 11:  # Bone mass
                bone_mass_kg = scaled_value

        return PhysiometricsSnapshot(
            athlete_id=athlete_id,
            effective_date=effective_date,
            weight_kg=weight_kg,
            fat_mass_kg=fat_mass_kg,
            body_fat_pct=body_fat_pct,
            muscle_mass_kg=muscle_mass_kg,
            bone_mass_kg=bone_mass_kg,
            visceral_fat_index=None,
            metabolic_age_years=None,
            hrv_ln_rmssd=None,
            resting_hr_bpm=None,
            sleep_duration_min=None,
            ftp_watts=None,
            cycling_vo2max_ml_kg_min=None,
            hr_lthr_bpm=None,
            hr_max_bpm=None,
            load=None,
            readiness_score=None,
            # Extended wellness fields (not from Withings)
            soreness=None,
            fatigue=None,
            stress=None,
            mood=None,
            motivation=None,
            injury=None,
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            steps=None,
            abdomen_cm=None,
            sport_info=None,
            data_sources="withings",
            measured_at_utc=date_obj,
        )


class GarminTrainingStateAdapter(BaseWellnessSourceAdapter):
    """Converts Garmin Connect API userSummary responses."""

    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract from nested stats structure."""
        stats = raw_data.get("stats", {})
        return {
            "ftp": stats.get("functionThreshold"),
            "vo2max_cycling": stats.get("vo2MaxCycling", {}).get("value"),
            "max_hr": stats.get("maxHeartRate"),
            "resting_hr": stats.get("restingHeartRate"),
            "readiness": stats.get("readiness", {}).get("score"),
        }

    def validate_semantic_contract(self, parsed: Dict[str, Any]) -> None:
        """Validate ranges: FTP 150-400W, VO2Max 30-100."""
        ftp = parsed.get("ftp")
        if ftp and (ftp < 150 or ftp > 400):
            raise AdapterError(f"FTP out of range: {ftp}")

        vo2max = parsed.get("vo2max_cycling")
        if vo2max and (vo2max < 30 or vo2max > 100):
            raise AdapterError(f"VO2Max out of range: {vo2max}")

    def map_to_canonical(
        self, parsed: Dict[str, Any], athlete_id: str
    ) -> PhysiometricsSnapshot:
        """Map to PhysiometricsSnapshot."""
        # Estimate LTHR as 85% of max HR
        max_hr = parsed.get("max_hr")
        lthr = int(max_hr * 0.85) if max_hr else None

        return PhysiometricsSnapshot(
            athlete_id=athlete_id,
            effective_date=datetime.now(timezone.utc).date().isoformat(),
            weight_kg=None,
            fat_mass_kg=None,
            body_fat_pct=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            visceral_fat_index=None,
            metabolic_age_years=None,
            hrv_ln_rmssd=None,
            resting_hr_bpm=parsed.get("resting_hr"),
            sleep_duration_min=None,
            ftp_watts=parsed.get("ftp"),
            cycling_vo2max_ml_kg_min=parsed.get("vo2max_cycling"),
            hr_lthr_bpm=lthr,
            hr_max_bpm=max_hr,
            load=None,
            readiness_score=parsed.get("readiness"),
            # Extended wellness fields (not from Garmin)
            soreness=None,
            fatigue=None,
            stress=None,
            mood=None,
            motivation=None,
            injury=None,
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            steps=None,
            abdomen_cm=None,
            sport_info=None,
            data_sources="garmin",
            measured_at_utc=None,
        )


class IntervalsPhysiometricsAdapter(BaseWellnessSourceAdapter):
    """Converts Intervals.icu API responses."""

    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract wellness fields with compatibility aliases."""
        sleep_minutes = raw_data.get("sleep")
        sleep_secs = raw_data.get("sleepSecs")
        if sleep_minutes is None and isinstance(sleep_secs, (int, float)):
            sleep_minutes = sleep_secs / 60.0

        return {
            "date": raw_data.get("id") or raw_data.get("date"),
            "hrv": raw_data.get("hrvRMSSD") or raw_data.get("hrv"),  # Already ln(RMSSD)
            "rhr": raw_data.get("restingHR") if raw_data.get("restingHR") is not None else raw_data.get("rhr"),
            "sleep": sleep_minutes,
            "readiness": raw_data.get("readiness"),
            # Subjective wellness
            "soreness": raw_data.get("soreness"),
            "fatigue": raw_data.get("fatigue"),
            "stress": raw_data.get("stress"),
            "mood": raw_data.get("mood"),
            "motivation": raw_data.get("motivation"),
            "injury": raw_data.get("injury"),
            # Nutrition
            "calories_kcal": raw_data.get("kcalConsumed"),
            "carbs_g": raw_data.get("carbohydrates"),
            "protein_g": raw_data.get("protein"),
            "fat_g": raw_data.get("fatTotal"),
            # Activity & body
            "steps": raw_data.get("steps"),
            "abdomen_cm": raw_data.get("abdomen"),
            # Nested sport metrics (pass through)
            "sport_info": raw_data.get("sportInfo"),
        }

    def validate_semantic_contract(self, parsed: Dict[str, Any]) -> None:
        """Validate: at least one field present (original or extended wellness)."""
        # Original core wellness fields
        core_fields = ["hrv", "rhr", "sleep", "readiness"]
        # Extended wellness fields (v2.1.0+): subjective, nutrition, activity, body
        extended_fields = [
            "soreness", "fatigue", "stress", "mood", "motivation", "injury",
            "calories_kcal", "carbs_g", "protein_g", "fat_g",
            "steps", "abdomen_cm", "sport_info"
        ]
        # Accept measurement if ANY core or extended field is present
        all_fields = core_fields + extended_fields
        if not any(parsed.get(f) is not None for f in all_fields):
            raise AdapterError("No core or extended wellness metrics in Intervals response")

    def map_to_canonical(
        self, parsed: Dict[str, Any], athlete_id: str
    ) -> PhysiometricsSnapshot:
        """Map to PhysiometricsSnapshot."""
        date = parsed.get("date", datetime.now(timezone.utc).date().isoformat())

        return PhysiometricsSnapshot(
            athlete_id=athlete_id,
            effective_date=date,
            weight_kg=None,
            fat_mass_kg=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            body_fat_pct=None,
            visceral_fat_index=None,
            metabolic_age_years=None,
            hrv_ln_rmssd=parsed.get("hrv"),
            resting_hr_bpm=parsed.get("rhr"),
            sleep_duration_min=parsed.get("sleep"),
            ftp_watts=None,
            cycling_vo2max_ml_kg_min=None,
            hr_lthr_bpm=None,
            hr_max_bpm=None,
            load=None,
            readiness_score=parsed.get("readiness"),
            soreness=parsed.get("soreness"),
            fatigue=parsed.get("fatigue"),
            stress=parsed.get("stress"),
            mood=parsed.get("mood"),
            motivation=parsed.get("motivation"),
            injury=parsed.get("injury"),
            calories_kcal=parsed.get("calories_kcal"),
            carbs_g=parsed.get("carbs_g"),
            protein_g=parsed.get("protein_g"),
            fat_g=parsed.get("fat_g"),
            steps=parsed.get("steps"),
            abdomen_cm=parsed.get("abdomen_cm"),
            sport_info=parsed.get("sport_info"),
            data_sources="intervals",
            measured_at_utc=None,
        )


def create_wellness_adapter(source_name: str) -> BaseWellnessSourceAdapter:
    """Factory: create appropriate adapter by source name.
    
    Args:
        source_name: Source identifier (withings, garmin, intervals)
        
    Returns:
        Adapter instance
        
    Raises:
        ValueError: If source unknown
    """
    adapters = {
        "withings": WithingsPhysiometricsAdapter,
        "garmin": GarminTrainingStateAdapter,
        "intervals": IntervalsPhysiometricsAdapter,
    }
    adapter_class = adapters.get(source_name)
    if not adapter_class:
        raise ValueError(f"Unknown wellness source: {source_name}")
    return adapter_class()
