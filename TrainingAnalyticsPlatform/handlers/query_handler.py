"""Handle analytics/query requests."""

import logging
from typing import Any, Dict, List, Tuple

from TrainingAnalyticsPlatform.analytics.analysis_service import AnalysisService
from TrainingAnalyticsPlatform.analytics.planning_service import PlanningService
from TrainingAnalyticsPlatform.analytics.rollup_service import RollupService
from TrainingAnalyticsPlatform.analytics.workout_query_service import WorkoutQueryService
from TrainingAnalyticsPlatform.platform.exceptions import StorageError

logger = logging.getLogger(__name__)


class QueryHandler:
    """Orchestrates analytics service queries."""

    def __init__(
        self,
        workout_service: WorkoutQueryService,
        planning_service: PlanningService,
        rollup_service: RollupService,
        analysis_service: AnalysisService,
    ):
        self.workout_service = workout_service
        self.planning_service = planning_service
        self.rollup_service = rollup_service
        self.analysis_service = analysis_service

    def query_athlete_workouts(
        self,
        athlete_id: str,
        limit: int = 20,
        since: str | None = None,
        until: str | None = None,
        sport: str | None = None,
    ) -> Tuple[List[Dict], int]:
        """
        Retrieve athlete's recent workouts.

        Args:
            athlete_id: Athlete identifier
            limit: Maximum workouts to return
            since: ISO start date (YYYY-MM-DD)
            until: ISO end date (YYYY-MM-DD)
            sport: Optional sport filter

        Returns:
            (list of workout dicts, HTTP status code)
        """
        try:
            results = self.workout_service.get_workouts(
                athlete_id,
                since=since,
                until=until,
                limit=limit,
                sport=sport,
            )
            return results, 200
        except ValueError as exc:
            logger.warning("Query validation failed: %s", exc)
            return [], 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Query failed: %s", exc, exc_info=True)
            return [], 500

    def query_workout_detail(
        self,
        athlete_id: str,
        workout_id: str,
        include_laps: bool = False,
        include_developer_fields: bool = False,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Get detailed workout data including time series.

        Args:
            athlete_id: Athlete identifier
            workout_id: Unique workout identifier

        Returns:
            (workout detail dict, HTTP status code)
        """
        try:
            workout = self.workout_service.get_workout_detail(
                athlete_id,
                workout_id,
                include_laps=include_laps,
                include_developer_fields=include_developer_fields,
            )
            if workout is None:
                return {"error": "Workout not found"}, 404
            return workout, 200
        except ValueError as exc:
            logger.warning("Workout detail validation failed: %s", exc)
            return {"error": str(exc)}, 400
        except StorageError as exc:
            logger.error("Workout detail storage failure: %s", exc, exc_info=True)
            return {"error": "Workout detail is temporarily unavailable"}, 500
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Workout detail query failed: %s", exc, exc_info=True)
            return {"error": "Internal server error"}, 500

    def query_workout_lap_detail(
        self,
        athlete_id: str,
        workout_id: str,
        lap_index: int,
    ) -> Tuple[Dict[str, Any], int]:
        """Get lap summary and records for a specific workout lap."""
        try:
            lap = self.workout_service.get_workout_lap_detail(
                athlete_id,
                workout_id,
                lap_index,
            )
            if lap is None:
                return {"error": "Lap not found"}, 404
            return lap, 200
        except ValueError as exc:
            logger.warning("Workout lap validation failed: %s", exc)
            return {"error": str(exc)}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Workout lap query failed: %s", exc, exc_info=True)
            return {"error": "Internal server error"}, 500

    def query_planning_context(self, athlete_id: str, days: int = 45) -> Tuple[Dict[str, Any], int]:
        """
        Get planning context for training decisions.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back

        Returns:
            (context dict, HTTP status code)
        """
        try:
            context = self.planning_service.get_planning_context(athlete_id, days)
            return context, 200
        except ValueError as exc:
            logger.warning("Planning query validation failed: %s", exc)
            return {}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Planning query failed: %s", exc, exc_info=True)
            return {}, 500

    def query_training_zones(self, athlete_id: str, days: int = 30) -> Tuple[Dict[str, Any], int]:
        """
        Compute training zone distribution.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to analyze

        Returns:
            (zone analysis dict, HTTP status code)
        """
        try:
            result = self.analysis_service.get_zone_distribution(athlete_id, days)
            return result, 200
        except ValueError as exc:
            logger.warning("Zone analysis validation failed: %s", exc)
            return {}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Zone analysis failed: %s", exc, exc_info=True)
            return {}, 500

    def query_efficiency_trends(
        self, athlete_id: str, days: int = 90
    ) -> Tuple[Dict[str, Any], int]:
        """
        Get aerobic efficiency trends.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to analyze

        Returns:
            (efficiency trends dict, HTTP status code)
        """
        try:
            trends = self.analysis_service.get_efficiency_trends(athlete_id, days)
            return trends, 200
        except ValueError as exc:
            logger.warning("Efficiency query validation failed: %s", exc)
            return {}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Efficiency query failed: %s", exc, exc_info=True)
            return {}, 500

    def query_weekly_rollups(self, athlete_id: str, weeks: int = 16) -> Tuple[Dict[str, Any], int]:
        """
        Get weekly rollup data.

        Args:
            athlete_id: Athlete identifier
            weeks: Number of weeks to retrieve

        Returns:
            (rollups dict, HTTP status code)
        """
        try:
            rollups = self.rollup_service.get_weekly_rollups(athlete_id, weeks)
            results: List[Dict[str, Any]] = []
            rollups_count = len(rollups)

            for index in range(weeks):
                weeks_ago = index + 1
                if index < rollups_count:
                    rollup = rollups[index]
                    results.append(
                        {
                            "weeks_ago": weeks_ago,
                            "status": "success",
                            "message": "Weekly rollup available",
                            "week_start_utc": rollup.get("week_start_utc"),
                            "week_end_utc": rollup.get("week_end_utc"),
                        }
                    )
                else:
                    results.append(
                        {
                            "weeks_ago": weeks_ago,
                            "status": "skipped",
                            "message": "No weekly rollup available for requested week",
                        }
                    )

            if rollups_count == 0:
                status = "skipped"
                message = "No weekly rollups available for requested window"
            elif rollups_count < weeks:
                status = "partial"
                message = "Weekly rollups available for part of requested window"
            else:
                status = "success"
                message = "Weekly rollups available for requested window"

            return {
                "athlete_id": athlete_id,
                "weeks": weeks,
                "count": rollups_count,
                "status": status,
                "message": message,
                "results": results,
                "rollups": rollups,
            }, 200
        except ValueError as exc:
            logger.warning("Rollup query validation failed: %s", exc)
            return {}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Rollup query failed: %s", exc, exc_info=True)
            return {}, 500
