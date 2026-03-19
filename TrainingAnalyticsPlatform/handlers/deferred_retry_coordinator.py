"""Coordinate timeout-risk retry deferral through Azure Queue + Table state."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue
from TrainingAnalyticsPlatform.models.retry import (
    DeferredRetryDecision,
    DeferredRetryWorkItem,
    RateLimitDeferralState,
    blocked_until_iso,
    parse_retry_after_seconds,
)
from TrainingAnalyticsPlatform.storage.retry_deferral_storage import RetryDeferralStorage

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_BUDGET_SEC = 220
DEFAULT_SAFETY_MARGIN_SEC = 20


@dataclass
class DeferredRetryPolicy:
    """Policy inputs controlling timeout-risk based deferral."""

    enabled: bool
    request_budget_sec: int
    safety_margin_sec: int
    schema_version: str


class DeferredRetryCoordinator:
    """Coordinate deferral decisions and persist deferred retry work/state."""

    def __init__(
        self,
        *,
        queue: DeferredRetryQueue,
        storage: RetryDeferralStorage,
        policy: DeferredRetryPolicy,
    ) -> None:
        self._queue = queue
        self._storage = storage
        self._policy = policy

    @classmethod
    def from_env(
        cls,
        *,
        queue: DeferredRetryQueue,
        storage: RetryDeferralStorage,
    ) -> "DeferredRetryCoordinator":
        """Build coordinator with environment-derived policy."""
        policy = DeferredRetryPolicy(
            enabled=os.getenv("DEFERRED_RETRY_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            request_budget_sec=max(
                1,
                int(os.getenv("DEFERRED_RETRY_HTTP_REQUEST_BUDGET_SEC", str(DEFAULT_REQUEST_BUDGET_SEC))),
            ),
            safety_margin_sec=max(
                0,
                int(os.getenv("DEFERRED_RETRY_SAFETY_MARGIN_SEC", str(DEFAULT_SAFETY_MARGIN_SEC))),
            ),
            schema_version=os.getenv("DEFERRED_RETRY_SCHEMA_VERSION", "1.0"),
        )
        return cls(queue=queue, storage=storage, policy=policy)

    def maybe_defer(
        self,
        *,
        athlete_id: str,
        source: str,
        lookback_days: int,
        retry_after_raw: Optional[str],
        elapsed_sec: float,
    ) -> DeferredRetryDecision:
        """Return deferral decision for timeout-risk scenario and persist when deferred."""
        if not self._policy.enabled:
            return DeferredRetryDecision(deferred=False, reason="disabled")

        retry_after_seconds = parse_retry_after_seconds(retry_after_raw)
        if retry_after_seconds is None or retry_after_seconds <= 0:
            return DeferredRetryDecision(deferred=False, reason="retry_after_unavailable")

        remaining_budget = max(
            0,
            self._policy.request_budget_sec - int(elapsed_sec) - self._policy.safety_margin_sec,
        )
        if retry_after_seconds <= remaining_budget:
            return DeferredRetryDecision(
                deferred=False,
                retry_after_raw=retry_after_raw,
                retry_after_seconds=retry_after_seconds,
                reason="safe_within_request_budget",
            )

        operation_id = str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc)
        safe_to_retry_at = blocked_until_iso(
            retry_after_seconds=retry_after_seconds,
            now_utc=now_utc,
        )
        idempotency_key = f"{athlete_id}:{source}:{lookback_days}:{safe_to_retry_at}"

        work_item = DeferredRetryWorkItem(
            operation_id=operation_id,
            schema_version=self._policy.schema_version,
            athlete_id=athlete_id,
            source=source,
            lookback_days=lookback_days,
            idempotency_key=idempotency_key,
            queued_at_utc=now_utc.isoformat(),
            blocked_until_utc=safe_to_retry_at,
            retry_after_raw=retry_after_raw,
            retry_after_seconds=retry_after_seconds,
        )

        state = RateLimitDeferralState(
            partition_key=athlete_id,
            row_key=operation_id,
            athlete_id=athlete_id,
            source=source,
            lookback_days=lookback_days,
            status="deferred",
            retry_after_raw=retry_after_raw,
            retry_after_seconds=retry_after_seconds,
            blocked_until_utc=safe_to_retry_at,
            created_at_utc=now_utc.isoformat(),
            updated_at_utc=now_utc.isoformat(),
            attempt_count=0,
            idempotency_key=idempotency_key,
        )

        self._storage.upsert_state(state)
        self._queue.enqueue(item=work_item, visibility_timeout=retry_after_seconds)

        logger.info(
            "Deferred retry scheduled due to timeout-risk policy",
            extra={
                "athlete_id": athlete_id,
                "source": source,
                "lookback_days": lookback_days,
                "operation_id": operation_id,
                "retry_after_seconds": retry_after_seconds,
                "request_budget_sec": self._policy.request_budget_sec,
                "remaining_budget_sec": remaining_budget,
                "safe_to_retry_at_utc": safe_to_retry_at,
            },
        )
        return DeferredRetryDecision(
            deferred=True,
            operation_id=operation_id,
            safe_to_retry_at_utc=safe_to_retry_at,
            retry_after_raw=retry_after_raw,
            retry_after_seconds=retry_after_seconds,
            reason="timeout_risk",
        )