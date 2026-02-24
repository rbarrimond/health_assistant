"""Unit tests for timezone offset inference semantics."""

from datetime import datetime, timezone

from TrainingAnalyticsPlatform.ingestion.timezone_utils import (
    infer_timezone_from_activity,
    resolve_timezone,
)


def test_infer_timezone_from_activity_returns_explicit_zero_offset() -> None:
    """Ensure zero offset is represented as UTC+00:00, not UTC."""
    local_time = datetime(2026, 2, 24, 12, 0, 0)
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)

    assert infer_timezone_from_activity(local_time, timestamp) == "UTC+00:00"


def test_resolve_timezone_returns_none_when_unknown() -> None:
    """Unknown local timezone must remain unset (None)."""
    assert resolve_timezone(None, None, None, None) is None
