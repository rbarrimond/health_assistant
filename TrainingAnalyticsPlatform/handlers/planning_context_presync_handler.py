"""Orchestrate just-in-time dependency syncs before planning context reads."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import uuid
from typing import Any, Dict, Optional

from TrainingAnalyticsPlatform.storage.garmin_activity_index_storage import GarminActivityIndexStorage

from TrainingAnalyticsPlatform.handlers.presync_core import (
    PreSyncOperation,
    PreSyncExecutionMixin,
    build_presync_operations,
    run_intervals_sync,
)

logger = logging.getLogger(__name__)

DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY_SEC = 1.0
DEFAULT_PARALLEL_MAX_WORKERS = 8
DEFAULT_FRESHNESS_TTL_SEC = 3600
DEFAULT_GARMIN_PRESYNC_FALLBACK_LOOKBACK_DAYS = 7
ENV_PLANNING_PRESYNC_GARMIN_ACTIVITIES_ENABLED = (
    "PLANNING_PRESYNC_GARMIN_ACTIVITIES_ENABLED"
)
ENV_PLANNING_PRESYNC_GARMIN_PHYSIOMETRICS_ENABLED = (
    "PLANNING_PRESYNC_GARMIN_PHYSIOMETRICS_ENABLED"
)
ENV_PLANNING_PRESYNC_FRESHNESS_TTL_SEC = "PLANNING_PRESYNC_FRESHNESS_TTL_SEC"


class PlanningContextPreSyncHandler(PreSyncExecutionMixin):
    """Run best-available dependency syncs before planning context reads.

    Unlike the fail-fast ``WeeklyRollupPreSyncHandler``, this handler uses
    best-available tolerance: every source is attempted regardless of prior
    source failures. Partial success is surfaced in the result rather than
    causing the read to abort.

    The lookback window (``days``) is supplied at call time so it matches the
    planning context request parameter - it is not fixed at construction.
    """

    def __init__(
        self,
        *,
        onedrive_service: Any,
        garmin_service: Any,
        garmin_physiometrics_service: Any,
        withings_service: Any,
        intervals_service: Any,
        intervals_athlete_id: Optional[str],
        planning_presync_garmin_activities_enabled: bool = False,
        planning_presync_garmin_physiometrics_enabled: bool = False,
        deferred_retry_coordinator: Optional[Any] = None,
        retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
        retry_base_delay_sec: float = DEFAULT_RETRY_BASE_DELAY_SEC,
        planning_presync_freshness_ttl_sec: int = DEFAULT_FRESHNESS_TTL_SEC,
        garmin_activity_index_storage: Optional[GarminActivityIndexStorage] = None,
    ) -> None:
        self._onedrive_service = onedrive_service
        self._garmin_service = garmin_service
        self._garmin_physiometrics_service = garmin_physiometrics_service
        self._withings_service = withings_service
        self._intervals_service = intervals_service
        self._intervals_athlete_id = intervals_athlete_id
        self._planning_presync_garmin_activities_enabled = (
            planning_presync_garmin_activities_enabled
        )
        self._planning_presync_garmin_physiometrics_enabled = (
            planning_presync_garmin_physiometrics_enabled
        )
        self._deferred_retry_coordinator = deferred_retry_coordinator
        self._retry_max_attempts = max(1, int(retry_max_attempts))
        self._retry_base_delay_sec = max(0.1, float(retry_base_delay_sec))
        self._planning_presync_freshness_ttl_sec = max(
            0, int(planning_presync_freshness_ttl_sec)
        )
        self._garmin_activity_index_storage = garmin_activity_index_storage
        self._freshness_lock = threading.Lock()
        self._freshness_registry: dict[tuple[str, int, str], datetime] = {}

    @staticmethod
    def _parse_bool_env(value: str) -> bool:
        """Parse a conventional environment boolean string."""
        return value.lower() in {"1", "true", "yes", "on"}

    @classmethod
    def from_env(
        cls,
        *,
        onedrive_service: Any,
        garmin_service: Any,
        garmin_activity_index_storage: Optional[GarminActivityIndexStorage] = None,
        garmin_physiometrics_service: Any,
        withings_service: Any,
        intervals_service: Any,
        deferred_retry_coordinator: Optional[Any] = None,
    ) -> "PlanningContextPreSyncHandler":
        """Build handler from environment-backed defaults."""
        return cls(
            onedrive_service=onedrive_service,
            garmin_service=garmin_service,
            garmin_activity_index_storage=garmin_activity_index_storage,
            garmin_physiometrics_service=garmin_physiometrics_service,
            withings_service=withings_service,
            intervals_service=intervals_service,
            intervals_athlete_id=os.getenv("INTERVALS_ATHLETE_ID"),
            planning_presync_garmin_activities_enabled=cls._parse_bool_env(
                os.getenv(
                    ENV_PLANNING_PRESYNC_GARMIN_ACTIVITIES_ENABLED,
                    "false",
                )
            ),
            planning_presync_garmin_physiometrics_enabled=cls._parse_bool_env(
                os.getenv(
                    ENV_PLANNING_PRESYNC_GARMIN_PHYSIOMETRICS_ENABLED,
                    "false",
                )
            ),
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
            planning_presync_freshness_ttl_sec=int(
                os.getenv(
                    ENV_PLANNING_PRESYNC_FRESHNESS_TTL_SEC,
                    str(DEFAULT_FRESHNESS_TTL_SEC),
                )
            ),
        )

    def run(self, athlete_id: str, *, days: int, force: bool = False) -> Dict[str, Any]:
        """Run all dependency syncs with best-available tolerance.

        All sources are attempted; individual failures produce a warning log
        and are recorded in the result but do not abort the remaining sources.
        The caller always receives a non-raising result dictionary.
        """
        lookback_days = max(1, int(days))
        operations = self._build_operations(athlete_id, lookback_days)
        presync_execution_id = str(uuid.uuid4())
        results_by_index: dict[int, Dict[str, Any]] = {}
        runnable_operations: list[tuple[int, PreSyncOperation]] = []

        for index, operation in enumerate(operations):
            if operation.source == "onedrive_workouts":
                runnable_operations.append((index, operation))
                continue

            if not force:
                should_skip, last_success_at = self._is_source_fresh(
                    athlete_id=athlete_id,
                    lookback_days=lookback_days,
                    source=operation.source,
                )
                if should_skip and last_success_at is not None:
                    logger.info(
                        "Planning context pre-sync source skipped due to freshness window",
                        extra={
                            "source": operation.source,
                            "athlete_id": athlete_id,
                            "lookback_days": lookback_days,
                            "reason": "fresh_within_ttl",
                            "last_success_at_utc": last_success_at.isoformat(),
                            "freshness_ttl_sec": self._planning_presync_freshness_ttl_sec,
                            "force": force,
                            "presync_execution_id": presync_execution_id,
                            "operation_index": index,
                        },
                    )
                    results_by_index[index] = {
                        "source": operation.source,
                        "status": "skipped",
                        "http_status": 200,
                        "message": "Skipped: source is fresh within TTL window",
                        "reason": "fresh_within_ttl",
                        "freshness_ttl_sec": self._planning_presync_freshness_ttl_sec,
                        "last_success_at_utc": last_success_at.isoformat(),
                        "duration_ms": 0,
                        "attempts": 0,
                    }
                    continue

            runnable_operations.append((index, operation))

        results_by_index.update(
            self._execute_operations_parallel(
                operations=runnable_operations,
                athlete_id=athlete_id,
                lookback_days=lookback_days,
                presync_execution_id=presync_execution_id,
            )
        )
        source_results = [results_by_index[index] for index in range(len(operations))]

        failed = sum(1 for r in source_results if r["status"] == "failed")
        total = len(source_results)

        if failed == 0:
            status = "all_succeeded"
            message = "Planning context pre-sync completed successfully"
        elif failed < total:
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

    def _compute_garmin_lookback_days(self, athlete_id: str, max_days: int) -> int:
        """Derive the Garmin lookback window from the last indexed activity.

        Returns the number of days between now and the most recent indexed
        Garmin activity, plus one to ensure the boundary day is included.
        If no activity is indexed yet, falls back to
        ``DEFAULT_GARMIN_PRESYNC_FALLBACK_LOOKBACK_DAYS``.  The result is
        capped at ``max_days`` so it never exceeds the caller's context window.
        """
        if self._garmin_activity_index_storage is None:
            return min(DEFAULT_GARMIN_PRESYNC_FALLBACK_LOOKBACK_DAYS, max_days)
        try:
            latest_iso = self._garmin_activity_index_storage.get_latest_indexed_start_time_utc(
                athlete_id=athlete_id
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Planning context pre-sync could not read Garmin activity index; "
                "falling back to default Garmin lookback window",
                extra={
                    "athlete_id": athlete_id,
                    "fallback_days": DEFAULT_GARMIN_PRESYNC_FALLBACK_LOOKBACK_DAYS,
                },
                exc_info=True,
            )
            return min(DEFAULT_GARMIN_PRESYNC_FALLBACK_LOOKBACK_DAYS, max_days)
        if latest_iso is None:
            return min(DEFAULT_GARMIN_PRESYNC_FALLBACK_LOOKBACK_DAYS, max_days)
        try:
            latest_dt = datetime.fromisoformat(latest_iso)
            if latest_dt.tzinfo is None:
                latest_dt = latest_dt.replace(tzinfo=timezone.utc)
            days_since = (datetime.now(timezone.utc) - latest_dt).days + 1
            return max(1, min(days_since, max_days))
        except (ValueError, TypeError):
            return min(DEFAULT_GARMIN_PRESYNC_FALLBACK_LOOKBACK_DAYS, max_days)

    def _build_operations(
        self, athlete_id: str, lookback_days: int
    ) -> list[PreSyncOperation]:
        """Build ordered source sync operations for the given window.

        OneDrive is always included for planning reads so the latest incremental
        delta is applied before semantic context is queried. Garmin lookback is
        derived from the most recent indexed activity rather than mirroring the
        full context ``lookback_days``.
        """
        garmin_lookback = self._compute_garmin_lookback_days(athlete_id, lookback_days)
        operations = build_presync_operations(
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            onedrive_service=self._onedrive_service,
            garmin_service=self._garmin_service,
            garmin_physiometrics_service=self._garmin_physiometrics_service,
            withings_service=self._withings_service,
            intervals_execute=lambda: self._run_intervals_sync(
                athlete_id=athlete_id,
                lookback_days=lookback_days,
            ),
            include_onedrive=True,
            garmin_lookback_days=garmin_lookback,
        )

        filtered_operations: list[PreSyncOperation] = []
        for operation in operations:
            if (
                operation.source == "garmin_activities"
                and not self._planning_presync_garmin_activities_enabled
            ):
                logger.info(
                    "Planning context pre-sync source skipped by configuration",
                    extra={
                        "source": operation.source,
                        "athlete_id": athlete_id,
                        "lookback_days": lookback_days,
                        "reason": "config_disabled",
                    },
                )
                continue

            if (
                operation.source == "garmin_physiometrics"
                and not self._planning_presync_garmin_physiometrics_enabled
            ):
                logger.info(
                    "Planning context pre-sync source skipped by configuration",
                    extra={
                        "source": operation.source,
                        "athlete_id": athlete_id,
                        "lookback_days": lookback_days,
                        "reason": "config_disabled",
                    },
                )
                continue

            filtered_operations.append(operation)

        return filtered_operations

    def _execute_operations_parallel(
        self,
        *,
        operations: list[tuple[int, PreSyncOperation]],
        athlete_id: str,
        lookback_days: int,
        presync_execution_id: str,
    ) -> dict[int, Dict[str, Any]]:
        """Execute operations concurrently while preserving source order."""
        if not operations:
            return {}

        max_workers = min(len(operations), DEFAULT_PARALLEL_MAX_WORKERS)
        results_by_index: dict[int, Dict[str, Any]] = {}

        logger.info(
            "Planning context pre-sync parallel execution started",
            extra={
                "athlete_id": athlete_id,
                "lookback_days": lookback_days,
                "source_count": len(operations),
                "max_workers": max_workers,
                "presync_execution_id": presync_execution_id,
            },
        )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_meta = {
                executor.submit(
                    copy_context().run,
                    self._execute_operation_worker,
                    operation,
                    athlete_id,
                    lookback_days,
                    presync_execution_id,
                    original_index,
                ): (original_index, operation.source)
                for original_index, operation in operations
            }

            for future in as_completed(future_to_meta):
                original_index, source = future_to_meta[future]
                result = future.result()
                results_by_index[original_index] = result

                if result["status"] == "success":
                    self._record_source_success(
                        athlete_id=athlete_id,
                        lookback_days=lookback_days,
                        source=source,
                    )

                if result["status"] != "success":
                    logger.warning(
                        "Planning context pre-sync source failed; continuing with remaining sources",
                        extra={
                            "source": source,
                            "athlete_id": athlete_id,
                            "http_status": result.get("http_status"),
                            "source_message": result.get("message"),
                            "presync_execution_id": presync_execution_id,
                            "operation_index": original_index,
                        },
                    )

        return results_by_index

    def _execute_operation_worker(
        self,
        operation: PreSyncOperation,
        athlete_id: str,
        lookback_days: int,
        presync_execution_id: str,
        operation_index: int,
    ) -> Dict[str, Any]:
        """Execute one operation inside a worker thread with traceable logs."""
        thread_name = threading.current_thread().name
        thread_id = threading.get_ident()

        logger.info(
            "Planning context pre-sync worker started",
            extra={
                "source": operation.source,
                "athlete_id": athlete_id,
                "lookback_days": lookback_days,
                "presync_execution_id": presync_execution_id,
                "operation_index": operation_index,
                "worker_thread_name": thread_name,
                "worker_thread_id": thread_id,
            },
        )
        result = self._execute_with_retry(operation)
        logger.info(
            "Planning context pre-sync worker completed",
            extra={
                "source": operation.source,
                "athlete_id": athlete_id,
                "lookback_days": lookback_days,
                "status": result.get("status"),
                "http_status": result.get("http_status"),
                "duration_ms": result.get("duration_ms"),
                "presync_execution_id": presync_execution_id,
                "operation_index": operation_index,
                "worker_thread_name": thread_name,
                "worker_thread_id": thread_id,
            },
        )
        return result

    def _is_source_fresh(
        self,
        *,
        athlete_id: str,
        lookback_days: int,
        source: str,
    ) -> tuple[bool, Optional[datetime]]:
        """Return whether the source succeeded recently enough to skip execution."""
        if self._planning_presync_freshness_ttl_sec <= 0:
            return False, None

        freshness_key = (athlete_id, lookback_days, source)
        with self._freshness_lock:
            last_success_at = self._freshness_registry.get(freshness_key)

        if last_success_at is None:
            return False, None

        now_utc = datetime.now(timezone.utc)
        is_fresh = (now_utc - last_success_at) < timedelta(
            seconds=self._planning_presync_freshness_ttl_sec
        )
        return is_fresh, last_success_at

    def _record_source_success(
        self,
        *,
        athlete_id: str,
        lookback_days: int,
        source: str,
    ) -> None:
        """Record successful source execution timestamp for freshness gating."""
        if self._planning_presync_freshness_ttl_sec <= 0:
            return

        freshness_key = (athlete_id, lookback_days, source)
        with self._freshness_lock:
            self._freshness_registry[freshness_key] = datetime.now(timezone.utc)

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
