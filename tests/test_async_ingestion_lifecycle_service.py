"""Unit tests for async ingestion lifecycle service."""

from unittest.mock import MagicMock, call

import pytest

from TrainingAnalyticsPlatform.handlers.async_ingestion_lifecycle_service import (
    AsyncIngestionLifecycleService,
)


def _make_work_item(
    *,
    athlete_id: str = "rob",
    operation_id: str = "op-1",
    source: str = "onedrive",
    lookback_days: int = 14,
    queued_at_utc: str = "2026-03-19T00:00:00+00:00",
) -> MagicMock:
    item = MagicMock()
    item.athlete_id = athlete_id
    item.operation_id = operation_id
    item.source = source
    item.lookback_days = lookback_days
    item.queued_at_utc = queued_at_utc
    item.request_id = None
    item.correlation_id = None
    item.context = {}
    return item


class TestGetOrInitialize:
    def test_returns_existing_state_without_upsert(self):
        storage = MagicMock()
        existing = MagicMock()
        storage.get_state.return_value = existing

        service = AsyncIngestionLifecycleService(storage=storage)
        result = service.get_or_initialize(work_item=_make_work_item())

        assert result is existing
        storage.upsert_state.assert_not_called()

    def test_upserts_and_returns_new_state_when_absent(self):
        storage = MagicMock()
        created = MagicMock()
        storage.get_state.side_effect = [None, created]

        service = AsyncIngestionLifecycleService(storage=storage)
        result = service.get_or_initialize(work_item=_make_work_item())

        assert result is created
        storage.upsert_state.assert_called_once()
        assert storage.get_state.call_count == 2


class TestStartProcessing:
    def test_delegates_to_storage_with_processing_status(self):
        storage = MagicMock()
        in_progress = MagicMock()
        storage.mark_status.return_value = in_progress

        service = AsyncIngestionLifecycleService(storage=storage)
        result = service.start_processing(
            athlete_id="rob", operation_id="op-1", etag="etag-1"
        )

        assert result is in_progress
        storage.mark_status.assert_called_once_with(
            athlete_id="rob",
            operation_id="op-1",
            status="processing",
            etag="etag-1",
        )

    def test_passes_none_etag_for_unconditional_write(self):
        storage = MagicMock()
        service = AsyncIngestionLifecycleService(storage=storage)
        service.start_processing(athlete_id="rob", operation_id="op-1", etag=None)

        kwargs = storage.mark_status.call_args.kwargs
        assert kwargs["etag"] is None


class TestCompleteSuccess:
    def test_delegates_to_storage_with_succeeded_status(self):
        storage = MagicMock()
        final = MagicMock()
        storage.mark_status.return_value = final

        service = AsyncIngestionLifecycleService(storage=storage)
        result = service.complete_success(
            athlete_id="rob",
            operation_id="op-1",
            result={"found": 3, "ingested": 2},
        )

        assert result is final
        storage.mark_status.assert_called_once_with(
            athlete_id="rob",
            operation_id="op-1",
            status="succeeded",
            result={"found": 3, "ingested": 2},
        )


class TestCompleteFailure:
    def test_delegates_to_storage_with_failed_status(self):
        storage = MagicMock()
        final = MagicMock()
        storage.mark_status.return_value = final

        service = AsyncIngestionLifecycleService(storage=storage)
        result = service.complete_failure(
            athlete_id="rob",
            operation_id="op-1",
            error="sync exploded",
        )

        assert result is final
        storage.mark_status.assert_called_once_with(
            athlete_id="rob",
            operation_id="op-1",
            status="failed",
            error="sync exploded",
        )
