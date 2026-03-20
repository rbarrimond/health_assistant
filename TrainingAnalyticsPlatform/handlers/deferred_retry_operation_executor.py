"""Domain executor for deferred retry queue work items."""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from TrainingAnalyticsPlatform.handlers.deferred_retry_coordinator import (
    DeferredRetryCoordinator,
)
from TrainingAnalyticsPlatform.handlers.deferred_retry_lifecycle_service import (
    DeferredRetryLifecycleService,
)
from TrainingAnalyticsPlatform.handlers.source_handler_registry import (
    DeferredRetrySourceHandler,
    SourceHandlerRegistry,
)
from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue

logger = logging.getLogger(__name__)


class DeferredRetryOperationExecutor:
    """Execute one deferred retry queue message end-to-end."""

    def __init__(
        self,
        *,
        queue: DeferredRetryQueue,
        lifecycle: DeferredRetryLifecycleService,
        coordinator: DeferredRetryCoordinator | None,
        source_registry: SourceHandlerRegistry[DeferredRetrySourceHandler],
    ):
        self._queue = queue
        self._lifecycle = lifecycle
        self._coordinator = coordinator
        self._source_registry = source_registry

    def process_message(self, message_body: str) -> None:
        """Process one deferred retry message body."""
        work_item = self._queue.decode_message(message_body)

        state = self._lifecycle.get_state(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
        )
        if state is None:
            logger.warning(
                "Deferred retry state not found; message ignored",
                extra={
                    "athlete_id": work_item.athlete_id,
                    "operation_id": work_item.operation_id,
                    "source": work_item.source,
                },
            )
            return

        in_progress = self._lifecycle.start_retrying(
            athlete_id=work_item.athlete_id,
            operation_id=work_item.operation_id,
            etag=state.etag,
        )

        source_response = self._execute_source(
            source=work_item.source,
            athlete_id=work_item.athlete_id,
            lookback_days=work_item.lookback_days,
        )
        body, status_code, headers = self._normalize_source_response(source_response)

        if status_code == 200:
            self._lifecycle.complete_success(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                etag=in_progress.etag,
            )
            logger.info(
                "Deferred retry replay succeeded",
                extra={
                    "athlete_id": work_item.athlete_id,
                    "operation_id": work_item.operation_id,
                    "source": work_item.source,
                },
            )
            return

        retry_after_raw = self._extract_retry_after_from_response(body, headers)
        elapsed_sec = 0.0
        if self._coordinator is None:
            self._lifecycle.complete_failure(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                etag=in_progress.etag,
            )
            logger.warning(
                "Deferred retry coordinator unavailable; replay marked failed",
                extra={
                    "athlete_id": work_item.athlete_id,
                    "operation_id": work_item.operation_id,
                    "source": work_item.source,
                    "http_status": status_code,
                },
            )
            return

        decision = self._coordinator.maybe_defer(
            athlete_id=work_item.athlete_id,
            source=work_item.source,
            lookback_days=work_item.lookback_days,
            retry_after_raw=retry_after_raw,
            elapsed_sec=elapsed_sec,
        )
        if decision.deferred:
            self._lifecycle.defer_again(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                etag=in_progress.etag,
            )
        else:
            self._lifecycle.complete_failure(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                etag=in_progress.etag,
            )
        logger.warning(
            "Deferred retry replay did not succeed",
            extra={
                "athlete_id": work_item.athlete_id,
                "operation_id": work_item.operation_id,
                "source": work_item.source,
                "http_status": status_code,
                "deferred_again": decision.deferred,
                "safe_to_retry_at_utc": decision.safe_to_retry_at_utc,
            },
        )

    def _execute_source(
        self,
        *,
        source: str,
        athlete_id: str,
        lookback_days: int,
    ) -> tuple[Dict[str, Any], int] | tuple[Dict[str, Any], int, Dict[str, Any]]:
        handler = self._source_registry.resolve(source)
        if handler is not None:
            return handler(athlete_id, lookback_days)

        return {"error": f"Unsupported deferred retry source: {source}"}, 400

    @staticmethod
    def _extract_retry_after_from_response(
        body: Dict[str, Any],
        headers: Dict[str, Any],
    ) -> str | None:
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "retry-after":
                return None if value is None else str(value)

        for key in ("retry_after", "retryAfter"):
            value = body.get(key)
            if value is not None:
                return str(value)
        return None

    @staticmethod
    def _normalize_source_response(
        response: Any,
    ) -> Tuple[Dict[str, Any], int, Dict[str, Any]]:
        if isinstance(response, tuple) and len(response) == 2:
            body, status_code = response
            if isinstance(body, dict):
                return body, int(status_code), {}
        if isinstance(response, tuple) and len(response) == 3:
            body, status_code, headers = response
            if isinstance(body, dict):
                return body, int(status_code), headers if isinstance(headers, dict) else {}
        return {"error": "Invalid deferred retry response shape"}, 500, {}
