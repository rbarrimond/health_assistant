"""Handle analytics/query requests."""

import logging
from typing import Any, Dict, List, Tuple

from FitParser.semantic_layer import SemanticLayer

logger = logging.getLogger(__name__)


class QueryHandler:
    """Orchestrates semantic layer queries."""

    def __init__(self, semantic_layer: SemanticLayer):
        self.semantic_layer = semantic_layer

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
            results = self.semantic_layer.get_workouts(
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

    def query_workout_detail(self, athlete_id: str, workout_id: str) -> Tuple[Dict[str, Any], int]:
        """
        Get detailed workout data including time series.

        Args:
            athlete_id: Athlete identifier
            workout_id: Unique workout identifier

        Returns:
            (workout detail dict, HTTP status code)
        """
        try:
            workout = self.semantic_layer.get_workout_detail(athlete_id, workout_id)
            if workout is None:
                return {"error": "Workout not found"}, 404
            return workout, 200
        except ValueError as exc:
            logger.warning("Workout detail validation failed: %s", exc)
            return {"error": str(exc)}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Workout detail query failed: %s", exc, exc_info=True)
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
            context = self.semantic_layer.get_planning_context(athlete_id, days)
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
            result = self.semantic_layer.get_zone_distribution(athlete_id, days)
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
            trends = self.semantic_layer.get_efficiency_trends(athlete_id, days)
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
            rollups = self.semantic_layer.get_weekly_rollups(athlete_id, weeks)
            return {
                "athlete_id": athlete_id,
                "weeks": weeks,
                "count": len(rollups),
                "rollups": rollups,
            }, 200
        except ValueError as exc:
            logger.warning("Rollup query validation failed: %s", exc)
            return {}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Rollup query failed: %s", exc, exc_info=True)
            return {}, 500
