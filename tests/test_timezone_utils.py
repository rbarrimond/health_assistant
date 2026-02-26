"""Unit tests for timezone offset inference semantics."""

from datetime import datetime, timezone

from TrainingAnalyticsPlatform.ingestion.timezone_utils import (
    infer_timezone_from_activity,
    infer_timezone_from_session,
    resolve_timezone,
)


def test_infer_timezone_from_activity_returns_explicit_zero_offset() -> None:
    """Ensure zero offset is represented as UTC+00:00, not UTC."""
    local_time = datetime(2026, 2, 24, 12, 0, 0)
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)

    assert infer_timezone_from_activity(local_time, timestamp) == "UTC+00:00"


def test_infer_timezone_from_activity_ignores_fit_epoch() -> None:
    """FIT epoch local timestamps must not be used for timezone inference."""
    local_time = datetime(1989, 12, 31, 0, 0, 0)
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)

    assert infer_timezone_from_activity(local_time, timestamp) is None


def test_resolve_timezone_returns_none_when_unknown() -> None:
    """Unknown local timezone must remain unset (None)."""
    assert resolve_timezone(None, None, None, None) is None


def test_infer_timezone_from_session_uses_local_vs_utc_start_math() -> None:
    """Session offset should derive from local start vs UTC (timestamp-elapsed)."""
    start_time_local = datetime(2026, 2, 24, 10, 0, 0)
    timestamp_utc = datetime(2026, 2, 24, 15, 0, 0, tzinfo=timezone.utc)
    duration_sec = 3600

    assert (
        infer_timezone_from_session(start_time_local, timestamp_utc, duration_sec)
        == "UTC-04:00"
    )
