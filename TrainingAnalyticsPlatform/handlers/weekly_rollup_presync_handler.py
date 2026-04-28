"""Orchestrate just-in-time dependency syncs before weekly rollup computation."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from TrainingAnalyticsPlatform.handlers.presync_core import (
    PreSyncOperation,
    PreSyncExecutionMixin,
    build_presync_operations,
    run_intervals_sync,
)

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 8
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SEC = 1.0


class WeeklyRollupPreSyncHandler(PreSyncExecutionMixin):
    """Run dependency syncs before weekly rollup persistence."""

    def __init__(
        self,
        *,
        onedrive_service: Any,
        garmin_service: Any,
        garmin_physiometrics_service: Any,
        withings_service: Any,
        intervals_service: Any,
        intervals_athlete_id: Optional[str],
        deferred_retry_coordinator: Optional[Any] = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
        retry_base_delay_sec: float = DEFAULT_RETRY_BASE_DELAY_SEC,
    ) -> None:
        self._onedrive_service = onedrive_service
        self._garmin_service = garmin_service
        self._garmin_physiometrics_service = garmin_physiometrics_service
        self._withings_service = withings_service
        self._intervals_service = intervals_service
        self._intervals_athlete_id = intervals_athlete_id
        self._deferred_retry_coordinator = deferred_retry_coordinator
        self._lookback_days = max(1, int(lookback_days))
        self._retry_max_attempts = max(1, int(retry_max_attempts))
        self._retry_base_delay_sec = max(0.1, float(retry_base_delay_sec))

    @classmethod
    def from_env(
        cls,
        *,
        onedrive_service: Any,
        garmin_service: Any,
        garmin_physiometrics_service: Any,
        withings_service: Any,
        intervals_service: Any,
        deferred_retry_coordinator: Optional[Any] = None,
    ) -> "WeeklyRollupPreSyncHandler":
        """Build handler from environment-backed defaults."""
        return cls(
            onedrive_service=onedrive_service,
            garmin_service=garmin_service,
            garmin_physiometrics_service=garmin_physiometrics_service,
            withings_service=withings_service,
            intervals_service=intervals_service,
            intervals_athlete_id=os.getenv("INTERVALS_ATHLETE_ID"),
            deferred_retry_coordinator=deferred_retry_coordinator,
            lookback_days=int(
                os.getenv(
                    "WEEKLY_ROLLUP_PRESYNC_LOOKBACK_DAYS",
                    str(DEFAULT_LOOKBACK_DAYS),
                )
            ),
            retry_max_attempts=int(
                os.getenv(
                    "WEEKLY_ROLLUP_PRESYNC_RETRY_MAX_ATTEMPTS",
                    str(DEFAULT_RETRY_MAX_ATTEMPTS),
                )
            ),
            retry_base_delay_sec=float(
                os.getenv(
                    "WEEKLY_ROLLUP_PRESYNC_RETRY_BASE_DELAY_SEC",
                    str(DEFAULT_RETRY_BASE_DELAY_SEC),
                )
            ),
        )

    def run(self, athlete_id: str, *, enabled: bool = True) -> Dict[str, Any]:
        """Run configured dependency syncs and return an execution summary."""
        if not enabled:
            return {
                "enabled": False,
                "lookback_days": self._lookback_days,
                "status": "skipped",
                "message": "Pre-sync disabled by request",
                "sources": [],
            }

        source_results = []
        for operation in self._build_operations(athlete_id):
            result = self._execute_with_retry(operation)
            source_results.append(result)
            if result["status"] != "success":
                return {
                    "enabled": True,
                    "lookback_days": self._lookback_days,
                    "status": "failed",
                    "message": "Weekly rollup pre-sync failed; computation aborted",
                    "sources": source_results,
                }

        return {
            "enabled": True,
            "lookback_days": self._lookback_days,
            "status": "success",
            "message": "Weekly rollup pre-sync completed",
            "sources": source_results,
        }

    def _build_operations(self, athlete_id: str) -> list[PreSyncOperation]:
        """Build ordered source sync operations."""
        return build_presync_operations(
            athlete_id=athlete_id,
            lookback_days=self._lookback_days,
            onedrive_service=self._onedrive_service,
            garmin_service=self._garmin_service,
            garmin_physiometrics_service=self._garmin_physiometrics_service,
            withings_service=self._withings_service,
            intervals_execute=lambda: run_intervals_sync(
                intervals_service=self._intervals_service,
                intervals_athlete_id=self._intervals_athlete_id,
                athlete_id=athlete_id,
                lookback_days=self._lookback_days,
                missing_identity_error="INTERVALS_ATHLETE_ID is required for weekly pre-sync",
            ),
        )

    def _execute_with_retry(self, operation: PreSyncOperation) -> Dict[str, Any]:
        """Execute one source operation with bounded retry/backoff."""
        return super()._execute_operation_with_retry(
            operation,
            logger=logger,
            exception_log_message="Weekly rollup pre-sync source raised exception",
            retry_log_message="Weekly rollup pre-sync retrying source",
        )