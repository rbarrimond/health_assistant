"""Physiometrics data handler."""

from datetime import date
import logging
from typing import Dict, List, Tuple, Any, Optional

from TrainingAnalyticsPlatform.analytics.physiometrics_service import PhysiometricsService
from TrainingAnalyticsPlatform.handlers.request_models import PhysiometricsUpdateRequest

logger = logging.getLogger(__name__)

# Error message constants
ERROR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"
ERROR_INVALID_SINCE = "Invalid since date; expected YYYY-MM-DD"
ERROR_INVALID_UNTIL = "Invalid until date; expected YYYY-MM-DD"
ERROR_INVALID_DATE_RANGE = "Invalid date range; since must be on or before until"


class PhysiometricsHandler:
    """Handles physiometric data operations."""

    def __init__(self, physiometrics_service: PhysiometricsService):
        """Initialize handler with physiometrics service dependency."""
        self.physiometrics_service = physiometrics_service

    def get_current(self, athlete_id: str) -> Tuple[Dict[str, Any], int]:
        """Get current physiometric snapshot for an athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Tuple of (response_dict, status_code)
        """
        if not athlete_id:
            return {"error": ERROR_MISSING_ATHLETE_ID}, 400

        try:
            result = self.physiometrics_service.get_current_physiometrics(athlete_id)
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
            return {"error": ERROR_MISSING_ATHLETE_ID}, 400

        try:
            days = min(days, 365)  # Cap at 365

            result = self.physiometrics_service.get_physiometrics_trends(
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
            result = self.physiometrics_service.update_physiometric_value(
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
                result = self.physiometrics_service.update_physiometric_value(
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

    def handle_update_request(
        self,
        update_request: PhysiometricsUpdateRequest,
    ) -> Tuple[Dict[str, Any], int]:
        """Dispatch a normalized physiometrics update request."""
        if not (update_request.has_single_metric or update_request.has_bulk_metrics):
            return {"error": "Either 'metric'+'value' or 'metrics' dict required"}, 400

        if update_request.has_single_metric:
            return self.update_metric(
                athlete_id=update_request.athlete_id or "",
                metric=update_request.metric or "",
                value=update_request.value,
                effective_date=update_request.effective_date,
                source=update_request.source,
            )

        return self.update_metrics(
            athlete_id=update_request.athlete_id or "",
            metrics=update_request.metrics or {},
            effective_date=update_request.effective_date,
            source=update_request.source,
        )

    def get_training_state_current(self, athlete_id: str) -> Tuple[Dict[str, Any], int]:
        """Get current training state (on-demand projection from Workouts + Physiometrics).

        Args:
            athlete_id: Athlete identifier

        Returns:
            Tuple of (response_dict, status_code) containing:
            - cts_rolling_7d, cts_rolling_28d (chronic training stress)
            - ats_rolling (acute training stress)
            - fatigue_index (ATS/CTS ratio)
            - readiness_score, garmin_readiness_score
        """
        if not athlete_id:
            return {"error": ERROR_MISSING_ATHLETE_ID}, 400

        try:
            result = self.physiometrics_service.compute_current_training_state(athlete_id)
            return result, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error computing training state: %s", exc, exc_info=True)
            return {"error": "Failed to compute training state"}, 500

    def get_training_state_history(
        self,
        athlete_id: str,
        days: int = 45,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """Get training state history (on-demand projection for date range).

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back (default 45, max 90)
            since: Optional inclusive start date (YYYY-MM-DD)
            until: Optional inclusive end date (YYYY-MM-DD)

        Returns:
            Tuple of (response_dict, status_code) containing:
            - query_window (start_date, end_date, days)
            - data_points (list of daily training state snapshots)
        """
        if not athlete_id:
            return {"error": ERROR_MISSING_ATHLETE_ID}, 400

        since_date: Optional[date] = None
        until_date: Optional[date] = None

        if since is not None:
            try:
                since_date = date.fromisoformat(since)
            except ValueError:
                return {"error": ERROR_INVALID_SINCE}, 400

        if until is not None:
            try:
                until_date = date.fromisoformat(until)
            except ValueError:
                return {"error": ERROR_INVALID_UNTIL}, 400

        effective_until = until_date or date.today()

        if since_date is not None and since_date > effective_until:
            return {"error": ERROR_INVALID_DATE_RANGE}, 400

        try:
            days = min(days, 90)  # Cap at 90 days

            result = self.physiometrics_service.compute_training_state_history(
                athlete_id=athlete_id,
                days=days,
                since=since_date.isoformat() if since_date is not None else None,
                until=until_date.isoformat() if until_date is not None else None,
            )

            return result, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error computing training state history: %s", exc, exc_info=True)
            return {"error": "Failed to compute training state history"}, 500
