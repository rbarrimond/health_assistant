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
            ({"error": "Rate limited"}, 429),
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

        with patch("TrainingAnalyticsPlatform.handlers.weekly_rollup_presync_handler.time.sleep"):
            result = handler.run("rob", enabled=True)

        assert result["status"] == "success"
        assert onedrive.handle.call_count == 2

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
