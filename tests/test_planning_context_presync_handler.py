"""Unit tests for PlanningContextPreSyncHandler."""

# pylint: disable=missing-function-docstring,missing-class-docstring,protected-access

import time
from unittest.mock import MagicMock

import pytest

from TrainingAnalyticsPlatform.handlers.planning_context_presync_handler import (
    PlanningContextPreSyncHandler,
)
from TrainingAnalyticsPlatform.platform.logging_setup import current_correlation_id


def _make_handler(**overrides) -> PlanningContextPreSyncHandler:
    defaults = {
        "onedrive_service": MagicMock(),
        "garmin_service": MagicMock(),
        "garmin_physiometrics_service": MagicMock(),
        "withings_service": MagicMock(),
        "intervals_service": MagicMock(),
        "intervals_athlete_id": "athlete123",
        "planning_presync_garmin_activities_enabled": True,
        "planning_presync_garmin_physiometrics_enabled": True,
        "planning_presync_freshness_ttl_sec": 3600,
        "retry_max_attempts": 1,
        "retry_base_delay_sec": 0.01,
    }
    defaults.update(overrides)
    return PlanningContextPreSyncHandler(**defaults)


class TestPlanningContextPreSyncHandlerAllSucceeded:
    def test_all_sources_succeed_returns_all_succeeded(self):
        handler = _make_handler()

        success_response = ({"status": "ok", "message": "synced"}, 200)
        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = success_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        result = handler.run(athlete_id="rob", days=30)

        assert result["status"] == "all_succeeded"
        assert result["lookback_days"] == 30
        assert len(result["sources"]) == 5
        assert all(s["status"] == "success" for s in result["sources"])

    def test_garmin_source_result_includes_cache_execution_metadata(self):
        handler = _make_handler()

        onedrive_response = ({"status": "ok", "message": "synced"}, 200)
        garmin_response = (
            {
                "status": "success",
                "message": "synced",
                "list_window_days_used": 3,
                "list_calls_made": 1,
                "cache_hit_count": 22,
                "cache_miss_days": 0,
            },
            200,
        )
        handler._onedrive_service.handle.return_value = onedrive_response
        handler._garmin_service.handle.return_value = garmin_response
        handler._garmin_physiometrics_service.handle.return_value = onedrive_response
        handler._withings_service.sync_metrics.return_value = onedrive_response
        handler._intervals_service.handle.return_value = onedrive_response

        result = handler.run(athlete_id="rob", days=30)

        garmin_result = next(
            source for source in result["sources"] if source["source"] == "garmin_activities"
        )
        assert garmin_result["list_window_days_used"] == 3
        assert garmin_result["list_calls_made"] == 1
        assert garmin_result["cache_hit_count"] == 22
        assert garmin_result["cache_miss_days"] == 0

    def test_parallel_execution_preserves_source_order(self):
        handler = _make_handler()

        def delayed_response(source: str, delay_sec: float):
            time.sleep(delay_sec)
            return {"status": "ok", "message": source}, 200

        handler._onedrive_service.handle.side_effect = lambda _: delayed_response("onedrive", 0.02)
        handler._garmin_service.handle.side_effect = lambda _: delayed_response("garmin", 0.04)
        handler._garmin_physiometrics_service.handle.side_effect = (
            lambda *_: delayed_response("garmin_physiometrics", 0.01)
        )
        handler._withings_service.sync_metrics.side_effect = (
            lambda *_: delayed_response("withings", 0.03)
        )
        handler._intervals_service.handle.side_effect = lambda **_: delayed_response("intervals", 0.005)

        result = handler.run(athlete_id="rob", days=30)

        assert [source["source"] for source in result["sources"]] == [
            "onedrive_workouts",
            "garmin_activities",
            "garmin_physiometrics",
            "withings_physiometrics",
            "intervals_physiometrics",
        ]

    def test_parallel_workers_preserve_correlation_context(self):
        handler = _make_handler()
        expected_correlation_id = "corr-planning-123"
        observed = []

        def capture_and_succeed(*_args, **_kwargs):
            observed.append(current_correlation_id.get())
            return {"status": "ok", "message": "synced"}, 200

        handler._onedrive_service.handle.side_effect = capture_and_succeed
        handler._garmin_service.handle.side_effect = capture_and_succeed
        handler._garmin_physiometrics_service.handle.side_effect = capture_and_succeed
        handler._withings_service.sync_metrics.side_effect = capture_and_succeed
        handler._intervals_service.handle.side_effect = capture_and_succeed

        token = current_correlation_id.set(expected_correlation_id)
        try:
            result = handler.run(athlete_id="rob", days=30)
        finally:
            current_correlation_id.reset(token)

        assert result["status"] == "all_succeeded"
        assert observed == [expected_correlation_id] * 5


class TestPlanningContextPreSyncHandlerPartialSuccess:
    def test_one_source_fails_continues_others(self):
        handler = _make_handler()

        success_response = ({"status": "ok", "message": "synced"}, 200)
        fail_response = ({"error": "rate limited"}, 429)

        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = fail_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        result = handler.run(athlete_id="rob", days=45)

        assert result["status"] == "partial"
        assert len(result["sources"]) == 5
        failed = [s for s in result["sources"] if s["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["source"] == "garmin_activities"

    def test_withings_not_connected_continues_others(self):
        handler = _make_handler()

        success_response = ({"status": "ok", "message": "synced"}, 200)
        withings_not_connected = (
            {"error": "Withings account is not connected for this athlete"},
            404,
        )

        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = success_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = withings_not_connected
        handler._intervals_service.handle.return_value = success_response

        result = handler.run(athlete_id="rob", days=45)

        assert result["status"] == "partial"
        failed = next(
            source for source in result["sources"] if source["source"] == "withings_physiometrics"
        )
        assert failed["status"] == "failed"
        assert failed["http_status"] == 404

    def test_rate_limited_source_includes_retry_after(self):
        handler = _make_handler()

        success_response = ({"status": "ok", "message": "synced"}, 200)
        fail_response = (
            {"error": "rate limited"},
            429,
            {"Retry-After": "30"},
        )

        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = fail_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        result = handler.run(athlete_id="rob", days=45)

        failed = next(s for s in result["sources"] if s["source"] == "garmin_activities")
        assert failed["retry_after"] == "30"

    def test_long_retry_after_marks_source_deferred(self):
        coordinator = MagicMock()
        coordinator.maybe_defer.return_value = MagicMock(
            deferred=True,
            operation_id="op-456",
            safe_to_retry_at_utc="2026-03-19T00:00:00+00:00",
            retry_after_raw="86400",
        )
        handler = _make_handler(deferred_retry_coordinator=coordinator)

        success_response = ({"status": "ok", "message": "synced"}, 200)
        fail_response = (
            {"error": "rate limited"},
            429,
            {"Retry-After": "86400"},
        )

        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = fail_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        result = handler.run(athlete_id="rob", days=45)

        failed = next(s for s in result["sources"] if s["source"] == "garmin_activities")
        assert result["status"] == "partial"
        assert failed["deferred"] is True
        assert failed["deferred_operation_id"] == "op-456"

    def test_garmin_physiometrics_rate_limit_can_be_deferred(self):
        coordinator = MagicMock()
        coordinator.maybe_defer.return_value = MagicMock(
            deferred=True,
            operation_id="op-garmin-physio",
            safe_to_retry_at_utc="2026-03-19T00:00:00+00:00",
            retry_after_raw="1800",
        )
        handler = _make_handler(deferred_retry_coordinator=coordinator)

        success_response = ({"status": "ok", "message": "synced"}, 200)
        garmin_physio_fail_response = (
            {"error": "rate limited", "error_code": "GARMIN_RATE_LIMITED"},
            429,
            {"Retry-After": "1800"},
        )

        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = success_response
        handler._garmin_physiometrics_service.handle.return_value = garmin_physio_fail_response
        handler._withings_service.sync_metrics.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        result = handler.run(athlete_id="rob", days=45)

        failed = next(
            s for s in result["sources"] if s["source"] == "garmin_physiometrics"
        )
        assert result["status"] == "partial"
        assert failed["http_status"] == 429
        assert failed["retry_after"] == "1800"
        assert failed["deferred"] is True
        assert failed["deferred_operation_id"] == "op-garmin-physio"


class TestPlanningContextPreSyncHandlerFreshness:
    def test_repeated_call_skips_fresh_sources_when_not_forced(self):
        handler = _make_handler(planning_presync_freshness_ttl_sec=3600)

        success_response = ({"status": "ok", "message": "synced"}, 200)
        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = success_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        first = handler.run(athlete_id="rob", days=30)
        second = handler.run(athlete_id="rob", days=30)

        assert first["status"] == "all_succeeded"
        assert second["status"] == "all_succeeded"
        assert all(source["status"] == "skipped" for source in second["sources"])
        assert {
            source.get("reason") for source in second["sources"]
        } == {"fresh_within_ttl"}

        handler._onedrive_service.handle.assert_called_once()
        handler._garmin_service.handle.assert_called_once()
        handler._garmin_physiometrics_service.handle.assert_called_once()
        handler._withings_service.sync_metrics.assert_called_once()
        handler._intervals_service.handle.assert_called_once()

    def test_force_true_bypasses_freshness_skip(self):
        handler = _make_handler(planning_presync_freshness_ttl_sec=3600)

        success_response = ({"status": "ok", "message": "synced"}, 200)
        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = success_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        handler.run(athlete_id="rob", days=30)
        forced = handler.run(athlete_id="rob", days=30, force=True)

        assert forced["status"] == "all_succeeded"
        assert all(source["status"] == "success" for source in forced["sources"])

        assert handler._onedrive_service.handle.call_count == 2
        assert handler._garmin_service.handle.call_count == 2
        assert handler._garmin_physiometrics_service.handle.call_count == 2
        assert handler._withings_service.sync_metrics.call_count == 2
        assert handler._intervals_service.handle.call_count == 2


class TestPlanningContextPreSyncHandlerAllFailed:
    def test_all_sources_fail_returns_failed(self):
        handler = _make_handler()

        fail_response = ({"error": "connection error"}, 500)
        handler._onedrive_service.handle.return_value = fail_response
        handler._garmin_service.handle.return_value = fail_response
        handler._garmin_physiometrics_service.handle.return_value = fail_response
        handler._withings_service.sync_metrics.return_value = fail_response
        handler._intervals_service.handle.return_value = fail_response

        result = handler.run(athlete_id="rob", days=14)

        assert result["status"] == "failed"
        assert all(s["status"] == "failed" for s in result["sources"])


class TestPlanningContextPreSyncHandlerGarminSourcesDisabled:
    def test_disabled_garmin_sources_are_not_executed(self):
        handler = _make_handler(
            planning_presync_garmin_activities_enabled=False,
            planning_presync_garmin_physiometrics_enabled=False,
        )

        success_response = ({"status": "ok", "message": "synced"}, 200)
        handler._onedrive_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = success_response
        handler._intervals_service.handle.return_value = success_response

        result = handler.run(athlete_id="rob", days=21)

        assert result["status"] == "all_succeeded"
        assert len(result["sources"]) == 3
        assert {source["source"] for source in result["sources"]} == {
            "onedrive_workouts",
            "withings_physiometrics",
            "intervals_physiometrics",
        }
        handler._garmin_service.handle.assert_not_called()
        handler._garmin_physiometrics_service.handle.assert_not_called()


class TestPlanningContextPreSyncHandlerIntervalsMissing:
    def test_missing_intervals_athlete_id_produces_failed_source_not_exception(self):
        handler = _make_handler(intervals_athlete_id=None)

        success_response = ({"status": "ok", "message": "synced"}, 200)
        handler._onedrive_service.handle.return_value = success_response
        handler._garmin_service.handle.return_value = success_response
        handler._garmin_physiometrics_service.handle.return_value = success_response
        handler._withings_service.sync_metrics.return_value = success_response

        result = handler.run(athlete_id="rob", days=30)

        # Should be partial — 3 succeeded, 1 failed (intervals)
        assert result["status"] == "partial"
        intervals_result = next(
            s for s in result["sources"] if s["source"] == "intervals_physiometrics"
        )
        assert intervals_result["status"] == "failed"
        assert intervals_result["http_status"] == 424


class TestPlanningContextPreSyncHandlerFromEnv:
    def test_from_env_reads_retry_settings(self, monkeypatch):
        monkeypatch.setenv("PLANNING_PRESYNC_RETRY_MAX_ATTEMPTS", "5")
        monkeypatch.setenv("PLANNING_PRESYNC_RETRY_BASE_DELAY_SEC", "2.0")
        monkeypatch.setenv("PLANNING_PRESYNC_FRESHNESS_TTL_SEC", "900")
        monkeypatch.setenv("PLANNING_PRESYNC_GARMIN_ACTIVITIES_ENABLED", "true")
        monkeypatch.setenv("PLANNING_PRESYNC_GARMIN_PHYSIOMETRICS_ENABLED", "yes")
        monkeypatch.setenv("INTERVALS_ATHLETE_ID", "envathlete")

        handler = PlanningContextPreSyncHandler.from_env(
            onedrive_service=MagicMock(),
            garmin_service=MagicMock(),
            garmin_physiometrics_service=MagicMock(),
            withings_service=MagicMock(),
            intervals_service=MagicMock(),
        )

        assert handler._retry_max_attempts == 5
        assert handler._retry_base_delay_sec == pytest.approx(2.0)
        assert handler._planning_presync_freshness_ttl_sec == 900
        assert handler._intervals_athlete_id == "envathlete"
        assert handler._planning_presync_garmin_activities_enabled is True
        assert handler._planning_presync_garmin_physiometrics_enabled is True

    def test_from_env_defaults_garmin_sources_to_disabled(self, monkeypatch):
        monkeypatch.delenv("PLANNING_PRESYNC_GARMIN_ACTIVITIES_ENABLED", raising=False)
        monkeypatch.delenv("PLANNING_PRESYNC_GARMIN_PHYSIOMETRICS_ENABLED", raising=False)

        handler = PlanningContextPreSyncHandler.from_env(
            onedrive_service=MagicMock(),
            garmin_service=MagicMock(),
            garmin_physiometrics_service=MagicMock(),
            withings_service=MagicMock(),
            intervals_service=MagicMock(),
        )

        assert handler._planning_presync_garmin_activities_enabled is False
        assert handler._planning_presync_garmin_physiometrics_enabled is False
