"""Unit tests for deferred retry lifecycle service."""

from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.handlers.deferred_retry_lifecycle_service import (
    DeferredRetryLifecycleService,
)


class TestGetState:
    def test_returns_state_from_storage(self):
        storage = MagicMock()
        state = MagicMock()
        storage.get_state.return_value = state

        service = DeferredRetryLifecycleService(storage=storage)
        result = service.get_state(athlete_id="rob", operation_id="op-1")

        assert result is state
        storage.get_state.assert_called_once_with(athlete_id="rob", operation_id="op-1")

    def test_returns_none_when_absent(self):
        storage = MagicMock()
        storage.get_state.return_value = None

        service = DeferredRetryLifecycleService(storage=storage)
        result = service.get_state(athlete_id="rob", operation_id="op-1")

        assert result is None


class TestStartRetrying:
    def test_delegates_with_retrying_status_and_increments_attempts(self):
        storage = MagicMock()
        in_progress = MagicMock()
        storage.mark_status.return_value = in_progress

        service = DeferredRetryLifecycleService(storage=storage)
        result = service.start_retrying(
            athlete_id="rob", operation_id="op-1", etag="etag-1"
        )

        assert result is in_progress
        storage.mark_status.assert_called_once_with(
            athlete_id="rob",
            operation_id="op-1",
            status="retrying",
            etag="etag-1",
            increment_attempts=True,
        )


class TestCompleteSuccess:
    def test_delegates_with_succeeded_status(self):
        storage = MagicMock()
        final = MagicMock()
        storage.mark_status.return_value = final

        service = DeferredRetryLifecycleService(storage=storage)
        result = service.complete_success(
            athlete_id="rob", operation_id="op-1", etag="etag-retrying"
        )

        assert result is final
        storage.mark_status.assert_called_once_with(
            athlete_id="rob",
            operation_id="op-1",
            status="succeeded",
            etag="etag-retrying",
            increment_attempts=False,
        )


class TestCompleteFailure:
    def test_delegates_with_failed_status(self):
        storage = MagicMock()
        final = MagicMock()
        storage.mark_status.return_value = final

        service = DeferredRetryLifecycleService(storage=storage)
        result = service.complete_failure(
            athlete_id="rob", operation_id="op-1", etag="etag-retrying"
        )

        assert result is final
        storage.mark_status.assert_called_once_with(
            athlete_id="rob",
            operation_id="op-1",
            status="failed",
            etag="etag-retrying",
            increment_attempts=False,
        )


class TestDeferAgain:
    def test_delegates_with_deferred_status(self):
        storage = MagicMock()
        final = MagicMock()
        storage.mark_status.return_value = final

        service = DeferredRetryLifecycleService(storage=storage)
        result = service.defer_again(
            athlete_id="rob", operation_id="op-1", etag="etag-retrying"
        )

        assert result is final
        storage.mark_status.assert_called_once_with(
            athlete_id="rob",
            operation_id="op-1",
            status="deferred",
            etag="etag-retrying",
            increment_attempts=False,
        )
