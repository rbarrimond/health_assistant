"""Unit tests for async ingestion operation executor."""

import json
from unittest.mock import MagicMock

import pytest

from TrainingAnalyticsPlatform.handlers.async_ingestion_operation_executor import (
    AsyncIngestionOperationExecutor,
)
from TrainingAnalyticsPlatform.handlers.source_handler_registry import SourceHandlerRegistry
from TrainingAnalyticsPlatform.platform.exceptions import StorageError, ValidationError


class TestAsyncIngestionOperationExecutor:
    def test_process_message_succeeds_for_onedrive(self):
        lifecycle = MagicMock()
        existing_state = MagicMock()
        existing_state.etag = "etag-1"
        lifecycle.get_or_initialize.return_value = existing_state

        onedrive_handler = MagicMock()
        onedrive_handler.return_value = {
            "status": "success",
            "found": 3,
            "ingested": 2,
            "skipped": 1,
            "failed": 0,
        }
        registry = SourceHandlerRegistry(
            handlers={
                "onedrive": onedrive_handler,
            }
        )

        executor = AsyncIngestionOperationExecutor(
            lifecycle=lifecycle,
            source_registry=registry,
        )

        message = {
            "operation_id": "op-1",
            "source": "onedrive",
            "athlete_id": "rob",
            "lookback_days": 14,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
        }

        executor.process_message(json.dumps(message))

        onedrive_handler.assert_called_once_with("rob", 14, False)
        lifecycle.get_or_initialize.assert_called_once()
        lifecycle.start_processing.assert_called_once_with(
            athlete_id="rob", operation_id="op-1", etag="etag-1"
        )
        lifecycle.complete_success.assert_called_once()
        lifecycle.complete_failure.assert_not_called()

    def test_process_message_sends_force_for_garmin(self):
        lifecycle = MagicMock()
        existing_state = MagicMock()
        existing_state.etag = "etag-2"
        lifecycle.get_or_initialize.return_value = existing_state

        garmin_handler = MagicMock()
        garmin_handler.return_value = {
            "status": "success",
            "found": 10,
            "ingested": 4,
            "skipped": 6,
            "failed": 0,
        }
        registry = SourceHandlerRegistry(
            handlers={
                "garmin": garmin_handler,
            }
        )

        executor = AsyncIngestionOperationExecutor(
            lifecycle=lifecycle,
            source_registry=registry,
        )

        message = {
            "operation_id": "op-2",
            "source": "garmin",
            "athlete_id": "rob",
            "lookback_days": 30,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
            "context": {"force": True},
        }

        executor.process_message(json.dumps(message))

        garmin_handler.assert_called_once_with("rob", 30, True)

    def test_process_message_marks_failed_and_raises(self):
        lifecycle = MagicMock()
        existing_state = MagicMock()
        existing_state.etag = "etag-3"
        lifecycle.get_or_initialize.return_value = existing_state

        failing_handler = MagicMock()
        failing_handler.side_effect = RuntimeError("sync-failed")
        registry = SourceHandlerRegistry(
            handlers={
                "onedrive": failing_handler,
            }
        )

        executor = AsyncIngestionOperationExecutor(
            lifecycle=lifecycle,
            source_registry=registry,
        )

        message = {
            "operation_id": "op-3",
            "source": "onedrive",
            "athlete_id": "rob",
            "lookback_days": 14,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
        }

        with pytest.raises(RuntimeError, match="sync-failed"):
            executor.process_message(json.dumps(message))

        lifecycle.complete_failure.assert_called_once()
        kwargs = lifecycle.complete_failure.call_args.kwargs
        assert "sync-failed" in kwargs["error"]

    def test_process_message_marks_failed_without_retry_for_terminal_exception(self):
        lifecycle = MagicMock()
        existing_state = MagicMock()
        existing_state.etag = "etag-terminal"
        lifecycle.get_or_initialize.return_value = existing_state

        terminal_handler = MagicMock()
        terminal_handler.side_effect = ValidationError("invalid-payload")
        registry = SourceHandlerRegistry(
            handlers={
                "onedrive": terminal_handler,
            }
        )

        executor = AsyncIngestionOperationExecutor(
            lifecycle=lifecycle,
            source_registry=registry,
        )

        message = {
            "operation_id": "op-terminal-1",
            "source": "onedrive",
            "athlete_id": "rob",
            "lookback_days": 14,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
        }

        executor.process_message(json.dumps(message))

        lifecycle.complete_failure.assert_called_once()
        lifecycle.complete_success.assert_not_called()

    def test_process_message_keeps_retry_for_retryable_typed_exception(self):
        lifecycle = MagicMock()
        existing_state = MagicMock()
        existing_state.etag = "etag-retryable"
        lifecycle.get_or_initialize.return_value = existing_state

        retryable_handler = MagicMock()
        retryable_handler.side_effect = StorageError("table-timeout")
        registry = SourceHandlerRegistry(
            handlers={
                "onedrive": retryable_handler,
            }
        )

        executor = AsyncIngestionOperationExecutor(
            lifecycle=lifecycle,
            source_registry=registry,
        )

        message = {
            "operation_id": "op-retryable-1",
            "source": "onedrive",
            "athlete_id": "rob",
            "lookback_days": 14,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
        }

        with pytest.raises(StorageError, match="table-timeout"):
            executor.process_message(json.dumps(message))

        lifecycle.complete_failure.assert_called_once()

    def test_process_message_unknown_source_marks_processing_only(self):
        lifecycle = MagicMock()
        existing_state = MagicMock()
        existing_state.etag = "etag-4"
        lifecycle.get_or_initialize.return_value = existing_state

        executor = AsyncIngestionOperationExecutor(
            lifecycle=lifecycle,
            source_registry=SourceHandlerRegistry(handlers={}),
        )

        message = {
            "operation_id": "op-4",
            "source": "unknown-source",
            "athlete_id": "rob",
            "lookback_days": 7,
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
        }

        executor.process_message(json.dumps(message))

        lifecycle.start_processing.assert_called_once()
        lifecycle.complete_success.assert_not_called()
        lifecycle.complete_failure.assert_not_called()
