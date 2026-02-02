"""Physiometrics data handler."""

import logging
from typing import Dict, List, Tuple, Any, Optional

from FitParser.semantic_layer import SemanticLayer

logger = logging.getLogger(__name__)


class PhysiometricsHandler:
    """Handles physiometric data operations."""

    def __init__(self, semantic_layer: SemanticLayer):
        """Initialize handler with semantic layer dependency."""
        self.semantic_layer = semantic_layer

    def get_current(self, athlete_id: str) -> Tuple[Dict[str, Any], int]:
        """Get current physiometric snapshot for an athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": "Missing required parameter: athlete_id"}, 400

        try:
            result = self.semantic_layer.get_current_physiometrics(athlete_id)
            return result, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error getting current physiometrics: %s", exc, exc_info=True)
            return {"error": "Failed to retrieve physiometrics"}, 500

    def get_history(
        self,
        athlete_id: str,
        days: int = 90,
        metrics: Optional[List[str]] = None
    ) -> Tuple[Dict[str, Any], int]:
        """Get time-series physiometric data.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back (default 90, max 365)
            metrics: Optional list of specific metrics to retrieve

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": "Missing required parameter: athlete_id"}, 400

        try:
            days = min(days, 365)  # Cap at 365

            result = self.semantic_layer.get_physiometrics_trends(
                athlete_id=athlete_id,
                days=days,
                metrics=metrics
            )

            return result, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error getting physiometrics history: %s", exc, exc_info=True)
            return {"error": "Failed to retrieve physiometrics history"}, 500

    def update_metric(
        self,
        athlete_id: str,
        metric: str,
        value: float,
        effective_date: Optional[str] = None,
        source: str = "chatgpt"
    ) -> Tuple[Dict[str, Any], int]:
        """Update a single physiometric value.

        Args:
            athlete_id: Athlete identifier
            metric: Metric name (e.g., "weight_kg", "cycling_vo2max_ml_kg_min")
            value: Metric value
            effective_date: Optional ISO date string for when the value takes effect
            source: Source of the update (default: "chatgpt")

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": "athlete_id required"}, 400

        try:
            result = self.semantic_layer.update_physiometric_value(
                athlete_id=athlete_id,
                metric=metric,
                value=value,
                effective_date=effective_date,
                source=source
            )
            return result, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating physiometric: %s", exc, exc_info=True)
            return {"error": "Failed to update physiometric"}, 500

    def update_metrics(
        self,
        athlete_id: str,
        metrics: Dict[str, float],
        effective_date: Optional[str] = None,
        source: str = "chatgpt"
    ) -> Tuple[Dict[str, Any], int]:
        """Bulk update physiometric values.

        Args:
            athlete_id: Athlete identifier
            metrics: Dictionary of metric_name -> value pairs
            effective_date: Optional ISO date string for when the values take effect
            source: Source of the update (default: "chatgpt")

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": "athlete_id required"}, 400

        try:
            results = []
            for metric, value in metrics.items():
                result = self.semantic_layer.update_physiometric_value(
                    athlete_id=athlete_id,
                    metric=metric,
                    value=value,
                    effective_date=effective_date,
                    source=source
                )
                results.append(result)

            return {
                "status": "success",
                "updates": results
            }, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error updating physiometrics: %s", exc, exc_info=True)
            return {"error": "Failed to update physiometrics"}, 500
