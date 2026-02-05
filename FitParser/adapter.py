"""Adapter to map fitparse messages into pydantic workout entities."""

from __future__ import annotations

from datetime import datetime, timedelta

import fitparse

from .apple_workout_types import AppleWorkoutTypeResolver
from .models import DeviceInfo, RecordSample, Workout, WorkoutSession


def _get_field_value(msg, field_name: str):
    """Return field value from a fitparse message if present."""
    if not msg:
        return None
    field = msg.get(field_name)
    return field.value if field else None


def _cache_core_messages(fit):
    """Cache the first file_id and session messages for reuse."""
    file_id_msg = None
    session_msg = None
    for m in fit.get_messages("file_id"):
        file_id_msg = m
    for m in fit.get_messages("session"):
        session_msg = m
    return file_id_msg, session_msg


def _to_iso_z(dt: datetime | None) -> str | None:
    """Convert a datetime to an ISO8601 string with trailing Z."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _extract_sport_names(session_msg):
    """Extract sport and sub_sport enum names."""
    sport = _get_field_value(session_msg, "sport")
    if sport:
        sport_name = str(sport.name).lower() if hasattr(sport, "name") else str(sport).lower()
    else:
        sport_name = None

    sub_sport = _get_field_value(session_msg, "sub_sport")
    if sub_sport:
        if hasattr(sub_sport, "name"):
            sub_sport_name = str(sub_sport.name).lower()
        else:
            sub_sport_name = str(sub_sport).lower()
    else:
        sub_sport_name = None

    return sport_name, sub_sport_name


def _extract_session_times(session_msg):
    """Extract start, end, and duration times."""
    start_time = _get_field_value(session_msg, "start_time")
    start_iso = _to_iso_z(start_time) if isinstance(start_time, datetime) else None

    duration = _get_field_value(session_msg, "total_elapsed_time")
    duration_sec = int(duration) if duration is not None else None

    end_iso = None
    if start_iso and duration_sec:
        dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        end_dt = dt + timedelta(seconds=duration_sec)
        end_iso = end_dt.isoformat() + "Z"

    return start_iso, end_iso, duration_sec


def _extract_session_metrics(session_msg):
    """Extract distance, elevation, and speed metrics."""
    distance = _get_field_value(session_msg, "total_distance")
    distance_m = float(distance) if distance is not None else None

    elev_gain = _get_field_value(session_msg, "total_ascent")
    elev_loss = _get_field_value(session_msg, "total_descent")
    elev_gain_m = float(elev_gain) if elev_gain is not None else None
    elev_loss_m = float(elev_loss) if elev_loss is not None else None

    avg_speed = _get_field_value(session_msg, "avg_speed")
    max_speed = _get_field_value(session_msg, "max_speed")
    avg_speed_mps = float(avg_speed) if avg_speed is not None else None
    max_speed_mps = float(max_speed) if max_speed is not None else None

    return distance_m, elev_gain_m, elev_loss_m, avg_speed_mps, max_speed_mps


def _build_session(session_msg) -> WorkoutSession:
    """Build a WorkoutSession from cached messages."""
    sport_name, sub_sport_name = _extract_sport_names(session_msg)
    start_iso, end_iso, duration_sec = _extract_session_times(session_msg)
    (distance_m, elev_gain_m, elev_loss_m,
     avg_speed_mps, max_speed_mps) = _extract_session_metrics(session_msg)

    workout_name = _get_field_value(session_msg, "session_name")
    indoor = _get_field_value(session_msg, "indoor")
    moving = _get_field_value(session_msg, "total_timer_time")
    moving_sec = int(moving) if moving is not None else None
    calories = _get_field_value(session_msg, "total_calories")
    calories_kcal = float(calories) if calories is not None else None

    # Infer is_indoor from sub_sport or explicit flag
    is_indoor_flag = bool(indoor) if indoor is not None else None
    if is_indoor_flag is None and sub_sport_name:
        # Check for known indoor/virtual ride types
        indoor_keywords = [
            "indoor",
            "virtual",
            "zwift",
            "trainer",
            "stationary",
        ]
        is_indoor_flag = any(
            keyword in sub_sport_name.lower() for keyword in indoor_keywords
        )

    # Extract Apple Watch workout type
    resolver = AppleWorkoutTypeResolver(
        session_name=str(workout_name) if workout_name is not None else None,
        sport=sport_name,
        sub_sport=sub_sport_name,
    )
    apple_workout_type = resolver.resolve()

    return WorkoutSession(
        sport=sport_name,
        sub_sport=sub_sport_name,
        apple_workout_type=apple_workout_type,
        workout_name=str(workout_name) if workout_name is not None else None,
        is_indoor=is_indoor_flag,
        start_time_utc=start_iso,
        end_time_utc=end_iso,
        timezone="UTC",
        duration_sec=duration_sec,
        moving_time_sec=moving_sec,
        distance_m=distance_m,
        elevation_gain_m=elev_gain_m,
        elevation_loss_m=elev_loss_m,
        avg_speed_mps=avg_speed_mps,
        max_speed_mps=max_speed_mps,
        calories_kcal=calories_kcal,
    )


def _build_device(file_id_msg) -> DeviceInfo:
    """Build DeviceInfo from the file_id message."""
    manufacturer = _get_field_value(file_id_msg, "manufacturer")
    manufacturer_name = (
        str(manufacturer.name)
        if manufacturer and hasattr(manufacturer, "name")
        else None
    )
    return DeviceInfo(manufacturer_name=manufacturer_name)


def _build_records(fit) -> list[RecordSample]:
    """Extract record samples into domain objects."""
    records: list[RecordSample] = []
    for record in fit.get_messages("record"):
        hr = _get_field_value(record, "heart_rate")
        pwr = _get_field_value(record, "power")
        cad = _get_field_value(record, "cadence")
        lat = _get_field_value(record, "position_lat")
        lon = _get_field_value(record, "position_long")
        records.append(
            RecordSample(
                heart_rate=hr,
                power=pwr,
                cadence=cad,
                position_lat=lat,
                position_long=lon,
            )
        )
    return records


def load_workout_from_fit(file_path: str) -> Workout:
    """Parse a FIT file and map it into Workout entities."""
    fit = fitparse.FitFile(file_path)
    file_id_msg, session_msg = _cache_core_messages(fit)
    session = _build_session(session_msg)
    device = _build_device(file_id_msg)
    records = _build_records(fit)
    return Workout(session=session, device=device, records=records)
