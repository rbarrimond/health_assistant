"""Unit tests for async ingestion queue adapter initialization and bootstrap behavior."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from TrainingAnalyticsPlatform.integrations.async_ingestion_queue import AsyncIngestionQueue
from TrainingAnalyticsPlatform.platform.dependencies import FunctionAppDependencies
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


def _make_queue(monkeypatch, *, side_effect: Any = None) -> AsyncIngestionQueue:
    """Build an AsyncIngestionQueue with the fake client wired in."""
    _FakeQueueClient.create_queue_side_effect = side_effect
    monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
    monkeypatch.setattr(
        AsyncIngestionQueue,
        "_import_queue_client",
        staticmethod(lambda: _FakeQueueClient),
    )
    return AsyncIngestionQueue(queue_name="async-ingestion")


class TestAsyncIngestionQueueInitialization:
    def test_constructor_does_not_call_create_queue(self, monkeypatch):
        """Constructor must be pure wiring — no I/O side effects."""
        mock_client_cls = MagicMock()
        mock_client_instance = mock_client_cls.from_connection_string.return_value

        monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
        monkeypatch.setattr(
            AsyncIngestionQueue,
            "_import_queue_client",
            staticmethod(lambda: mock_client_cls),
        )

        AsyncIngestionQueue(queue_name="async-ingestion")

        mock_client_instance.create_queue.assert_not_called()

    def test_constructor_exposes_queue_name(self, monkeypatch):
        queue = _make_queue(monkeypatch)
        assert queue.queue_name == "async-ingestion"

    def test_constructor_raises_when_connection_string_missing(self, monkeypatch):
        monkeypatch.delenv("AzureWebJobsStorage", raising=False)
        monkeypatch.setattr(
            AsyncIngestionQueue,
            "_import_queue_client",
            staticmethod(lambda: _FakeQueueClient),
        )
        with pytest.raises(ValueError, match="AzureWebJobsStorage"):
            AsyncIngestionQueue(queue_name="async-ingestion")


class TestAsyncIngestionQueueBootstrap:
    def test_bootstrap_creates_queue_on_first_call(self, monkeypatch):
        """bootstrap() calls create_queue() once on the underlying client."""
        mock_client_cls = MagicMock()
        mock_client_instance = mock_client_cls.from_connection_string.return_value

        monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
        monkeypatch.setattr(
            AsyncIngestionQueue,
            "_import_queue_client",
            staticmethod(lambda: mock_client_cls),
        )

        queue = AsyncIngestionQueue(queue_name="async-ingestion")
        queue.bootstrap()

        mock_client_instance.create_queue.assert_called_once()

    def test_bootstrap_is_idempotent_when_queue_already_exists(self, monkeypatch):
        """bootstrap() succeeds silently when queue already exists — no exception raised."""
        queue = _make_queue(
            monkeypatch,
            side_effect=_QueueAlreadyExistsError("StorageErrorCode.QUEUE_ALREADY_EXISTS"),
        )
        queue.bootstrap()  # must not raise

        assert queue.queue_name == "async-ingestion"

    def test_bootstrap_raises_storage_error_on_unexpected_failure(self, monkeypatch):
        """bootstrap() raises StorageError when create_queue() fails with an unexpected error."""
        queue = _make_queue(monkeypatch, side_effect=RuntimeError("network timeout"))

        with pytest.raises(StorageError, match="Failed to bootstrap async ingestion queue"):
            queue.bootstrap()

    def test_bootstrap_preserves_causal_exception(self, monkeypatch):
        """StorageError raised by bootstrap() chains the original exception as cause."""
        original = RuntimeError("connection refused")
        queue = _make_queue(monkeypatch, side_effect=original)

        with pytest.raises(StorageError) as exc_info:
            queue.bootstrap()

        assert exc_info.value.__cause__ is original


class TestWarmupQueueBootstrap:
    """Verify FunctionAppDependencies.warmup() bootstraps all enabled queue adapters."""

    def _patch_dep(self, attr, value):
        return patch.object(FunctionAppDependencies, attr, new=PropertyMock(return_value=value))

    def test_warmup_calls_bootstrap_on_all_enabled_queues(self, monkeypatch):
        """warmup() bootstraps onedrive_async_queue, garmin_async_queue, and deferred_retry_queue."""
        from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue

        deps = FunctionAppDependencies()
        mock_onedrive = MagicMock(spec=AsyncIngestionQueue)
        mock_garmin = MagicMock(spec=AsyncIngestionQueue)
        mock_deferred = MagicMock(spec=DeferredRetryQueue)

        with self._patch_dep("storage", MagicMock()):
            with self._patch_dep("semantic_layer", MagicMock()):
                with self._patch_dep("onedrive_async_queue", mock_onedrive):
                    with self._patch_dep("garmin_async_queue", mock_garmin):
                        with self._patch_dep("deferred_retry_queue", mock_deferred):
                            deps.warmup()

        mock_onedrive.bootstrap.assert_called_once()
        mock_garmin.bootstrap.assert_called_once()
        mock_deferred.bootstrap.assert_called_once()

    def test_warmup_skips_bootstrap_for_disabled_async_queues(self, monkeypatch):
        """warmup() skips None queue adapters (disabled by config)."""
        from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue

        deps = FunctionAppDependencies()
        mock_deferred = MagicMock(spec=DeferredRetryQueue)

        with self._patch_dep("storage", MagicMock()):
            with self._patch_dep("semantic_layer", MagicMock()):
                with self._patch_dep("onedrive_async_queue", None):
                    with self._patch_dep("garmin_async_queue", None):
                        with self._patch_dep("deferred_retry_queue", mock_deferred):
                            deps.warmup()  # must not raise AttributeError on None.bootstrap()

        mock_deferred.bootstrap.assert_called_once()

    def test_warmup_continues_on_queue_bootstrap_failure(self, monkeypatch):
        """A StorageError from one queue's bootstrap() does not abort warmup() for others."""
        from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue

        deps = FunctionAppDependencies()
        mock_onedrive = MagicMock(spec=AsyncIngestionQueue)
        mock_onedrive.bootstrap.side_effect = StorageError("queue unavailable")
        mock_garmin = MagicMock(spec=AsyncIngestionQueue)
        mock_deferred = MagicMock(spec=DeferredRetryQueue)

        with self._patch_dep("storage", MagicMock()):
            with self._patch_dep("semantic_layer", MagicMock()):
                with self._patch_dep("onedrive_async_queue", mock_onedrive):
                    with self._patch_dep("garmin_async_queue", mock_garmin):
                        with self._patch_dep("deferred_retry_queue", mock_deferred):
                            deps.warmup()  # must not raise despite onedrive bootstrap failing

        mock_garmin.bootstrap.assert_called_once()
        mock_deferred.bootstrap.assert_called_once()
