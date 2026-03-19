"""Unit tests for deferred retry queue adapter initialization behavior."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue
from TrainingAnalyticsPlatform.platform.exceptions import StorageError


class _FakeQueueClient:
    """Test double for Azure QueueClient."""

    create_queue_side_effect: ClassVar[Any | None] = None

    @classmethod
    def from_connection_string(cls, _connection_string: str, _queue_name: str):
        return cls()

    def create_queue(self) -> None:
        if self.create_queue_side_effect is None:
            return
        if isinstance(self.create_queue_side_effect, Exception):
            raise self.create_queue_side_effect
        raise self.create_queue_side_effect()


class _QueueAlreadyExistsError(Exception):
    """Simulate Azure queue already exists exception shape."""

    error_code = "Queue_Already_Exists"


class TestDeferredRetryQueueInitialization:
    def test_init_succeeds_when_queue_already_exists(self, monkeypatch):
        monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
        _FakeQueueClient.create_queue_side_effect = _QueueAlreadyExistsError(
            "StorageErrorCode.QUEUE_ALREADY_EXISTS"
        )
        monkeypatch.setattr(
            DeferredRetryQueue,
            "_import_queue_client",
            staticmethod(lambda: _FakeQueueClient),
        )

        queue = DeferredRetryQueue(queue_name="rate-limit-deferrals")

        assert queue.queue_name == "rate-limit-deferrals"

    def test_init_raises_for_non_already_exists_error(self, monkeypatch):
        monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
        _FakeQueueClient.create_queue_side_effect = RuntimeError("boom")
        monkeypatch.setattr(
            DeferredRetryQueue,
            "_import_queue_client",
            staticmethod(lambda: _FakeQueueClient),
        )

        with pytest.raises(StorageError, match="Failed to initialize deferred retry queue"):
            DeferredRetryQueue(queue_name="rate-limit-deferrals")
