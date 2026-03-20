"""Lifecycle service for deferred retry operation state transitions."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from TrainingAnalyticsPlatform.models.retry import RateLimitDeferralState
from TrainingAnalyticsPlatform.storage.retry_deferral_storage import RetryDeferralStorage

logger = logging.getLogger(__name__)

# Valid state transitions: target status -> set of legal current statuses.
# Documented for readability; implicit enforcement through named methods.
_VALID_FROM_STATES: Dict[str, frozenset[str]] = {
    "retrying": frozenset({"queued", "deferred"}),
    "succeeded": frozenset({"retrying"}),
    "deferred": frozenset({"retrying"}),
    "failed": frozenset({"retrying"}),
}


class DeferredRetryLifecycleService:
    """Owns legal lifecycle transitions for deferred retry operations.

    Centralises all mark_status choreography and enforces state machine
    semantics through named transition methods rather than an open
    set_status(status=...) interface.

    State machine:
        queued/deferred -> retrying -> succeeded
                                   \\-> deferred
                                   \\-> failed
    """

    def __init__(self, storage: RetryDeferralStorage) -> None:
        self._storage = storage

    def get_state(
        self,
        *,
        athlete_id: str,
        operation_id: str,
    ) -> Optional[RateLimitDeferralState]:
        """Return current deferred retry state, or None if absent."""
        return self._storage.get_state(
            athlete_id=athlete_id,
            operation_id=operation_id,
        )

    def start_retrying(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        etag: Optional[str],
    ) -> RateLimitDeferralState:
        """Transition -> retrying, incrementing the attempt counter.

        ETag from the current state is passed for optimistic concurrency.
        """
        return self._storage.mark_status(
            athlete_id=athlete_id,
            operation_id=operation_id,
            status="retrying",
            etag=etag,
            increment_attempts=True,
        )

    def complete_success(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        etag: Optional[str],
    ) -> RateLimitDeferralState:
        """Transition retrying -> succeeded."""
        return self._storage.mark_status(
            athlete_id=athlete_id,
            operation_id=operation_id,
            status="succeeded",
            etag=etag,
            increment_attempts=False,
        )

    def complete_failure(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        etag: Optional[str],
    ) -> RateLimitDeferralState:
        """Transition retrying -> failed."""
        return self._storage.mark_status(
            athlete_id=athlete_id,
            operation_id=operation_id,
            status="failed",
            etag=etag,
            increment_attempts=False,
        )

    def defer_again(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        etag: Optional[str],
    ) -> RateLimitDeferralState:
        """Transition retrying -> deferred."""
        return self._storage.mark_status(
            athlete_id=athlete_id,
            operation_id=operation_id,
            status="deferred",
            etag=etag,
            increment_attempts=False,
        )
