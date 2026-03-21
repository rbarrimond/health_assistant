"""Tests for weekly rollup pre-sync orchestration."""

from unittest.mock import MagicMock, patch

from TrainingAnalyticsPlatform.handlers.weekly_rollup_presync_handler import (
    WeeklyRollupPreSyncHandler,
)


class TestWeeklyRollupPreSyncHandler:
    def test_run_disabled_returns_skipped(self):
        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=MagicMock(),
            garmin_service=MagicMock(),
            garmin_physiometrics_service=MagicMock(),
            intervals_service=MagicMock(),
            intervals_athlete_id="i508584",
        )

        result = handler.run("rob", enabled=False)

        assert result["status"] == "skipped"
        assert result["enabled"] is False
        assert result["sources"] == []

    def test_run_success_for_all_sources(self):
        onedrive = MagicMock()
        onedrive.handle.return_value = ({"message": "ok"}, 200)

        garmin = MagicMock()
        garmin.handle.return_value = ({"message": "ok"}, 200)

        garmin_physiometrics = MagicMock()
        garmin_physiometrics.handle.return_value = ({"message": "ok"}, 200)

        intervals = MagicMock()
        intervals.handle.return_value = ({"message": "ok"}, 200)

        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=onedrive,
            garmin_service=garmin,
            garmin_physiometrics_service=garmin_physiometrics,
            intervals_service=intervals,
            intervals_athlete_id="i508584",
            lookback_days=8,
        )

        result = handler.run("rob", enabled=True)

        assert result["status"] == "success"
        assert len(result["sources"]) == 4
        assert intervals.handle.call_args.kwargs["lookback_days"] == 8

    def test_fail_fast_stops_after_first_failure(self):
        onedrive = MagicMock()
        onedrive.handle.return_value = ({"message": "ok"}, 200)

        garmin = MagicMock()
        garmin.handle.return_value = ({"error": "Rate limited"}, 429)

        garmin_physiometrics = MagicMock()
        garmin_physiometrics.handle.return_value = ({"message": "ok"}, 200)

        intervals = MagicMock()
        intervals.handle.return_value = ({"message": "ok"}, 200)

        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=onedrive,
            garmin_service=garmin,
            garmin_physiometrics_service=garmin_physiometrics,
            intervals_service=intervals,
            intervals_athlete_id="i508584",
            retry_max_attempts=1,
        )

        result = handler.run("rob", enabled=True)

        assert result["status"] == "failed"
        assert len(result["sources"]) == 2
        garmin_physiometrics.handle.assert_not_called()
        intervals.handle.assert_not_called()

    def test_retryable_status_retries_then_succeeds(self):
        onedrive = MagicMock()
        onedrive.handle.side_effect = [
            ({"error": "Rate limited"}, 429, {"Retry-After": "60"}),
            ({"message": "ok"}, 200),
        ]

        garmin = MagicMock()
        garmin.handle.return_value = ({"message": "ok"}, 200)

        garmin_physiometrics = MagicMock()
        garmin_physiometrics.handle.return_value = ({"message": "ok"}, 200)

        intervals = MagicMock()
        intervals.handle.return_value = ({"message": "ok"}, 200)

        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=onedrive,
            garmin_service=garmin,
            garmin_physiometrics_service=garmin_physiometrics,
            intervals_service=intervals,
            intervals_athlete_id="i508584",
            retry_max_attempts=2,
            retry_base_delay_sec=0.01,
        )

        with patch("TrainingAnalyticsPlatform.handlers.presync_core.time.sleep"):
            result = handler.run("rob", enabled=True)

        assert result["status"] == "success"
        assert onedrive.handle.call_count == 2

    def test_failed_rate_limit_includes_retry_after(self):
        onedrive = MagicMock()
        onedrive.handle.return_value = (
            {"error": "Rate limited"},
            429,
            {"Retry-After": "120"},
        )

        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=onedrive,
            garmin_service=MagicMock(),
            garmin_physiometrics_service=MagicMock(),
            intervals_service=MagicMock(),
            intervals_athlete_id="i508584",
            retry_max_attempts=1,
        )

        result = handler.run("rob", enabled=True)

        assert result["status"] == "failed"
        assert result["sources"][0]["http_status"] == 429
        assert result["sources"][0]["retry_after"] == "120"

    def test_missing_intervals_identity_fails(self):
        onedrive = MagicMock()
        onedrive.handle.return_value = ({"message": "ok"}, 200)

        garmin = MagicMock()
        garmin.handle.return_value = ({"message": "ok"}, 200)

        garmin_physiometrics = MagicMock()
        garmin_physiometrics.handle.return_value = ({"message": "ok"}, 200)

        intervals = MagicMock()

        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=onedrive,
            garmin_service=garmin,
            garmin_physiometrics_service=garmin_physiometrics,
            intervals_service=intervals,
            intervals_athlete_id=None,
            retry_max_attempts=1,
        )

        result = handler.run("rob", enabled=True)

        assert result["status"] == "failed"
        assert result["sources"][-1]["source"] == "intervals_physiometrics"

    def test_long_retry_after_defers_without_extra_inline_retries(self):
        onedrive = MagicMock()
        onedrive.handle.return_value = (
            {"error": "Rate limited"},
            429,
            {"Retry-After": "86400"},
        )

        coordinator = MagicMock()
        coordinator.maybe_defer.return_value = MagicMock(
            deferred=True,
            operation_id="op-123",
            safe_to_retry_at_utc="2026-03-19T00:00:00+00:00",
            retry_after_raw="86400",
        )

        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=onedrive,
            garmin_service=MagicMock(),
            garmin_physiometrics_service=MagicMock(),
            intervals_service=MagicMock(),
            intervals_athlete_id="i508584",
            retry_max_attempts=3,
            deferred_retry_coordinator=coordinator,
        )

        with patch("TrainingAnalyticsPlatform.handlers.presync_core.time.sleep"):
            result = handler.run("rob", enabled=True)

        assert result["status"] == "failed"
        assert onedrive.handle.call_count == 1
        assert result["sources"][0]["deferred"] is True
        assert result["sources"][0]["deferred_operation_id"] == "op-123"

    def test_sleep_with_backoff_uses_equal_jitter(self):
        handler = WeeklyRollupPreSyncHandler(
            onedrive_service=MagicMock(),
            garmin_service=MagicMock(),
            garmin_physiometrics_service=MagicMock(),
            intervals_service=MagicMock(),
            intervals_athlete_id="i508584",
            retry_max_attempts=2,
            retry_base_delay_sec=2.0,
        )

        with patch(
            "TrainingAnalyticsPlatform.handlers.presync_core.random.random",
            return_value=0.5,
        ), patch("TrainingAnalyticsPlatform.handlers.presync_core.time.sleep") as sleep_mock:
            handler._sleep_with_backoff(
                source="garmin_activities",
                attempt=3,
                logger=MagicMock(),
                retry_log_message="retry",
            )

        sleep_mock.assert_called_once_with(6.0)
