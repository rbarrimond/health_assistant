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
            # Body composition (Withings exclusive)
            weight_kg=weight_kg,
            fat_mass_kg=fat_mass_kg,
            body_fat_pct=body_fat_pct,
            muscle_mass_kg=muscle_mass_kg,
            bone_mass_kg=bone_mass_kg,
            # Recovery metrics (Intervals exclusive)
            hrv_ln_rmssd=None,
            hrv_sdnn_ms=None,
            sleep_duration_sec=None,
            resting_hr_bpm=None,
            # Activity (Intervals exclusive)
            steps=None,
            # Nutrition (Intervals exclusive)
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            # Extended body/recovery metrics
            spo2_pct=None,
            # Performance baselines (Garmin exclusive)
            ftp_watts=None,
            cycling_vo2max_ml_kg_min=None,
            running_vo2max_ml_kg_min=None,
            hr_lthr_bpm=None,
            hr_max_bpm=None,
            # Training state (Garmin exclusive)
            training_load=None,
            recovery_time_minutes=None,
            readiness_score=None,
            # Extended training metrics (Garmin exclusive)
            training_effect_aerobic=None,
            training_effect_anaerobic=None,
            training_stress_score=None,
            training_stress_balance=None,
            atp_probability=None,
            # Training status and load focus (Garmin exclusive)
            training_status_label=None,
            load_focus_low_aerobic_pct=None,
            load_focus_high_aerobic_pct=None,
            load_focus_anaerobic_pct=None,
            # Metadata
            data_sources="withings",
            canonical_version="4.2.0",
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

    @staticmethod
    def _first_map_value(source: Dict[str, Any]) -> Dict[str, Any]:
        """Return first dictionary value from a keyed map payload."""
        if not isinstance(source, dict) or not source:
            return {}
        first_value = next(iter(source.values()))
        return first_value if isinstance(first_value, dict) else {}

    def _extract_training_context(self, training_status: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Extract normalized Garmin v2 payload fragments used for metric mapping."""
        most_recent_vo2max = self._extract_first(
            training_status,
            [("mostRecentVO2Max",)],
        ) or {}

        most_recent_training_status = self._extract_first(
            training_status,
            [("mostRecentTrainingStatus",)],
        ) or {}
        latest_training_status_map = self._extract_first(
            most_recent_training_status,
            [("latestTrainingStatusData",)],
        ) or {}
        latest_training_status = self._first_map_value(latest_training_status_map)

        acute_training_load = self._extract_first(
            latest_training_status,
            [("acuteTrainingLoadDTO",)],
        ) or {}

        most_recent_training_load_balance = self._extract_first(
            training_status,
            [("mostRecentTrainingLoadBalance",)],
        ) or {}

        metrics_training_load_balance_map = self._extract_first(
            most_recent_training_load_balance,
            [("metricsTrainingLoadBalanceDTOMap",)],
        ) or {}
        metrics_training_load_balance = self._first_map_value(metrics_training_load_balance_map)

        return {
            "most_recent_vo2max": most_recent_vo2max,
            "latest_training_status": latest_training_status,
            "acute_training_load": acute_training_load,
            "most_recent_training_load_balance": most_recent_training_load_balance,
            "metrics_training_load_balance": metrics_training_load_balance,
        }

    def _extract_training_status_label(self, latest_training_status: Dict[str, Any]) -> Any:
        """Extract Garmin training status label with modern-path priority."""
        return self._extract_first(
            latest_training_status,
            [
                ("trainingStatusFeedbackPhrase",),
                ("trainingStatusLabel",),
                ("status",),
            ],
        )

    @staticmethod
    def _normalize_minutes(
        minutes: Optional[Any] = None,
        hours: Optional[Any] = None,
    ) -> Optional[int]:
        """Normalize recovery duration to minutes when provided as hours or minutes."""
        if minutes is not None:
            try:
                return int(round(float(minutes)))
            except (TypeError, ValueError):
                return None
        if hours is not None:
            try:
                return int(round(float(hours) * 60))
            except (TypeError, ValueError):
                return None
        return None

    def _extract_readiness_recovery(
        self,
        summary: Dict[str, Any],
        training_status: Dict[str, Any],
        training_readiness: Optional[Union[list[Dict[str, Any]], Dict[str, Any]]],
        morning_training_readiness: Optional[Dict[str, Any]],
    ) -> Dict[str, Optional[Any]]:
        """Extract readiness and recovery fields with dedicated readiness payload priority."""
        # Normalize: prefer morning_training_readiness (already a single dict from SDK),
        # then select the best entry from training_readiness (list or dict).
        readiness_entry: Optional[Dict[str, Any]] = morning_training_readiness
        if readiness_entry is None:
            if isinstance(training_readiness, list) and training_readiness:
                # Mirror SDK preference: AFTER_WAKEUP_RESET first, else first valid entry
                readiness_entry = next(
                    (e for e in training_readiness if isinstance(e, dict) and e.get("inputContext") == "AFTER_WAKEUP_RESET"),
                    next((e for e in training_readiness if isinstance(e, dict)), None),
                )
            elif isinstance(training_readiness, dict):
                readiness_entry = training_readiness
        readiness_payload: Dict[str, Any] = readiness_entry or {}

        readiness = self._extract_first(
            readiness_payload,
            [
                ("score",),
                ("trainingReadinessScore",),
                ("readiness", "score"),
                ("readinessScore",),
                ("value",),
            ],
        )
        if readiness is None:
            readiness = self._extract_first(
                summary,
                [
                    ("stats", "readiness", "score"),
                    ("stats", "readinessScore"),
                    ("stats", "trainingReadiness", "score"),
                    ("trainingReadiness", "score"),
                ],
            )

        recovery_minutes = self._normalize_minutes(
            minutes=self._extract_first(
                readiness_payload,
                [
                    ("recoveryTimeMinutes",),
                    ("recoveryMinutes",),
                    ("recoveryDurationMinutes",),
                    ("recoveryTime", "minutes"),
                ],
            ),
            hours=self._extract_first(
                readiness_payload,
                [
                    ("recoveryTimeHours",),
                    ("recoveryHours",),
                    ("recoveryTime", "hours"),
                ],
            ),
        )
        if recovery_minutes is None:
            recovery_minutes = self._normalize_minutes(
                minutes=self._extract_first(
                    training_status,
                    [
                        ("recoveryTimeMinutes",),
                        ("recoveryMinutes",),
                    ],
                )
            )

        return {
            "readiness": readiness,
            "recovery_time_minutes": recovery_minutes,
        }

    def _extract_load_focus_metrics(
        self,
        most_recent_training_load_balance: Dict[str, Any],
        metrics_training_load_balance: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Extract load-focus metrics from modern map shape with legacy fallback."""
        monthly_low = self._extract_first(
            metrics_training_load_balance,
            [("monthlyLoadAerobicLow",)],
        )
        monthly_high = self._extract_first(
            metrics_training_load_balance,
            [("monthlyLoadAerobicHigh",)],
        )
        monthly_anaerobic = self._extract_first(
            metrics_training_load_balance,
            [("monthlyLoadAnaerobic",)],
        )

        monthly_values = [monthly_low, monthly_high, monthly_anaerobic]
        if any(value is not None for value in monthly_values):
            numeric_values = [float(value) if value is not None else 0.0 for value in monthly_values]
            total = sum(numeric_values)
            if total > 0:
                return {
                    "load_focus_low_aerobic_pct": (numeric_values[0] / total) * 100,
                    "load_focus_high_aerobic_pct": (numeric_values[1] / total) * 100,
                    "load_focus_anaerobic_pct": (numeric_values[2] / total) * 100,
                }

        return {
            "load_focus_low_aerobic_pct": self._extract_first(
                most_recent_training_load_balance,
                [("loadFocusWeek", "lowAerobic"), ("loadFocusWeek", "low_aerobic")],
            ),
            "load_focus_high_aerobic_pct": self._extract_first(
                most_recent_training_load_balance,
                [("loadFocusWeek", "highAerobic"), ("loadFocusWeek", "high_aerobic")],
            ),
            "load_focus_anaerobic_pct": self._extract_first(
                most_recent_training_load_balance,
                [("loadFocusWeek", "anaerobic")],
            ),
        }

    def _extract_vo2_metrics(self, stats: Dict[str, Any], most_recent_vo2max: Dict[str, Any]) -> Dict[str, Any]:
        """Extract cycling and running VO2 max from legacy or current Garmin payloads."""
        vo2max_cycling = stats.get("vo2MaxCycling", {}).get("value") or self._extract_first(
            most_recent_vo2max,
            [
                ("cycling", "vo2MaxPreciseValue"),
                ("cycling", "vo2MaxValue"),
            ],
        )
        vo2max_running = stats.get("vo2MaxRunning", {}).get("value") or self._extract_first(
            most_recent_vo2max,
            [
                ("running", "vo2MaxPreciseValue"),
                ("running", "vo2MaxValue"),
                ("generic", "vo2MaxPreciseValue"),
                ("generic", "vo2MaxValue"),
            ],
        )
        return {
            "vo2max_cycling": vo2max_cycling,
            "vo2max_running": vo2max_running,
        }

    def _log_parsed_metric_presence(self, parsed: Dict[str, Any]) -> None:
        """Log high-signal Garmin metric presence for troubleshooting payload drift."""
        logger.info(
            "Parsed Garmin physiometrics payload",
            extra={
                "effective_date": parsed.get("effective_date"),
                "has_ftp": parsed.get("ftp") is not None,
                "has_vo2max_cycling": parsed.get("vo2max_cycling") is not None,
                "has_vo2max_running": parsed.get("vo2max_running") is not None,
                "has_training_load": parsed.get("training_load") is not None,
                "has_training_stress_score": parsed.get("training_stress_score") is not None,
                "has_readiness": parsed.get("readiness") is not None,
                "has_recovery_time": parsed.get("recovery_time_minutes") is not None,
                "has_training_status_label": parsed.get("training_status_label") is not None,
                "has_load_focus_low_aerobic": parsed.get("load_focus_low_aerobic_pct") is not None,
                "has_load_focus_high_aerobic": parsed.get("load_focus_high_aerobic_pct") is not None,
                "has_load_focus_anaerobic": parsed.get("load_focus_anaerobic_pct") is not None,
            },
        )

    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract queryable Garmin metrics from summary and training status payloads."""
        summary = raw_data.get("summary", raw_data)
        training_status = raw_data.get("training_status", {})
        training_readiness = raw_data.get("training_readiness")
        morning_training_readiness = raw_data.get("morning_training_readiness")
        cycling_ftp = raw_data.get("cycling_ftp") or {}
        lactate_threshold = raw_data.get("lactate_threshold") or {}
        stats = summary.get("stats", summary)
        context = self._extract_training_context(training_status)
        most_recent_vo2max = context["most_recent_vo2max"]
        latest_training_status = context["latest_training_status"]
        acute_training_load = context["acute_training_load"]
        most_recent_training_load_balance = context["most_recent_training_load_balance"]
        metrics_training_load_balance = context["metrics_training_load_balance"]
        vo2_metrics = self._extract_vo2_metrics(stats, most_recent_vo2max)

        training_effect = self._extract_first(
            training_status,
            [
                ("trainingEffect",),
                ("trainingEffectValues",),
            ],
        ) or {}

        lactate_threshold_hr = self._extract_first(
            lactate_threshold,
            [
                ("speed_and_heart_rate", "heartRateCycling"),
                ("speed_and_heart_rate", "heartRate"),
            ],
        )
        if lactate_threshold_hr is None:
            lactate_threshold_hr = self._extract_first(
                training_status,
                [
                ("lactateThresholdHeartRate",),
                ("lactateThreshold", "heartRate"),
                ("recoveryMetrics", "lactateThresholdHeartRate"),
                ("recoveryMetrics", "lthr"),
                ],
            )

        training_status_label = self._extract_training_status_label(latest_training_status)
        load_focus_metrics = self._extract_load_focus_metrics(
            most_recent_training_load_balance,
            metrics_training_load_balance,
        )
        readiness_recovery = self._extract_readiness_recovery(
            summary=summary,
            training_status=training_status,
            training_readiness=training_readiness,
            morning_training_readiness=morning_training_readiness,
        )

        parsed = {
            "ftp": self._extract_first(
                cycling_ftp,
                [
                    ("functionalThresholdPower",),
                ],
            )
            if cycling_ftp
            else stats.get("functionThreshold"),
            "vo2max_cycling": vo2_metrics["vo2max_cycling"],
            "vo2max_running": vo2_metrics["vo2max_running"],
            "max_hr": stats.get("maxHeartRate"),
            "resting_hr": stats.get("restingHeartRate"),
            "readiness": readiness_recovery["readiness"],
            "training_load": self._extract_first(
                training_status,
                [
                    ("trainingLoad", "load"),
                    ("trainingLoad",),
                ],
            )
            or self._extract_first(
                latest_training_status,
                [
                    ("weeklyTrainingLoad",),
                ],
            )
            or self._extract_first(
                acute_training_load,
                [
                    ("dailyTrainingLoadAcute",),
                    ("dailyTrainingLoadChronic",),
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
            )
            or self._extract_first(
                acute_training_load,
                [
                    ("dailyTrainingLoadAcute",),
                ],
            ),
            "training_stress_balance": self._extract_first(
                training_status,
                [
                    ("trainingStressBalance",),
                    ("stressBalance",),
                ],
            )
            or self._extract_first(
                acute_training_load,
                [
                    ("dailyAcuteChronicWorkloadRatio",),
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
            "recovery_time_minutes": readiness_recovery["recovery_time_minutes"],
            "lactate_threshold_hr_bpm": lactate_threshold_hr,
            "training_status_label": training_status_label,
            "load_focus_low_aerobic_pct": load_focus_metrics["load_focus_low_aerobic_pct"],
            "load_focus_high_aerobic_pct": load_focus_metrics["load_focus_high_aerobic_pct"],
            "load_focus_anaerobic_pct": load_focus_metrics["load_focus_anaerobic_pct"],
            "effective_date": summary.get("calendarDate"),
            "ext_json": json.dumps(
                {
                    "summary": summary,
                    "training_status": training_status,
                    "training_readiness": training_readiness,
                    "morning_training_readiness": morning_training_readiness,
                    "cycling_ftp": cycling_ftp,
                    "lactate_threshold": lactate_threshold,
                }
            ),
        }
        self._log_parsed_metric_presence(parsed)
        return parsed

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
        """Map to PhysiometricsSnapshot.
        
        Note: Garmin's resting_hr_bpm and steps are intentionally ignored per schema v3.0.0.
        Intervals is the exclusive source for these metrics (Garmin values inaccurate).
        """
        # Prefer Garmin lactate threshold HR; fallback to estimate from max HR.
        max_hr = parsed.get("max_hr")
        lthr = parsed.get("lactate_threshold_hr_bpm") or (
            int(max_hr * 0.85) if max_hr else None
        )

        return PhysiometricsSnapshot(
            athlete_id=athlete_id,
            effective_date=parsed.get("effective_date")
            or datetime.now(timezone.utc).date().isoformat(),
            # Body composition (Withings exclusive)
            weight_kg=None,
            fat_mass_kg=None,
            body_fat_pct=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            # Recovery metrics (Intervals exclusive)
            hrv_ln_rmssd=None,
            hrv_sdnn_ms=None,
            sleep_duration_sec=None,
            resting_hr_bpm=None,  # Intervals exclusive; Garmin ignored
            # Activity (Intervals exclusive)
            steps=None,  # Intervals exclusive; Garmin ignored
            # Nutrition (Intervals exclusive)
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            # Extended body/recovery metrics
            spo2_pct=None,
            # Performance baselines (Garmin exclusive)
            ftp_watts=parsed.get("ftp"),
            cycling_vo2max_ml_kg_min=parsed.get("vo2max_cycling"),
            running_vo2max_ml_kg_min=parsed.get("vo2max_running"),
            hr_lthr_bpm=lthr,
            hr_max_bpm=max_hr,
            # Training state (Garmin exclusive)
            training_load=parsed.get("training_load"),
            recovery_time_minutes=parsed.get("recovery_time_minutes"),
            readiness_score=parsed.get("readiness"),
            # Extended training metrics (Garmin exclusive)
            training_effect_aerobic=parsed.get("training_effect_aerobic"),
            training_effect_anaerobic=parsed.get("training_effect_anaerobic"),
            training_stress_score=parsed.get("training_stress_score"),
            training_stress_balance=parsed.get("training_stress_balance"),
            atp_probability=parsed.get("atp_probability"),
            # Training status and load focus (Garmin exclusive, new in v4.2.0)
            training_status_label=parsed.get("training_status_label"),
            load_focus_low_aerobic_pct=parsed.get("load_focus_low_aerobic_pct"),
            load_focus_high_aerobic_pct=parsed.get("load_focus_high_aerobic_pct"),
            load_focus_anaerobic_pct=parsed.get("load_focus_anaerobic_pct"),
            # Metadata
            data_sources="garmin",
            canonical_version="4.2.0",
        )


class IntervalsPhysiometricsAdapter(BaseWellnessSourceAdapter):
    """Converts Intervals.icu API responses."""

    def _do_parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Intervals wellness fields used by canonical physiometrics schema."""
        sleep_seconds = raw_data.get("sleepSecs") or raw_data.get("sleep")

        return {
            "date": raw_data.get("id") or raw_data.get("date"),
            # Recovery metrics (Intervals exclusive)
            "hrv": raw_data.get("hrvRMSSD") or raw_data.get("hrv"),  # Already ln(RMSSD)
            "hrv_sdnn_ms": raw_data.get("hrvSDNN"),
            "rhr": raw_data.get("restingHR") if raw_data.get("restingHR") is not None else raw_data.get("rhr"),
            "sleep_sec": sleep_seconds,
            "readiness": raw_data.get("readiness"),
            # Nutrition (Intervals exclusive)
            "calories_kcal": raw_data.get("kcalConsumed"),
            "carbs_g": raw_data.get("carbohydrates"),
            "protein_g": raw_data.get("protein"),
            "fat_g": raw_data.get("fatTotal"),
            # Activity (Intervals exclusive)
            "steps": raw_data.get("steps"),
            # Extended metrics and source fallbacks
            "spo2_pct": raw_data.get("spO2"),
            "weight_kg": raw_data.get("weight"),
            "body_fat_pct": raw_data.get("bodyFat"),
            # Non-scalar source payloads
            "sport_info_json": json.dumps(raw_data.get("sportInfo"))
            if raw_data.get("sportInfo") is not None
            else None,
            "source_updated_at_utc": raw_data.get("updated"),
        }

    def validate_semantic_contract(self, parsed: Dict[str, Any]) -> None:
        """Validate at least one canonical Intervals metric is present."""
        # Recovery metrics (Intervals exclusive)
        recovery_fields = ["hrv", "hrv_sdnn_ms", "rhr", "sleep_sec", "readiness"]
        # Nutrition (Intervals exclusive)
        nutrition_fields = ["calories_kcal", "carbs_g", "protein_g", "fat_g"]
        # Activity (Intervals exclusive)
        activity_fields = ["steps"]
        # Intervals fallback body metrics + extended recovery
        fallback_fields = ["weight_kg", "body_fat_pct", "spo2_pct"]
        
        all_fields = (
            recovery_fields
            + nutrition_fields
            + activity_fields
            + fallback_fields
        )
        if not any(parsed.get(field) is not None for field in all_fields):
            raise AdapterError("No canonical wellness metrics in Intervals response")

    def map_to_canonical(
        self, parsed: Dict[str, Any], athlete_id: str
    ) -> PhysiometricsSnapshot:
        """Map to PhysiometricsSnapshot.
        
        Intervals provides recovery metrics (HRV, sleep, resting HR), activity (steps),
        nutrition, and fallback body metrics when Withings is unavailable.
        """
        date = parsed.get("date", datetime.now(timezone.utc).date().isoformat())

        return PhysiometricsSnapshot(
            athlete_id=athlete_id,
            effective_date=date,
            # Body composition (Withings primary; Intervals fallback)
            weight_kg=parsed.get("weight_kg"),
            fat_mass_kg=None,
            muscle_mass_kg=None,
            bone_mass_kg=None,
            body_fat_pct=parsed.get("body_fat_pct"),
            # Recovery metrics (Intervals exclusive)
            hrv_ln_rmssd=parsed.get("hrv"),
            hrv_sdnn_ms=parsed.get("hrv_sdnn_ms"),
            sleep_duration_sec=parsed.get("sleep_sec"),
            resting_hr_bpm=parsed.get("rhr"),
            # Activity (Intervals exclusive)
            steps=parsed.get("steps"),
            # Nutrition (Intervals exclusive)
            calories_kcal=parsed.get("calories_kcal"),
            carbs_g=parsed.get("carbs_g"),
            protein_g=parsed.get("protein_g"),
            fat_g=parsed.get("fat_g"),
            # Extended body/recovery metrics
            spo2_pct=parsed.get("spo2_pct"),
            # Performance baselines (Garmin exclusive)
            ftp_watts=None,
            cycling_vo2max_ml_kg_min=None,
            running_vo2max_ml_kg_min=None,
            hr_lthr_bpm=None,
            hr_max_bpm=None,
            # Training state (Garmin exclusive)
            training_load=None,
            recovery_time_minutes=None,
            readiness_score=parsed.get("readiness"),  # Intervals fallback; Garmin preferred
            # Extended training metrics (Garmin exclusive)
            training_effect_aerobic=None,
            training_effect_anaerobic=None,
            training_stress_score=None,
            training_stress_balance=None,
            atp_probability=None,
            # Training status and load focus (Garmin exclusive)
            training_status_label=None,
            load_focus_low_aerobic_pct=None,
            load_focus_high_aerobic_pct=None,
            load_focus_anaerobic_pct=None,
            # Metadata
            data_sources="intervals",
            canonical_version="4.2.0",
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
