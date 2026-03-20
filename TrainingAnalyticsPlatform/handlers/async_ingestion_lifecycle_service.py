"""Lifecycle service for async ingestion operation state transitions."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from TrainingAnalyticsPlatform.models.async_ingestion import AsyncIngestionWorkItem
from TrainingAnalyticsPlatform.models.async_operation import AsyncIngestionOperationState
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.async_ingestion_operation_storage import (
    AsyncIngestionOperationStorage,
)

logger = logging.getLogger(__name__)

# Valid state transitions: target status -> set of legal current statuses.
# Documented for readability; implicit enforcement through named methods.
_VALID_FROM_STATES: Dict[str, frozenset[str]] = {
    "processing": frozenset({"queued"}),
    "succeeded": frozenset({"processing"}),
    "failed": frozenset({"queued", "processing"}),
}


class AsyncIngestionLifecycleService:
    """Owns legal lifecycle transitions for async ingestion operations.

    Centralises all mark_status choreography and enforces state machine
    semantics through named transition methods rather than an open
    set_status(status=...) interface.

    State machine:
        queued -> processing -> succeeded
                            \\-> failed
    """

    def __init__(self, storage: AsyncIngestionOperationStorage) -> None:
        self._storage = storage

    def get_or_initialize(
        self,
        *,
        work_item: AsyncIngestionWorkItem,
    ) -> AsyncIngestionOperationState:
        """Return existing state for operation, or upsert initial queued state.

        Idempotent: safe to call multiple times for the same work item.
        """
        state = self._storage.get_state(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
        )
        if state is None:
            self._storage.upsert_state(
                AsyncIngestionOperationState.queued(
                    athlete_id=work_item.athlete_id,
                    operation_id=work_item.operation_id,
                    source=work_item.source,
                    lookback_days=work_item.lookback_days,
                    mode="async_queue",
                    queued_at_utc=work_item.queued_at_utc,
                    request_id=work_item.request_id,
                    correlation_id=work_item.correlation_id,
                    context=work_item.context,
                )
            )
            state = self._storage.get_state(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
            )
            if state is None:
                raise StorageError(
                    f"Async ingestion operation state missing after upsert: "
                    f"{work_item.operation_id}"
                )
        return state

    def start_processing(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        etag: Optional[str],
    ) -> AsyncIngestionOperationState:
        """Transition queued -> processing with optimistic concurrency.

        The ETag from the queued state is passed to guard against concurrent
        workers acquiring the processing lock simultaneously.
        """
        return self._storage.mark_status(
            athlete_id=athlete_id,
            operation_id=operation_id,
            status="processing",
            etag=etag,
        )

    def complete_success(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        result: Dict[str, Any],
    ) -> AsyncIngestionOperationState:
        """Transition processing -> succeeded, persisting result payload."""
        return self._storage.mark_status(
            athlete_id=athlete_id,
            operation_id=operation_id,
            status="succeeded",
            result=result,
        )

    def complete_failure(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        error: str,
    ) -> AsyncIngestionOperationState:
        """Transition processing -> failed, persisting error description."""
        return self._storage.mark_status(
            athlete_id=athlete_id,
            operation_id=operation_id,
            status="failed",
            error=error,
        )
