"""Shared helpers for inferring FIT timezone offsets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

FIT_EPOCH_LOCAL = datetime(1989, 12, 31, 0, 0, 0)



def format_utc_offset(minutes: int) -> str:
    """Format minutes offset as 'UTC±HH:MM'."""
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    hours, mins = divmod(minutes, 60)
    return f"UTC{sign}{hours:02d}:{mins:02d}"


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_local_naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None)


def _is_fit_epoch_local_time(dt: datetime) -> bool:
    return _to_local_naive(dt) == FIT_EPOCH_LOCAL


def _normalize_offset_minutes(offset_minutes: float) -> Optional[int]:
    rounded_minutes = round(offset_minutes / 15) * 15
    if abs(offset_minutes - rounded_minutes) > 3:
        return None
    if rounded_minutes < -14 * 60 or rounded_minutes > 14 * 60:
        return None
    return int(rounded_minutes)


def infer_timezone_from_activity(
    local_time: Optional[datetime],
    timestamp: Optional[datetime],
) -> Optional[str]:
    """Infer timezone from activity local_time vs UTC timestamp."""
    if not isinstance(local_time, datetime):
        return None
    if not isinstance(timestamp, datetime):
        return None

    if _is_fit_epoch_local_time(local_time):
        return None

    local_dt = _to_local_naive(local_time)
    utc_dt = _to_utc_naive(timestamp)

    offset_minutes = (local_dt - utc_dt).total_seconds() / 60
    normalized = _normalize_offset_minutes(offset_minutes)
    if normalized is None:
        return None
    return format_utc_offset(normalized)


def infer_timezone_from_session(
    start_time_local: Optional[datetime],
    timestamp: Optional[datetime],
    duration_sec: Optional[int],
) -> Optional[str]:
    """Infer timezone from session timestamp vs local start time."""
    if not isinstance(start_time_local, datetime):
        return None
    if not isinstance(timestamp, datetime):
        return None
    if duration_sec is None:
        return None

    utc_start = timestamp - timedelta(seconds=duration_sec)
    start_dt = _to_local_naive(start_time_local)
    utc_start_dt = _to_utc_naive(utc_start)

    offset_minutes = (start_dt - utc_start_dt).total_seconds() / 60
    normalized = _normalize_offset_minutes(offset_minutes)
    if normalized is None:
        return None
    return format_utc_offset(normalized)


def resolve_timezone(
    tz_name: Optional[str],
    offset_minutes: Optional[int],
    inferred_activity: Optional[str],
    inferred_session: Optional[str],
) -> Optional[str]:
    """Resolve local timezone offset in priority order.

    Returns a UTC-offset string (for example, ``UTC-05:00``) when known,
    otherwise ``None`` when the offset cannot be reliably derived.
    """
    if tz_name:
        return tz_name
    if offset_minutes is not None:
        return format_utc_offset(offset_minutes)
    if inferred_activity:
        return inferred_activity
    if inferred_session:
        return inferred_session
    return None
