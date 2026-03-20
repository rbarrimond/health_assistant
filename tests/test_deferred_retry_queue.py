"""Unit tests for deferred retry queue adapter initialization and bootstrap behavior."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import ANY, MagicMock

import pytest

from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue
from TrainingAnalyticsPlatform.platform.exceptions import StorageError


class _FakeQueueClient:
    """Test double for Azure QueueClient."""

    create_queue_side_effect: ClassVar[Any | None] = None

    @classmethod
    def from_connection_string(
        cls,
        _connection_string: str,
        _queue_name: str,
        **_kwargs: Any,
    ):
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


class _FakeEncodePolicy:
    """Test double for queue encode policy."""


class _FakeDecodePolicy:
    """Test double for queue decode policy."""


def _make_queue(monkeypatch, *, side_effect: Any = None) -> DeferredRetryQueue:
    """Build a DeferredRetryQueue with the fake client wired in."""
    _FakeQueueClient.create_queue_side_effect = side_effect
    monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
    monkeypatch.setattr(
        DeferredRetryQueue,
        "_import_queue_client",
        staticmethod(lambda: (_FakeQueueClient, _FakeEncodePolicy, _FakeDecodePolicy)),
    )
    return DeferredRetryQueue(queue_name="rate-limit-deferrals")


class TestDeferredRetryQueueInitialization:
    def test_constructor_does_not_call_create_queue(self, monkeypatch):
        """Constructor must be pure wiring — no I/O side effects."""
        mock_client_cls = MagicMock()
        mock_client_instance = mock_client_cls.from_connection_string.return_value

        monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
        monkeypatch.setattr(
            DeferredRetryQueue,
            "_import_queue_client",
            staticmethod(lambda: (mock_client_cls, _FakeEncodePolicy, _FakeDecodePolicy)),
        )

        DeferredRetryQueue(queue_name="rate-limit-deferrals")

        mock_client_cls.from_connection_string.assert_called_once_with(
            "UseDevelopmentStorage=true",
            "rate-limit-deferrals",
            message_encode_policy=ANY,
            message_decode_policy=ANY,
        )
        mock_client_instance.create_queue.assert_not_called()

    def test_constructor_exposes_queue_name(self, monkeypatch):
        queue = _make_queue(monkeypatch)
        assert queue.queue_name == "rate-limit-deferrals"

    def test_constructor_raises_when_connection_string_missing(self, monkeypatch):
        monkeypatch.delenv("AzureWebJobsStorage", raising=False)
        monkeypatch.setattr(
            DeferredRetryQueue,
            "_import_queue_client",
            staticmethod(lambda: (_FakeQueueClient, _FakeEncodePolicy, _FakeDecodePolicy)),
        )
        with pytest.raises(ValueError, match="AzureWebJobsStorage"):
            DeferredRetryQueue(queue_name="rate-limit-deferrals")


class TestDeferredRetryQueueBootstrap:
    def test_bootstrap_creates_queue_on_first_call(self, monkeypatch):
        """bootstrap() calls create_queue() once on the underlying client."""
        mock_client_cls = MagicMock()
        mock_client_instance = mock_client_cls.from_connection_string.return_value

        monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
        monkeypatch.setattr(
            DeferredRetryQueue,
            "_import_queue_client",
            staticmethod(lambda: (mock_client_cls, _FakeEncodePolicy, _FakeDecodePolicy)),
        )

        queue = DeferredRetryQueue(queue_name="rate-limit-deferrals")
        queue.bootstrap()

        mock_client_instance.create_queue.assert_called_once()

    def test_bootstrap_is_idempotent_when_queue_already_exists(self, monkeypatch):
        """bootstrap() succeeds silently when queue already exists — no exception raised."""
        queue = _make_queue(
            monkeypatch,
            side_effect=_QueueAlreadyExistsError("StorageErrorCode.QUEUE_ALREADY_EXISTS"),
        )
        queue.bootstrap()  # must not raise

        assert queue.queue_name == "rate-limit-deferrals"

    def test_bootstrap_raises_storage_error_on_unexpected_failure(self, monkeypatch):
        """bootstrap() raises StorageError when create_queue() fails with an unexpected error."""
        queue = _make_queue(monkeypatch, side_effect=RuntimeError("network timeout"))

        with pytest.raises(StorageError, match="Failed to bootstrap deferred retry queue"):
            queue.bootstrap()

    def test_bootstrap_preserves_causal_exception(self, monkeypatch):
        """StorageError raised by bootstrap() chains the original exception as cause."""
        original = RuntimeError("connection refused")
        queue = _make_queue(monkeypatch, side_effect=original)

        with pytest.raises(StorageError) as exc_info:
            queue.bootstrap()

        assert exc_info.value.__cause__ is original
