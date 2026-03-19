"""Tests for deferred retry coordinator and retry-after parsing."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.handlers.deferred_retry_coordinator import (
    DeferredRetryCoordinator,
    DeferredRetryPolicy,
)
from TrainingAnalyticsPlatform.models.retry import parse_retry_after_seconds


class TestRetryAfterParsing:
    def test_parse_retry_after_seconds_numeric(self):
        assert parse_retry_after_seconds("120") == 120

    def test_parse_retry_after_seconds_http_date(self):
        now_utc = datetime(2026, 3, 18, 0, 0, tzinfo=timezone.utc)
        retry_date = now_utc + timedelta(seconds=90)
        raw = retry_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
        assert parse_retry_after_seconds(raw, now_utc=now_utc) == 90


class TestDeferredRetryCoordinator:
    def test_no_defer_when_disabled(self):
        queue = MagicMock()
        storage = MagicMock()
        coordinator = DeferredRetryCoordinator(
            queue=queue,
            storage=storage,
            policy=DeferredRetryPolicy(
                enabled=False,
                request_budget_sec=220,
                safety_margin_sec=20,
                schema_version="1.0",
            ),
        )

        decision = coordinator.maybe_defer(
            athlete_id="rob",
            source="garmin_activities",
            lookback_days=45,
            retry_after_raw="86400",
            elapsed_sec=5,
        )

        assert decision.deferred is False
        queue.enqueue.assert_not_called()
        storage.upsert_state.assert_not_called()

    def test_defer_when_retry_after_exceeds_remaining_budget(self):
        queue = MagicMock()
        storage = MagicMock()
        coordinator = DeferredRetryCoordinator(
            queue=queue,
            storage=storage,
            policy=DeferredRetryPolicy(
                enabled=True,
                request_budget_sec=60,
                safety_margin_sec=10,
                schema_version="1.0",
            ),
        )

        decision = coordinator.maybe_defer(
            athlete_id="rob",
            source="garmin_activities",
            lookback_days=45,
            retry_after_raw="120",
            elapsed_sec=5,
        )

        assert decision.deferred is True
        assert decision.operation_id is not None
        assert decision.retry_after_seconds == 120
        queue.enqueue.assert_called_once()
        storage.upsert_state.assert_called_once()