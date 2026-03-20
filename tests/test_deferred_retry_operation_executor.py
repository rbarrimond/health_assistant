"""Unit tests for deferred retry operation executor."""

from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.handlers.deferred_retry_operation_executor import (
    DeferredRetryOperationExecutor,
)
from TrainingAnalyticsPlatform.handlers.source_handler_registry import SourceHandlerRegistry


def _make_work_item(source: str = "garmin_activities") -> MagicMock:
    item = MagicMock()
    item.athlete_id = "rob"
    item.operation_id = "op-1"
    item.source = source
    item.lookback_days = 45
    return item


class TestDeferredRetryOperationExecutor:
    def test_process_message_ignores_missing_state(self):
        queue = MagicMock()
        queue.decode_message.return_value = _make_work_item()
        lifecycle = MagicMock()
        lifecycle.get_state.return_value = None

        executor = DeferredRetryOperationExecutor(
            queue=queue,
            lifecycle=lifecycle,
            coordinator=MagicMock(),
            source_registry=SourceHandlerRegistry(handlers={}),
        )

        executor.process_message("{}")

        lifecycle.start_retrying.assert_not_called()

    def test_process_message_marks_succeeded_on_200(self):
        queue = MagicMock()
        queue.decode_message.return_value = _make_work_item("garmin_activities")

        state = MagicMock()
        state.etag = "etag-initial"
        in_progress = MagicMock()
        in_progress.etag = "etag-retrying"

        lifecycle = MagicMock()
        lifecycle.get_state.return_value = state
        lifecycle.start_retrying.return_value = in_progress

        garmin_handler = MagicMock()
        garmin_handler.return_value = ({"status": "ok"}, 200)

        executor = DeferredRetryOperationExecutor(
            queue=queue,
            lifecycle=lifecycle,
            coordinator=MagicMock(),
            source_registry=SourceHandlerRegistry(
                handlers={
                    "garmin_activities": garmin_handler,
                }
            ),
        )

        executor.process_message("{}")

        lifecycle.start_retrying.assert_called_once_with(
            athlete_id="rob", operation_id="op-1", etag="etag-initial"
        )
        lifecycle.complete_success.assert_called_once_with(
            athlete_id="rob", operation_id="op-1", etag="etag-retrying"
        )

    def test_process_message_marks_deferred_when_coordinator_defers(self):
        queue = MagicMock()
        queue.decode_message.return_value = _make_work_item("garmin_activities")

        state = MagicMock()
        state.etag = "etag-initial"
        in_progress = MagicMock()
        in_progress.etag = "etag-retrying"

        lifecycle = MagicMock()
        lifecycle.get_state.return_value = state
        lifecycle.start_retrying.return_value = in_progress

        decision = MagicMock()
        decision.deferred = True
        decision.safe_to_retry_at_utc = "2026-03-19T00:00:00+00:00"
        coordinator = MagicMock()
        coordinator.maybe_defer.return_value = decision

        garmin_handler = MagicMock()
        garmin_handler.return_value = (
            {"error": "rate-limited", "retry_after": "3600"},
            429,
            {"Retry-After": "3600"},
        )

        executor = DeferredRetryOperationExecutor(
            queue=queue,
            lifecycle=lifecycle,
            coordinator=coordinator,
            source_registry=SourceHandlerRegistry(
                handlers={
                    "garmin_activities": garmin_handler,
                }
            ),
        )

        executor.process_message("{}")

        lifecycle.defer_again.assert_called_once_with(
            athlete_id="rob", operation_id="op-1", etag="etag-retrying"
        )
        lifecycle.complete_failure.assert_not_called()

    def test_process_message_unknown_source_marks_failed_without_deferral(self):
        queue = MagicMock()
        queue.decode_message.return_value = _make_work_item("unknown")

        state = MagicMock()
        state.etag = "etag-initial"
        in_progress = MagicMock()
        in_progress.etag = "etag-retrying"

        lifecycle = MagicMock()
        lifecycle.get_state.return_value = state
        lifecycle.start_retrying.return_value = in_progress

        decision = MagicMock()
        decision.deferred = False
        decision.safe_to_retry_at_utc = None
        coordinator = MagicMock()
        coordinator.maybe_defer.return_value = decision

        executor = DeferredRetryOperationExecutor(
            queue=queue,
            lifecycle=lifecycle,
            coordinator=coordinator,
            source_registry=SourceHandlerRegistry(handlers={}),
        )

        executor.process_message("{}")

        lifecycle.complete_failure.assert_called_once_with(
            athlete_id="rob", operation_id="op-1", etag="etag-retrying"
        )
        lifecycle.defer_again.assert_not_called()
