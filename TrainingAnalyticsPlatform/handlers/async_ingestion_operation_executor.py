"""Domain executor for async ingestion queue work items."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Dict

from TrainingAnalyticsPlatform.handlers.async_ingestion_lifecycle_service import (
    AsyncIngestionLifecycleService,
)
from TrainingAnalyticsPlatform.handlers.source_handler_registry import (
    AsyncIngestionSourceHandler,
    SourceHandlerRegistry,
)
from TrainingAnalyticsPlatform.models.async_ingestion import AsyncIngestionWorkItem
from TrainingAnalyticsPlatform.platform.exceptions import (
    CompressionError,
    ConfigError,
    DeviceFilteredError,
    ExternalServiceError,
    FitParsingError,
    HealthAssistantError,
    IngestionIdResolutionError,
    InvalidFileFormatError,
    StorageError,
    SyncError,
    ValidationError,
    WorkoutIdCalculationError,
)

logger = logging.getLogger(__name__)


_TERMINAL_HEALTH_ASSISTANT_EXCEPTIONS = (
    ValidationError,
    ConfigError,
    FitParsingError,
    CompressionError,
    InvalidFileFormatError,
    DeviceFilteredError,
    IngestionIdResolutionError,
    WorkoutIdCalculationError,
)

_RETRYABLE_HEALTH_ASSISTANT_EXCEPTIONS = (
    StorageError,
    ExternalServiceError,
    SyncError,
)

_RETRYABLE_EXCEPTION_TYPE_NAMES = {
    "AzureError",
    "HttpResponseError",
    "ServiceRequestError",
    "ServiceResponseError",
    "ServiceRequestTimeoutError",
    "ResourceExistsError",
    "ResourceModifiedError",
    "ConnectTimeout",
    "ReadTimeout",
    "Timeout",
    "ConnectionError",
}


class AsyncIngestionOperationExecutor:
    """Execute one async ingestion queue message end-to-end."""

    def __init__(
        self,
        *,
        lifecycle: AsyncIngestionLifecycleService,
        source_registry: SourceHandlerRegistry[AsyncIngestionSourceHandler],
    ):
        self._lifecycle = lifecycle
        self._source_registry = source_registry

    def process_message(self, message_body: str) -> None:
        """Process one async ingestion message body."""
        work_item = AsyncIngestionWorkItem.model_validate_json(message_body)
        force = bool(work_item.context.get("force", False))

        state = self._lifecycle.get_or_initialize(work_item=work_item)
        etag = state.etag if state else None

        logger.info(
            "Async ingestion worker started",
            extra={
                "operation_id": work_item.operation_id,
                "source": work_item.source,
                "athlete_id": work_item.athlete_id,
                "lookback_days": work_item.lookback_days,
                "force": force,
            },
        )

        try:
            self._lifecycle.start_processing(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                etag=etag,
            )

            result = self._execute_source(work_item=work_item, force=force)
            if result is None:
                return

            self._lifecycle.complete_success(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                result={
                    "status": result.get("status"),
                    "found": result.get("found"),
                    "ingested": result.get("ingested"),
                    "skipped": result.get("skipped"),
                    "failed": result.get("failed"),
                },
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            should_retry = self._should_retry_exception(exc)
            self._lifecycle.complete_failure(
                athlete_id=work_item.athlete_id,
                operation_id=work_item.operation_id,
                error=str(exc),
            )
            logger.error(
                "Async ingestion worker failed",
                extra={
                    "operation_id": work_item.operation_id,
                    "source": work_item.source,
                    "athlete_id": work_item.athlete_id,
                    "lookback_days": work_item.lookback_days,
                    "force": force,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "retryable": should_retry,
                },
                exc_info=True,
            )
            if should_retry:
                raise
            return

        logger.info(
            "Async ingestion worker completed",
            extra={
                "operation_id": work_item.operation_id,
                "source": work_item.source,
                "athlete_id": work_item.athlete_id,
                "lookback_days": work_item.lookback_days,
                "force": force,
                "result_status": result.get("status"),
                "ingested": result.get("ingested"),
                "skipped": result.get("skipped"),
                "failed": result.get("failed"),
            },
        )

    def _should_retry_exception(self, exc: Exception) -> bool:
        """Return True when host-level retry should be requested for this failure."""
        if isinstance(exc, _TERMINAL_HEALTH_ASSISTANT_EXCEPTIONS):
            return False

        if isinstance(exc, _RETRYABLE_HEALTH_ASSISTANT_EXCEPTIONS):
            return True

        if isinstance(exc, HealthAssistantError):
            return False

        for cause in self._iter_exception_chain(exc):
            if isinstance(cause, _TERMINAL_HEALTH_ASSISTANT_EXCEPTIONS):
                return False
            if isinstance(cause, _RETRYABLE_HEALTH_ASSISTANT_EXCEPTIONS):
                return True
            if isinstance(cause, (ConnectionError, TimeoutError, OSError)):
                return True
            if type(cause).__name__ in _RETRYABLE_EXCEPTION_TYPE_NAMES:
                return True

        return True

    @staticmethod
    def _iter_exception_chain(exc: Exception) -> Iterator[Exception]:
        """Yield exception and explicit cause/context chain once each."""
        seen: set[int] = set()
        current: Exception | None = exc
        while current is not None:
            current_id = id(current)
            if current_id in seen:
                break
            seen.add(current_id)
            yield current
            current = current.__cause__ or current.__context__

    def _execute_source(
        self,
        *,
        work_item: AsyncIngestionWorkItem,
        force: bool,
    ) -> Dict[str, Any] | None:
        handler = self._source_registry.resolve(work_item.source)
        if handler is not None:
            return handler(work_item.athlete_id, work_item.lookback_days, force)

        logger.warning(
            "Unsupported async ingestion source",
            extra={
                "operation_id": work_item.operation_id,
                "source": work_item.source,
                "athlete_id": work_item.athlete_id,
            },
        )
        return None
