"""Analysis service — zone distribution and efficiency trends."""
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List

from TrainingAnalyticsPlatform.analytics import utils

if TYPE_CHECKING:
    from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)


class AnalysisService:
    """Aerobic-efficiency and zone-distribution analysis for a single athlete."""

    def __init__(self, storage: "StorageCoordinator") -> None:
        self.storage = storage

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_zone_distribution(self, athlete_id: str, days: int = 30) -> Dict:
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

        workouts = utils.get_workouts_in_range(self.storage, athlete_id, start_date, end_date)

        zones = {
            "z1": 0.0,
            "z2": 0.0,
            "z3": 0.0,
            "z4": 0.0,
            "z5": 0.0,
        }

        for workout in workouts:
            for i, zone in enumerate(["z1", "z2", "z3", "z4", "z5"], 1):
                hr_sec = workout.get(f"hr_z{i}_sec", 0) or 0
                pwr_sec = workout.get(f"pwr_z{i}_sec", 0) or 0
                zone_sec = hr_sec if hr_sec > 0 else pwr_sec
                zones[zone] += zone_sec / 60

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

    def get_efficiency_trends(self, athlete_id: str, days: int = 90) -> Dict:
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

        workouts = utils.get_workouts_in_range(self.storage, athlete_id, start_date, end_date)

        efficiency_data: List[Dict] = []
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
                        2,
                    )
                    if efficiency_data
                    else None
                ),
            },
        }
