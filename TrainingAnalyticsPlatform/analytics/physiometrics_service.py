"""Physiometrics service — physiometric values and training state projections."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.analytics import utils
from TrainingAnalyticsPlatform.analytics.physiometrics_resolution import (
    BASELINE_SOURCE_PRECEDENCE,
    build_source_rows_by_source,
    canonical_sources_from_row,
    effective_date_from_row,
    parse_iso_timestamp,
    resolve_latest_metric_across_sources,
)
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot, TrainingStateSnapshot
from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import StorageError, ValidationError

if TYPE_CHECKING:
    from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

UTC_OFFSET = "+00:00"

RECENCY_RESOLVED_BASELINE_METRICS = frozenset(BASELINE_SOURCE_PRECEDENCE.keys())

PHYSIOMETRICS_SOURCE_PRECEDENCE = {
    "weight_kg": ["withings", "intervals"],
    "fat_mass_kg": ["withings"],
    "muscle_mass_kg": ["withings"],
    "bone_mass_kg": ["withings"],
    "body_fat_pct": ["withings", "intervals"],
    "visceral_fat_index": ["withings"],
    "metabolic_age_years": ["withings"],
    "hrv_ln_rmssd": ["intervals", "garmin"],
    "hrv_sdnn_ms": ["intervals", "garmin"],
    "resting_hr_bpm": ["intervals"],
    "sleep_duration_sec": ["intervals", "garmin"],
    "soreness": ["intervals"],
    "fatigue": ["intervals"],
    "stress": ["intervals"],
    "mood": ["intervals"],
    "motivation": ["intervals"],
    "injury": ["intervals"],
    "calories_kcal": ["intervals"],
    "carbs_g": ["intervals"],
    "protein_g": ["intervals"],
    "fat_g": ["intervals"],
    "steps": ["intervals", "garmin"],
    "abdomen_cm": ["intervals", "withings"],
    "spo2_pct": ["intervals", "garmin"],
    "systolic_bp": ["intervals"],
    "diastolic_bp": ["intervals"],
    "vo2max_ml_kg_min": ["intervals", "garmin"],
    "menstrual_phase": ["intervals"],
    "menstrual_phase_predicted": ["intervals"],
    "ftp_watts": ["garmin", "chatgpt", "manual"],
    "cycling_vo2max_ml_kg_min": ["garmin", "intervals"],
    "running_vo2max_ml_kg_min": ["garmin", "intervals"],
    "hr_lthr_bpm": ["garmin", "chatgpt", "manual"],
    "hr_max_bpm": ["garmin", "chatgpt", "manual"],
    "load": ["garmin"],
    "readiness_score": ["garmin", "intervals"],
    "training_load": ["garmin"],
    "training_effect_aerobic": ["garmin"],
    "training_effect_anaerobic": ["garmin"],
    "training_stress_score": ["garmin"],
    "training_stress_balance": ["garmin"],
    "atp_probability": ["garmin"],
    "recovery_time_minutes": ["garmin"],
    "lactate_threshold_hr_bpm": ["garmin"],
    "training_status_label": ["garmin"],
    "load_focus_low_aerobic_pct": ["garmin"],
    "load_focus_high_aerobic_pct": ["garmin"],
    "load_focus_anaerobic_pct": ["garmin"],
}

TRAINING_STATE_PHYSIOMETRICS_SOURCES = {
    "hrv_ln_rmssd": ["intervals"],
    "readiness_score": ["garmin"],
    "training_load": ["garmin"],
    "recovery_time_minutes": ["garmin"],
    "training_status_label": ["garmin"],
    "load_focus_low_aerobic_pct": ["garmin"],
    "load_focus_high_aerobic_pct": ["garmin"],
    "load_focus_anaerobic_pct": ["garmin"],
}

PHYSIOMETRICS_CANONICAL_SECTIONS = {
    "heart_rate": ["lthr_bpm", "hr_max_bpm", "resting_hr_bpm", "hrv_ln_rmssd", "hrv_sdnn_ms"],
    "power": ["ftp_watts"],
    "vo2max": ["cycling_vo2max_ml_kg_min", "running_vo2max_ml_kg_min"],
    "body_composition": ["weight_kg", "fat_mass_kg", "muscle_mass_kg", "bone_mass_kg", "body_fat_pct"],
    "recovery": ["sleep_duration_sec", "spo2_pct"],
    "activity": ["steps"],
    "nutrition": ["calories_kcal", "carbs_g", "protein_g", "fat_g"],
    "training_state": [
        "training_load",
        "recovery_time_minutes",
        "readiness_score",
        "training_effect_aerobic",
        "training_effect_anaerobic",
        "training_stress_score",
        "training_stress_balance",
        "atp_probability",
        "training_status_label",
        "load_focus_low_aerobic_pct",
        "load_focus_high_aerobic_pct",
        "load_focus_anaerobic_pct",
    ],
}

PHYSIOMETRICS_OPTIONAL_METRICS = [
    "visceral_fat_index",
    "metabolic_age_years",
    "soreness",
    "fatigue",
    "stress",
    "mood",
    "motivation",
    "injury",
    "systolic_bp",
    "diastolic_bp",
    "abdomen_cm",
    "vo2max_ml_kg_min",
    "menstrual_phase",
    "menstrual_phase_predicted",
    "lactate_threshold_hr_bpm",
]

PHYSIOMETRICS_STORAGE_FIELD_ALIASES = {
    "ftp_watts": ["ftp_watts", "power_ftp_watts"],
    "hr_lthr_bpm": ["hr_lthr_bpm", "heart_rate_lthr_bpm", "lactate_threshold_hr_bpm"],
    "hr_max_bpm": ["hr_max_bpm", "heart_rate_hr_max_bpm"],
    "resting_hr_bpm": ["resting_hr_bpm", "heart_rate_resting_bpm"],
    "soreness": ["soreness", "subjective_soreness"],
    "fatigue": ["fatigue", "subjective_fatigue"],
    "stress": ["stress", "subjective_stress"],
    "mood": ["mood", "subjective_mood"],
    "motivation": ["motivation", "subjective_motivation"],
    "injury": ["injury", "subjective_injury"],
    "calories_kcal": ["calories_kcal", "nutrition_calories_kcal"],
    "carbs_g": ["carbs_g", "nutrition_carbs_g"],
    "protein_g": ["protein_g", "nutrition_protein_g"],
    "fat_g": ["fat_g", "nutrition_fat_g"],
    "steps": ["steps", "activity_steps"],
    "abdomen_cm": ["abdomen_cm", "body_abdomen_cm"],
}


class PhysiometricsService:
    """Service for physiometric data management and training state projections."""

    def __init__(self, storage: "StorageCoordinator") -> None:
        self.storage = storage

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_current_physiometrics(self, athlete_id: str) -> Dict:
        """Get current physiometric values for an athlete."""
        source_rows_by_source = self._get_source_rows_by_source(athlete_id)
        source_rows = {
            source: rows[0]
            for source, rows in source_rows_by_source.items()
            if rows
        }
        if not source_rows_by_source:
            return {
                "athlete_id": athlete_id,
                "error": "No physiometrics data found",
            }

        merged = self._resolve_current_from_precedence(source_rows_by_source)
        data_sources = sorted(source_rows.keys())
        source_effective_dates = {
            source: row.get("effective_date")
            for source, row in source_rows.items()
            if row.get("effective_date")
        }
        latest_effective_date = max(
            (d for d in source_effective_dates.values() if d is not None),
            default=None,
        )

        result = {
            "athlete_id": athlete_id,
            "heart_rate": {
                "basis": merged.get("heart_rate_basis"),
                "lthr_bpm": merged.get("hr_lthr_bpm"),
                "hr_max_bpm": merged.get("hr_max_bpm"),
                "resting_hr_bpm": merged.get("resting_hr_bpm"),
                "hrv_ln_rmssd": merged.get("hrv_ln_rmssd"),
                "hrv_sdnn_ms": merged.get("hrv_sdnn_ms"),
            },
            "power": {
                "ftp_watts": merged.get("ftp_watts"),
            },
            "vo2max": {
                "cycling_vo2max_ml_kg_min": merged.get("cycling_vo2max_ml_kg_min"),
                "running_vo2max_ml_kg_min": merged.get("running_vo2max_ml_kg_min"),
            },
            "body_composition": {
                "weight_kg": merged.get("weight_kg"),
                "fat_mass_kg": merged.get("fat_mass_kg"),
                "muscle_mass_kg": merged.get("muscle_mass_kg"),
                "bone_mass_kg": merged.get("bone_mass_kg"),
                "body_fat_pct": merged.get("body_fat_pct"),
            },
            "recovery": {
                "sleep_duration_sec": merged.get("sleep_duration_sec"),
                "spo2_pct": merged.get("spo2_pct"),
            },
            "activity": {
                "steps": merged.get("steps"),
            },
            "nutrition": {
                "calories_kcal": merged.get("calories_kcal"),
                "carbs_g": merged.get("carbs_g"),
                "protein_g": merged.get("protein_g"),
                "fat_g": merged.get("fat_g"),
            },
            "training_state": {
                "training_load": merged.get("training_load"),
                "recovery_time_minutes": merged.get("recovery_time_minutes"),
                "readiness_score": merged.get("readiness_score"),
                "training_stress_score": merged.get("training_stress_score"),
                "training_stress_balance": merged.get("training_stress_balance"),
                "atp_probability": merged.get("atp_probability"),
                "training_status_label": merged.get("training_status_label"),
                "load_focus_low_aerobic_pct": merged.get("load_focus_low_aerobic_pct"),
                "load_focus_high_aerobic_pct": merged.get("load_focus_high_aerobic_pct"),
                "load_focus_anaerobic_pct": merged.get("load_focus_anaerobic_pct"),
            },
        }

        for metric_name in PHYSIOMETRICS_OPTIONAL_METRICS:
            if merged.get(metric_name) is not None:
                result[metric_name] = merged.get(metric_name)

        if latest_effective_date:
            result["effective_date"] = latest_effective_date
        result["data_sources"] = data_sources
        if source_effective_dates:
            result["source_effective_dates"] = source_effective_dates

        return result

    def get_physiometrics_trends(
        self,
        athlete_id: str,
        days: int = 90,
        metrics: Optional[List[str]] = None,
    ) -> Dict:
        """Get time-series physiometric trends."""
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        history = self.storage.physiometrics.get_physiometrics_history(
            athlete_id=athlete_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            metrics=metrics,
        )

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "count": len(history),
            "data_points": history,
        }

    def update_physiometric_value(
        self,
        athlete_id: str,
        metric: str,
        value: float,
        effective_date: Optional[str] = None,
        source: str = "chatgpt",
    ) -> Dict:
        """Update a single physiometric value."""
        try:
            timestamp = self.storage.physiometrics.update_single_metric(
                athlete_id=athlete_id,
                metric_name=metric,
                value=value,
                effective_date=effective_date,
                data_source=source,
            )
            Config.invalidate_physiometrics_cache()

            logger.info(
                "Updated physiometric",
                extra={
                    "athlete_id": athlete_id,
                    "metric": metric,
                    "value": value,
                    "effective_date": effective_date,
                    "source": source,
                },
            )

            return {
                "status": "success",
                "athlete_id": athlete_id,
                "metric": metric,
                "value": value,
                "effective_date": effective_date,
                "source": source,
                "updated_at_utc": timestamp,
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Error updating physiometric",
                extra={
                    "athlete_id": athlete_id,
                    "metric": metric,
                    "value": value,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
                exc_info=True,
            )
            return {
                "status": "error",
                "error": str(e),
            }

    def compute_current_training_state(self, athlete_id: str) -> Dict:
        """Compute current training state on-demand from Workouts + Physiometrics."""
        end_date = datetime.now(timezone.utc).date()
        snapshot = self._compute_training_state_for_date(athlete_id, end_date)

        return {
            "athlete_id": athlete_id,
            "effective_date": snapshot.effective_date,
            "cts_rolling_7d": snapshot.cts_rolling_7d,
            "cts_rolling_28d": snapshot.cts_rolling_28d,
            "ats_rolling": snapshot.ats_rolling,
            "fatigue_index": snapshot.fatigue_index,
            "readiness_score": snapshot.readiness_score,
            "garmin_readiness_score": snapshot.garmin_readiness_score,
            "garmin_training_status": snapshot.garmin_training_status,
            "garmin_training_load": snapshot.garmin_training_load,
            "garmin_recovery_time_hours": snapshot.garmin_recovery_time_hours,
            "garmin_load_focus_low_aerobic_pct": snapshot.garmin_load_focus_low_aerobic_pct,
            "garmin_load_focus_high_aerobic_pct": snapshot.garmin_load_focus_high_aerobic_pct,
            "garmin_load_focus_anaerobic_pct": snapshot.garmin_load_focus_anaerobic_pct,
            "mood": snapshot.mood,
            "soreness": snapshot.soreness,
            "pred_recovery_days": snapshot.pred_recovery_days,
            "data_sources": snapshot.data_sources,
            "canonical_version": snapshot.canonical_version,
            "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def compute_training_state_history(
        self,
        athlete_id: str,
        days: int = 45,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> Dict:
        """Compute training state history on-demand for a date range."""
        end_date = (
            datetime.now(timezone.utc).date()
            if until is None
            else datetime.fromisoformat(until).date()
        )
        start_date = (
            end_date - timedelta(days=days)
            if since is None
            else datetime.fromisoformat(since).date()
        )
        days = (end_date - start_date).days

        daily_tss = self._prefetch_training_state_history_tss(
            athlete_id,
            start_date,
            end_date,
        )
        full_window_start = start_date - timedelta(days=28)
        cumulative_tss = [0.0]
        current_prefix_date = full_window_start
        while current_prefix_date <= end_date:
            cumulative_tss.append(
                cumulative_tss[-1] + daily_tss.get(current_prefix_date, 0.0)
            )
            current_prefix_date += timedelta(days=1)

        snapshots = []
        current_date = start_date

        while current_date <= end_date:
            current_index = (current_date - full_window_start).days
            tss_7d = cumulative_tss[current_index + 1] - cumulative_tss[current_index - 7]
            tss_28d = cumulative_tss[current_index + 1]
            snapshot = self._build_training_state_snapshot_from_tss(
                athlete_id,
                current_date,
                tss_7d,
                tss_28d,
            )
            snapshots.append({
                "effective_date": snapshot.effective_date,
                "cts_rolling_7d": snapshot.cts_rolling_7d,
                "cts_rolling_28d": snapshot.cts_rolling_28d,
                "ats_rolling": snapshot.ats_rolling,
                "fatigue_index": snapshot.fatigue_index,
                "readiness_score": snapshot.readiness_score,
                "garmin_readiness_score": snapshot.garmin_readiness_score,
                "garmin_training_status": snapshot.garmin_training_status,
                "garmin_training_load": snapshot.garmin_training_load,
                "garmin_recovery_time_hours": snapshot.garmin_recovery_time_hours,
                "garmin_load_focus_low_aerobic_pct": snapshot.garmin_load_focus_low_aerobic_pct,
                "garmin_load_focus_high_aerobic_pct": snapshot.garmin_load_focus_high_aerobic_pct,
                "garmin_load_focus_anaerobic_pct": snapshot.garmin_load_focus_anaerobic_pct,
            })
            current_date += timedelta(days=1)

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "count": len(snapshots),
            "data_points": snapshots,
            "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    # -------------------------------------------------------------------------
    # Training state — internal helpers
    # -------------------------------------------------------------------------

    def _prefetch_training_state_history_tss(
        self,
        athlete_id: str,
        start_date: Any,
        end_date: Any,
    ) -> Dict[Any, float]:
        """Load and resolve workout TSS once for the full history window."""
        full_window_start = start_date - timedelta(days=28)
        start_dt = datetime.combine(full_window_start, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        workouts_table = self.storage.infrastructure.get_table_client("Workouts")
        months = utils.get_month_partitions(athlete_id, start_dt, end_dt)
        workout_entities = self._query_training_window_workouts(
            workouts_table,
            months,
            start_dt,
            end_dt,
        )

        daily_tss: Dict[Any, float] = defaultdict(float)
        for entity in workout_entities:
            workout_date = self._parse_workout_start_date(entity)
            if workout_date is None or workout_date < full_window_start or workout_date > end_date:
                continue

            tss = self._resolve_workout_tss(entity)
            if tss is None:
                continue

            daily_tss[workout_date] += tss

        return dict(daily_tss)

    def _build_training_state_snapshot_from_tss(
        self,
        athlete_id: str,
        date: Any,
        tss_7d: float,
        tss_28d: float,
    ) -> TrainingStateSnapshot:
        """Build a training-state snapshot from precomputed rolling TSS values."""
        training_load = self._compute_training_load_components(tss_7d, tss_28d)
        training_state_physiometrics = self._resolve_training_state_physiometrics_as_of(
            athlete_id,
            date.isoformat(),
        )
        hrv_ln = training_state_physiometrics.get("hrv_ln_rmssd")
        garmin_readiness = training_state_physiometrics.get("readiness_score")
        training_status_label = training_state_physiometrics.get("training_status_label")
        load_focus_low_aerobic_pct = training_state_physiometrics.get("load_focus_low_aerobic_pct")
        load_focus_high_aerobic_pct = training_state_physiometrics.get("load_focus_high_aerobic_pct")
        load_focus_anaerobic_pct = training_state_physiometrics.get("load_focus_anaerobic_pct")
        garmin_training_load = training_state_physiometrics.get("training_load")
        recovery_time_minutes = training_state_physiometrics.get("recovery_time_minutes")
        composite_readiness = self._compute_composite_readiness(
            hrv_ln,
            training_load["fatigue_index"],
        )
        return self._build_training_state_snapshot(
            athlete_id,
            date,
            training_load,
            composite_readiness,
            garmin_readiness,
            garmin_training_load,
            recovery_time_minutes,
            training_status_label,
            load_focus_low_aerobic_pct,
            load_focus_high_aerobic_pct,
            load_focus_anaerobic_pct,
        )

    def _compute_training_state_for_date(
        self,
        athlete_id: str,
        date: Any,
    ) -> TrainingStateSnapshot:
        """Compute TrainingStateSnapshot for a specific date."""
        workouts_table = self.storage.infrastructure.get_table_client("Workouts")
        tss_7d, tss_28d = self._compute_rolling_tss(athlete_id, date, workouts_table)
        snapshot = self._build_training_state_snapshot_from_tss(
            athlete_id,
            date,
            tss_7d,
            tss_28d,
        )

        logger.debug(
            "Computed training state for %s on %s: CTS_7d=%.1f, CTS_28d=%.1f, fatigue_idx=%.2f",
            athlete_id,
            date.isoformat(),
            snapshot.cts_rolling_7d or 0,
            snapshot.cts_rolling_28d or 0,
            snapshot.fatigue_index or 0,
        )

        return snapshot

    @staticmethod
    def _compute_training_load_components(
        tss_7d: float,
        tss_28d: float,
    ) -> Dict[str, Optional[float]]:
        """Compute CTS/ATS/fatigue summary from rolling TSS windows."""
        cts_7d = tss_7d / 7.0 if tss_7d else 0.0
        cts_28d = tss_28d / 28.0 if tss_28d else 0.0
        fatigue_index = None
        if cts_28d > 0:
            fatigue_index = cts_7d / cts_28d
        return {
            "cts_7d": cts_7d,
            "cts_28d": cts_28d,
            "ats": cts_7d,
            "fatigue_index": fatigue_index,
        }

    def _resolve_training_state_physiometrics_as_of(
        self,
        athlete_id: str,
        target_date: str,
    ) -> Dict[str, Any]:
        """Resolve as-of physiometrics inputs needed by training-state projections."""
        source_rows_by_source = self._get_source_rows_by_source(
            athlete_id,
            target_date=target_date,
        )
        resolved: Dict[str, Any] = {}

        for metric_name, sources in TRAINING_STATE_PHYSIOMETRICS_SOURCES.items():
            metric_value, _ = self._resolve_metric_from_sources(
                metric_name,
                sources,
                source_rows_by_source,
            )
            if metric_value is not None:
                resolved[metric_name] = metric_value

        return resolved

    def _load_latest_physiometrics_snapshot(
        self,
        athlete_id: str,
        target_date: str,
    ) -> Optional[PhysiometricsSnapshot]:
        """Load latest typed physiometrics snapshot for athlete as-of target_date."""
        try:
            return self.storage.physiometrics.get_physiometrics_snapshot_as_of(
                athlete_id,
                target_date,
            )
        except StorageError:
            return None

    @staticmethod
    def _build_training_state_snapshot(
        athlete_id: str,
        date: Any,
        training_load: Dict[str, Optional[float]],
        composite_readiness: Optional[float],
        garmin_readiness: Optional[float],
        garmin_training_load: Optional[float] = None,
        recovery_time_minutes: Optional[int] = None,
        training_status_label: Optional[str] = None,
        load_focus_low_aerobic_pct: Optional[float] = None,
        load_focus_high_aerobic_pct: Optional[float] = None,
        load_focus_anaerobic_pct: Optional[float] = None,
    ) -> TrainingStateSnapshot:
        """Build training state snapshot payload from computed inputs."""
        recovery_time_hours = (
            recovery_time_minutes / 60 if recovery_time_minutes is not None else None
        )

        return TrainingStateSnapshot(
            athlete_id=athlete_id,
            effective_date=date.isoformat(),
            cts_rolling_7d=training_load["cts_7d"],
            cts_rolling_28d=training_load["cts_28d"],
            ats_rolling=training_load["ats"],
            fatigue_index=training_load["fatigue_index"],
            readiness_score=composite_readiness,
            garmin_readiness_score=garmin_readiness,
            garmin_training_status=training_status_label,
            garmin_training_load=garmin_training_load,
            garmin_recovery_time_hours=recovery_time_hours,
            garmin_load_focus_low_aerobic_pct=load_focus_low_aerobic_pct,
            garmin_load_focus_high_aerobic_pct=load_focus_high_aerobic_pct,
            garmin_load_focus_anaerobic_pct=load_focus_anaerobic_pct,
            mood=None,
            soreness=None,
            pred_recovery_days=None,
            data_sources="workouts,physiometrics",
            canonical_version="5.1.0",
        )

    def _compute_rolling_tss(
        self,
        athlete_id: str,
        end_date: Any,
        workouts_table: Any,
    ) -> Tuple[float, float]:
        """Compute rolling TSS for last 7 and 28 days from Workouts table."""
        start_date_7 = end_date - timedelta(days=7)
        start_date_28 = end_date - timedelta(days=28)

        start_dt_28 = datetime.combine(start_date_28, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        months = utils.get_month_partitions(athlete_id, start_dt_28, end_dt)
        workout_entities = self._query_training_window_workouts(
            workouts_table,
            months,
            start_dt_28,
            end_dt,
        )

        tss_7d = 0.0
        tss_28d = 0.0

        for entity in workout_entities:
            start_date = self._parse_workout_start_date(entity)
            if start_date is None:
                continue

            tss = self._resolve_workout_tss(entity)
            if tss is None:
                continue

            if start_date_28 <= start_date <= end_date:
                tss_28d += tss
            if start_date_7 <= start_date <= end_date:
                tss_7d += tss

        return tss_7d, tss_28d

    def _query_training_window_workouts(
        self,
        workouts_table: Any,
        months: List[str],
        start_dt: datetime,
        end_dt: datetime,
    ) -> List[Dict[str, Any]]:
        """Query workout entities across all month partitions for the requested window."""
        workout_entities: List[Dict[str, Any]] = []

        for partition_key in months:
            query = utils.build_partition_date_range_query(
                partition_key,
                start_dt,
                end_dt,
            )
            try:
                workout_entities.extend(list(workouts_table.query_entities(query)))
            except HttpResponseError:
                continue

        return workout_entities

    def _parse_workout_start_date(self, entity: Dict[str, Any]) -> Optional[Any]:
        """Parse a workout entity start date from `start_time_utc`."""
        start_str = entity.get("start_time_utc")
        if not start_str:
            return None

        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", UTC_OFFSET))
        except (ValueError, AttributeError):
            return None

        return start_dt.date()

    def _resolve_workout_tss(self, entity: Dict[str, Any]) -> Optional[float]:
        """Resolve workout TSS from the table projection or canonical analytics fallback."""
        tss = entity.get("tss")
        if tss is not None:
            return float(tss)

        try:
            metrics_model = utils.build_rollup_metrics_model(self.storage, entity)
        except (StorageError, ValidationError) as exc:
            logger.warning(
                "Skipping workout in training-state TSS calculation",
                extra={
                    "workout_id": entity.get("workout_id"),
                    "partition_key": entity.get("PartitionKey"),
                    "row_key": entity.get("RowKey"),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None

        training_load = metrics_model.training_load
        if not training_load or training_load.tss is None:
            return None

        return float(training_load.tss)

    def _compute_composite_readiness(
        self,
        hrv_ln: Optional[float],
        fatigue_index: Optional[float],
    ) -> Optional[float]:
        """Compute composite readiness score (0-100) from HRV and fatigue load.

        Both inputs must be present and credible for a score to be produced.
        Garmin native readiness is a separate field (garmin_readiness_score) and
        is never mixed into this calculation.

        Components:
        - HRV (ln_rmssd): normalized from range 2.5–4.5 → 0–100
          formula: clamp((hrv_ln - 2.5) / 2.0 * 100, 0, 100)
        - Fatigue (fatigue_index = cts_7d / cts_28d): inverted from range 0.5–2.0 → 0–100
          formula: clamp((2.0 - fatigue_index) / 1.5 * 100, 0, 100)
        - Score: simple average of the two normalized components
        """
        if hrv_ln is None or fatigue_index is None or fatigue_index <= 0:
            return None

        hrv_normalized = max(0, min(100, (hrv_ln - 2.5) / 2.0 * 100))
        fatigue_normalized = max(0, min(100, (2.0 - fatigue_index) / 1.5 * 100))

        return (hrv_normalized + fatigue_normalized) / 2.0

    # -------------------------------------------------------------------------
    # Physiometrics resolution helpers
    # -------------------------------------------------------------------------

    def _get_source_rows_by_source(
        self,
        athlete_id: str,
        target_date: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get physiometrics rows grouped by source, sorted newest-first."""
        table_client = self.storage.infrastructure.get_table_client("Physiometrics")
        rows = list(table_client.query_entities(f"PartitionKey eq '{athlete_id}'"))
        tracked_sources = {"intervals", "garmin", "withings", "manual", "chatgpt"}
        grouped = build_source_rows_by_source(
            rows,
            tracked_sources=tracked_sources,
            target_date=target_date,
        )
        return {
            source: [dict(source_row) for source_row in source_rows]
            for source, source_rows in grouped.items()
        }

    def _get_latest_source_rows(self, athlete_id: str) -> Dict[str, Dict[str, Any]]:
        """Get latest physiometrics row per source for the athlete."""
        source_rows_by_source = self._get_source_rows_by_source(athlete_id)
        return {
            source: rows[0]
            for source, rows in source_rows_by_source.items()
            if rows
        }

    def _is_row_newer(
        self, candidate: Dict[str, Any], existing: Dict[str, Any]
    ) -> bool:
        """Compare two source rows and return whether candidate is newer."""
        candidate_effective = self._effective_date_from_row(candidate)
        existing_effective = self._effective_date_from_row(existing)
        if candidate_effective > existing_effective:
            return True
        if candidate_effective < existing_effective:
            return False
        return self._parse_iso_timestamp(
            candidate.get("updated_at_utc")
        ) > self._parse_iso_timestamp(existing.get("updated_at_utc"))

    def _update_latest_for_source(
        self,
        latest_per_source: Dict[str, Dict[str, Any]],
        source: str,
        row: Dict[str, Any],
    ) -> None:
        """Insert/replace latest row for a source based on date and update timestamp."""
        existing = latest_per_source.get(source)
        if existing is None or self._is_row_newer(row, existing):
            latest_per_source[source] = row

    @staticmethod
    def _resolve_row_metric_value(
        row: Dict[str, Any], metric_name: str
    ) -> Optional[Any]:
        """Resolve a metric from canonical/storage alias columns."""
        candidate_fields = PHYSIOMETRICS_STORAGE_FIELD_ALIASES.get(metric_name, [metric_name])
        for field_name in candidate_fields:
            value = row.get(field_name)
            if value is not None:
                return value
        return None

    def _resolve_metric_from_sources(
        self,
        metric_name: str,
        sources: List[str],
        source_rows_by_source: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Resolve one metric using source precedence and latest non-null value per source."""
        if metric_name in RECENCY_RESOLVED_BASELINE_METRICS:
            metric_value, row, _ = resolve_latest_metric_across_sources(
                metric_name,
                source_rows_by_source,
                field_aliases=PHYSIOMETRICS_STORAGE_FIELD_ALIASES,
                source_precedence=BASELINE_SOURCE_PRECEDENCE,
            )
            if metric_value is not None:
                return metric_value, row.get("heart_rate_basis") if row else None

        for source in sources:
            source_rows = source_rows_by_source.get(source, [])
            for row in source_rows:
                value = self._resolve_row_metric_value(row, metric_name)
                if value is not None:
                    return value, row.get("heart_rate_basis")
        return None, None

    def _resolve_current_from_precedence(
        self,
        source_rows_by_source: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Resolve consolidated metric values from latest source rows using precedence."""
        resolved: Dict[str, Any] = {}

        for metric_name, sources in PHYSIOMETRICS_SOURCE_PRECEDENCE.items():
            metric_value, basis = self._resolve_metric_from_sources(
                metric_name,
                sources,
                source_rows_by_source,
            )
            if metric_value is None:
                continue
            resolved[metric_name] = metric_value
            if metric_name in {"hr_lthr_bpm", "hr_max_bpm", "resting_hr_bpm"}:
                if isinstance(basis, str) and basis.strip():
                    resolved["heart_rate_basis"] = basis

        return resolved

    @staticmethod
    def _parse_iso_timestamp(value: Optional[str]) -> datetime:
        """Parse ISO timestamp; fallback to minimum UTC time when missing/invalid."""
        return parse_iso_timestamp(value)

    @staticmethod
    def _canonical_sources_from_row(row: Dict[str, Any]) -> Set[str]:
        """Return canonical source IDs present in a physiometrics row."""
        return canonical_sources_from_row(row)

    @staticmethod
    def _effective_date_from_row(row: Dict[str, Any]) -> str:
        """Return the row's effective date fallback key for ordering."""
        return effective_date_from_row(row)
