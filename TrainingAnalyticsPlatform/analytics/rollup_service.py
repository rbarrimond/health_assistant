"""Rollup service — weekly aggregation computation and persistence."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.analytics import utils
from TrainingAnalyticsPlatform.models.core import WorkoutMetricsModel
from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.platform.exceptions import StorageError, ValidationError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity

if TYPE_CHECKING:
    from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frozen schema invariants — NEVER modify these tuples without a MAJOR version
# bump and a corresponding CHANGELOG / schema-documentation update.
# ---------------------------------------------------------------------------
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


class RollupService:
    """Weekly rollup computation, normalisation, and persistence."""

    def __init__(self, storage: "StorageCoordinator") -> None:
        self.storage = storage

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_weekly_rollups(self, athlete_id: str, weeks: int = 16) -> List[Dict]:
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
                extra={"athlete_id": athlete_id},
            )
            return None

        try:
            athlete_tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Skipping weekly rollup persistence: invalid athlete timezone",
                extra={"athlete_id": athlete_id, "athlete_home_timezone": timezone_name},
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

    def list_athletes_with_workouts(self) -> List[str]:
        """List athlete identifiers observed in Workouts table."""
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")
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
                extra={"error_type": "HttpResponseError", "error": str(exc)},
                exc_info=True,
            )
            return []

    # -------------------------------------------------------------------------
    # Private — rollup retrieval
    # -------------------------------------------------------------------------

    def _get_weekly_rollups(self, athlete_id: str, days: int) -> List[Dict]:
        """Get weekly rollup data for specified number of days."""
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        try:
            table_client = self.storage.infrastructure.get_table_client("WeeklyRollups")
            rollups: List[Dict[str, Any]] = []

            current = start_date
            years: Set[int] = set()
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

            rollups.sort(key=lambda r: r.get("RowKey", ""), reverse=True)
            normalized_rollups: List[Dict[str, Any]] = []
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
                    extra={"athlete_id": athlete_id, "days": days},
                )
                return self._compute_weekly_rollups_from_workouts(
                    athlete_id=athlete_id,
                    start_date=start_date,
                    end_date=end_date,
                )

            return normalized_rollups

        except HttpResponseError as exc:
            logger.error(
                "Error retrieving weekly rollups",
                extra={
                    "athlete_id": athlete_id,
                    "days": days,
                    "error_type": "HttpResponseError",
                    "error": str(exc),
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
        current_week_start_local = now_local - timedelta(
            days=now_local.weekday(),
            hours=now_local.hour,
            minutes=now_local.minute,
            seconds=now_local.second,
            microseconds=now_local.microsecond,
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
        """Get rollup metrics models belonging to athlete local week."""
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
                    str(start_time_utc).replace("Z", utils.UTC_OFFSET)
                ).astimezone(timezone.utc)
            except ValueError:
                skipped_invalid_start += 1
                continue
            workout_start_local = workout_start_utc.astimezone(athlete_tz)
            if week_start_local <= workout_start_local <= week_end_local:
                candidate_entities.append(entity)

        for entity in candidate_entities:
            included.append(utils.build_rollup_metrics_model(self.storage, entity))

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
        """Build weekly rollup with local-week authoritative semantics."""
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
                str(start_time_utc).replace("Z", utils.UTC_OFFSET)
            ).astimezone(timezone.utc)
            week_start = workout_date - timedelta(
                days=workout_date.weekday(),
                hours=workout_date.hour,
                minutes=workout_date.minute,
                seconds=workout_date.second,
                microseconds=workout_date.microsecond,
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

        self._add_optional_rollup_metrics(rollup, week_workouts)

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
                sum(decoupling_values) / len(decoupling_values), 2
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
        metrics_models = [utils.build_rollup_metrics_model(self.storage, entity) for entity in entities]
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
            table_client = self.storage.infrastructure.get_table_client("Workouts")
            months = utils.get_month_partitions(athlete_id, start_date, end_date)
            entities_in_range: List[Dict[str, Any]] = []

            for partition_key in months:
                query = utils.build_partition_date_range_query(
                    partition_key,
                    start_date,
                    end_date,
                )
                entities = table_client.query_entities(query)
                for entity in entities:
                    if not utils.entity_within_date_range(entity, start_date, end_date):
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

    # -------------------------------------------------------------------------
    # Private — athlete-level multi-week orchestration
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Private — timezone resolution
    # -------------------------------------------------------------------------

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
            table_client = self.storage.infrastructure.get_table_client("AgentPreferences")
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
