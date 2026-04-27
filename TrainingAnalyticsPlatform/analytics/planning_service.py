"""Planning service — training context and pattern analysis."""
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from TrainingAnalyticsPlatform.analytics import utils

if TYPE_CHECKING:
    from TrainingAnalyticsPlatform.analytics.workout_query_service import WorkoutQueryService
    from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)


class PlanningService:
    """Planning context: recent workouts, rollups, and pattern flags."""

    def __init__(
        self,
        storage: "StorageCoordinator",
        workout_service: "WorkoutQueryService",
    ) -> None:
        self.storage = storage
        self._workout_service = workout_service

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_planning_context(self, athlete_id: str, days: int = 45) -> Dict:
        """
        Get planning context for training decisions.

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

        # Single table scan — derive both full workout metrics and projections from
        # the same entity batch to avoid redundant partition queries.
        entities = utils.collect_all_workout_entities(self.storage, athlete_id, start_date, end_date)

        full_workouts = utils.build_workout_summaries_from_entities(self.storage, entities)
        full_workouts.sort(key=lambda w: w.get("start_time_utc", ""), reverse=True)

        projections = [
            p
            for entity in entities
            if (p := self._workout_service.build_workout_projection(entity)) is not None
        ]
        projections.sort(key=lambda p: p.start_time_utc or "", reverse=True)

        last_hard_day = self._find_last_hard_day(full_workouts)
        last_long_day = self._find_last_long_day(full_workouts)
        z2_minutes = self._sum_zone_time(full_workouts, "hr_z2_sec")
        intensity_minutes = self._sum_high_intensity(full_workouts)
        flags = self._detect_notable_flags(full_workouts)

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
    # Private helpers
    # -------------------------------------------------------------------------

    def _get_weekly_rollups(self, athlete_id: str, days: int) -> List[Dict]:
        """Delegate to RollupService-style query (inline to avoid circular import)."""
        from TrainingAnalyticsPlatform.analytics.rollup_service import RollupService  # local import

        rollup_service = RollupService(self.storage)
        return rollup_service.get_weekly_rollups(athlete_id, weeks=days // 7)

    def _find_last_hard_day(self, workouts: List[Dict]) -> Optional[str]:
        """Find date of last high-intensity workout (intensity_sec > 300)."""
        for workout in workouts:
            if float(workout.get("intensity_sec") or 0) > 300:
                return workout.get("start_time_utc")
        return None

    def _find_last_long_day(self, workouts: List[Dict]) -> Optional[str]:
        """Find date of last long aerobic workout (Z2 > 3600 sec)."""
        for workout in workouts:
            hr_z2_sec = workout.get("hr_z2_sec", 0) or 0
            pwr_z2_sec = workout.get("pwr_z2_sec", 0) or 0
            if max(hr_z2_sec, pwr_z2_sec) > 3600:
                return workout.get("start_time_utc")
        return None

    def _sum_zone_time(self, workouts: List[Dict], zone_field: str) -> float:
        """Sum zone time across workouts, converting to minutes."""
        total = 0.0
        for workout in workouts:
            value = float(workout.get(zone_field, 0) or 0)
            total += value / 60 if zone_field.endswith("_sec") else value
        return round(total, 2)

    def _sum_high_intensity(self, workouts: List[Dict]) -> float:
        """Sum high intensity minutes (Z4+) across workouts."""
        return sum(float(w.get("intensity_sec") or 0) / 60 for w in workouts)

    def _detect_notable_flags(self, workouts: List[Dict]) -> List[str]:
        """Detect notable issues in recent workouts."""
        flags: List[str] = []

        no_hr_count = sum(1 for w in workouts if not w.get("hr_avg_bpm"))
        if no_hr_count > 0:
            flags.append(f"{no_hr_count} workout(s) missing heart rate data")

        high_decoupling = [
            w for w in workouts
            if w.get("decoupling_pct", 0) and w["decoupling_pct"] > 5.0
        ]
        if high_decoupling:
            flags.append(f"{len(high_decoupling)} workout(s) with high decoupling (>5%)")

        very_short = [
            w for w in workouts
            if w.get("duration_sec", 0) and w["duration_sec"] < 600
        ]
        if very_short:
            flags.append(f"{len(very_short)} very short workout(s) (<10 min)")

        return flags
