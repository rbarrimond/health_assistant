"""Semantic Access Layer - Exposes meaningful questions about training data.

This layer sits between the raw metrics DB and the ChatGPT UI.
It shapes data for reasoning, constrains scope, and encodes how humans think about training.
"""
# pylint: disable=too-many-lines

import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, TypedDict
import pandas as pd

from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.models.core import (
    CanonicalAnalyticsEngine,
    WorkoutDetailResponse,
    WorkoutMetricsModel,
    WorkoutProjection,
)
from TrainingAnalyticsPlatform.models.wellness import TrainingStateSnapshot
from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import (
    StorageError,
    ValidationError,
)
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity

if TYPE_CHECKING:
    from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)
UTC_OFFSET = "+00:00"
CANONICAL_DISTORTION_WARN_PCT = float(os.getenv("CANONICAL_DISTORTION_WARN_PCT", "5.0"))
_NON_1HZ_EPSILON_SEC = 1.01

WEEKLY_ROLLUP_REQUIRED_FIELDS = (
    "week_start_utc",
    "week_end_utc",
    "workouts_count",
    "total_duration_min",
    "total_hr_z2_min",
    "total_pwr_z2_min",
    "total_low_aerobic_min",
    "total_intensity_min",
    "last_updated_at_utc",
)

WEEKLY_ROLLUP_OPTIONAL_FIELDS = (
    "total_distance_km",
    "total_elev_m",
    "avg_decoupling_pct",
    "hard_days_count",
    "long_rides_count",
    "athlete_home_timezone",
    "week_start_local",
    "week_end_local",
)

WEEKLY_ROLLUP_ALLOWED_FIELDS = (
    *WEEKLY_ROLLUP_REQUIRED_FIELDS,
    *WEEKLY_ROLLUP_OPTIONAL_FIELDS,
)

# Keep source precedence local to avoid circular import with handlers package.
PHYSIOMETRICS_SOURCE_PRECEDENCE = {
    "weight_kg": ["withings"],
    "fat_mass_kg": ["withings"],
    "muscle_mass_kg": ["withings"],
    "bone_mass_kg": ["withings"],
    "body_fat_pct": ["withings"],
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
}

PHYSIOMETRICS_STORAGE_FIELD_ALIASES = {
    "ftp_watts": ["ftp_watts", "power_ftp_watts"],
    "hr_lthr_bpm": ["hr_lthr_bpm", "heart_rate_lthr_bpm"],
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


class DevFieldSummary(TypedDict):
    """Summary of developer fields in a workout."""
    message_type: str
    field: str
    count: int
    units: set[str]
    sample_values: list[object]


class SemanticLayer:
    """Semantic access layer for workout intelligence queries."""

    def __init__(self, storage: Optional["StorageCoordinator"] = None):
        """Initialize semantic layer with storage backend."""
        if storage is None:
            from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

            self.storage = StorageCoordinator()
        else:
            self.storage = storage

    # -------------------------------------------------------------------------
    # Planning Context - The Most Important Endpoint
    # -------------------------------------------------------------------------

    def get_planning_context(
        self, athlete_id: str, days: int = 45
    ) -> Dict:
        """
        Get planning context for training decisions.

        This is the single most important endpoint:
        GET /api/planning/context?days=N

        Returns everything needed to answer:
        "Given what I've actually done, what does tomorrow look like?"

        Response includes lightweight WorkoutProjection objects (identity + summary + data flags).
        For full metrics, call /api/workouts/{workout_id}.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back (default 45)

        Returns:
            Dict containing:
            - recent_workouts: List of WorkoutProjection objects (last N days)
            - weekly_rollups: Weekly aggregated data
            - last_hard_day: Date of last high-intensity workout
            - last_long_day: Date of last long aerobic workout
            - cumulative_z2_minutes: Total Z2 time in window
            - cumulative_intensity_minutes: Total Z4+ time in window
            - notable_flags: Warnings (missing HR, excessive drift, etc.)
            - query_window: Time range of data
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        # Get full workouts for analysis (need zone data for hard day detection, etc.)
        full_workouts = self._get_workouts_in_range(
            athlete_id, start_date, end_date
        )

        # Get projections for client response (lightweight, efficient for batch queries)
        projections = self._get_workout_projections_in_range(
            athlete_id, start_date, end_date
        )

        # Analyze patterns using full workouts
        last_hard_day = self._find_last_hard_day(full_workouts)
        last_long_day = self._find_last_long_day(full_workouts)
        z2_minutes = self._sum_zone_time(full_workouts, "hr_z2_sec")
        intensity_minutes = self._sum_high_intensity(full_workouts)
        flags = self._detect_notable_flags(full_workouts)

        # Get weekly rollups
        weeks = self._get_weekly_rollups(athlete_id, days)

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "recent_workouts": [p.model_dump() for p in projections],
            "weekly_rollups": weeks,
            "summary": {
                "last_hard_day": last_hard_day,
                "last_long_day": last_long_day,
                "cumulative_z2_minutes": z2_minutes,
                "cumulative_intensity_minutes": intensity_minutes,
                "total_workouts": len(full_workouts),
            },
            "notable_flags": flags,
        }

    # -------------------------------------------------------------------------
    # Workout Queries
    # -------------------------------------------------------------------------

    def get_workouts(
        self,
        athlete_id: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 50,
        sport: Optional[str] = None,
    ) -> List[Dict]:
        """
        Query workouts with filters.

        GET /api/workouts?since=2026-01-01&limit=50&sport=Cycling

        Returns lightweight WorkoutProjection objects (identity + summary + data flags).
        For full metrics, call /api/workouts/{workout_id}.

        Args:
            athlete_id: Athlete identifier
            since: ISO date string (start of range)
            until: ISO date string (end of range)
            limit: Maximum number of workouts to return
            sport: Filter by sport type

        Returns:
            List of WorkoutProjection dictionaries
        """
        # Parse date range
        end_date = (
            datetime.fromisoformat(until.replace("Z", UTC_OFFSET))
            if until
            else datetime.now(timezone.utc)
        )

        # Default to 90 days if no start date
        start_date = (
            datetime.fromisoformat(since.replace("Z", UTC_OFFSET))
            if since
            else end_date - timedelta(days=90)
        )

        projections = self._get_workout_projections_in_range(
            athlete_id, start_date, end_date
        )

        # Filter by sport if specified
        if sport:
            projections = [p for p in projections if p.sport == sport]

        # Apply limit and convert to dicts for response
        return [p.model_dump() for p in projections[:limit]]

    def get_workout_detail(
        self,
        athlete_id: str,
        workout_id: str,
        include_laps: bool = False,
        include_developer_fields: bool = False,
    ) -> Optional[Dict]:
        """
        Get detailed workout data with optional lap summaries.

        GET /api/workouts/{workout_id}

        Args:
            athlete_id: Athlete identifier
            workout_id: Unique workout identifier

        Returns:
            Full workout data, or None if not found
        """
        try:
            entity = self._query_workout_entity(workout_id)
            if entity is None:
                return None

            # Verify athlete_id matches
            if entity.get("athlete_id") != athlete_id:
                return None

            workout_entity = WorkoutEntity.from_table_entity(entity)
            response = self._build_workout_detail_response(entity, workout_entity)

            if include_laps:
                self._populate_workout_detail_laps(response, workout_entity, entity)

            if include_developer_fields:
                self._populate_workout_detail_developer_fields(response, entity, workout_id)

            return response.model_dump(exclude_none=True)

        except HttpResponseError as e:
            logger.error(
                "Error retrieving workout",
                extra={
                    "workout_id": workout_id,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    def _query_workout_entity(self, workout_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single workout entity by workout_id from Workouts table."""
        table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access
        query = f"workout_id eq '{workout_id}'"
        entities = list(table_client.query_entities(query, top=1))
        return entities[0] if entities else None

    def _build_workout_detail_response(
        self,
        entity: Dict[str, Any],
        workout_entity: WorkoutEntity,
    ) -> WorkoutDetailResponse:
        """Build typed workout detail response from table entity and derived metrics."""
        workout = self._entity_to_workout_dict(entity)
        metrics = WorkoutMetricsModel.from_flat_metrics(
            workout,
            metadata={
                "sport": workout.get("sport"),
                "sub_sport": workout.get("sub_sport"),
                "workout_name": workout.get("workout_name"),
                "device_name": workout_entity.device_model,
                "is_indoor": workout.get("is_indoor"),
                "start_time_utc": workout.get("start_time_utc"),
                "local_tz_offset": workout.get("local_tz_offset"),
                "duration_sec": workout.get("duration_sec"),
                "moving_time_sec": workout.get("moving_time_sec"),
                "has_gps": workout_entity.has_gps,
                "hr_resting_bpm": workout.get("hr_resting_bpm"),
            },
        )
        return WorkoutDetailResponse(
            workout_id=workout_entity.workout_id,
            athlete_id=workout_entity.athlete_id,
            source_system=entity.get("source_system"),
            metrics=metrics,
        )

    def _populate_workout_detail_laps(
        self,
        response: WorkoutDetailResponse,
        workout_entity: WorkoutEntity,
        entity: Dict[str, Any],
    ) -> None:
        """Attach lap payload and lap errors to response when available."""
        laps = self._load_stored_laps(workout_entity)
        errors: Dict[str, str] = {}
        if laps is None:
            _, fit_laps, fit_errors = self._load_fit_timeseries(
                entity,
                include_records=False,
                include_laps=True,
            )
            laps = fit_laps
            errors.update(fit_errors)

        if laps is not None:
            response.laps = laps
            response.laps_count = len(laps)
        if errors:
            response.lap_errors = errors

    def _populate_workout_detail_developer_fields(
        self,
        response: WorkoutDetailResponse,
        entity: Dict[str, Any],
        workout_id: str,
    ) -> None:
        """Attach developer field summary, preserving current error behavior."""
        try:
            ingestion_id = entity.get("ingestion_id") or workout_id
            metadata_payload = self.storage.workouts.load_metadata_json(ingestion_id)
            response.developer_fields_summary = self._summarize_developer_fields(metadata_payload)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to load developer fields for workout detail",
                extra={
                    "workout_id": workout_id,
                    "ingestion_id": entity.get("ingestion_id") or workout_id,
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            response.developer_fields_error = str(exc)

    # -------------------------------------------------------------------------
    # Rollup Queries
    # -------------------------------------------------------------------------

    def get_weekly_rollups(
        self, athlete_id: str, weeks: int = 16
    ) -> List[Dict]:
        """
        Get weekly rollup data.

        GET /api/rollups/weekly?weeks=16

        Args:
            athlete_id: Athlete identifier
            weeks: Number of weeks to retrieve

        Returns:
            List of weekly rollup summaries
        """
        return self._get_weekly_rollups(athlete_id, weeks * 7)

    def compute_and_persist_previous_week_rollup(
        self,
        athlete_id: str,
        athlete_home_timezone: Optional[str] = None,
        now_utc: Optional[datetime] = None,
        weeks_ago: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Compute and persist previous completed week rollup using athlete local week semantics."""
        if weeks_ago < 1:
            raise ValidationError("weeks_ago must be >= 1")

        timezone_name = self._resolve_athlete_home_timezone(
            athlete_id=athlete_id,
            fallback_timezone=athlete_home_timezone,
        )
        if not timezone_name:
            logger.warning(
                "Skipping weekly rollup persistence: athlete timezone not configured",
                extra={
                    "athlete_id": athlete_id,
                },
            )
            return None

        try:
            athlete_tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Skipping weekly rollup persistence: invalid athlete timezone",
                extra={
                    "athlete_id": athlete_id,
                    "athlete_home_timezone": timezone_name,
                },
            )
            return None

        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)

        week_window = self._previous_local_week_window(
            now_utc=now,
            athlete_tz=athlete_tz,
            weeks_ago=weeks_ago,
        )
        workouts = self._workouts_for_local_week(
            athlete_id=athlete_id,
            week_start_local=week_window["week_start_local"],
            week_end_local=week_window["week_end_local"],
            athlete_tz=athlete_tz,
        )
        rollup = self._build_weekly_rollup_for_local_window(
            week_start_local=week_window["week_start_local"],
            week_end_local=week_window["week_end_local"],
            athlete_home_timezone=timezone_name,
            week_workouts=workouts,
        )

        iso_year, iso_week, _ = week_window["week_start_local"].isocalendar()
        self.storage.aggregation.update_weekly_rollup(
            athlete_id=athlete_id,
            year=str(iso_year),
            week=f"{iso_week:02d}",
            rollup_data=rollup,
        )
        return rollup

    def compute_and_persist_previous_week_rollups(
        self,
        athlete_ids: Optional[List[str]] = None,
        now_utc: Optional[datetime] = None,
        weeks: int = 1,
    ) -> Dict[str, Any]:
        """Compute and persist previous week rollups for one or many athletes."""
        if weeks < 1:
            raise ValidationError("weeks must be >= 1")

        target_athletes = athlete_ids or self.list_athletes_with_workouts()
        unique_athletes = sorted(set(target_athletes))
        success_count = 0
        skipped_count = 0
        failed_count = 0
        results: List[Dict[str, Any]] = []

        for athlete_id in unique_athletes:
            athlete_results = self._compute_weekly_rollup_athlete_results(
                athlete_id=athlete_id,
                now_utc=now_utc,
                weeks=weeks,
            )
            week_results = athlete_results["weeks"]
            athlete_successes = athlete_results["summary"]["succeeded"]
            athlete_skips = athlete_results["summary"]["skipped"]
            athlete_failures = athlete_results["summary"]["failed"]

            if athlete_failures > 0:
                failed_count += 1
                athlete_status = (
                    "failed"
                    if athlete_successes == 0 and athlete_skips == 0
                    else "partial"
                )
                athlete_message = (
                    "All requested week rollups failed"
                    if athlete_status == "failed"
                    else "Some requested week rollups failed"
                )
            elif athlete_successes > 0:
                success_count += 1
                athlete_status = "success"
                athlete_message = "All requested week rollups persisted successfully"
            else:
                skipped_count += 1
                athlete_status = "skipped"
                athlete_message = "No requested week rollups were persisted"

            results.append(
                {
                    "athlete_id": athlete_id,
                    "status": athlete_status,
                    "message": athlete_message,
                    "weeks": week_results,
                    "summary": {
                        "requested_weeks": weeks,
                        "succeeded": athlete_successes,
                        "skipped": athlete_skips,
                        "failed": athlete_failures,
                    },
                }
            )

        overall_status, overall_message = self._derive_rollup_status_message(
            successes=success_count,
            skips=skipped_count,
            failures=failed_count,
        )

        return {
            "status": overall_status,
            "message": overall_message,
            "results": results,
        }

    def _compute_weekly_rollup_athlete_results(
        self,
        athlete_id: str,
        now_utc: Optional[datetime],
        weeks: int,
    ) -> Dict[str, Any]:
        """Compute per-week outcomes for a single athlete weekly rollup request."""
        week_results: List[Dict[str, Any]] = []
        athlete_successes = 0
        athlete_skips = 0
        athlete_failures = 0

        for weeks_ago in range(1, weeks + 1):
            week_result = self._compute_weekly_rollup_week_result(
                athlete_id=athlete_id,
                now_utc=now_utc,
                weeks_ago=weeks_ago,
            )
            week_results.append(week_result)
            if week_result["status"] == "success":
                athlete_successes += 1
            elif week_result["status"] == "skipped":
                athlete_skips += 1
            else:
                athlete_failures += 1

        return {
            "weeks": week_results,
            "summary": {
                "requested_weeks": weeks,
                "succeeded": athlete_successes,
                "skipped": athlete_skips,
                "failed": athlete_failures,
            },
        }

    def _compute_weekly_rollup_week_result(
        self,
        athlete_id: str,
        now_utc: Optional[datetime],
        weeks_ago: int,
    ) -> Dict[str, Any]:
        """Compute one week result payload for rollup persistence response."""
        try:
            rollup = self.compute_and_persist_previous_week_rollup(
                athlete_id=athlete_id,
                now_utc=now_utc,
                weeks_ago=weeks_ago,
            )
            if rollup is None:
                return {
                    "weeks_ago": weeks_ago,
                    "status": "skipped",
                    "message": "No weekly rollup persisted for requested week",
                }

            return {
                "weeks_ago": weeks_ago,
                "status": "success",
                "message": "Weekly rollup persisted",
                "rollup": rollup,
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed weekly rollup persistence for athlete week",
                extra={
                    "athlete_id": athlete_id,
                    "weeks_ago": weeks_ago,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "weeks_ago": weeks_ago,
                "status": "failed",
                "message": "Failed to persist weekly rollup for requested week",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    @staticmethod
    def _derive_rollup_status_message(
        successes: int,
        skips: int,
        failures: int,
    ) -> Tuple[str, str]:
        """Derive stable status/message for weekly rollup operation outcomes."""
        if failures > 0 and successes == 0 and skips == 0:
            return "failed", "Weekly rollup persistence failed for all requested athletes"
        if failures > 0:
            return "partial", "Weekly rollup persistence completed with partial failures"
        if successes > 0:
            return "success", "Weekly rollup persistence completed successfully"
        return "skipped", "No weekly rollups were persisted for requested athletes"

    def list_athletes_with_workouts(self) -> List[str]:
        """List athlete identifiers observed in Workouts table."""
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access
            athletes: Set[str] = set()
            for entity in table_client.query_entities(""):
                athlete_id = entity.get("athlete_id")
                if athlete_id:
                    athletes.add(str(athlete_id))
                elif isinstance(entity.get("PartitionKey"), str):
                    partition_key = str(entity.get("PartitionKey"))
                    if "|" in partition_key:
                        athletes.add(partition_key.split("|", 1)[0])
            return sorted(athletes)
        except HttpResponseError as exc:
            logger.error(
                "Error listing athletes from workouts",
                extra={
                    "error_type": "HttpResponseError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            return []

    def _resolve_athlete_home_timezone(
        self,
        athlete_id: str,
        fallback_timezone: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve athlete home timezone with athlete-specific precedence first."""
        timezone_name = fallback_timezone
        if not timezone_name:
            timezone_name = self._resolve_timezone_from_agent_preferences(athlete_id)

        if not timezone_name:
            latest_physiometrics = self.storage.physiometrics.get_physiometrics(athlete_id)
            timezone_name = self._timezone_from_physiometrics(latest_physiometrics)

        if not timezone_name:
            timezone_name = Config.get_athlete_timezone()

        return timezone_name

    @staticmethod
    def _clean_timezone_name(value: Any) -> Optional[str]:
        """Normalize candidate timezone values."""
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _timezone_from_physiometrics(self, latest_physiometrics: Any) -> Optional[str]:
        """Extract athlete timezone from physiometrics payload when present."""
        if not isinstance(latest_physiometrics, dict):
            return None

        athlete_info = latest_physiometrics.get("athlete_info")
        if isinstance(athlete_info, dict):
            timezone_name = self._clean_timezone_name(athlete_info.get("home_timezone"))
            if timezone_name:
                return timezone_name

        return self._clean_timezone_name(latest_physiometrics.get("athlete_timezone"))

    def _resolve_timezone_from_agent_preferences(self, athlete_id: str) -> Optional[str]:
        """Resolve athlete timezone from long-lived AgentPreferences records."""
        try:
            table_client = self.storage.infrastructure.get_table_client("AgentPreferences")  # pylint: disable=protected-access
            entities = table_client.query_entities(f"PartitionKey eq '{athlete_id}'")
            matches = []
            valid_categories = {"athlete_home_timezone", "home_timezone"}

            for entity in entities:
                if entity.get("RowKey") == "preferences":
                    continue

                category = entity.get("category")
                status = entity.get("status", "active")
                summary = entity.get("summary")
                if category not in valid_categories or status != "active":
                    continue
                if not isinstance(summary, str) or not summary.strip():
                    continue

                matches.append(
                    (
                        entity.get("updated_at") or entity.get("created_at") or "",
                        summary.strip(),
                    )
                )

            if not matches:
                return None

            matches.sort(key=lambda item: item[0], reverse=True)
            return matches[0][1]

        except HttpResponseError as exc:
            logger.warning(
                "Failed to resolve timezone from AgentPreferences",
                extra={
                    "athlete_id": athlete_id,
                    "error_type": "HttpResponseError",
                    "error": str(exc),
                },
            )
            return None

    # -------------------------------------------------------------------------
    # Analysis Queries
    # -------------------------------------------------------------------------

    def get_zone_distribution(
        self, athlete_id: str, days: int = 30
    ) -> Dict:
        """
        Get time-in-zone distribution for planning.

        GET /api/analysis/zones?days=30

        Args:
            athlete_id: Athlete identifier
            days: Number of days to analyze

        Returns:
            Dict with zone distribution percentages
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        workouts = self._get_workouts_in_range(
            athlete_id, start_date, end_date
        )

        # Aggregate zone minutes (use HR zones as primary, fallback to power)
        zones = {
            "z1": 0.0,
            "z2": 0.0,
            "z3": 0.0,
            "z4": 0.0,
            "z5": 0.0,
        }

        for workout in workouts:
            for i, zone in enumerate(["z1", "z2", "z3", "z4", "z5"], 1):
                # Try HR zone first, then power zone
                hr_sec = workout.get(f"hr_z{i}_sec", 0) or 0
                pwr_sec = workout.get(f"pwr_z{i}_sec", 0) or 0
                # Use whichever has data, prefer HR
                zone_sec = hr_sec if hr_sec > 0 else pwr_sec
                zones[zone] += zone_sec / 60  # Convert to minutes

        total_minutes = sum(zones.values())

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "total_minutes": total_minutes,
            "zones": zones,
            "percentages": {
                zone: round((minutes / total_minutes * 100), 1) if total_minutes > 0 else 0
                for zone, minutes in zones.items()
            },
        }

    def get_efficiency_trends(
        self, athlete_id: str, days: int = 90
    ) -> Dict:
        """
        Get aerobic efficiency and decoupling trends.

        GET /api/analysis/efficiency?days=90

        Args:
            athlete_id: Athlete identifier
            days: Number of days to analyze

        Returns:
            Dict with efficiency metrics over time
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        workouts = self._get_workouts_in_range(
            athlete_id, start_date, end_date
        )

        # Filter for workouts with efficiency data
        efficiency_data = []
        for workout in workouts:
            if workout.get("decoupling_pct") is not None:
                efficiency_data.append({
                    "date": workout.get("start_time_utc"),
                    "sport": workout.get("sport"),
                    "decoupling_pct": workout.get("decoupling_pct"),
                    "ef_overall": workout.get("ef_overall"),
                    "hr_drift_bpm": workout.get("hr_drift_bpm"),
                })

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "samples": efficiency_data,
            "summary": {
                "total_samples": len(efficiency_data),
                "avg_decoupling": (
                    round(
                        sum(d["decoupling_pct"] for d in efficiency_data) / len(efficiency_data),
                        2
                    )
                    if efficiency_data
                    else None
                ),
            },
        }

    # -------------------------------------------------------------------------
    # Private Helper Methods
    # -------------------------------------------------------------------------

    def _get_workouts_in_range(
        self,
        athlete_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict]:
        """
        Retrieve workouts within a date range.

        Args:
            athlete_id: Athlete identifier
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)
        Returns:
            List of workout dicts
        """
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access

            # Build query for athlete and date range
            # PartitionKey format: athlete_id|YYYY-MM
            # We need to query multiple partitions if range spans multiple months
            months = self._get_month_partitions(athlete_id, start_date, end_date)

            workouts = []
            for partition_key in months:
                workouts.extend(
                    self._collect_partition_workouts(
                        table_client=table_client,
                        partition_key=partition_key,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )

            # Sort by date descending (newest first)
            workouts.sort(
                key=lambda w: w.get("start_time_utc", ""), reverse=True
            )

            return workouts

        except HttpResponseError as e:
            logger.error(
                "Error querying workouts",
                extra={
                    "athlete_id": athlete_id,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return []

    def _collect_partition_workouts(
        self,
        table_client: Any,
        partition_key: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict[str, Any]]:
        """Collect workouts for a single partition constrained to date window."""
        query = self._build_partition_date_range_query(
            partition_key,
            start_date,
            end_date,
        )
        entities = table_client.query_entities(query)

        workouts: List[Dict[str, Any]] = []
        for entity in entities:
            workout_start = entity.get("start_time_utc")
            if not workout_start:
                continue

            try:
                workout_date = datetime.fromisoformat(
                    workout_start.replace("Z", UTC_OFFSET)
                ).astimezone(timezone.utc)
            except ValueError:
                continue

            if not (start_date <= workout_date <= end_date):
                continue

            workout = self._entity_to_workout_dict(entity)
            workouts.append(workout)

        return workouts

    def _get_workout_projections_in_range(
        self,
        athlete_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[WorkoutProjection]:
        """
        Retrieve WorkoutProjection objects for a date range (efficient for batch queries).

        Returns lightweight projections (identity + summary + data flags, no computation)
        suitable for planning context and list endpoints.

        Args:
            athlete_id: Athlete identifier
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)

        Returns:
            List of WorkoutProjection objects sorted by date (newest first)
        """
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access
            months = self._get_month_partitions(athlete_id, start_date, end_date)
            projections = self._collect_workout_projections(
                table_client,
                months,
                start_date,
                end_date,
            )
            projections.sort(key=lambda p: p.start_time_utc or "", reverse=True)
            return projections

        except HttpResponseError as e:
            logger.error(
                "Error querying workout projections",
                extra={
                    "athlete_id": athlete_id,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return []

    def _collect_workout_projections(
        self,
        table_client: Any,
        months: List[str],
        start_date: datetime,
        end_date: datetime,
    ) -> List[WorkoutProjection]:
        """Collect projections for entities that fall in the requested date window."""
        projections: List[WorkoutProjection] = []
        for partition_key in months:
            query = self._build_partition_date_range_query(
                partition_key,
                start_date,
                end_date,
            )
            entities = table_client.query_entities(query)
            for entity in entities:
                if not self._entity_within_date_range(entity, start_date, end_date):
                    continue
                projection = self.build_workout_projection(entity)
                if projection is not None:
                    projections.append(projection)
        return projections

    @staticmethod
    def _build_partition_date_range_query(
        partition_key: str,
        start_date: datetime,
        end_date: datetime,
    ) -> str:
        """Build a PartitionKey-scoped query with UTC `start_time_utc` bounds."""
        start_utc = start_date.astimezone(timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
        end_utc = end_date.astimezone(timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
        return (
            f"PartitionKey eq '{partition_key}' "
            f"and start_time_utc ge '{start_utc}' "
            f"and start_time_utc le '{end_utc}'"
        )

    def _entity_within_date_range(
        self,
        entity: Dict[str, Any],
        start_date: datetime,
        end_date: datetime,
    ) -> bool:
        """Return True when entity start time exists and falls within [start_date, end_date]."""
        workout_start = entity.get("start_time_utc")
        if not workout_start:
            return False
        workout_date = datetime.fromisoformat(
            workout_start.replace("Z", UTC_OFFSET)
        ).astimezone(timezone.utc)
        return start_date <= workout_date <= end_date

    def _get_month_partitions(
        self, athlete_id: str, start_date: datetime, end_date: datetime
    ) -> List[str]:
        """
        Generate partition keys for all months in date range.

        Args:
            athlete_id: Athlete identifier
            start_date: Start date
            end_date: End date

        Returns:
            List of partition key strings (e.g., ['rob|2026-01', 'rob|2026-02'])
        """
        partitions = []
        current = start_date.replace(day=1)

        while current <= end_date:
            partition_key = f"{athlete_id}|{current.strftime('%Y-%m')}"
            partitions.append(partition_key)

            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return partitions

    def _entity_to_workout_dict(self, entity: Dict) -> Dict:
        """
        Convert Azure Table entity to workout dict.

        Args:
            entity: Raw table entity

        Returns:
            Cleaned workout dict
        """
        workout_entity = WorkoutEntity.from_table_entity(entity)
        metadata_blob = self._load_metadata_blob_for_workout(entity, workout_entity)
        session, enrichment, activity_metadata = self._extract_workout_metadata_sections(
            metadata_blob
        )

        # Combine zones for inferential methods.
        metrics = {**session, **enrichment, **activity_metadata}
        metrics = self._apply_canonical_metrics(workout_entity, metrics)
        workout = self._build_workout_base_dict(
            workout_entity,
            session,
            enrichment,
            activity_metadata,
            metrics,
        )
        self._add_workout_capability_metrics(workout, metrics)

        return workout

    def _load_metadata_blob_for_workout(
        self,
        entity: Dict[str, Any],
        workout_entity: WorkoutEntity,
    ) -> Dict[str, Any]:
        """Load metadata.json blob for workout-centric transformations."""
        lookup_id = entity.get("ingestion_id") or workout_entity.workout_id
        return self._load_metadata_blob(lookup_id, workout_entity.workout_id)

    def _load_metadata_blob(self, lookup_id: str, workout_id: str) -> Dict[str, Any]:
        """Load metadata blob and normalize non-dict payloads to an empty dict."""
        try:
            metadata_blob = self.storage.workouts.load_metadata_json(lookup_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug(
                "Could not load metadata blob",
                extra={
                    "lookup_id": lookup_id,
                    "workout_id": workout_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return {}
        return metadata_blob if isinstance(metadata_blob, dict) else {}

    @staticmethod
    def _extract_workout_metadata_sections(
        metadata_blob: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Return session, enrichment, and activity metadata sections from metadata blob."""
        return (
            metadata_blob.get("session", {}),
            metadata_blob.get("enrichment", {}),
            metadata_blob.get("activity_metadata", {}),
        )

    def _build_workout_base_dict(
        self,
        workout_entity: WorkoutEntity,
        session: Dict[str, Any],
        enrichment: Dict[str, Any],
        activity_metadata: Dict[str, Any],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build workout identity and summary fields with schema-defined precedence."""
        sport = workout_entity.sport or self._infer_sport(metrics)
        local_tz_offset = activity_metadata.get("local_tz_offset")
        return {
            "workout_id": workout_entity.workout_id,
            "athlete_id": workout_entity.athlete_id,
            "sport": sport,
            "sub_sport": workout_entity.sub_sport or enrichment.get("sub_sport") or sport,
            "workout_name": enrichment.get("workout_name")
            or self._infer_workout_name(metrics, sport),
            "is_indoor": enrichment.get("is_indoor") or self._infer_is_indoor(metrics),
            "start_time_utc": workout_entity.start_time_utc,
            "local_tz_offset": local_tz_offset,
            "timezone": local_tz_offset,
            "duration_sec": workout_entity.duration_sec or session.get("duration_sec"),
            "moving_time_sec": session.get("moving_time_sec"),
            "distance_m": workout_entity.distance_m or session.get("distance_m"),
            "elevation_gain_m": session.get("elevation_gain_m"),
            "elevation_loss_m": session.get("elevation_loss_m"),
            "calories_kcal": session.get("calories_kcal")
            or self._infer_calories(metrics, sport),
        }

    def _add_workout_capability_metrics(
        self,
        workout: Dict[str, Any],
        metrics: Dict[str, Any],
    ) -> None:
        """Attach capability-specific and sample-level metrics onto workout response."""
        if metrics.get("hr_avg_bpm"):
            workout.update(
                self._select_fields(
                    metrics,
                    {
                        "hr_avg_bpm",
                        "hr_max_bpm",
                        "hr_min_bpm",
                        "hr_samples_count",
                        "hr_missing_pct",
                        "hr_z1_sec",
                        "hr_z2_sec",
                        "hr_z3_sec",
                        "hr_z4_sec",
                        "hr_z5_sec",
                        "hr_zone_total_sec",
                        "hr_zone_basis",
                        "hr_zone_reference_bpm",
                    },
                )
            )

        if metrics.get("pwr_avg_watts"):
            workout.update(
                self._select_fields(
                    metrics,
                    {
                        "pwr_avg_watts",
                        "pwr_max_watts",
                        "pwr_normalized_watts",
                        "pwr_variability_index",
                        "pwr_samples_count",
                        "pwr_missing_pct",
                        "cad_avg_rpm",
                        "cad_max_rpm",
                        "cad_samples_count",
                        "pwr_z1_sec",
                        "pwr_z2_sec",
                        "pwr_z3_sec",
                        "pwr_z4_sec",
                        "pwr_z5_sec",
                        "pwr_z6_sec",
                        "pwr_z7_sec",
                        "low_aerobic_sec",
                        "intensity_sec",
                        "ftp_watts",
                        "intensity_factor",
                        "tss",
                        "decoupling_pct",
                        "hr_drift_bpm",
                        "ef_first_half",
                        "ef_second_half",
                        "ef_overall",
                    },
                )
            )

        workout.update(
            self._select_fields(
                metrics,
                {
                    "hr_samples_count",
                    "hr_missing_pct",
                    "pwr_samples_count",
                    "pwr_missing_pct",
                    "cad_samples_count",
                    "cad_avg_rpm",
                    "cad_max_rpm",
                },
            )
        )

    def _apply_canonical_metrics(
        self,
        workout_entity: WorkoutEntity,
        metrics: Dict,
    ) -> Dict:
        """Derive metrics from canonical parquet when table metrics are missing."""
        has_baseline_metrics = bool(metrics.get("hr_avg_bpm") or metrics.get("pwr_avg_watts"))
        hr_zone_total_inconsistent = self._is_hr_zone_total_inconsistent(metrics)

        if has_baseline_metrics and not hr_zone_total_inconsistent:
            return metrics

        blob_name = workout_entity.canonical_records_blob or metrics.get(
            "canonical_records_blob"
        )
        if not blob_name:
            return metrics

        try:
            df = self.storage.workouts.load_canonical_records(blob_name)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to load canonical records",
                extra={
                    "blob_name": blob_name,
                    "workout_id": workout_entity.workout_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return metrics

        if df.empty:
            return metrics

        enriched = dict(metrics)
        enriched.update(self._compute_metrics_from_canonical(df, enriched))
        return enriched

    @staticmethod
    def _is_hr_zone_total_inconsistent(metrics: Dict[str, Any]) -> bool:
        """Return True when HR zone total is absent/mismatched against per-zone seconds."""
        zone_values = [float(metrics.get(f"hr_z{i}_sec") or 0) for i in range(1, 6)]
        zones_sum = float(sum(zone_values))
        total = metrics.get("hr_zone_total_sec")

        has_any_zone = any(value > 0 for value in zone_values)
        if not has_any_zone:
            return False
        if total is None:
            return True

        try:
            return float(total) != zones_sum
        except (TypeError, ValueError):
            return True

    def _compute_metrics_from_canonical(
        self,
        df: pd.DataFrame,
        metadata: Dict,
    ) -> Dict:
        """Compute derived metrics using CanonicalAnalyticsEngine."""
        try:
            canonical = CanonicalAnalyticsEngine.from_dataframe(df, metadata)
        except ValidationError as exc:
            distortion = self._canonical_sampling_distortion(df)
            try:
                canonical = CanonicalAnalyticsEngine.from_dataframe(df, metadata, resample=True)
            except ValidationError:
                logger.warning(
                    "Canonical analytics computation skipped: canonical validation error",
                    extra={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "record_count": len(df),
                        "failure_category": "canonical_sampling_validation",
                        "is_1hz_validation_failure": True,
                        **distortion,
                    },
                )
                return self._compute_basic_metrics_from_canonical(df)

            self._log_canonical_resample_fallback(
                scope="semantic_metrics",
                strict_error=exc,
                record_count=len(df),
                distortion=distortion,
            )
        return canonical.to_metrics_dict()

    def _canonical_sampling_distortion(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Compute sparse-gap distortion summary for canonical timeline."""
        if "timestamp_utc" not in df.columns or df.empty:
            return {
                "gap_count": 0,
                "max_gap_sec": 0.0,
                "inserted_missing_bins": 0,
                "distortion_pct": None,
            }

        timestamps = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
        timestamps = timestamps.dropna().sort_values().reset_index(drop=True)
        if len(timestamps) < 2:
            return {
                "gap_count": 0,
                "max_gap_sec": 0.0,
                "inserted_missing_bins": 0,
                "distortion_pct": None,
            }

        diffs = timestamps.diff().dt.total_seconds().dropna()
        gaps = diffs[diffs > _NON_1HZ_EPSILON_SEC]
        if gaps.empty:
            return {
                "gap_count": 0,
                "max_gap_sec": 0.0,
                "inserted_missing_bins": 0,
                "distortion_pct": 0.0,
            }

        span_sec = float((timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds())
        inserted_missing_bins = int(sum(max(int(round(float(gap))) - 1, 0) for gap in gaps))
        distortion_pct = (
            round((inserted_missing_bins / span_sec) * 100, 3)
            if span_sec > 0
            else None
        )
        return {
            "gap_count": int(len(gaps)),
            "max_gap_sec": round(float(gaps.max()), 3),
            "inserted_missing_bins": inserted_missing_bins,
            "distortion_pct": distortion_pct,
        }

    def _log_canonical_resample_fallback(
        self,
        *,
        scope: str,
        strict_error: ValidationError,
        record_count: int,
        distortion: Dict[str, Any],
        workout_id: Optional[str] = None,
        blob_name: Optional[str] = None,
    ) -> None:
        """Log strict->resample canonical fallback with thresholded warning level."""
        distortion_pct = distortion.get("distortion_pct")
        exceeds_threshold = (
            isinstance(distortion_pct, (int, float))
            and distortion_pct > CANONICAL_DISTORTION_WARN_PCT
        )
        log_level = logger.warning if exceeds_threshold else logger.info
        log_level(
            "Canonical analytics strict validation failed; resample fallback applied",
            extra={
                "scope": scope,
                "workout_id": workout_id,
                "blob_name": blob_name,
                "error_type": type(strict_error).__name__,
                "error": str(strict_error),
                "record_count": record_count,
                "failure_category": "canonical_sampling_validation",
                "is_1hz_validation_failure": True,
                "resample_fallback_applied": True,
                "distortion_warn_threshold_pct": CANONICAL_DISTORTION_WARN_PCT,
                "distortion_warn_exceeded": exceeds_threshold,
                **distortion,
            },
        )

    def _compute_basic_metrics_from_canonical(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Compute minimal sample statistics when full canonical analytics are unavailable."""
        metrics: Dict[str, Any] = {}
        row_count = len(df)
        if row_count == 0:
            return metrics

        if "heart_rate_bpm" in df.columns:
            hr = pd.to_numeric(df["heart_rate_bpm"], errors="coerce")
            hr_valid = hr.notna()
            hr_count = int(hr_valid.sum())
            metrics["hr_samples_count"] = hr_count
            metrics["hr_missing_pct"] = float((1 - (hr_count / row_count)) * 100)
            if hr_count > 0:
                metrics["hr_avg_bpm"] = float(hr[hr_valid].mean())
                metrics["hr_max_bpm"] = float(hr[hr_valid].max())
                metrics["hr_min_bpm"] = float(hr[hr_valid].min())

        if "power_watts" in df.columns:
            pwr = pd.to_numeric(df["power_watts"], errors="coerce")
            pwr_valid = pwr.notna()
            pwr_count = int(pwr_valid.sum())
            metrics["pwr_samples_count"] = pwr_count
            metrics["pwr_missing_pct"] = float((1 - (pwr_count / row_count)) * 100)
            if pwr_count > 0:
                metrics["pwr_avg_watts"] = float(pwr[pwr_valid].mean())
                metrics["pwr_max_watts"] = float(pwr[pwr_valid].max())

        if "cadence_rpm" in df.columns:
            cad = pd.to_numeric(df["cadence_rpm"], errors="coerce")
            cad_valid = cad.notna()
            cad_count = int(cad_valid.sum())
            metrics["cad_samples_count"] = cad_count
            if cad_count > 0:
                metrics["cad_avg_rpm"] = float(cad[cad_valid].mean())
                metrics["cad_max_rpm"] = float(cad[cad_valid].max())

        return metrics

    def build_workout_projection(
        self,
        entity: Dict,
        ingestion_id: Optional[str] = None,
    ) -> Optional[WorkoutProjection]:
        """
        Build lightweight WorkoutProjection from Workouts table entity + metadata.json.
        
        Used for efficient planning context and list queries. Projection contains:
        - Identity fields (workout_id, sport, device, timestamps)
        - Session summary (duration, distance, elevation, calories)
        - Data availability flags (has_power, has_hr, has_gps)
        - Sport-specific peaks (HR/power/cadence if available)
        - Status/enrichment flags (indoor, race, commute)
        - Provenance (ingestion version, timestamp)
        
        All fields extracted directly from WorkoutEntity + metadata.json (no computation).
        
        Args:
            entity: Raw Azure Table entity (Workouts table)
            ingestion_id: Optional override for metadata blob lookup (else uses entity ingestion_id)
            
        Returns:
            WorkoutProjection typed model, or None if critical fields missing
        """
        try:
            workout_entity = WorkoutEntity.from_table_entity(entity)
            lookup_id = ingestion_id or entity.get("ingestion_id") or workout_entity.workout_id
            metadata_blob = self._load_projection_metadata_blob(lookup_id, workout_entity.workout_id)
            metadata = self._extract_projection_metadata_sections(metadata_blob)
            projection_kwargs = self._build_workout_projection_kwargs(workout_entity, metadata)
            return WorkoutProjection(**projection_kwargs)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Error building workout projection",
                extra={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return None

    def _load_projection_metadata_blob(self, lookup_id: str, workout_id: str) -> Dict[str, Any]:
        """Load metadata blob used by projection paths and normalize non-dict payloads."""
        metadata_blob = self._load_metadata_blob(lookup_id, workout_id)
        if metadata_blob:
            return metadata_blob
        logger.debug(
            "Could not load metadata blob for projection",
            extra={
                "lookup_id": lookup_id,
                "workout_id": workout_id,
            },
        )
        return {}

    def _extract_projection_metadata_sections(
        self,
        metadata_blob: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Extract projection metadata sections used to build WorkoutProjection."""
        return {
            "identity": metadata_blob.get("identity", {}),
            "session": metadata_blob.get("session", {}),
            "enrichment": metadata_blob.get("enrichment", {}),
            "capabilities": metadata_blob.get("capabilities", {}),
            "activity_metadata": metadata_blob.get("activity_metadata", {}),
            "provenance": metadata_blob.get("provenance", {}),
        }

    def _build_workout_projection_kwargs(
        self,
        workout_entity: WorkoutEntity,
        metadata: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble validated kwargs for WorkoutProjection construction."""
        start_time_utc = self._resolve_projection_start_time(workout_entity, metadata)
        if not start_time_utc:
            raise ValueError("Missing required start_time_utc for workout projection")

        has_power = bool(workout_entity.has_power or metadata["capabilities"].get("has_power", False))
        has_hr = bool(workout_entity.has_hr or metadata["capabilities"].get("has_hr", False))
        has_gps = bool(workout_entity.has_gps or metadata["capabilities"].get("has_gps", False))
        capability_metrics = self._projection_capability_metrics(
            metadata["session"],
            has_hr,
            has_power,
        )

        projection_kwargs = {
            "workout_id": workout_entity.workout_id,
            "athlete_id": workout_entity.athlete_id,
            "sport": workout_entity.sport or metadata["identity"].get("sport") or "unknown",
            "sub_sport": workout_entity.sub_sport or metadata["identity"].get("sub_sport") or metadata["enrichment"].get("sub_sport"),
            "workout_name": metadata["enrichment"].get("workout_name") or metadata["identity"].get("workout_name"),
            "device_name": metadata["identity"].get("device_name") or workout_entity.device_model,
            "device_manufacturer": workout_entity.device_manufacturer or metadata["identity"].get("device_manufacturer"),
            "start_time_utc": start_time_utc,
            "local_tz_offset": metadata["activity_metadata"].get("local_tz_offset"),
            "timezone": metadata["activity_metadata"].get("timezone") or metadata["activity_metadata"].get("local_tz_offset"),
            "duration_sec": workout_entity.duration_sec or metadata["session"].get("duration_sec") or 0,
            "moving_time_sec": metadata["session"].get("moving_time_sec"),
            "distance_m": workout_entity.distance_m or metadata["session"].get("distance_m"),
            "elevation_gain_m": metadata["session"].get("elevation_gain_m"),
            "elevation_loss_m": metadata["session"].get("elevation_loss_m"),
            "calories_kcal": metadata["session"].get("calories_kcal"),
            "has_power": has_power,
            "has_hr": has_hr,
            "has_gps": has_gps,
            "is_indoor": bool(metadata["enrichment"].get("is_indoor", False)),
            "race_flag": bool(metadata["enrichment"].get("race_flag", False)),
            "commute_flag": bool(metadata["enrichment"].get("commute_flag", False)),
            "ingestion_version": metadata["provenance"].get("ingestion_version"),
            "ingestion_timestamp_utc": metadata["provenance"].get("ingestion_timestamp_utc"),
        }
        projection_kwargs.update(capability_metrics)
        return projection_kwargs

    def _projection_capability_metrics(
        self,
        session_metrics: Dict[str, Any],
        has_hr: bool,
        has_power: bool,
    ) -> Dict[str, Any]:
        """Return capability-dependent projection metrics (HR/power) plus cadence values."""
        return {
            "hr_avg_bpm": session_metrics.get("hr_avg_bpm") if has_hr else None,
            "hr_max_bpm": session_metrics.get("hr_max_bpm") if has_hr else None,
            "pwr_avg_watts": session_metrics.get("pwr_avg_watts") if has_power else None,
            "pwr_max_watts": session_metrics.get("pwr_max_watts") if has_power else None,
            "pwr_normalized_watts": session_metrics.get("pwr_normalized_watts") if has_power else None,
            "cad_avg_rpm": session_metrics.get("cad_avg_rpm"),
            "cad_max_rpm": session_metrics.get("cad_max_rpm"),
        }

    def _resolve_projection_start_time(
        self,
        workout_entity: WorkoutEntity,
        metadata: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        """Resolve start time for projection from entity first, then metadata fallbacks."""
        return (
            workout_entity.start_time_utc
            or metadata["identity"].get("start_time_utc")
            or metadata["session"].get("start_time_utc")
        )

    def _load_stored_laps(self, workout_entity: WorkoutEntity) -> Optional[List[Dict]]:
        ingestion_id: str = ""
        try:
            ingestion_id = workout_entity.ingestion_id or workout_entity.workout_id
            payload = self.storage.workouts.load_laps_json(ingestion_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to load laps.json",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "ingestion_id": ingestion_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None
        laps = payload.get("laps") if isinstance(payload, dict) else None
        if not isinstance(laps, list) or not laps:
            return None
        return laps

    def get_workout_lap_detail(
        self,
        athlete_id: str,
        workout_id: str,
        lap_index: int,
    ) -> Optional[Dict]:
        """Get detailed lap data for a specific workout lap."""
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access
            query = f"workout_id eq '{workout_id}'"
            entities = list(table_client.query_entities(query, top=1))
            if not entities:
                return None

            entity = entities[0]
            if entity.get("athlete_id") != athlete_id:
                return None

            ingestion_id = entity.get("ingestion_id") or workout_id
            laps_payload = self.storage.workouts.load_laps_json(ingestion_id)
            laps = laps_payload.get("laps") if isinstance(laps_payload, dict) else None
            if not isinstance(laps, list) or not laps:
                return None

            lap_payload = None
            for lap in laps:
                if lap.get("message_index") == lap_index:
                    lap_payload = lap
                    break
            if lap_payload is None and 0 <= lap_index < len(laps):
                lap_payload = laps[lap_index]
            if lap_payload is None:
                return None

            return {
                "workout_id": workout_id,
                "athlete_id": athlete_id,
                "lap_index": lap_index,
                "lap": lap_payload,
            }

        except HttpResponseError as e:
            logger.error(
                "Error retrieving lap",
                extra={
                    "workout_id": workout_id,
                    "athlete_id": athlete_id,
                    "lap_index": lap_index,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    def _load_fit_timeseries(
        self,
        entity: Dict,
        *,
        include_records: bool,
        include_laps: bool,
    ) -> Tuple[Optional[List[Dict]], Optional[List[Dict]], Dict[str, str]]:
        records: Optional[List[Dict]] = None
        laps: Optional[List[Dict]] = None
        errors: Dict[str, str] = {}

        if include_records:
            records, error = self._load_canonical_records_payload(entity)
            if error:
                errors["records_error"] = error

        if include_laps:
            laps, error = self._load_laps_json_payload(entity)
            if error:
                errors["laps_error"] = error

        return records, laps, errors

    def _load_canonical_records_payload(
        self, entity: Dict
    ) -> tuple[Optional[List[Dict]], Optional[str]]:
        workout_id = entity.get("workout_id")
        ingestion_id = entity.get("ingestion_id") or workout_id
        if not ingestion_id:
            return None, "No workout id available"

        records_blob = entity.get("canonical_records_blob") or f"{ingestion_id}/canonical.parquet"
        try:
            records_df = self.storage.workouts.load_canonical_records(records_blob)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, str(exc)

        if records_df.empty:
            return None, None
        return records_df.to_dict(orient="records"), None

    def _load_laps_json_payload(
        self, entity: Dict
    ) -> tuple[Optional[List[Dict]], Optional[str]]:
        workout_id = entity.get("workout_id")
        ingestion_id = entity.get("ingestion_id") or workout_id
        if not ingestion_id:
            return None, "No workout id available"

        try:
            payload = self.storage.workouts.load_laps_json(ingestion_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, str(exc)

        laps = payload.get("laps") if isinstance(payload, dict) else None
        if not isinstance(laps, list) or not laps:
            return None, None
        return laps, None

    @staticmethod
    def _set_timeseries_error(
        errors: Dict[str, str],
        include_records: bool,
        include_laps: bool,
        message: str,
    ) -> None:
        if include_records:
            errors["records_error"] = message
        if include_laps:
            errors["laps_error"] = message

    @staticmethod
    def _iter_metadata_messages(metadata_payload: Dict):
        for message_type, messages in metadata_payload.items():
            if not isinstance(messages, list):
                continue
            for message in messages:
                yield message_type, message

    @staticmethod
    def _iter_developer_fields(message: Dict):
        msg_fields = message.get("fields", {})
        if not isinstance(msg_fields, dict):
            return
        for field_name, field_payload in msg_fields.items():
            if str(field_name).startswith("dev_"):
                yield field_name, field_payload

    @staticmethod
    def _extract_units_and_value(field_payload: object) -> tuple[Optional[str], Optional[object]]:
        if isinstance(field_payload, dict):
            return field_payload.get("units"), field_payload.get("value")
        return None, None

    def _summarize_developer_fields(self, metadata_payload: Dict) -> Dict:
        """Build a compact developer-field summary from metadata artifact."""
        fields_by_key: Dict[str, DevFieldSummary] = {}
        for message_type, message in self._iter_metadata_messages(metadata_payload):
            for field_name, field_payload in self._iter_developer_fields(message):
                key = f"{message_type}.{field_name}"
                entry = fields_by_key.setdefault(
                    key,
                    DevFieldSummary(
                        {
                            "message_type": message_type,
                            "field": field_name,
                            "count": 0,
                            "units": set(),
                            "sample_values": [],
                        }
                    ),
                )
                entry["count"] = int(entry["count"]) + 1
                units, value = self._extract_units_and_value(field_payload)
                if units:
                    entry["units"].add(units)
                if value is not None and len(entry["sample_values"]) < 3:
                    entry["sample_values"].append(value)

        fields = []
        for entry in fields_by_key.values():
            fields.append(
                {
                    "message_type": entry["message_type"],
                    "field": entry["field"],
                    "count": entry["count"],
                    "units": sorted(entry["units"]),
                    "sample_values": entry["sample_values"],
                }
            )
        fields.sort(key=lambda item: (item["message_type"], item["field"]))
        return {
            "field_count": len(fields),
            "fields": fields,
        }


    @staticmethod
    def _select_fields(source: Dict, fields: set[str]) -> Dict:
        return {field: source.get(field) for field in fields}


    @staticmethod
    def _infer_sport(metrics: Dict) -> str:
        sport = metrics.get("sport")
        if sport:
            return sport

        sub_sport = metrics.get("sub_sport")
        if sub_sport:
            lowered = sub_sport.lower()
            if "cycling" in lowered or "bike" in lowered:
                return "cycling"
            if "run" in lowered:
                return "running"
            if "swim" in lowered:
                return "swimming"
        return "unknown"

    @staticmethod
    def _infer_is_indoor(metrics: Dict) -> bool:
        is_indoor = metrics.get("is_indoor")
        if is_indoor is not None:
            return bool(is_indoor)

        elevation = metrics.get("elevation_gain_m", 0) or 0
        distance = metrics.get("distance_m", 0) or 0
        return bool(distance > 100 and elevation < 5)

    @staticmethod
    def _infer_workout_name(metrics: Dict, sport: str) -> str:
        workout_name = metrics.get("workout_name")
        if workout_name:
            return workout_name

        start_time = metrics.get("start_time_utc")
        if start_time:
            try:
                parsed = datetime.fromisoformat(
                    str(start_time).replace("Z", UTC_OFFSET)
                )
                return f"{sport.title()} - {parsed.strftime('%b %d, %Y')}"
            except (ValueError, AttributeError):
                return f"{sport.title()} Workout"

        return f"{sport.title()} Workout"

    @staticmethod
    def _infer_calories(metrics: Dict, sport: str) -> Optional[int]:
        calories = metrics.get("calories_kcal")
        if calories is not None:
            return calories

        duration_min = (metrics.get("duration_sec") or 0) / 60
        if "run" in sport.lower():
            return int(duration_min * 15)
        return int(duration_min * 10)

    def _get_weekly_rollups(
        self, athlete_id: str, days: int
    ) -> List[Dict]:
        """
        Get weekly rollup data for specified number of days.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back

        Returns:
            List of weekly rollup dicts
        """
        # Calculate week range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        try:
            table_client = self.storage.infrastructure.get_table_client("WeeklyRollups")  # pylint: disable=protected-access
            rollups = []

            # Query each year partition
            # Note: Currently queries all weeks in range years (can be optimized later)
            current = start_date
            years = set()
            while current <= end_date:
                years.add(current.year)
                current = current + timedelta(days=7)

            for year in sorted(years):
                entities_for_year: List[Dict[str, Any]] = []
                for delimiter in ("|", "#"):
                    partition_key = f"{athlete_id}{delimiter}{year}"
                    query = f"PartitionKey eq '{partition_key}'"
                    entities = [dict(e) for e in table_client.query_entities(query)]
                    if entities:
                        entities_for_year = entities
                        break

                for entity in entities_for_year:
                    rollups.append(dict(entity))

            # Sort by week descending
            rollups.sort(key=lambda r: r.get("RowKey", ""), reverse=True)
            normalized_rollups = []
            for entity in rollups:
                normalized = self._normalize_weekly_rollup_entity(
                    athlete_id=athlete_id,
                    entity=entity,
                )
                if normalized is not None:
                    normalized_rollups.append(normalized)

            if not normalized_rollups:
                logger.info(
                    "No precomputed weekly rollups found; computing from workouts",
                    extra={
                        "athlete_id": athlete_id,
                        "days": days,
                    },
                )
                return self._compute_weekly_rollups_from_workouts(
                    athlete_id=athlete_id,
                    start_date=start_date,
                    end_date=end_date,
                )

            return normalized_rollups

        except HttpResponseError as e:
            logger.error(
                "Error retrieving weekly rollups",
                extra={
                    "athlete_id": athlete_id,
                    "days": days,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return []

    def _normalize_weekly_rollup_entity(
        self, athlete_id: str, entity: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Normalize raw WeeklyRollups table entity to strict API schema."""
        missing_fields = [
            field for field in WEEKLY_ROLLUP_REQUIRED_FIELDS
            if entity.get(field) is None
        ]
        if missing_fields:
            logger.warning(
                "Skipping malformed weekly rollup entity",
                extra={
                    "athlete_id": athlete_id,
                    "partition_key": entity.get("PartitionKey"),
                    "row_key": entity.get("RowKey"),
                    "missing_fields": missing_fields,
                },
            )
            return None

        normalized = {}
        for field in WEEKLY_ROLLUP_ALLOWED_FIELDS:
            value = entity.get(field)
            if value is not None:
                normalized[field] = value

        return normalized

    def _compute_weekly_rollups_from_workouts(
        self,
        athlete_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict[str, Any]]:
        """Compute weekly rollups on read from workouts when table rollups are unavailable."""
        metrics_models = self._get_rollup_metrics_models_in_range(
            athlete_id=athlete_id,
            start_date=start_date,
            end_date=end_date,
        )
        if not metrics_models:
            return []

        weekly_buckets = self._bucket_workouts_by_week(metrics_models)
        rollups = [
            self._build_weekly_rollup(week_start, week_workouts)
            for week_start, week_workouts in weekly_buckets.items()
        ]
        rollups.sort(key=lambda item: item["week_start_utc"], reverse=True)
        return rollups

    def _bucket_workouts_by_week(
        self, workouts: List[WorkoutMetricsModel]
    ) -> Dict[datetime, List[WorkoutMetricsModel]]:
        """Organize workouts into weekly buckets."""
        weekly_buckets: Dict[datetime, List[WorkoutMetricsModel]] = {}
        for workout in workouts:
            week_start = self._extract_week_start(workout)
            if week_start:
                weekly_buckets.setdefault(week_start, []).append(workout)
        return weekly_buckets

    @staticmethod
    def _previous_local_week_window(
        now_utc: datetime,
        athlete_tz: ZoneInfo,
        weeks_ago: int = 1,
    ) -> Dict[str, datetime]:
        """Return previous completed local week boundaries and UTC query window."""
        if weeks_ago < 1:
            raise ValidationError("weeks_ago must be >= 1")

        now_local = now_utc.astimezone(athlete_tz)
        current_week_start_local = (
            now_local
            - timedelta(
                days=now_local.weekday(),
                hours=now_local.hour,
                minutes=now_local.minute,
                seconds=now_local.second,
                microseconds=now_local.microsecond,
            )
        )
        week_start_local = current_week_start_local - timedelta(days=7 * weeks_ago)
        week_end_local = week_start_local + timedelta(days=7) - timedelta(seconds=1)

        return {
            "week_start_local": week_start_local,
            "week_end_local": week_end_local,
            "query_start_utc": week_start_local.astimezone(timezone.utc),
            "query_end_utc": week_end_local.astimezone(timezone.utc),
        }

    def _workouts_for_local_week(
        self,
        athlete_id: str,
        week_start_local: datetime,
        week_end_local: datetime,
        athlete_tz: ZoneInfo,
    ) -> List[WorkoutMetricsModel]:
        """Get rollup metrics models belonging to athlete local week based on Workouts.start_time_utc."""
        entities = self._get_rollup_entities_in_range(
            athlete_id=athlete_id,
            start_date=week_start_local.astimezone(timezone.utc),
            end_date=week_end_local.astimezone(timezone.utc),
        )
        included: List[WorkoutMetricsModel] = []
        skipped_missing_start = 0
        skipped_invalid_start = 0
        candidate_entities: List[Dict[str, Any]] = []
        for entity in entities:
            start_time_utc = entity.get("start_time_utc")
            if not start_time_utc:
                skipped_missing_start += 1
                continue
            try:
                workout_start_utc = datetime.fromisoformat(
                    str(start_time_utc).replace("Z", UTC_OFFSET)
                ).astimezone(timezone.utc)
            except ValueError:
                skipped_invalid_start += 1
                continue
            workout_start_local = workout_start_utc.astimezone(athlete_tz)
            if week_start_local <= workout_start_local <= week_end_local:
                candidate_entities.append(entity)

        for entity in candidate_entities:
            included.append(self._build_rollup_metrics_model(entity))

        if skipped_missing_start or skipped_invalid_start:
            logger.warning(
                "Skipping workouts with malformed Workouts.start_time_utc while building weekly rollup",
                extra={
                    "athlete_id": athlete_id,
                    "week_start_local": week_start_local.isoformat(),
                    "week_end_local": week_end_local.isoformat(),
                    "candidate_workouts": len(entities),
                    "included_workouts": len(included),
                    "skipped_missing_start_time_utc": skipped_missing_start,
                    "skipped_invalid_start_time_utc": skipped_invalid_start,
                },
            )
        included.sort(
            key=lambda model: model.session.start_time_utc or "",
            reverse=True,
        )
        return included

    def _build_weekly_rollup_for_local_window(
        self,
        week_start_local: datetime,
        week_end_local: datetime,
        athlete_home_timezone: str,
        week_workouts: List[WorkoutMetricsModel],
    ) -> Dict[str, Any]:
        """Build weekly rollup with local-week authoritative semantics and persisted timezone context."""
        week_start_utc = week_start_local.astimezone(timezone.utc)
        week_end_utc = week_end_local.astimezone(timezone.utc)
        rollup = self._build_weekly_rollup(
            week_start=week_start_utc,
            week_workouts=week_workouts,
        )
        rollup["week_start_utc"] = week_start_utc.isoformat()
        rollup["week_end_utc"] = week_end_utc.isoformat()
        rollup["week_start_local"] = week_start_local.isoformat()
        rollup["week_end_local"] = week_end_local.isoformat()
        rollup["athlete_home_timezone"] = athlete_home_timezone
        return rollup

    def _extract_week_start(self, workout: WorkoutMetricsModel) -> Optional[datetime]:
        """Extract and normalize week start date from a workout."""
        start_time_utc = workout.session.start_time_utc
        if not start_time_utc:
            raise StorageError(
                "Missing start_time_utc while grouping weekly workouts"
            )
        try:
            workout_date = datetime.fromisoformat(
                str(start_time_utc).replace("Z", UTC_OFFSET)
            ).astimezone(timezone.utc)
            week_start = (
                workout_date
                - timedelta(
                    days=workout_date.weekday(),
                    hours=workout_date.hour,
                    minutes=workout_date.minute,
                    seconds=workout_date.second,
                    microseconds=workout_date.microsecond,
                )
            )
            return week_start
        except ValueError as exc:
            raise StorageError(
                "Invalid start_time_utc while grouping weekly workouts"
            ) from exc

    def _build_weekly_rollup(
        self, week_start: datetime, week_workouts: List[WorkoutMetricsModel]
    ) -> Dict[str, Any]:
        """Build a single weekly rollup from workouts."""
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        now_utc = datetime.now(timezone.utc).isoformat()

        rollup: Dict[str, Any] = {
            "week_start_utc": week_start.isoformat(),
            "week_end_utc": week_end.isoformat(),
            "workouts_count": len(week_workouts),
            "total_duration_min": round(sum(
                float(workout.session.duration_sec or 0) / 60
                for workout in week_workouts
            ), 2),
            "total_hr_z2_min": round(sum(
                float(workout.zones_hr.hr_z2_sec or 0) / 60
                for workout in week_workouts
                if workout.zones_hr is not None
            ), 2),
            "total_pwr_z2_min": round(sum(
                float(workout.zones_power.pwr_z2_sec or 0) / 60
                for workout in week_workouts
                if workout.zones_power is not None
            ), 2),
            "total_low_aerobic_min": round(sum(
                float(workout.zones_power.low_aerobic_sec or 0) / 60
                for workout in week_workouts
                if workout.zones_power is not None
            ), 2),
            "total_intensity_min": round(sum(
                float(workout.zones_power.intensity_sec or 0) / 60
                for workout in week_workouts
                if workout.zones_power is not None
            ), 2),
            "last_updated_at_utc": now_utc,
        }

        # Add optional aggregated metrics
        self._add_optional_rollup_metrics(rollup, week_workouts)
        
        # Add derived counts
        rollup["hard_days_count"] = sum(
            1
            for workout in week_workouts
            if workout.zones_power is not None
            and float(workout.zones_power.intensity_sec or 0) > 300
        )
        rollup["long_rides_count"] = sum(
            1
            for workout in week_workouts
            if max(
                float(workout.zones_hr.hr_z2_sec or 0)
                if workout.zones_hr is not None else 0,
                float(workout.zones_power.pwr_z2_sec or 0)
                if workout.zones_power is not None else 0,
            ) > 3600
        )

        return rollup

    def _add_optional_rollup_metrics(
        self, rollup: Dict[str, Any], week_workouts: List[WorkoutMetricsModel]
    ) -> None:
        """Add optional aggregated metrics to rollup if data is available."""
        distance_values_m = [
            float(workout.distance.distance_m)
            for workout in week_workouts
            if workout.distance.distance_m is not None
        ]
        elevation_values_m = [
            float(workout.distance.elevation_gain_m)
            for workout in week_workouts
            if workout.distance.elevation_gain_m is not None
        ]
        decoupling_values = [
            float(workout.durability.decoupling_pct)
            for workout in week_workouts
            if workout.durability is not None
            and workout.durability.decoupling_pct is not None
        ]

        if distance_values_m:
            rollup["total_distance_km"] = round(sum(distance_values_m) / 1000, 2)
        if elevation_values_m:
            rollup["total_elev_m"] = round(sum(elevation_values_m), 2)
        if decoupling_values:
            rollup["avg_decoupling_pct"] = round(
                sum(decoupling_values) / len(decoupling_values),
                2,
            )

    def _get_rollup_metrics_models_in_range(
        self,
        athlete_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[WorkoutMetricsModel]:
        """Load weekly-rollup input models from canonical parquet for a date range."""
        entities = self._get_rollup_entities_in_range(
            athlete_id=athlete_id,
            start_date=start_date,
            end_date=end_date,
        )
        metrics_models = [self._build_rollup_metrics_model(entity) for entity in entities]
        metrics_models.sort(
            key=lambda model: model.session.start_time_utc or "",
            reverse=True,
        )
        return metrics_models

    def _get_rollup_entities_in_range(
        self,
        athlete_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict[str, Any]]:
        """Load Workouts entities for rollup processing within a UTC date range."""
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access
            months = self._get_month_partitions(athlete_id, start_date, end_date)
            entities_in_range: List[Dict[str, Any]] = []

            for partition_key in months:
                query = self._build_partition_date_range_query(
                    partition_key,
                    start_date,
                    end_date,
                )
                entities = table_client.query_entities(query)
                for entity in entities:
                    if not self._entity_within_date_range(entity, start_date, end_date):
                        continue
                    entities_in_range.append(entity)

            return entities_in_range

        except HttpResponseError as exc:
            logger.error(
                "Error querying rollup entities",
                extra={
                    "athlete_id": athlete_id,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "error_type": "HttpResponseError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            return []

    def _build_rollup_metrics_model(
        self,
        entity: Dict[str, Any],
    ) -> WorkoutMetricsModel:
        """Build the typed rollup input model from canonical parquet for one workout."""
        workout_entity = WorkoutEntity.from_table_entity(entity)
        metadata_blob = self._load_metadata_blob_for_workout(entity, workout_entity)
        canonical_metadata = self._prepare_rollup_metadata_for_canonical(
            metadata_blob,
            workout_entity,
        )

        blob_name = workout_entity.canonical_records_blob or entity.get("canonical_records_blob")
        if not blob_name:
            raise StorageError(
                "Missing canonical records blob for weekly rollup workout"
            )

        try:
            df = self.storage.workouts.load_canonical_records(blob_name)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed to load canonical records for weekly rollup",
                extra={
                    "blob_name": blob_name,
                    "workout_id": workout_entity.workout_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise StorageError("Failed to load canonical records for weekly rollup") from exc

        if df.empty:
            raise StorageError(
                "Canonical records parquet is empty for weekly rollup workout"
            )

        try:
            return WorkoutMetricsModel.from_canonical(df, canonical_metadata)
        except ValidationError as exc:
            distortion = self._canonical_sampling_distortion(df)
            try:
                model = WorkoutMetricsModel.from_canonical(
                    df,
                    canonical_metadata,
                    resample=True,
                )
            except ValidationError:
                logger.error(
                    "Weekly rollup canonical validation failed",
                    extra={
                        "workout_id": workout_entity.workout_id,
                        "blob_name": blob_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "failure_category": "canonical_sampling_validation",
                        "is_1hz_validation_failure": True,
                        "status_code": exc.status_code,
                        **distortion,
                    },
                    exc_info=True,
                )
                raise ValidationError(
                    "Weekly rollup canonical validation failed for workout "
                    f"{workout_entity.workout_id} (blob={blob_name}): {exc}",
                    status_code=exc.status_code,
                ) from exc

            self._log_canonical_resample_fallback(
                scope="weekly_rollup",
                workout_id=workout_entity.workout_id,
                blob_name=blob_name,
                strict_error=exc,
                record_count=len(df),
                distortion=distortion,
            )
            return model
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed to build WorkoutMetricsModel for weekly rollup",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "blob_name": blob_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "failure_category": "workout_metrics_model_build",
                    "is_1hz_validation_failure": False,
                },
                exc_info=True,
            )
            raise StorageError("Failed to build WorkoutMetricsModel for weekly rollup") from exc

    @staticmethod
    def _prepare_rollup_metadata_for_canonical(
        metadata_blob: Dict[str, Any],
        workout_entity: WorkoutEntity,
    ) -> Dict[str, Any]:
        """Prepare canonical metadata for analytics engine with authoritative metadata precedence.

        Weekly rollup metadata artifacts are stored in semantic zones (`identity`, `session`,
        `enrichment`, `activity_metadata`). `CanonicalAnalyticsEngine` expects top-level keys,
        so this method projects authoritative metadata fields to top level while preserving any
        existing top-level values already present.
        """
        metadata = dict(metadata_blob) if isinstance(metadata_blob, dict) else {}
        identity_raw = metadata.get("identity")
        session_raw = metadata.get("session")
        enrichment_raw = metadata.get("enrichment")
        activity_raw = metadata.get("activity_metadata")

        identity: Dict[str, Any] = identity_raw if isinstance(identity_raw, dict) else {}
        session: Dict[str, Any] = session_raw if isinstance(session_raw, dict) else {}
        enrichment: Dict[str, Any] = (
            enrichment_raw if isinstance(enrichment_raw, dict) else {}
        )
        activity: Dict[str, Any] = activity_raw if isinstance(activity_raw, dict) else {}

        promoted_defaults = {
            "start_time_utc": (
                identity.get("start_time_utc")
                or session.get("start_time_utc")
                or workout_entity.start_time_utc
            ),
            "sport": identity.get("sport") or workout_entity.sport,
            "sub_sport": identity.get("sub_sport") or workout_entity.sub_sport,
            "workout_name": enrichment.get("workout_name"),
            "device_name": identity.get("device_name") or workout_entity.device_model,
            "is_indoor": enrichment.get("is_indoor"),
            "local_tz_offset": activity.get("local_tz_offset"),
            "duration_sec": session.get("duration_sec") or workout_entity.duration_sec,
            "moving_time_sec": session.get("moving_time_sec"),
            "distance_m": session.get("distance_m") or workout_entity.distance_m,
            "elevation_gain_m": session.get("elevation_gain_m"),
            "elevation_loss_m": session.get("elevation_loss_m"),
            "calories_kcal": session.get("calories_kcal"),
        }

        for key, value in promoted_defaults.items():
            if metadata.get(key) is None and value is not None:
                metadata[key] = value

        return metadata

    def _find_last_hard_day(self, workouts: List[Dict]) -> Optional[str]:
        """
        Find date of last high-intensity workout.

        High intensity = intensity_sec > 300 (5 minutes)
        """
        for workout in workouts:
            intensity_sec = float(workout.get("intensity_sec") or 0)
            if intensity_sec > 300:  # > 5 minutes
                return workout.get("start_time_utc")

        return None

    def _find_last_long_day(self, workouts: List[Dict]) -> Optional[str]:
        """
        Find date of last long aerobic workout.

        Long = Z2 seconds > 3600 (60 minutes)
        """
        for workout in workouts:
            # Check HR Z2 or power Z2 (stored in seconds)
            hr_z2_sec = workout.get("hr_z2_sec", 0) or 0
            pwr_z2_sec = workout.get("pwr_z2_sec", 0) or 0
            z2_sec = max(hr_z2_sec, pwr_z2_sec)

            if z2_sec > 3600:  # > 60 minutes
                return workout.get("start_time_utc")

        return None

    def _sum_zone_time(
        self, workouts: List[Dict], zone_field: str
    ) -> float:
        """Sum zone time across workouts, converting to minutes.
        
        Args:
            workouts: List of workout dicts
            zone_field: Field name (e.g., 'hr_z2_sec', 'pwr_z2_sec')
            
        Returns:
            Total time in minutes, rounded to 2 decimal places
        """
        total = 0
        for workout in workouts:
            value = workout.get(zone_field, 0) or 0
            # Convert seconds to minutes if field name ends with _sec
            if zone_field.endswith("_sec"):
                total += value / 60
            else:
                total += value
        return round(total, 2)

    def _sum_high_intensity(self, workouts: List[Dict]) -> float:
        """Sum high intensity minutes (Z4+) across workouts."""
        total = 0.0
        for workout in workouts:
            total += float(workout.get("intensity_sec") or 0) / 60
        return total

    def _detect_notable_flags(self, workouts: List[Dict]) -> List[str]:
        """
        Detect notable issues in recent workouts.

        Returns list of human-readable warning strings.
        """
        flags = []

        # Check for workouts missing HR data
        no_hr_count = sum(1 for w in workouts if not w.get("hr_avg_bpm"))
        if no_hr_count > 0:
            flags.append(f"{no_hr_count} workout(s) missing heart rate data")

        # Check for excessive decoupling
        high_decoupling = [
            w for w in workouts
            if w.get("decoupling_pct", 0) and w["decoupling_pct"] > 5.0
        ]
        if high_decoupling:
            flags.append(
                f"{len(high_decoupling)} workout(s) with high decoupling (>5%)"
            )

        # Check for very short workouts (possible data issues)
        very_short = [
            w for w in workouts
            if w.get("duration_sec", 0) and w["duration_sec"] < 600  # < 10 min
        ]
        if very_short:
            flags.append(f"{len(very_short)} very short workout(s) (<10 min)")

        return flags

    # -------------------------------------------------------------------------
    # Physiometrics Management
    # -------------------------------------------------------------------------

    def get_current_physiometrics(self, athlete_id: str) -> Dict:
        """
        Get current physiometric values for an athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Dict containing current weight, FTP, LTHR, cycling VO2Max, body composition, etc.
        """
        source_rows = self._get_latest_source_rows(athlete_id)
        if not source_rows:
            return {
                "athlete_id": athlete_id,
                "error": "No physiometrics data found"
            }

        merged = self._resolve_current_from_precedence(source_rows)
        data_sources = sorted(source_rows.keys())
        source_effective_dates = {
            source: row.get("effective_date")
            for source, row in source_rows.items()
            if row.get("effective_date")
        }
        latest_effective_date = max(
            (d for d in source_effective_dates.values() if d is not None),
            default=None
        )

        # Extract values for easy consumption
        result = {
            "athlete_id": athlete_id,
            "heart_rate": {
                "basis": merged.get("heart_rate_basis"),
                "lthr_bpm": merged.get("hr_lthr_bpm"),
                "hr_max_bpm": merged.get("hr_max_bpm"),
                "resting_hr_bpm": merged.get("resting_hr_bpm"),
            },
            "power": {
                "ftp_watts": merged.get("ftp_watts"),
            },
        }

        # Add body composition if present
        optional_metrics = [
            "weight_kg",
            "fat_mass_kg",
            "muscle_mass_kg",
            "bone_mass_kg",
            "body_fat_pct",
            "visceral_fat_index",
            "metabolic_age_years",
            "cycling_vo2max_ml_kg_min",
            "running_vo2max_ml_kg_min",
            "training_load",
            "training_effect_aerobic",
            "training_effect_anaerobic",
            "training_stress_score",
            "training_stress_balance",
            "atp_probability",
            "recovery_time_minutes",
            "lactate_threshold_hr_bpm",
            "hrv_ln_rmssd",
            "hrv_sdnn_ms",
            "sleep_duration_sec",
            "readiness_score",
            "soreness",
            "fatigue",
            "stress",
            "mood",
            "motivation",
            "injury",
            "steps",
            "spo2_pct",
            "systolic_bp",
            "diastolic_bp",
        ]
        for metric_name in optional_metrics:
            if merged.get(metric_name) is not None:
                result[metric_name] = merged.get(metric_name)

        # Add metadata
        if latest_effective_date:
            result["effective_date"] = latest_effective_date
        result["data_sources"] = data_sources
        if source_effective_dates:
            result["source_effective_dates"] = source_effective_dates

        return result

    @staticmethod
    def _parse_iso_timestamp(value: Optional[str]) -> datetime:
        """Parse ISO timestamp; fallback to minimum UTC time when missing/invalid."""
        if not value:
            return datetime.min.replace(tzinfo=timezone.utc)
        normalized = value.replace("Z", UTC_OFFSET)
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _canonical_sources_from_row(row: Dict[str, Any]) -> Set[str]:
        """Return canonical source IDs present in a physiometrics row."""
        sources: Set[str] = set()
        singular = row.get("data_source")
        if isinstance(singular, str) and singular.strip():
            sources.add(singular.strip().lower())
        csv_sources = row.get("data_sources")
        if isinstance(csv_sources, str) and csv_sources.strip():
            for value in csv_sources.split(","):
                normalized = value.strip().lower()
                if normalized:
                    sources.add(normalized)
        return sources

    @staticmethod
    def _effective_date_from_row(row: Dict[str, Any]) -> str:
        """Return the row's effective date fallback key for ordering."""
        return row.get("effective_date") or row.get("RowKey", "")

    def _is_row_newer(self, candidate: Dict[str, Any], existing: Dict[str, Any]) -> bool:
        """Compare two source rows and return whether candidate is newer."""
        candidate_effective = self._effective_date_from_row(candidate)
        existing_effective = self._effective_date_from_row(existing)
        if candidate_effective > existing_effective:
            return True
        if candidate_effective < existing_effective:
            return False
        return self._parse_iso_timestamp(candidate.get("updated_at_utc")) > self._parse_iso_timestamp(
            existing.get("updated_at_utc")
        )

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

    def _get_latest_source_rows(self, athlete_id: str) -> Dict[str, Dict[str, Any]]:
        """Get latest physiometrics row per source for the athlete."""
        table_client = self.storage.infrastructure.get_table_client("Physiometrics")
        rows = list(table_client.query_entities(f"PartitionKey eq '{athlete_id}'"))
        tracked_sources = {"intervals", "garmin", "withings", "manual", "chatgpt"}
        latest_per_source: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            for source in self._canonical_sources_from_row(row):
                if source not in tracked_sources:
                    continue
                self._update_latest_for_source(latest_per_source, source, row)

        return latest_per_source

    @staticmethod
    def _resolve_row_metric_value(row: Dict[str, Any], metric_name: str) -> Optional[Any]:
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
        latest_source_rows: Dict[str, Dict[str, Any]],
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Resolve one metric using source precedence order."""
        for source in sources:
            row = latest_source_rows.get(source)
            if row is None:
                continue
            value = self._resolve_row_metric_value(row, metric_name)
            if value is not None:
                return value, row.get("heart_rate_basis")
        return None, None

    def _resolve_current_from_precedence(
        self, latest_source_rows: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Resolve consolidated metric values from latest source rows using precedence."""
        resolved: Dict[str, Any] = {}

        for metric_name, sources in PHYSIOMETRICS_SOURCE_PRECEDENCE.items():
            metric_value, basis = self._resolve_metric_from_sources(
                metric_name,
                sources,
                latest_source_rows,
            )
            if metric_value is None:
                continue
            resolved[metric_name] = metric_value
            if metric_name in {"hr_lthr_bpm", "hr_max_bpm", "resting_hr_bpm"}:
                if isinstance(basis, str) and basis.strip():
                    resolved["heart_rate_basis"] = basis

        return resolved

    def get_physiometrics_trends(self, athlete_id: str, days: int = 90,
                                metrics: Optional[List[str]] = None) -> Dict:
        """
        Get time-series physiometric trends.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back
            metrics: List of specific metrics to return (None = all)

        Returns:
            Dict with query window and time-series data points
        """
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        history = self.storage.physiometrics.get_physiometrics_history(
            athlete_id=athlete_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            metrics=metrics
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

    def update_physiometric_value(self, athlete_id: str,
                                  metric: str,
                                  value: float,
                                  effective_date: Optional[str] = None,
                                  source: str = "chatgpt") -> Dict:
        """
        Update a single physiometric value.

        Args:
            athlete_id: Athlete identifier
            metric: Metric name (e.g., "weight_kg", "cycling_vo2max_ml_kg_min")
            value: New value
            effective_date: ISO date when effective (defaults to today)
            source: Source of update (chatgpt, manual, withings)

        Returns:
            Dict with update confirmation
        """
        try:
            timestamp = self.storage.physiometrics.update_single_metric(
                athlete_id=athlete_id,
                metric_name=metric,
                value=value,
                effective_date=effective_date,
                data_source=source
            )

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
                "error": str(e)
            }

    def recalculate_workout_zones(self, workout_id: str,
                                 physiometrics_override: Optional[Dict] = None) -> Dict:
        """
        Recalculate workout zones with different physiometric values (read-only).

        This provides a "what-if" view of how zones would look with different FTP/LTHR,
        without modifying the original workout data.

        Args:
            workout_id: Workout identifier
            physiometrics_override: Dict with ftp_watts and/or lthr_bpm to use

        Returns:
            Dict with recalculated zone data
        """
        # Placeholder until retroactive zone recalculation is implemented.
        # Expected steps:
        # 1. Fetch original workout and time series records
        # 2. Recompute zones using override values
        # 3. Return new zone distribution without storing

        return {
            "status": "not_implemented",
            "message": "Retroactive zone recalculation coming soon",
            "workout_id": workout_id,
            "override": physiometrics_override,
        }

    # -------------------------------------------------------------------------
    # Training State Projections (On-Demand Computation)
    # -------------------------------------------------------------------------

    def compute_current_training_state(self, athlete_id: str) -> Dict:
        """
        Compute current training state on-demand from Workouts + Physiometrics.

        IMPORTANT: TrainingState is a pure projection - NOT stored in a table.
        Computed fresh for each API request.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Dict containing TrainingStateSnapshot with:
            - cts_rolling_7d, cts_rolling_28d, ats_rolling, fatigue_index
            - readiness_score, garmin_readiness_score
            - effective_date (today)
        """
        end_date = datetime.now(timezone.utc).date()
        
        # Compute TrainingStateSnapshot for today
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
            "mood": snapshot.mood,
            "soreness": snapshot.soreness,
            "pred_recovery_days": snapshot.pred_recovery_days,
            "data_sources": snapshot.data_sources,
            "canonical_version": snapshot.canonical_version,
            "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def compute_training_state_history(
        self, athlete_id: str, days: int = 45
    ) -> Dict:
        """
        Compute training state history on-demand for a date range.

        Computes TrainingStateSnapshot for each day in the range by querying
        Workouts table and calculating rolling TSS. NOT stored - pure projection.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back (default 45)

        Returns:
            Dict with query window and list of daily training state snapshots
        """
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)
        
        # Compute training state for each day in range
        snapshots = []
        current_date = start_date
        
        while current_date <= end_date:
            snapshot = self._compute_training_state_for_date(athlete_id, current_date)
            snapshots.append({
                "effective_date": snapshot.effective_date,
                "cts_rolling_7d": snapshot.cts_rolling_7d,
                "cts_rolling_28d": snapshot.cts_rolling_28d,
                "ats_rolling": snapshot.ats_rolling,
                "fatigue_index": snapshot.fatigue_index,
                "readiness_score": snapshot.readiness_score,
                "garmin_readiness_score": snapshot.garmin_readiness_score,
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

    def _compute_training_state_for_date(
        self, athlete_id: str, date: Any  # datetime.date
    ) -> TrainingStateSnapshot:
        """
        Compute TrainingStateSnapshot for a specific date (internal helper).

        Args:
            athlete_id: Athlete identifier
            date: Target date (datetime.date)

        Returns:
            TrainingStateSnapshot with computed training state metrics
        """
        workouts_table = self.storage.infrastructure.get_table_client("Workouts")
        phys_table = self.storage.infrastructure.get_table_client("Physiometrics")

        tss_7d, tss_28d = self._compute_rolling_tss(
            athlete_id, date, workouts_table
        )
        training_load = self._compute_training_load_components(tss_7d, tss_28d)
        latest_physio = self._load_latest_physiometrics_snapshot(phys_table, athlete_id)
        hrv_ln = latest_physio.get("hrv_ln_rmssd")
        garmin_readiness = latest_physio.get("readiness_score")
        composite_readiness = self._compute_composite_readiness(
            hrv_ln,
            training_load["fatigue_index"],
            garmin_readiness,
        )
        snapshot = self._build_training_state_snapshot(
            athlete_id,
            date,
            training_load,
            composite_readiness,
            garmin_readiness,
        )

        logger.debug(
            "Computed training state for %s on %s: CTS_7d=%.1f, CTS_28d=%.1f, fatigue_idx=%.2f",
            athlete_id,
            date.isoformat(),
            training_load["cts_7d"] or 0,
            training_load["cts_28d"] or 0,
            training_load["fatigue_index"] or 0,
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

    @staticmethod
    def _load_latest_physiometrics_snapshot(
        phys_table: Any,
        athlete_id: str,
    ) -> Dict[str, Any]:
        """Load latest physiometrics row for athlete, returning empty dict on query errors."""
        physio_filter = f"PartitionKey eq '{athlete_id}'"
        try:
            physio_entities = list(phys_table.query_entities(physio_filter))
        except HttpResponseError:
            return {}
        physio_entities.sort(key=lambda e: e.get("effective_date", ""), reverse=True)
        return physio_entities[0] if physio_entities else {}

    @staticmethod
    def _build_training_state_snapshot(
        athlete_id: str,
        date: Any,
        training_load: Dict[str, Optional[float]],
        composite_readiness: Optional[float],
        garmin_readiness: Optional[float],
    ) -> TrainingStateSnapshot:
        """Build training state snapshot payload from computed inputs."""
        return TrainingStateSnapshot(
            athlete_id=athlete_id,
            effective_date=date.isoformat(),
            cts_rolling_7d=training_load["cts_7d"],
            cts_rolling_28d=training_load["cts_28d"],
            ats_rolling=training_load["ats"],
            fatigue_index=training_load["fatigue_index"],
            readiness_score=composite_readiness or garmin_readiness,
            garmin_readiness_score=garmin_readiness,
            mood=None,
            soreness=None,
            pred_recovery_days=None,
            data_sources="workouts,physiometrics",
            canonical_version="3.0.0",
        )

    def _compute_rolling_tss(
        self,
        athlete_id: str,
        end_date: Any,  # datetime.date
        workouts_table: Any,
    ) -> Tuple[float, float]:
        """
        Compute rolling TSS for last 7 and 28 days from Workouts table.

        Args:
            athlete_id: Athlete identifier
            end_date: End date (datetime.date)
            workouts_table: Workouts table client

        Returns:
            Tuple of (tss_7d, tss_28d)
        """
        start_date_7 = end_date - timedelta(days=7)
        start_date_28 = end_date - timedelta(days=28)

        # Query workouts for this athlete
        filter_str = f"PartitionKey eq '{athlete_id}'"
        try:
            workout_entities = list(workouts_table.query_entities(filter_str))
        except HttpResponseError:
            return 0.0, 0.0

        tss_7d = 0.0
        tss_28d = 0.0

        for entity in workout_entities:
            tss = entity.get("tss", 0)
            if not tss:
                continue

            # Parse start_time_utc
            start_str = entity.get("start_time_utc")
            if not start_str:
                continue

            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", UTC_OFFSET))
                start_date = start_dt.date()
            except (ValueError, AttributeError):
                continue

            # Accumulate TSS
            if start_date_28 <= start_date <= end_date:
                tss_28d += tss
            if start_date_7 <= start_date <= end_date:
                tss_7d += tss

        return tss_7d, tss_28d

    def _compute_composite_readiness(
        self,
        hrv_ln: Optional[float],
        fatigue_index: Optional[float],
        garmin_readiness: Optional[float],
    ) -> Optional[float]:
        """
        Compute composite readiness score (0-100) from HRV and fatigue.

        Simple weighted model:
        - HRV (ln_rmssd): typically 2.5-4.5, normalized to 0-100
        - Fatigue index: typically 0.5-2.0, inverted and normalized
        - Garmin readiness: preferred if available

        Args:
            hrv_ln: Natural log of RMSSD (HRV metric)
            fatigue_index: ATS/CTS ratio (higher = more fatigued)
            garmin_readiness: Garmin native readiness score (0-100)

        Returns:
            Composite readiness score (0-100), or None if insufficient data
        """
        # Prefer Garmin readiness if available
        if garmin_readiness is not None:
            return garmin_readiness

        # Otherwise compute from HRV and fatigue index
        if hrv_ln is None and fatigue_index is None:
            return None

        score_components = []

        # HRV component (normalize ln_rmssd from 2.5-4.5 to 0-100)
        if hrv_ln is not None:
            hrv_normalized = max(0, min(100, (hrv_ln - 2.5) / 2.0 * 100))
            score_components.append(hrv_normalized)

        # Fatigue component (invert fatigue_index: lower fatigue = higher readiness)
        if fatigue_index is not None:
            # Typical range: 0.5 (fresh) to 2.0 (fatigued)
            # Invert: 2.0 -> 0, 0.5 -> 100
            fatigue_normalized = max(0, min(100, (2.0 - fatigue_index) / 1.5 * 100))
            score_components.append(fatigue_normalized)

        if not score_components:
            return None

        # Weighted average
        return sum(score_components) / len(score_components)
