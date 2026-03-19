"""Orchestrate just-in-time dependency syncs before planning context reads."""

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

DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SEC = 1.0


class PlanningContextPreSyncHandler(PreSyncExecutionMixin):
    """Run best-available dependency syncs before planning context reads.

    Unlike the fail-fast ``WeeklyRollupPreSyncHandler``, this handler uses
    best-available tolerance: every source is attempted regardless of prior
    source failures.  Partial success is surfaced in the result rather than
    causing the read to abort.

    The lookback window (``days``) is supplied at call time so it matches the
    planning context request parameter — it is not fixed at construction.
    """

    def __init__(
        self,
        *,
        onedrive_service: Any,
        garmin_service: Any,
        garmin_physiometrics_service: Any,
        intervals_service: Any,
        intervals_athlete_id: Optional[str],
        deferred_retry_coordinator: Optional[Any] = None,
        retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
        retry_base_delay_sec: float = DEFAULT_RETRY_BASE_DELAY_SEC,
    ) -> None:
        self._onedrive_service = onedrive_service
        self._garmin_service = garmin_service
        self._garmin_physiometrics_service = garmin_physiometrics_service
        self._intervals_service = intervals_service
        self._intervals_athlete_id = intervals_athlete_id
        self._deferred_retry_coordinator = deferred_retry_coordinator
        self._retry_max_attempts = max(1, int(retry_max_attempts))
        self._retry_base_delay_sec = max(0.1, float(retry_base_delay_sec))

    @classmethod
    def from_env(
        cls,
        *,
        onedrive_service: Any,
        garmin_service: Any,
        garmin_physiometrics_service: Any,
        intervals_service: Any,
        deferred_retry_coordinator: Optional[Any] = None,
    ) -> "PlanningContextPreSyncHandler":
        """Build handler from environment-backed defaults."""
        return cls(
            onedrive_service=onedrive_service,
            garmin_service=garmin_service,
            garmin_physiometrics_service=garmin_physiometrics_service,
            intervals_service=intervals_service,
            intervals_athlete_id=os.getenv("INTERVALS_ATHLETE_ID"),
            deferred_retry_coordinator=deferred_retry_coordinator,
            retry_max_attempts=int(
                os.getenv(
                    "PLANNING_PRESYNC_RETRY_MAX_ATTEMPTS",
                    str(DEFAULT_RETRY_MAX_ATTEMPTS),
                )
            ),
            retry_base_delay_sec=float(
                os.getenv(
                    "PLANNING_PRESYNC_RETRY_BASE_DELAY_SEC",
                    str(DEFAULT_RETRY_BASE_DELAY_SEC),
                )
            ),
        )

    def run(self, athlete_id: str, *, days: int) -> Dict[str, Any]:
        """Run all dependency syncs with best-available tolerance.

        All sources are attempted; individual failures produce a warning log
        and are recorded in the result but do not abort the remaining sources.
        The caller always receives a non-raising result dictionary.
        """
        lookback_days = max(1, int(days))
        source_results = []

        for operation in self._build_operations(athlete_id, lookback_days):
            result = self._execute_with_retry(operation)
            source_results.append(result)
            if result["status"] != "success":
                logger.warning(
                    "Planning context pre-sync source failed; continuing with remaining sources",
                    extra={
                        "source": result["source"],
                        "athlete_id": athlete_id,
                        "http_status": result.get("http_status"),
                        "source_message": result.get("message"),
                    },
                )

        succeeded = sum(1 for r in source_results if r["status"] == "success")
        total = len(source_results)

        if succeeded == total:
            status = "all_succeeded"
            message = "Planning context pre-sync completed successfully"
        elif succeeded > 0:
            status = "partial"
            message = "Planning context pre-sync completed with partial failures"
        else:
            status = "failed"
            message = "Planning context pre-sync failed for all sources"

        return {
            "lookback_days": lookback_days,
            "status": status,
            "message": message,
            "sources": source_results,
        }

    def _build_operations(
        self, athlete_id: str, lookback_days: int
    ) -> list[PreSyncOperation]:
        """Build ordered source sync operations for the given window."""
        return build_presync_operations(
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            onedrive_service=self._onedrive_service,
            garmin_service=self._garmin_service,
            garmin_physiometrics_service=self._garmin_physiometrics_service,
            intervals_execute=lambda: self._run_intervals_sync(
                athlete_id=athlete_id,
                lookback_days=lookback_days,
            ),
        )

    def _run_intervals_sync(
        self, *, athlete_id: str, lookback_days: int
    ) -> tuple[Dict[str, Any], int]:
        """Run Intervals sync with graceful handling of missing identity."""
        if not self._intervals_athlete_id:
            logger.warning(
                "Planning context pre-sync: INTERVALS_ATHLETE_ID not configured; "
                "skipping Intervals physiometrics",
                extra={"athlete_id": athlete_id},
            )

        return run_intervals_sync(
            intervals_service=self._intervals_service,
            intervals_athlete_id=self._intervals_athlete_id,
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            missing_identity_error="INTERVALS_ATHLETE_ID is not configured",
        )

    def _execute_with_retry(self, operation: PreSyncOperation) -> Dict[str, Any]:
        """Execute one source operation with bounded retry/backoff."""
        return super()._execute_operation_with_retry(
            operation,
            logger=logger,
            exception_log_message="Planning context pre-sync source raised exception",
            retry_log_message="Planning context pre-sync retrying source",
        )
