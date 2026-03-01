"""Shared helpers for inferring FIT timezone offsets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

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


def _check_preferred_zone(
    prefer_zone: Optional[str],
    target_offset: timedelta,
    timestamp: datetime,
) -> Optional[str]:
    """Check if preferred zone matches the target offset at given timestamp.

    Args:
        prefer_zone: Preferred IANA timezone name
        target_offset: Target UTC offset as timedelta
        timestamp: Reference timestamp

    Returns:
        Preferred zone name if it matches, else None.
    """
    if not prefer_zone:
        return None

    try:
        tz = ZoneInfo(prefer_zone)
        dt_in_tz = timestamp.astimezone(tz)
        if dt_in_tz.utcoffset() == target_offset:
            return prefer_zone
    except ZoneInfoNotFoundError:
        pass

    return None


def _find_matching_zones(
    target_offset: timedelta,
    timestamp: datetime,
) -> list[str]:
    """Find all IANA zones matching target offset at given timestamp.

    Args:
        target_offset: Target UTC offset as timedelta
        timestamp: Reference timestamp

    Returns:
        List of matching IANA timezone names.
    """
    matching_zones = []
    for tz_name in available_timezones():
        try:
            tz = ZoneInfo(tz_name)
            dt_in_tz = timestamp.astimezone(tz)
            if dt_in_tz.utcoffset() == target_offset:
                matching_zones.append(tz_name)
        except (ZoneInfoNotFoundError, OSError):
            continue

    return matching_zones


def _select_canonical_zone(matching_zones: list[str]) -> Optional[str]:
    """Select best canonical zone from matches.

    Prefers zones with format like "America/New_York" over "US/Eastern".
    Returns first canonical zone alphabetically for consistency.

    Args:
        matching_zones: List of matching IANA timezone names

    Returns:
        Selected timezone name or None.
    """
    if not matching_zones:
        return None
    if len(matching_zones) == 1:
        return matching_zones[0]

    # Prefer canonical zones (e.g., America/New_York over US/Eastern, Etc/GMT+5)
    canonical_zones = [
        z for z in matching_zones if "/" in z and not z.startswith("Etc/")
    ]
    if canonical_zones:
        return sorted(canonical_zones)[0]

    # No canonical zones found, return first match alphabetically
    return sorted(matching_zones)[0]


def iana_from_offset(
    offset_str: str,
    timestamp: datetime,
    prefer_zone: Optional[str] = None,
) -> Optional[str]:
    """Convert UTC offset string to IANA timezone name.

    Args:
        offset_str: UTC offset string like 'UTC-05:00' or 'UTC+01:00'
        timestamp: Reference timestamp for checking offset (handles DST)
        prefer_zone: Optional preferred IANA zone for disambiguation

    Returns:
        IANA timezone name if unambiguous or matches preferred zone,
        otherwise None.

    Examples:
        >>> dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        >>> iana_from_offset('UTC+09:00', dt)
        'Asia/Tokyo'
        >>> iana_from_offset('UTC-05:00', dt, prefer_zone='America/New_York')
        'America/New_York'
    """
    # Parse offset string to minutes
    offset_minutes = _parse_utc_offset_string(offset_str)
    if offset_minutes is None:
        return None

    # Build target offset for comparison
    target_offset = timedelta(minutes=offset_minutes)

    # Check preferred zone first if provided
    preferred_match = _check_preferred_zone(prefer_zone, target_offset, timestamp)
    if preferred_match:
        return preferred_match

    # Find all zones matching the offset at the given timestamp
    matching_zones = _find_matching_zones(target_offset, timestamp)

    # Select best canonical zone from matches
    return _select_canonical_zone(matching_zones)


def _parse_utc_offset_string(offset_str: str) -> Optional[int]:
    """Parse UTC offset string to minutes.

    Args:
        offset_str: String like 'UTC-05:00', 'UTC+01:00', or 'UTC'

    Returns:
        Offset in minutes, or None if invalid.
    """
    if not offset_str:
        return None

    normalized = offset_str.strip().upper()
    if normalized == "UTC":
        return 0

    if not normalized.startswith("UTC"):
        return None

    offset = normalized[3:]
    if len(offset) < 3:
        return None

    sign = 1
    if offset[0] == "+":
        sign = 1
        offset = offset[1:]
    elif offset[0] == "-":
        sign = -1
        offset = offset[1:]

    if ":" in offset:
        parts = offset.split(":", 1)
        hours_str, minutes_str = parts[0], parts[1]
    else:
        hours_str, minutes_str = offset, "0"

    try:
        hours = int(hours_str)
        minutes = int(minutes_str)
    except ValueError:
        return None

    return sign * (hours * 60 + minutes)


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
