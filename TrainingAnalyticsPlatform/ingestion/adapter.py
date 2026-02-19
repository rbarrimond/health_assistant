"""Adapter to map FIT messages into pydantic workout entities."""

from __future__ import annotations

from datetime import datetime, timezone
import io
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitdecode

from TrainingAnalyticsPlatform.platform.exceptions import FitAdapterError
from TrainingAnalyticsPlatform.models import DeviceInfo, RecordSample, Workout, WorkoutSession

from .apple_workout_types import AppleWorkoutTypeResolver
from .timezone_utils import (
    infer_timezone_from_activity,
    infer_timezone_from_session,
    resolve_timezone,
)

# FIT standard sub-sport keywords indicating indoor activities
# Covers documented FIT sub-sport types and common platform variants
INDOOR_KEYWORDS = [
    "indoor",  # Catches indoor_cycling, indoor_running, indoor_walk, etc.
    "virtual",  # virtual_ride, virtual_run (Zwift, etc.)
    "stationary",  # stationary_bike
    "trainer",  # Common cycling trainer terminology
    "treadmill",  # Indoor running variant
    "pool",  # pool_swimming vs open_water_swimming
    "strength_training",  # FIT standard training sub-sport
    "functional_training",  # FIT standard training sub-sport
    "core",  # FIT standard core training sub-sport
    "track_cycling",  # Velodrome (typically indoor)
    "spin",  # Common indoor cycling term
    "zwift",  # Specific virtual platform
    "peloton",  # Specific indoor cycling platform
    "rowing_machine",  # Indoor rowing variant
]


def _load_fit_messages(file_path_or_stream) -> tuple[List[Dict[str, Any]], str]:
    """Load FIT messages from a file or stream using fitdecode.

    Returns:
        Tuple of (messages list, source description for errors)
    """
    stream = None
    should_close = False
    source_desc = "unknown"

    try:
        if isinstance(file_path_or_stream, (bytes, bytearray)):
            stream = io.BytesIO(file_path_or_stream)
            source_desc = "bytes stream"
        elif isinstance(file_path_or_stream, (str, Path)):
            stream = open(file_path_or_stream, "rb")
            should_close = True
            source_desc = f"file {file_path_or_stream}"
        else:
            stream = file_path_or_stream
            source_desc = "file stream"

        messages: List[Dict[str, Any]] = []
        try:
            with fitdecode.FitReader(stream, processor=fitdecode.DefaultDataProcessor()) as reader:
                for frame in reader:
                    if not isinstance(frame, fitdecode.FitDataMessage):
                        continue
                    messages.append({
                        "name": frame.name,
                        "frame": frame,
                        "fields": {field.name: field for field in frame.fields},
                    })
        except Exception as exc:
            raise RuntimeError(
                f"FIT file parsing failed: {exc.__class__.__name__}: {exc}"
            ) from exc
        finally:
            if should_close and stream is not None:
                stream.close()

        return messages, source_desc
    except Exception:
        if should_close and stream is not None:
            stream.close()
        raise


class FitAdapter:
    """Build Workout entities from a FIT file."""

    def __init__(
        self,
        file_path: str,
        source_file_name: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
    ):
        self.file_path = file_path
        self.source_file_name = source_file_name
        self._gps_data_cache: Optional[bool] = None
        try:
            file_input = file_bytes if file_bytes is not None else file_path
            self.messages, source_desc = _load_fit_messages(file_input)
            self.file_id_msg, self.session_msg = self._cache_core_messages()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            source_desc = "bytes stream" if file_bytes is not None else f"file {file_path}"
            raise FitAdapterError(
                f"Failed to initialize FitAdapter for {source_desc}: {exc}"
            ) from exc

    def load_workout(self) -> Workout:
        """Parse the FIT file and map it into Workout entities."""
        try:
            session = self._build_session()
            device = self._build_device()
            records = self._build_records()
            return Workout(session=session, device=device, records=records)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise FitAdapterError(
                "Failed to build Workout from FIT data") from exc

    @staticmethod
    def _get_field_value(msg: Optional[Dict], field_name: str) -> Any:
        """Return field value from a FIT message if present."""
        if not msg:
            return None
        fields = msg.get("fields", {})
        field = fields.get(field_name)
        if not field:
            return None
        value = field.value
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _get_raw_field_value(msg: Optional[Dict], field_name: str) -> Any:
        """Return raw field value (no timezone coercion)."""
        if not msg:
            return None
        fields = msg.get("fields", {})
        field = fields.get(field_name)
        return field.value if field else None

    def _cache_core_messages(self) -> tuple[Optional[Dict], Optional[Dict]]:
        """Cache the first file_id and session messages for reuse."""
        file_id_msg = None
        session_msg = None
        for msg in self.messages:
            if msg["name"] == "file_id" and file_id_msg is None:
                file_id_msg = msg
            elif msg["name"] == "session" and session_msg is None:
                session_msg = msg
            if file_id_msg and session_msg:
                break
        return file_id_msg, session_msg

    @staticmethod
    def _to_iso_offset(dt: datetime | None) -> str | None:
        """Convert a datetime to an ISO8601 string with UTC offset."""
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()

    def _extract_sport_names(self, session_msg):
        """Extract sport and sub_sport enum names."""
        sport = self._get_field_value(session_msg, "sport")
        if sport:
            sport_name = (
                str(sport.name).lower()
                if hasattr(sport, "name")
                else str(sport).lower()
            )
        else:
            sport_name = None

        sub_sport = self._get_field_value(session_msg, "sub_sport")
        if sub_sport:
            if hasattr(sub_sport, "name"):
                sub_sport_name = str(sub_sport.name).lower()
            else:
                sub_sport_name = str(sub_sport).lower()
        else:
            sub_sport_name = None

        return sport_name, sub_sport_name

    def _extract_session_times(self, session_msg):
        """Extract start, end, and duration times."""
        start_time = self._get_field_value(session_msg, "start_time")
        start_iso = (
            self._to_iso_offset(start_time)
            if isinstance(start_time, datetime)
            else None
        )

        duration = self._get_field_value(session_msg, "total_elapsed_time")
        duration_sec = int(duration) if duration is not None else None

        return start_iso, duration_sec

    def _extract_timezone(self) -> str:
        """Extract timezone name or UTC offset from FIT messages.

        FIT timestamps are UTC by spec; prefer explicit time zone names,
        fallback to device UTC offsets when available.
        """
        tz_name = self._get_time_zone_name()
        offset_minutes = self._get_device_utc_offset_minutes()
        inferred_activity = self._infer_timezone_from_activity_times()
        inferred_session = self._infer_timezone_from_session_times(
            self.session_msg
        )
        return resolve_timezone(
            tz_name,
            offset_minutes,
            inferred_activity,
            inferred_session,
        )

    def _get_time_zone_name(self) -> Optional[str]:
        """Return time zone name from FIT messages, if present."""
        for msg in self.messages:
            if msg["name"] == "time_zone":
                name = self._get_field_value(msg, "name")
                if name:
                    return str(name)
        return None

    def _get_device_utc_offset_minutes(self) -> Optional[int]:
        """Return device UTC offset in minutes from settings, if present."""
        for msg in self.messages:
            if msg["name"] == "device_settings":
                offset = (
                    self._get_field_value(msg, "utc_offset")
                    or self._get_field_value(msg, "timezone_offset")
                )
                if isinstance(offset, (int, float)):
                    return int(round(offset / 60))
        return None

    def _infer_timezone_from_session_times(self, session_msg) -> Optional[str]:
        """Infer timezone from session timestamp vs local start time.

        Some exporters (e.g., HealthFit) may encode start_time as local time
        while keeping timestamp in UTC. We can infer the offset by comparing
        start_time to (timestamp - duration).
        """
        if not session_msg:
            return None

        start_time = self._get_raw_field_value(session_msg, "start_time")
        timestamp = self._get_field_value(session_msg, "timestamp")
        duration = self._get_field_value(session_msg, "total_elapsed_time")

        try:
            duration_sec = int(duration)
        except (TypeError, ValueError):
            return None
        return infer_timezone_from_session(
            start_time,
            timestamp,
            duration_sec,
        )

    def _infer_timezone_from_activity_times(self) -> Optional[str]:
        """Infer timezone from activity local_time vs UTC timestamp."""
        activity_msg = None
        for msg in self.messages:
            if msg["name"] == "activity":
                activity_msg = msg
                break
        if not activity_msg:
            return None

        local_time = (
            self._get_raw_field_value(activity_msg, "local_time")
            or self._get_raw_field_value(activity_msg, "local_timestamp")
        )
        timestamp = self._get_field_value(activity_msg, "timestamp")
        return infer_timezone_from_activity(local_time, timestamp)

    def _extract_session_metrics(self, session_msg):
        """Extract distance, elevation, and speed metrics."""
        distance = self._get_field_value(session_msg, "total_distance")
        distance_m = float(distance) if distance is not None else None

        elev_gain = self._get_field_value(session_msg, "total_ascent")
        elev_loss = self._get_field_value(session_msg, "total_descent")
        elev_gain_m = float(elev_gain) if elev_gain is not None else None
        elev_loss_m = float(elev_loss) if elev_loss is not None else None

        avg_speed = self._get_field_value(session_msg, "avg_speed")
        max_speed = self._get_field_value(session_msg, "max_speed")
        avg_speed_mps = float(avg_speed) if avg_speed is not None else None
        max_speed_mps = float(max_speed) if max_speed is not None else None

        return distance_m, elev_gain_m, elev_loss_m, avg_speed_mps, max_speed_mps

    def _has_gps_data(self) -> bool:
        """Check if any records in the FIT file have GPS coordinates (cached).

        Limits checks to first 100 records to avoid timeout on large files.
        """
        if self._gps_data_cache is not None:
            return self._gps_data_cache

        has_gps = False
        try:
            record_count = 0
            for record in self.messages:
                if record["name"] == "record":
                    lat = self._get_field_value(record, "position_lat")
                    lon = self._get_field_value(record, "position_long")
                    if lat is not None and lon is not None:
                        has_gps = True
                        break
                    record_count += 1
                    if record_count >= 100:
                        # Limit checks to first 100 records to avoid timeout on large files
                        break
        except Exception:  # pylint: disable=broad-exception-caught
            # If there's any error checking GPS, assume no GPS data
            has_gps = False

        self._gps_data_cache = has_gps
        return has_gps

    @staticmethod
    def _parse_indoor_flag(value) -> bool | None:
        """Parse the indoor flag, handling various input formats."""
        if value is None:
            return None
        # Handle empty strings
        if isinstance(value, str) and value.strip() == "":
            return None
        # Handle string representations of boolean
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                return True
            if value.lower() in ("false", "0", "no"):
                return False
            return None
        # Handle actual boolean
        if isinstance(value, bool):
            return value
        # Handle numeric (1/0)
        if isinstance(value, (int, float)):
            return bool(value)
        return None

    def _build_session(self) -> WorkoutSession:
        """Build a WorkoutSession from cached messages."""
        session_msg = self.session_msg
        sport_name, sub_sport_name = self._extract_sport_names(session_msg)
        start_iso, duration_sec = self._extract_session_times(
            session_msg)
        (distance_m, elev_gain_m, elev_loss_m,
         avg_speed_mps, max_speed_mps) = self._extract_session_metrics(session_msg)

        workout_name = self._get_field_value(session_msg, "session_name")
        if workout_name is None and self.source_file_name:
            file_name = Path(self.source_file_name).name
            if file_name.lower().endswith(".gz"):
                file_name = file_name[:-3]
            workout_name = Path(file_name).stem or None
        indoor = self._get_field_value(session_msg, "indoor")
        moving = self._get_field_value(session_msg, "total_timer_time")
        moving_sec = int(moving) if moving is not None else None
        calories = self._get_field_value(session_msg, "total_calories")
        calories_kcal = float(calories) if calories is not None else None
        tz_value = self._extract_timezone()

        # Infer is_indoor from explicit flag, keywords, GPS data
        is_indoor_flag = self._parse_indoor_flag(indoor)
        if is_indoor_flag is None:
            # Check for FIT standard indoor keywords first (handles virtual rides/runs with GPS)
            if sub_sport_name and any(
                keyword in sub_sport_name.lower() for keyword in INDOOR_KEYWORDS
            ):
                is_indoor_flag = True
            # If no indoor keywords, check if records have GPS data
            elif self._has_gps_data():
                is_indoor_flag = False  # GPS present without indoor keywords = outdoor
            # Otherwise leave as None

        resolver = AppleWorkoutTypeResolver(
            workout_name=str(
                workout_name) if workout_name is not None else None,
            sport=sport_name,
            sub_sport=sub_sport_name,
        )
        apple_workout_type = resolver.resolve()

        return WorkoutSession(
            sport=sport_name,
            sub_sport=sub_sport_name,
            apple_workout_type=apple_workout_type,
            workout_name=str(
                workout_name) if workout_name is not None else None,
            is_indoor=is_indoor_flag,
            start_time_utc=start_iso,
            timezone=tz_value,
            duration_sec=duration_sec,
            moving_time_sec=moving_sec,
            distance_m=distance_m,
            elevation_gain_m=elev_gain_m,
            elevation_loss_m=elev_loss_m,
            avg_speed_mps=avg_speed_mps,
            max_speed_mps=max_speed_mps,
            calories_kcal=calories_kcal,
        )

    def _build_device(self) -> DeviceInfo:
        """Build DeviceInfo from the file_id message."""
        manufacturer = self._get_field_value(self.file_id_msg, "manufacturer")
        manufacturer_name = (
            str(manufacturer.name)
            if manufacturer and hasattr(manufacturer, "name")
            else None
        )
        return DeviceInfo(manufacturer_name=manufacturer_name)

    def _build_records(self) -> list[RecordSample]:
        """Extract record samples into domain objects."""
        records: list[RecordSample] = []
        for record in self.messages:
            if record["name"] == "record":
                hr = self._get_field_value(record, "heart_rate")
                pwr = self._get_field_value(record, "power")
                cad = self._get_field_value(record, "cadence")
                lat = self._get_field_value(record, "position_lat")
                lon = self._get_field_value(record, "position_long")
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
