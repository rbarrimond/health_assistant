from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import fitparse

from .models import DeviceInfo, RecordSample, Workout, WorkoutSession


def _get_field_value(msg, field_name: str):
    if not msg:
        return None
    field = msg.get(field_name)
    return field.value if field else None


def load_workout_from_fit(file_path: str) -> Workout:
    """Parse a FIT file and map it into Workout entities."""
    fit = fitparse.FitFile(file_path)

    # Cache messages needed for session-level data
    file_id_msg = None
    session_msg = None
    for m in fit.get_messages("file_id"):
        file_id_msg = m
    for m in fit.get_messages("session"):
        session_msg = m

    # Identity and session fields
    sport = _get_field_value(file_id_msg, "type")
    sport_name = str(sport.name).lower() if sport and hasattr(sport, "name") else None

    sub_sport = _get_field_value(session_msg, "sub_sport")
    sub_sport_name = str(sub_sport.name).lower() if sub_sport and hasattr(sub_sport, "name") else None

    workout_name = _get_field_value(session_msg, "session_name")
    indoor = _get_field_value(session_msg, "indoor")

    start_time = _get_field_value(session_msg, "start_time")
    start_iso = None
    if start_time and isinstance(start_time, datetime):
        dt = start_time
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=None)
        start_iso = dt.isoformat() + "Z"

    duration = _get_field_value(session_msg, "total_elapsed_time")
    duration_sec = int(duration) if duration is not None else None

    end_iso = None
    if start_iso and duration_sec:
        dt = datetime.fromisoformat(start_iso.replace("Z", ""))
        end_dt = dt + timedelta(seconds=duration_sec)
        end_iso = end_dt.isoformat() + "Z"

    moving = _get_field_value(session_msg, "total_timer_time")
    moving_sec = int(moving) if moving is not None else None

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

    calories = _get_field_value(session_msg, "total_calories")
    calories_kcal = float(calories) if calories is not None else None

    # Device
    manufacturer = _get_field_value(file_id_msg, "manufacturer")
    manufacturer_name = str(manufacturer.name) if manufacturer and hasattr(manufacturer, "name") else None

    device = DeviceInfo(manufacturer_name=manufacturer_name)

    # Records
    records = []
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

    session = WorkoutSession(
        sport=sport_name,
        sub_sport=sub_sport_name,
        workout_name=str(workout_name) if workout_name is not None else None,
        is_indoor=bool(indoor) if indoor is not None else None,
        start_time_utc=start_iso,
        end_time_utc=end_iso,
        timezone="UTC",  # FIT timestamps are UTC by spec; devices may include offsets
        duration_sec=duration_sec,
        moving_time_sec=moving_sec,
        distance_m=distance_m,
        elevation_gain_m=elev_gain_m,
        elevation_loss_m=elev_loss_m,
        avg_speed_mps=avg_speed_mps,
        max_speed_mps=max_speed_mps,
        calories_kcal=calories_kcal,
    )

    return Workout(session=session, device=device, records=records)
