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
            sleep_duration_sec=None,
            ftp_watts=None,
            cycling_vo2max_ml_kg_min=None,
            hr_lthr_bpm=None,
            hr_max_bpm=None,
            load=None,
            readiness_score=None,
            hrv_sdnn_ms=None,
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
            spo2_pct=None,
            systolic_bp=None,
            diastolic_bp=None,
            vo2max_ml_kg_min=None,
            menstrual_phase=None,
            menstrual_phase_predicted=None,
            sport_info=None,
            data_sources="withings",
            measured_at_utc=date_obj,
            source_updated_at_utc=None,
            raw_intervals_icu_json=None,
            ext_json=None,
        )


class GarminTrainingStateAdapter(BaseWellnessSourceAdapter):
    """Converts Garmin Connect user summary + training status responses."""

    @staticmethod
    def _extract_first(source: Dict[str, Any], paths: list[tuple[str, ...]]) -> Any:
        """Return the first non-null nested value from candidate paths."""
        for path in paths:
            value: Any = source
            for key in path:
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(key)
            if value is not None:
                return value
        return None

    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract queryable Garmin metrics from summary and training status payloads."""
        summary = raw_data.get("summary", raw_data)
        training_status = raw_data.get("training_status", {})
        stats = summary.get("stats", summary)

        training_effect = self._extract_first(
            training_status,
            [
                ("trainingEffect",),
                ("trainingEffectValues",),
            ],
        ) or {}

        lactate_threshold_hr = self._extract_first(
            training_status,
            [
                ("lactateThresholdHeartRate",),
                ("lactateThreshold", "heartRate"),
                ("recoveryMetrics", "lactateThresholdHeartRate"),
                ("recoveryMetrics", "lthr"),
            ],
        )

        return {
            "ftp": stats.get("functionThreshold"),
            "vo2max_cycling": stats.get("vo2MaxCycling", {}).get("value"),
            "vo2max_running": stats.get("vo2MaxRunning", {}).get("value"),
            "max_hr": stats.get("maxHeartRate"),
            "resting_hr": stats.get("restingHeartRate"),
            "readiness": stats.get("readiness", {}).get("score"),
            "training_load": self._extract_first(
                training_status,
                [
                    ("trainingLoad", "load"),
                    ("trainingLoad",),
                ],
            ),
            "training_effect_aerobic": self._extract_first(
                training_status,
                [
                    ("trainingEffectAerobic",),
                    ("aerobicTrainingEffect",),
                    ("aerobic",),
                ],
            )
            if not isinstance(training_effect, dict)
            else self._extract_first(
                training_effect,
                [("aerobic",), ("aerobicValue",)],
            ),
            "training_effect_anaerobic": self._extract_first(
                training_status,
                [
                    ("trainingEffectAnaerobic",),
                    ("anaerobicTrainingEffect",),
                    ("anaerobic",),
                ],
            )
            if not isinstance(training_effect, dict)
            else self._extract_first(
                training_effect,
                [("anaerobic",), ("anaerobicValue",)],
            ),
            "training_stress_score": self._extract_first(
                training_status,
                [
                    ("trainingStressScore",),
                    ("tss",),
                ],
            ),
            "training_stress_balance": self._extract_first(
                training_status,
                [
                    ("trainingStressBalance",),
                    ("stressBalance",),
                ],
            ),
            "atp_probability": self._extract_first(
                training_status,
                [
                    ("atpProbability",),
                    ("atpProability",),
                    ("atp",),
                ],
            ),
            "recovery_time_minutes": self._extract_first(
                training_status,
                [
                    ("recoveryTimeMinutes",),
                    ("recoveryMinutes",),
                ],
            ),
            "lactate_threshold_hr_bpm": lactate_threshold_hr,
            "effective_date": summary.get("calendarDate"),
            "ext_json": json.dumps(
                {
                    "summary": summary,
                    "training_status": training_status,
                }
            ),
        }

    @staticmethod
    def _validate_range(
        parsed: Dict[str, Any], key: str, minimum: float, maximum: float, label: str
    ) -> None:
        """Validate optional numeric field within inclusive range."""
        value = parsed.get(key)
        if value is None:
            return
        if value < minimum or value > maximum:
            raise AdapterError(f"{label} out of range: {value}")

    def validate_semantic_contract(self, parsed: Dict[str, Any]) -> None:
        """Validate Garmin metric ranges for canonical integrity."""
        checks = [
            ("ftp", 150, 400, "FTP"),
            ("vo2max_cycling", 30, 100, "VO2Max"),
            ("vo2max_running", 20, 100, "Running VO2Max"),
            ("training_effect_aerobic", 0, 5, "Aerobic training effect"),
            ("training_effect_anaerobic", 0, 5, "Anaerobic training effect"),
            ("atp_probability", 0, 100, "ATP probability"),
            ("lactate_threshold_hr_bpm", 80, 220, "Lactate threshold HR"),
        ]
        for key, minimum, maximum, label in checks:
            self._validate_range(parsed, key, minimum, maximum, label)

    def map_to_canonical(
        self, parsed: Dict[str, Any], athlete_id: str
    ) -> PhysiometricsSnapshot:
        """Map to PhysiometricsSnapshot."""
        # Prefer Garmin lactate threshold HR; fallback to estimate from max HR.
        max_hr = parsed.get("max_hr")
        lthr = parsed.get("lactate_threshold_hr_bpm") or (
            int(max_hr * 0.85) if max_hr else None
        )

        return PhysiometricsSnapshot(
            athlete_id=athlete_id,
            effective_date=parsed.get("effective_date")
            or datetime.now(timezone.utc).date().isoformat(),
            weight_kg=None,
            fat_mass_kg=None,
            body_fat_pct=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            visceral_fat_index=None,
            metabolic_age_years=None,
            hrv_ln_rmssd=None,
            resting_hr_bpm=parsed.get("resting_hr"),
            sleep_duration_sec=None,
            ftp_watts=parsed.get("ftp"),
            cycling_vo2max_ml_kg_min=parsed.get("vo2max_cycling"),
            running_vo2max_ml_kg_min=parsed.get("vo2max_running"),
            hr_lthr_bpm=lthr,
            lactate_threshold_hr_bpm=parsed.get("lactate_threshold_hr_bpm"),
            hr_max_bpm=max_hr,
            load=parsed.get("training_load"),
            readiness_score=parsed.get("readiness"),
            training_load=parsed.get("training_load"),
            training_effect_aerobic=parsed.get("training_effect_aerobic"),
            training_effect_anaerobic=parsed.get("training_effect_anaerobic"),
            training_stress_score=parsed.get("training_stress_score"),
            training_stress_balance=parsed.get("training_stress_balance"),
            atp_probability=parsed.get("atp_probability"),
            recovery_time_minutes=parsed.get("recovery_time_minutes"),
            hrv_sdnn_ms=None,
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
            spo2_pct=None,
            systolic_bp=None,
            diastolic_bp=None,
            vo2max_ml_kg_min=None,
            menstrual_phase=None,
            menstrual_phase_predicted=None,
            sport_info=None,
            data_sources="garmin",
            measured_at_utc=None,
            source_updated_at_utc=None,
            raw_intervals_icu_json=None,
            ext_json=parsed.get("ext_json"),
        )


class IntervalsPhysiometricsAdapter(BaseWellnessSourceAdapter):
    """Converts Intervals.icu API responses."""

    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract wellness fields with compatibility aliases."""
        sleep_seconds = raw_data.get("sleepSecs") or raw_data.get("sleep")

        return {
            "date": raw_data.get("id") or raw_data.get("date"),
            "source_updated_at_utc": raw_data.get("updated"),
            "hrv": raw_data.get("hrvRMSSD") or raw_data.get("hrv"),  # Already ln(RMSSD)
            "hrv_sdnn_ms": raw_data.get("hrvSDNN"),
            "rhr": raw_data.get("restingHR") if raw_data.get("restingHR") is not None else raw_data.get("rhr"),
            "sleep_sec": sleep_seconds,
            "readiness": raw_data.get("readiness"),
            # Optional canonical body composition from Intervals
            "weight_kg": raw_data.get("weight"),
            "body_fat_pct": raw_data.get("bodyFat"),
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
            "spo2_pct": raw_data.get("spO2"),
            "systolic_bp": raw_data.get("systolic"),
            "diastolic_bp": raw_data.get("diastolic"),
            "vo2max_ml_kg_min": raw_data.get("vo2max"),
            "menstrual_phase": raw_data.get("menstrualPhase"),
            "menstrual_phase_predicted": raw_data.get("menstrualPhasePredicted"),
            # Nested sport metrics (pass through)
            "sport_info": raw_data.get("sportInfo"),
            # Raw source preservation (zero-loss)
            "raw_intervals_icu_json": json.dumps(raw_data),
            "ext_json": json.dumps(
                {
                    "hrv_sdnn_ms": raw_data.get("hrvSDNN"),
                    "soreness": raw_data.get("soreness"),
                    "fatigue": raw_data.get("fatigue"),
                    "stress": raw_data.get("stress"),
                    "mood": raw_data.get("mood"),
                    "motivation": raw_data.get("motivation"),
                    "injury": raw_data.get("injury"),
                    "calories_kcal": raw_data.get("kcalConsumed"),
                    "carbs_g": raw_data.get("carbohydrates"),
                    "protein_g": raw_data.get("protein"),
                    "fat_g": raw_data.get("fatTotal"),
                    "abdomen_cm": raw_data.get("abdomen"),
                    "spo2_pct": raw_data.get("spO2"),
                    "systolic_bp": raw_data.get("systolic"),
                    "diastolic_bp": raw_data.get("diastolic"),
                    "vo2max_ml_kg_min": raw_data.get("vo2max"),
                    "menstrual_phase": raw_data.get("menstrualPhase"),
                    "menstrual_phase_predicted": raw_data.get("menstrualPhasePredicted"),
                    "sport_info_json": json.dumps(raw_data.get("sportInfo")) if raw_data.get("sportInfo") is not None else None,
                    "source_updated_at_utc": raw_data.get("updated"),
                }
            ),
        }

    def validate_semantic_contract(self, parsed: Dict[str, Any]) -> None:
        """Validate: at least one field present (original or extended wellness)."""
        # Original core wellness fields
        core_fields = ["hrv", "rhr", "sleep", "readiness"]
        # Extended wellness fields (v2.1.0+): subjective, nutrition, activity, body
        extended_fields = [
            "soreness", "fatigue", "stress", "mood", "motivation", "injury",
            "calories_kcal", "carbs_g", "protein_g", "fat_g",
            "steps", "abdomen_cm", "sport_info", "weight_kg", "body_fat_pct",
            "hrv_sdnn_ms", "spo2_pct", "systolic_bp", "diastolic_bp", "vo2max_ml_kg_min"
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
            weight_kg=parsed.get("weight_kg"),
            fat_mass_kg=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            body_fat_pct=parsed.get("body_fat_pct"),
            visceral_fat_index=None,
            metabolic_age_years=None,
            hrv_ln_rmssd=parsed.get("hrv"),
            hrv_sdnn_ms=parsed.get("hrv_sdnn_ms"),
            resting_hr_bpm=parsed.get("rhr"),
            sleep_duration_sec=parsed.get("sleep_sec"),
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
            spo2_pct=parsed.get("spo2_pct"),
            systolic_bp=parsed.get("systolic_bp"),
            diastolic_bp=parsed.get("diastolic_bp"),
            vo2max_ml_kg_min=parsed.get("vo2max_ml_kg_min"),
            menstrual_phase=parsed.get("menstrual_phase"),
            menstrual_phase_predicted=parsed.get("menstrual_phase_predicted"),
            sport_info=parsed.get("sport_info"),
            data_sources="intervals",
            measured_at_utc=None,
            source_updated_at_utc=parsed.get("source_updated_at_utc"),
            raw_intervals_icu_json=parsed.get("raw_intervals_icu_json"),
            ext_json=parsed.get("ext_json"),
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
