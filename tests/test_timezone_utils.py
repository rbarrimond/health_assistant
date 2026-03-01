"""Unit tests for timezone offset inference semantics."""

from datetime import datetime, timezone

from TrainingAnalyticsPlatform.ingestion.timezone_utils import (
    iana_from_offset,
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


def test_iana_from_offset_unambiguous_offset() -> None:
    """Unambiguous offsets should return canonical IANA timezone."""
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    
    # UTC+09:00 should return a valid Asia/... zone
    result = iana_from_offset("UTC+09:00", timestamp)
    assert result is not None
    assert "Asia/" in result or result == "Pacific/Palau"
    
    # UTC+05:45 should return Asia/Kathmandu (only zone with this offset)
    result = iana_from_offset("UTC+05:45", timestamp)
    assert result == "Asia/Kathmandu"


def test_iana_from_offset_ambiguous_with_preference() -> None:
    """Ambiguous offsets should prefer athlete timezone when it matches."""
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    
    # UTC-05:00 is ambiguous (New York, Toronto, Detroit, Bogotá, etc.)
    # With preference for America/New_York, it should return that
    assert iana_from_offset("UTC-05:00", timestamp, prefer_zone="America/New_York") == "America/New_York"
    
    # With preference for America/Toronto, it should return that
    assert iana_from_offset("UTC-05:00", timestamp, prefer_zone="America/Toronto") == "America/Toronto"


def test_iana_from_offset_ambiguous_no_preference() -> None:
    """Ambiguous offsets without preference should return a canonical zone."""
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    
    # UTC-05:00 is ambiguous, should return one of the valid zones
    result = iana_from_offset("UTC-05:00", timestamp)
    assert result is not None
    # Should be one of the EST zones (exact choice doesn't matter as long as it's consistent)
    assert "America/" in result or result == "EST"


def test_iana_from_offset_preference_no_match() -> None:
    """When preferred zone doesn't match offset, return canonical zone."""
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    
    # UTC-05:00 with preference for Pacific time (which is UTC-08:00) should ignore preference
    result = iana_from_offset("UTC-05:00", timestamp, prefer_zone="America/Los_Angeles")
    assert result is not None
    assert result != "America/Los_Angeles"


def test_iana_from_offset_dst_awareness() -> None:
    """DST transitions should be handled correctly."""
    # Summer timestamp when EST is UTC-04:00 (EDT)
    summer = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert iana_from_offset("UTC-04:00", summer, prefer_zone="America/New_York") == "America/New_York"
    
    # Winter timestamp when EST is UTC-05:00
    winter = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert iana_from_offset("UTC-05:00", winter, prefer_zone="America/New_York") == "America/New_York"


def test_iana_from_offset_invalid_offset_string() -> None:
    """Invalid offset strings should return None gracefully."""
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    
    assert iana_from_offset("invalid", timestamp) is None
    assert iana_from_offset("UTC+99:00", timestamp) is None
    assert iana_from_offset("", timestamp) is None


def test_iana_from_offset_utc_zero() -> None:
    """UTC+00:00 should return UTC or a valid UTC+00:00 timezone."""
    timestamp = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    result = iana_from_offset("UTC+00:00", timestamp)
    assert result is not None
    # Could be UTC, GMT, or any Africa/... zone at UTC+00:00
    # Just verify it's a valid result
    assert isinstance(result, str) and len(result) > 0
