"""Orchestrate just-in-time dependency syncs before weekly rollup computation."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import GarminSyncRequest
from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import OneDriveSyncRequest

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 8
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SEC = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class _PreSyncOperation:
    """Single dependency pre-sync operation."""

    source: str
    execute: Callable[[], Tuple[Dict[str, Any], int]]


class WeeklyRollupPreSyncHandler:
    """Run dependency syncs before weekly rollup persistence."""

    def __init__(
        self,
        *,
        onedrive_service: Any,
        garmin_service: Any,
        garmin_physiometrics_service: Any,
        intervals_service: Any,
        intervals_athlete_id: Optional[str],
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
        retry_base_delay_sec: float = DEFAULT_RETRY_BASE_DELAY_SEC,
    ) -> None:
        self._onedrive_service = onedrive_service
        self._garmin_service = garmin_service
        self._garmin_physiometrics_service = garmin_physiometrics_service
        self._intervals_service = intervals_service
        self._intervals_athlete_id = intervals_athlete_id
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
        intervals_service: Any,
    ) -> "WeeklyRollupPreSyncHandler":
        """Build handler from environment-backed defaults."""
        return cls(
            onedrive_service=onedrive_service,
            garmin_service=garmin_service,
            garmin_physiometrics_service=garmin_physiometrics_service,
            intervals_service=intervals_service,
            intervals_athlete_id=os.getenv("INTERVALS_ATHLETE_ID"),
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

    def _build_operations(self, athlete_id: str) -> list[_PreSyncOperation]:
        """Build ordered source sync operations."""
        return [
            _PreSyncOperation(
                source="onedrive_workouts",
                execute=lambda: self._onedrive_service.handle(
                    OneDriveSyncRequest(
                        {
                            "athlete_id": athlete_id,
                            "days": self._lookback_days,
                            "async": False,
                        },
                        {},
                    )
                ),
            ),
            _PreSyncOperation(
                source="garmin_activities",
                execute=lambda: self._garmin_service.handle(
                    GarminSyncRequest(
                        {
                            "athlete_id": athlete_id,
                            "lookback_days": self._lookback_days,
                            "async": False,
                        },
                        {},
                    )
                ),
            ),
            _PreSyncOperation(
                source="garmin_physiometrics",
                execute=lambda: self._garmin_physiometrics_service.handle(
                    athlete_id,
                    self._lookback_days,
                    force=False,
                ),
            ),
            _PreSyncOperation(
                source="intervals_physiometrics",
                execute=lambda: self._run_intervals_sync(athlete_id),
            ),
        ]

    def _run_intervals_sync(self, athlete_id: str) -> Tuple[Dict[str, Any], int]:
        """Run Intervals sync with required identity validation."""
        if not self._intervals_athlete_id:
            return {
                "error": "INTERVALS_ATHLETE_ID is required for weekly pre-sync",
            }, 424

        return self._intervals_service.handle(
            intervals_athlete_id=self._intervals_athlete_id,
            athlete_id=athlete_id,
            lookback_days=self._lookback_days,
        )

    def _execute_with_retry(self, operation: _PreSyncOperation) -> Dict[str, Any]:
        """Execute one source operation with bounded retry/backoff."""
        attempts = 0
        last_status_code = 500
        last_message = "Source pre-sync failed"
        start = time.monotonic()

        while attempts < self._retry_max_attempts:
            attempts += 1
            try:
                body, status_code = operation.execute()
                last_status_code = status_code
                last_message = self._extract_message(body)

                if status_code == 200:
                    return self._build_result(
                        operation.source,
                        "success",
                        status_code,
                        last_message,
                        attempts,
                        start,
                    )

                retryable = status_code in RETRYABLE_STATUS_CODES
                if retryable and attempts < self._retry_max_attempts:
                    self._sleep_with_backoff(operation.source, attempts)
                    continue

                return self._build_result(
                    operation.source,
                    "failed",
                    status_code,
                    last_message,
                    attempts,
                    start,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_message = str(exc)
                retryable = self._is_retryable_exception(exc)
                logger.warning(
                    "Weekly rollup pre-sync source raised exception",
                    extra={
                        "source": operation.source,
                        "attempt": attempts,
                        "retryable": retryable,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    exc_info=True,
                )
                if retryable and attempts < self._retry_max_attempts:
                    self._sleep_with_backoff(operation.source, attempts)
                    continue

                return self._build_result(
                    operation.source,
                    "failed",
                    500,
                    last_message,
                    attempts,
                    start,
                )

        return self._build_result(
            operation.source,
            "failed",
            last_status_code,
            last_message,
            attempts,
            start,
        )

    @staticmethod
    def _extract_message(body: Dict[str, Any]) -> str:
        """Extract a stable message from source response body."""
        if not isinstance(body, dict):
            return "Source pre-sync completed"

        message = body.get("message") or body.get("error")
        if isinstance(message, str) and message.strip():
            return message

        status = body.get("status")
        if isinstance(status, str) and status.strip():
            return f"Source pre-sync returned status={status}"

        return "Source pre-sync completed"

    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        """Classify exceptions that should be retried."""
        error_type = type(exc).__name__.lower()
        text = str(exc).lower()
        retryable_fragments = (
            "timeout",
            "temporarily",
            "connection",
            "throttle",
            "rate limit",
            "429",
            "server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
        )
        if any(fragment in error_type for fragment in ("timeout", "connection")):
            return True
        return any(fragment in text for fragment in retryable_fragments)

    def _sleep_with_backoff(self, source: str, attempt: int) -> None:
        """Sleep with exponential backoff between retries."""
        delay = self._retry_base_delay_sec * (2 ** (attempt - 1))
        logger.info(
            "Weekly rollup pre-sync retrying source",
            extra={
                "source": source,
                "attempt": attempt,
                "sleep_sec": delay,
            },
        )
        time.sleep(delay)

    @staticmethod
    def _build_result(
        source: str,
        status: str,
        http_status: int,
        message: str,
        attempts: int,
        started_at: float,
    ) -> Dict[str, Any]:
        """Build source-level result payload."""
        duration_ms = int((time.monotonic() - started_at) * 1000)
        return {
            "source": source,
            "status": status,
            "http_status": http_status,
            "message": message,
            "attempts": attempts,
            "duration_ms": duration_ms,
        }