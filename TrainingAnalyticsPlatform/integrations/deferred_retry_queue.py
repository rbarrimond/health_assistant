"""Azure Queue adapter for deferred retry work items."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from TrainingAnalyticsPlatform.models.retry import DeferredRetryWorkItem
from TrainingAnalyticsPlatform.platform.exceptions import StorageError

logger = logging.getLogger(__name__)

DEFAULT_DEFERRED_RETRY_QUEUE_NAME = "rate-limit-deferrals"


@dataclass
class QueueEnqueueResult:
    """Message identifiers returned by Azure Queue enqueue operations."""

    message_id: str
    pop_receipt: str


class DeferredRetryQueue:
    """Encapsulate Azure Queue enqueue/decode behavior for deferred retries."""

    def __init__(
        self,
        *,
        queue_name: str = DEFAULT_DEFERRED_RETRY_QUEUE_NAME,
        connection_string: Optional[str] = None,
    ) -> None:
        queue_client_cls, encode_policy_cls, decode_policy_cls = self._import_queue_client()
        resolved_conn = connection_string or os.getenv("AzureWebJobsStorage")
        if not resolved_conn:
            raise ValueError("AzureWebJobsStorage is required for deferred retry queue")

        self._queue_client = queue_client_cls.from_connection_string(
            resolved_conn,
            queue_name,
            message_encode_policy=encode_policy_cls(),
            message_decode_policy=decode_policy_cls(),
        )
        self._queue_name = queue_name

    def bootstrap(self) -> None:
        """Create the queue if it does not already exist. Idempotent — safe to call multiple times."""
        try:
            self._queue_client.create_queue()
            logger.info(
                "Deferred retry queue bootstrapped",
                extra={
                    "queue_name": self._queue_name,
                    "queue_init_status": "created",
                },
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if self._is_queue_already_exists_error(exc):
                logger.info(
                    "Deferred retry queue bootstrapped",
                    extra={
                        "queue_name": self._queue_name,
                        "queue_init_status": "already_exists",
                    },
                )
            else:
                logger.error(
                    "Failed to bootstrap deferred retry queue",
                    extra={"queue_name": self._queue_name},
                    exc_info=True,
                )
                raise StorageError("Failed to bootstrap deferred retry queue") from exc

    @staticmethod
    def _import_queue_client() -> Any:
        """Import Azure Queue client lazily so non-queue tests can import the module."""
        try:
            from azure.storage.queue import QueueClient, TextBase64DecodePolicy, TextBase64EncodePolicy
        except ImportError as exc:  # pragma: no cover - environment-specific import guard
            raise StorageError(
                "azure-storage-queue is required for deferred retry queue support"
            ) from exc
        return QueueClient, TextBase64EncodePolicy, TextBase64DecodePolicy

    @property
    def queue_name(self) -> str:
        """Return configured queue name."""
        return self._queue_name

    @staticmethod
    def _is_queue_already_exists_error(exc: Exception) -> bool:
        """Return True when queue creation failed because queue already exists."""
        error_code = getattr(exc, "error_code", None) or getattr(exc, "code", None)
        if isinstance(error_code, str):
            normalized = error_code.upper()
            if normalized in {
                "QUEUE_ALREADY_EXISTS",
                "STORAGEERRORCODE.QUEUE_ALREADY_EXISTS",
            }:
                return True

        message = str(exc).upper()
        return (
            "QUEUE_ALREADY_EXISTS" in message
            or "STORAGEERRORCODE.QUEUE_ALREADY_EXISTS" in message
        )

    def enqueue(
        self,
        *,
        item: DeferredRetryWorkItem,
        visibility_timeout: int,
    ) -> QueueEnqueueResult:
        """Enqueue deferred retry work to become visible at a future time."""
        payload = item.model_dump_json()
        try:
            response = self._queue_client.send_message(
                payload,
                visibility_timeout=max(0, int(visibility_timeout)),
            )
            logger.info(
                "Deferred retry queued",
                extra={
                    "queue_name": self._queue_name,
                    "operation_id": item.operation_id,
                    "visibility_timeout": visibility_timeout,
                },
            )
            return QueueEnqueueResult(
                message_id=response.id,
                pop_receipt=response.pop_receipt,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Failed to enqueue deferred retry work item",
                extra={
                    "queue_name": self._queue_name,
                    "operation_id": item.operation_id,
                },
                exc_info=True,
            )
            raise StorageError("Failed to enqueue deferred retry work item") from exc

    @staticmethod
    def decode_message(message_body: str) -> DeferredRetryWorkItem:
        """Decode Queue message body into typed work item model."""
        data = json.loads(message_body)
        return DeferredRetryWorkItem.model_validate(data)