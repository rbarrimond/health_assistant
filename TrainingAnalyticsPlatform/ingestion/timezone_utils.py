"""Shared helpers for inferring FIT timezone offsets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

FIT_EPOCH_LOCAL = datetime(1989, 12, 31, 0, 0, 0)

ZWIFT_MANUFACTURER_NAME = "zwift"



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


def _normalized_string(value: Optional[str]) -> Optional[str]:
    """Return lower-cased, trimmed string value when present."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def is_zwift_cloud_workout(
    *,
    local_tz_offset: Optional[str],
    device_manufacturer: Optional[str] = None,
    device_name: Optional[str] = None,
    source_activity_name: Optional[str] = None,
    sport: Optional[str] = None,
    sub_sport: Optional[str] = None,
) -> bool:
    """Detect Zwift cloud workouts that require athlete home timezone override.

    Zwift cloud sessions are typically persisted with UTC+00:00 because device-local
    context is not available from source metadata. We only apply the Zwift override
    when a Zwift/virtual signal is present and offset is UTC+00:00.
    """
    if _normalized_string(local_tz_offset) != "utc+00:00":
        return False

    manufacturer = _normalized_string(device_manufacturer)
    if manufacturer == ZWIFT_MANUFACTURER_NAME:
        return True

    device = _normalized_string(device_name)
    if device and ZWIFT_MANUFACTURER_NAME in device:
        return True

    activity_name = _normalized_string(source_activity_name)
    if activity_name and ZWIFT_MANUFACTURER_NAME in activity_name:
        return True

    return _normalized_string(sub_sport) == "virtual_activity" or _normalized_string(sport) == "virtual_activity"


def _first_present(values: Sequence[Optional[str]]) -> Optional[str]:
    """Return first non-empty string from a sequence."""
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def resolve_canonical_timezone(
    *,
    explicit_timezone: Optional[str],
    session_offset: Optional[str],
    fallback_offsets: Sequence[Optional[str]],
    start_time_utc: Optional[datetime],
    athlete_timezone: Optional[str],
    is_zwift_workout: bool,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve canonical timezone context from a single shared precedence model.

    Returns:
        Tuple of (local_tz_offset, timezone), where:
        - local_tz_offset is session-derived when available, else fallback offset
        - timezone is explicit IANA, Zwift athlete override, IANA conversion, or offset
    """
    local_tz_offset = _first_present([session_offset, *fallback_offsets])

    if isinstance(explicit_timezone, str) and explicit_timezone.strip():
        return local_tz_offset, explicit_timezone.strip()

    if is_zwift_workout and isinstance(athlete_timezone, str) and athlete_timezone.strip():
        return local_tz_offset, athlete_timezone.strip()

    if (
        local_tz_offset
        and start_time_utc is not None
        and isinstance(athlete_timezone, str)
        and athlete_timezone.strip()
    ):
        resolved = iana_from_offset(
            local_tz_offset,
            start_time_utc,
            prefer_zone=athlete_timezone.strip(),
        )
        if resolved:
            return local_tz_offset, resolved

    return local_tz_offset, local_tz_offset


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


def _select_canonical_zone(
    matching_zones: list[str],
    timestamp: datetime,
) -> Optional[str]:
    """Select best canonical zone from matches.

    Prefers zones with DST transitions (e.g., America/New_York) over
    static offset zones (e.g., America/Atikokan). Within DST-aware zones,
    prefers major cities for predictability.

    Args:
        matching_zones: List of matching IANA timezone names
        timestamp: Reference timestamp for DST detection

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
    if not canonical_zones:
        return sorted(matching_zones)[0]

    # Prefer zones with DST transitions over static offset zones
    # Use timestamp's year for accurate DST detection
    year = timestamp.year
    dst_aware_zones = []
    for zone_name in canonical_zones:
        try:
            tz = ZoneInfo(zone_name)
            # Check if offset differs between January and July (DST indicator)
            winter = datetime(year, 1, 15, 12, 0, tzinfo=timezone.utc).astimezone(tz)
            summer = datetime(year, 7, 15, 12, 0, tzinfo=timezone.utc).astimezone(tz)
            if winter.utcoffset() != summer.utcoffset():
                dst_aware_zones.append(zone_name)
        except (ZoneInfoNotFoundError, OSError, ValueError):
            continue

    # If we have DST-aware zones, prefer those
    if dst_aware_zones:
        return _select_major_city(dst_aware_zones)

    # Fall back to canonical zones with major city preference
    return _select_major_city(canonical_zones)


def _select_major_city(zones: list[str]) -> str:
    """Select major city from list of zones using priority heuristic.

    Prefers well-known major cities over smaller locations for predictability
    and user expectations. Returns first match from priority-ordered list.

    Args:
        zones: List of IANA timezone names

    Returns:
        Selected timezone name (guaranteed non-None if zones is non-empty).
    """
    # Major cities by region in priority order
    # First match wins - ordered by population and common usage
    major_cities_priority = [
        # North America - Eastern (population order)
        "America/New_York",
        "America/Toronto",
        "America/Montreal",
        # North America - Central
        "America/Chicago",
        "America/Mexico_City",
        "America/Winnipeg",
        # North America - Mountain
        "America/Denver",
        "America/Edmonton",
        # North America - Pacific
        "America/Los_Angeles",
        "America/Vancouver",
        # North America - Alaska/Hawaii
        "America/Anchorage",
        "Pacific/Honolulu",
        # Europe (population/importance order)
        "Europe/London",
        "Europe/Paris",
        "Europe/Berlin",
        "Europe/Madrid",
        "Europe/Rome",
        "Europe/Amsterdam",
        # Asia
        "Asia/Tokyo",
        "Asia/Shanghai",
        "Asia/Hong_Kong",
        "Asia/Singapore",
        "Asia/Dubai",
        "Asia/Seoul",
        "Asia/Taipei",
        # Australia/Pacific
        "Australia/Sydney",
        "Australia/Melbourne",
        "Pacific/Auckland",
        # South America
        "America/Sao_Paulo",
        "America/Buenos_Aires",
        "America/Santiago",
        # Africa
        "Africa/Cairo",
        "Africa/Johannesburg",
    ]

    # Find first major city in priority order
    for major_city in major_cities_priority:
        if major_city in zones:
            return major_city

    # No major cities found - sort by path depth (simpler paths first), then alphabetically
    zones_sorted = sorted(zones, key=lambda z: (z.count('/'), z))
    return zones_sorted[0]


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
    return _select_canonical_zone(matching_zones, timestamp)


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
