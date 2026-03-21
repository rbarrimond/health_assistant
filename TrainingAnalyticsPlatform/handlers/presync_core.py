"""Shared pre-sync orchestration primitives for dependency hydration handlers."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import GarminSyncRequest
from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import OneDriveSyncRequest

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
PreSyncResponse = (
    tuple[Dict[str, Any], int]
    | tuple[Dict[str, Any], int, Dict[str, Any]]
)


@dataclass(frozen=True)
class PreSyncOperation:
    """Single dependency pre-sync operation."""

    source: str
    athlete_id: str
    lookback_days: int
    execute: Callable[[], PreSyncResponse]


def build_presync_operations(
    *,
    athlete_id: str,
    lookback_days: int,
    onedrive_service: Any,
    garmin_service: Any,
    garmin_physiometrics_service: Any,
    intervals_execute: Callable[[], PreSyncResponse],
) -> list[PreSyncOperation]:
    """Build ordered source sync operations for a given athlete and window."""
    return [
        PreSyncOperation(
            source="onedrive_workouts",
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            execute=lambda: onedrive_service.handle(
                OneDriveSyncRequest(
                    {
                        "athlete_id": athlete_id,
                        "days": lookback_days,
                        "async": False,
                    },
                    {},
                )
            ),
        ),
        PreSyncOperation(
            source="garmin_activities",
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            execute=lambda: garmin_service.handle(
                GarminSyncRequest(
                    {
                        "athlete_id": athlete_id,
                        "lookback_days": lookback_days,
                        "async": False,
                    },
                    {},
                )
            ),
        ),
        PreSyncOperation(
            source="garmin_physiometrics",
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            execute=lambda: garmin_physiometrics_service.handle(
                athlete_id,
                lookback_days,
                force=False,
            ),
        ),
        PreSyncOperation(
            source="intervals_physiometrics",
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            execute=intervals_execute,
        ),
    ]


class PreSyncExecutionMixin:
    """Shared retry/backoff execution logic for pre-sync handlers."""

    _retry_max_attempts: int
    _retry_base_delay_sec: float

    def _execute_operation_with_retry(
        self,
        operation: PreSyncOperation,
        *,
        logger: logging.Logger,
        exception_log_message: str,
        retry_log_message: str,
    ) -> Dict[str, Any]:
        """Execute one source operation with bounded retry/backoff."""
        attempts = 0
        last_status_code = 500
        last_message = "Source pre-sync failed"
        last_retry_after: str | None = None
        start = time.monotonic()

        while attempts < self._retry_max_attempts:
            attempts += 1
            try:
                body, status_code, headers = self._normalize_response(operation.execute())
                last_status_code = status_code
                last_message = self._extract_message(body)
                last_retry_after = self._extract_retry_after(headers, body)

                if status_code == 200:
                    return self._build_result(
                        operation.source,
                        "success",
                        status_code,
                        last_message,
                        attempts,
                        start,
                        retry_after=last_retry_after,
                    )

                retryable = status_code in RETRYABLE_STATUS_CODES
                decision = self._maybe_defer_retry(
                    operation=operation,
                    retry_after_raw=last_retry_after,
                    started_at=start,
                )
                if decision:
                    return self._build_result(
                        operation.source,
                        "failed",
                        status_code,
                        last_message,
                        attempts,
                        start,
                        retry_after=decision.get("retry_after"),
                        deferred=True,
                        safe_to_retry_at_utc=decision.get("safe_to_retry_at_utc"),
                        deferred_operation_id=decision.get("operation_id"),
                    )
                if retryable and attempts < self._retry_max_attempts:
                    self._sleep_with_backoff(
                        source=operation.source,
                        attempt=attempts,
                        logger=logger,
                        retry_log_message=retry_log_message,
                    )
                    continue

                return self._build_result(
                    operation.source,
                    "failed",
                    status_code,
                    last_message,
                    attempts,
                    start,
                    retry_after=last_retry_after,
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_message = str(exc)
                retryable = self._is_retryable_exception(exc)
                logger.warning(
                    exception_log_message,
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
                    self._sleep_with_backoff(
                        source=operation.source,
                        attempt=attempts,
                        logger=logger,
                        retry_log_message=retry_log_message,
                    )
                    continue

                return self._build_result(
                    operation.source,
                    "failed",
                    500,
                    last_message,
                    attempts,
                    start,
                    retry_after=last_retry_after,
                )

        return self._build_result(
            operation.source,
            "failed",
            last_status_code,
            last_message,
            attempts,
            start,
            retry_after=last_retry_after,
        )

    def _maybe_defer_retry(
        self,
        *,
        operation: PreSyncOperation,
        retry_after_raw: str | None,
        started_at: float,
    ) -> dict[str, Any] | None:
        """Evaluate timeout-risk deferral decision via optional coordinator."""
        coordinator = getattr(self, "_deferred_retry_coordinator", None)
        if coordinator is None:
            return None

        elapsed_sec = max(0.0, time.monotonic() - started_at)
        decision = coordinator.maybe_defer(
            athlete_id=operation.athlete_id,
            source=operation.source,
            lookback_days=operation.lookback_days,
            retry_after_raw=retry_after_raw,
            elapsed_sec=elapsed_sec,
        )
        if not getattr(decision, "deferred", False):
            return None

        return {
            "operation_id": decision.operation_id,
            "safe_to_retry_at_utc": decision.safe_to_retry_at_utc,
            "retry_after": decision.retry_after_raw,
        }

    @staticmethod
    def _normalize_response(response: PreSyncResponse) -> tuple[Dict[str, Any], int, Dict[str, Any]]:
        """Normalize source responses to (body, status_code, headers)."""
        if len(response) == 2:
            body, status_code = response
            return body, status_code, {}

        body, status_code, headers = response
        if not isinstance(headers, dict):
            return body, status_code, {}
        return body, status_code, headers

    @staticmethod
    def _extract_retry_after(headers: Dict[str, Any], body: Dict[str, Any]) -> str | None:
        """Extract Retry-After guidance from headers (preferred) or body fallback."""
        header_retry_after = PreSyncExecutionMixin._extract_retry_after_from_headers(headers)
        if header_retry_after is not None:
            return header_retry_after

        return PreSyncExecutionMixin._extract_retry_after_from_body(body)

    @staticmethod
    def _extract_retry_after_from_headers(headers: Dict[str, Any]) -> str | None:
        """Extract Retry-After from response headers."""
        if not isinstance(headers, dict):
            return None

        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "retry-after":
                if value is None:
                    return None
                return str(value)
        return None

    @staticmethod
    def _extract_retry_after_from_body(body: Dict[str, Any]) -> str | None:
        """Extract Retry-After style values from response body fallbacks."""
        if not isinstance(body, dict):
            return None

        for key in ("retry_after", "retryAfter"):
            value = body.get(key)
            if value is not None:
                return str(value)
        return None

    def _sleep_with_backoff(
        self,
        *,
        source: str,
        attempt: int,
        logger: logging.Logger,
        retry_log_message: str,
    ) -> None:
        """Sleep with exponential backoff between retries."""
        base_delay = self._retry_base_delay_sec * (2 ** (attempt - 1))
        delay = (base_delay / 2.0) + (random.random() * (base_delay / 2.0))
        logger.info(
            retry_log_message,
            extra={
                "source": source,
                "attempt": attempt,
                "sleep_sec": delay,
            },
        )
        time.sleep(delay)

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

    @staticmethod
    def _build_result(
        source: str,
        status: str,
        http_status: int,
        message: str,
        attempts: int,
        started_at: float,
        retry_after: str | None = None,
        deferred: bool = False,
        safe_to_retry_at_utc: str | None = None,
        deferred_operation_id: str | None = None,
    ) -> Dict[str, Any]:
        """Build source-level result payload."""
        duration_ms = int((time.monotonic() - started_at) * 1000)
        result = {
            "source": source,
            "status": status,
            "http_status": http_status,
            "message": message,
            "attempts": attempts,
            "duration_ms": duration_ms,
        }
        if retry_after is not None:
            result["retry_after"] = retry_after
        if deferred:
            result["deferred"] = True
        if safe_to_retry_at_utc is not None:
            result["safe_to_retry_at_utc"] = safe_to_retry_at_utc
        if deferred_operation_id is not None:
            result["deferred_operation_id"] = deferred_operation_id
        return result


def run_intervals_sync(
    *,
    intervals_service: Any,
    intervals_athlete_id: Optional[str],
    athlete_id: str,
    lookback_days: int,
    missing_identity_error: str,
) -> Tuple[Dict[str, Any], int]:
    """Run Intervals sync with required identity validation."""
    if not intervals_athlete_id:
        return {"error": missing_identity_error}, 424

    return intervals_service.handle(
        intervals_athlete_id=intervals_athlete_id,
        athlete_id=athlete_id,
        lookback_days=lookback_days,
    )