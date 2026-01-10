"""Parse FIT files and extract workout metrics."""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast

import fitparse
import numpy as np
from .adapter import load_workout_from_fit
from .models import Workout

logger = logging.getLogger(__name__)


class FitParser:
    """Parser for FIT format workout files."""

    def __init__(self, file_path: str):
        """Initialize FIT parser with file path."""
        self.file_path = file_path
        self.fit = None
        self.workout: Optional[Workout] = None
        self.metrics = {}
        self._file_id_msg = None
        self._session_msg = None
        self._records = None

    @property
    def file_id_msg(self):
        """Cached file_id message (None if unavailable)."""
        return self._file_id_msg

    @property
    def session_msg(self):
        """Cached session message (None if unavailable)."""
        return self._session_msg

    @property
    def records(self) -> List:
        """Cached list of record messages (lazily loaded)."""
        if self._records is None:
            self._records = list(
                self.fit.get_messages("record")) if self.fit else []
        return self._records

    def parse(self) -> Dict:
        """
        Parse FIT file and extract workout metrics.

        Returns:
            Dict with parsed workout data
        """
        try:
            # Build structured workout entities first
            self.workout = load_workout_from_fit(self.file_path)
            # Keep raw fitparse for any fallback access
            self.fit = fitparse.FitFile(self.file_path)
        except Exception as e:
            logger.error("Error parsing FIT file %s: %s", self.file_path, e)
            raise

        # Cache message lookups for efficiency
        self._cache_messages()

        session = self.workout.session if self.workout else None
        self.metrics = {
            # Identity
            "sport": session.sport if session else self._get_sport(),
            "sub_sport": session.sub_sport if session else self._get_sub_sport(),
            "workout_name": session.workout_name if session else self._get_workout_name(),
            "device_name": self._get_device_name(),
            "is_indoor": session.is_indoor if session else self._get_is_indoor(),

            # Temporal
            "start_time_utc": session.start_time_utc if session else self._get_start_time(),
            "end_time_utc": session.end_time_utc if session else self._get_end_time(),
            "timezone": session.timezone if session else self._get_timezone(),
            "duration_sec": session.duration_sec if session else self._get_duration(),
            "moving_time_sec": session.moving_time_sec if session else self._get_moving_time(),

            # GPS
            "has_gps": self._has_gps_data(),
            "distance_m": session.distance_m if session else self._get_distance(),

            # Elevation
            "elevation_gain_m": session.elevation_gain_m if session else self._get_elevation_gain(),
            "elevation_loss_m": session.elevation_loss_m if session else self._get_elevation_loss(),

            # Speed
            "avg_speed_mps": session.avg_speed_mps if session else self._get_avg_speed(),
            "max_speed_mps": session.max_speed_mps if session else self._get_max_speed(),

            # Heart Rate
            "hr_avg_bpm": self._get_hr_avg(),
            "hr_max_bpm": self._get_hr_max(),
            "hr_samples_count": self._get_hr_samples_count(),
            "hr_missing_pct": self._get_hr_missing_pct(),

            # Power (cycling)
            "pwr_avg_watts": self._get_power_avg(),
            "pwr_max_watts": self._get_power_max(),
            "pwr_normalized_watts": self._get_power_normalized(),
            "pwr_variability_index": self._get_power_vi(),
            "pwr_samples_count": self._get_power_samples_count(),
            "pwr_missing_pct": self._get_power_missing_pct(),

            # Cadence
            "cad_avg_rpm": self._get_cadence_avg(),
            "cad_max_rpm": self._get_cadence_max(),
            "cad_samples_count": self._get_cadence_samples_count(),

            # Energy
            "calories_kcal": session.calories_kcal if session else self._get_calories(),
        }

        # Compute zone metrics if data available
        if self.metrics.get("hr_avg_bpm"):
            self._compute_hr_zones()
        if self.metrics.get("pwr_avg_watts"):
            self._compute_power_zones()

        return self.metrics

    def _cache_messages(self) -> None:
        """Cache frequently-accessed FIT messages for efficiency."""
        if not self.fit:
            return
        for message in self.fit.get_messages("file_id"):
            self._file_id_msg = message
        for message in self.fit.get_messages("session"):
            self._session_msg = message

    # Removed Java-style getters in favor of properties above

    def _get_record_data(self, field_name: str) -> List:
        """Extract all values for a field from record messages or mapped entities."""
        values: List = []
        if self.workout:
            for rec in self.workout.records:
                val = getattr(rec, field_name, None)
                if val is not None:
                    values.append(val)
            return values

        # Fallback to raw fitparse records
        values = []
        for record in self.records:
            data = record.get(field_name)
            if data:
                values.append(data.value)
        return values

    def _get_field_from_msg(self, msg, field_name: str) -> Optional[Any]:
        """Safely get a field value from a FIT message."""
        if msg:
            field = msg.get(field_name)
            if field:
                return field.value
        return None

    def _get_sport(self) -> Optional[str]:
        """Get sport type from file messages."""
        file_msg = self.file_id_msg
        sport = self._get_field_from_msg(file_msg, "type")
        if sport and hasattr(sport, "name"):
            return str(cast(Any, sport).name).lower()
        return None

    def _get_sub_sport(self) -> Optional[str]:
        """Get sub-sport type."""
        session = self.session_msg
        sub_sport = self._get_field_from_msg(session, "sub_sport")
        if sub_sport and hasattr(sub_sport, "name"):
            return str(cast(Any, sub_sport).name).lower()
        return None

    def _get_workout_name(self) -> Optional[str]:
        """Get workout/session name if available."""
        session = self.session_msg
        name = self._get_field_from_msg(session, "session_name")
        return str(name) if name is not None else None

    def _get_device_name(self) -> Optional[str]:
        """Get device/manufacturer info."""
        file_msg = self.file_id_msg
        manufacturer = self._get_field_from_msg(file_msg, "manufacturer")
        if manufacturer and hasattr(manufacturer, "name"):
            return str(cast(Any, manufacturer).name)
        return None

    def _get_is_indoor(self) -> Optional[bool]:
        """Determine if workout is indoor."""
        session = self.session_msg
        indoor = self._get_field_from_msg(session, "indoor")
        return bool(indoor) if indoor is not None else None

    def _get_start_time(self) -> Optional[str]:
        """Get workout start time as ISO string."""
        session = self.session_msg
        timestamp = self._get_field_from_msg(session, "start_time")
        if timestamp and isinstance(timestamp, datetime):
            dt = timestamp
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=None)
            return dt.isoformat() + "Z"
        return None

    def _get_end_time(self) -> Optional[str]:
        """Calculate end time from start + duration."""
        start = self._get_start_time()
        duration = self._get_duration()
        if start and duration:
            dt = datetime.fromisoformat(start.replace("Z", ""))
            end_dt = dt + timedelta(seconds=duration)
            return end_dt.isoformat() + "Z"
        return None

    def _get_timezone(self) -> Optional[str]:
        """Get timezone if present; default to 'UTC'.

        Prefers explicit `time_zone` message name; otherwise uses device
        settings offsets when available. FIT timestamps are UTC by spec,
        so the default is 'UTC'.
        """
        try:
            if not self.fit:
                return "UTC"

            tz_name = self._get_time_zone_name()
            if tz_name:
                return tz_name

            offset_minutes = self._get_device_utc_offset_minutes()
            if offset_minutes is not None:
                return self._format_utc_offset(offset_minutes)
        except (AttributeError, TypeError, ValueError):
            # Be defensive; timezone is non-critical
            pass
        return "UTC"

    def _get_time_zone_name(self) -> Optional[str]:
        """Return time zone name from FIT messages, if present."""
        if not self.fit:
            return None
        for msg in self.fit.get_messages("time_zone"):
            name = self._get_field_from_msg(msg, "name")
            if name:
                return str(name)
        return None

    def _get_device_utc_offset_minutes(self) -> Optional[int]:
        """Return device UTC offset in minutes from settings, if present."""
        if not self.fit:
            return None
        for msg in self.fit.get_messages("device_settings"):
            offset = (
                self._get_field_from_msg(msg, "utc_offset")
                or self._get_field_from_msg(msg, "timezone_offset")
            )
            if isinstance(offset, (int, float)):
                # offset is typically seconds; convert to minutes
                return int(round(offset / 60))
        return None

    def _format_utc_offset(self, minutes: int) -> str:
        """Format minutes offset as 'UTC±HH:MM'."""
        sign = "+" if minutes >= 0 else "-"
        minutes = abs(minutes)
        hours, mins = divmod(minutes, 60)
        return f"UTC{sign}{hours:02d}:{mins:02d}"

    def _get_duration(self) -> Optional[int]:
        """Get total elapsed time in seconds."""
        session = self.session_msg
        elapsed = self._get_field_from_msg(session, "total_elapsed_time")
        return int(elapsed) if elapsed is not None else None

    def _get_moving_time(self) -> Optional[int]:
        """Get moving time if available (for cycling usually equals duration)."""
        session = self.session_msg
        timer = self._get_field_from_msg(session, "total_timer_time")
        return int(timer) if timer is not None else None

    def _has_gps_data(self) -> bool:
        """Check if GPS data (lat/lon) exists in records."""
        if self.workout:
            for rec in self.workout.records:
                if rec.position_lat is not None and rec.position_long is not None:
                    return True
            return False
        for record in self.records:
            if record.get("position_lat") and record.get("position_long"):
                return True
        return False

    def _get_distance(self) -> Optional[float]:
        """Get total distance in meters."""
        session = self.session_msg
        distance = self._get_field_from_msg(session, "total_distance")
        return float(distance) if distance is not None else None

    def _get_elevation_gain(self) -> Optional[float]:
        """Get total elevation gain in meters."""
        session = self.session_msg
        elev = self._get_field_from_msg(session, "total_ascent")
        return float(elev) if elev is not None else None

    def _get_elevation_loss(self) -> Optional[float]:
        """Get total elevation loss in meters."""
        session = self.session_msg
        elev = self._get_field_from_msg(session, "total_descent")
        return float(elev) if elev is not None else None

    def _get_avg_speed(self) -> Optional[float]:
        """Get average speed in m/s."""
        session = self.session_msg
        speed = self._get_field_from_msg(session, "avg_speed")
        return float(speed) if speed is not None else None

    def _get_max_speed(self) -> Optional[float]:
        """Get max speed in m/s."""
        session = self.session_msg
        speed = self._get_field_from_msg(session, "max_speed")
        return float(speed) if speed is not None else None

    def _get_hr_avg(self) -> Optional[float]:
        """Get average heart rate."""
        hrs = self._get_record_data("heart_rate")
        if not hrs:
            return None
        hrs_array = np.array(hrs)
        return float(np.round(np.mean(hrs_array), 1))

    def _get_hr_max(self) -> Optional[float]:
        """Get max heart rate."""
        hrs = self._get_record_data("heart_rate")
        if not hrs:
            return None
        return float(np.max(hrs))

    def _get_hr_samples_count(self) -> int:
        """Get count of HR samples."""
        return len(self._get_record_data("heart_rate"))

    def _get_hr_missing_pct(self) -> Optional[float]:
        """Calculate percent of missing HR samples."""
        duration = self._get_duration()
        samples = self._get_hr_samples_count()
        if duration and samples:
            expected = duration  # Typically sampled once per second
            return round(
                (1 - samples / expected) * 100,
                1) if expected > 0 else 0.0
        return None

    def _get_power_avg(self) -> Optional[float]:
        """Get average power."""
        powers = self._get_record_data("power")
        if not powers:
            return None
        powers_array = np.array(powers)
        return float(np.round(np.mean(powers_array), 1))

    def _get_power_max(self) -> Optional[float]:
        """Get max power."""
        powers = self._get_record_data("power")
        if not powers:
            return None
        return float(np.max(powers))

    def _get_power_normalized(self) -> Optional[float]:
        """Compute Normalized Power (simplified 30s rolling avg)."""
        powers = self._get_record_data("power")
        if not powers or len(powers) < 30:
            return None

        # Simplified: use 4th power mean
        powers_array = np.array(powers)
        np_sum = np.mean(powers_array ** 4)
        return float(np.round(np_sum ** 0.25, 1)) if np_sum > 0 else None

    def _get_power_vi(self) -> Optional[float]:
        """Calculate Variability Index (NP / AP)."""
        normalized_power = self._get_power_normalized()
        average_power = self._get_power_avg()
        if normalized_power and average_power and average_power > 0:
            return round(normalized_power / average_power, 2)
        return None

    def _get_power_samples_count(self) -> int:
        """Get count of power samples."""
        return len(self._get_record_data("power"))

    def _get_power_missing_pct(self) -> Optional[float]:
        """Calculate percent of missing power samples."""
        duration = self._get_duration()
        samples = self._get_power_samples_count()
        if duration and samples:
            expected = duration
            return round(
                (1 - samples / expected) * 100,
                1) if expected > 0 else 0.0
        return None

    def _get_cadence_avg(self) -> Optional[float]:
        """Get average cadence."""
        cads = self._get_record_data("cadence")
        if not cads:
            return None
        cads_array = np.array(cads)
        return float(np.round(np.mean(cads_array), 1))

    def _get_cadence_max(self) -> Optional[float]:
        """Get max cadence."""
        cads = self._get_record_data("cadence")
        if not cads:
            return None
        return float(np.max(cads))

    def _get_cadence_samples_count(self) -> int:
        """Get count of cadence samples."""
        return len(self._get_record_data("cadence"))

    def _get_calories(self) -> Optional[float]:
        """Get total calories."""
        session = self.session_msg
        calories = self._get_field_from_msg(session, "total_calories")
        return float(calories) if calories is not None else None

    def _get_hr_zones(self, zone_basis: str, reference_bpm: float,
                      hr_rest: Optional[float] = None) -> Dict[str, tuple]:
        """Get HR zone boundaries based on calculation method."""
        if zone_basis == "HRmax":
            return {
                "hr_z1": (int(reference_bpm * 0.50), int(reference_bpm * 0.60)),
                "hr_z2": (int(reference_bpm * 0.60), int(reference_bpm * 0.70)),
                "hr_z3": (int(reference_bpm * 0.70), int(reference_bpm * 0.80)),
                "hr_z4": (int(reference_bpm * 0.80), int(reference_bpm * 0.90)),
                "hr_z5": (int(reference_bpm * 0.90), int(reference_bpm * 1.00)),
            }
        if zone_basis == "LTHR":
            return {
                "hr_z1": (int(reference_bpm * 0.65), int(reference_bpm * 0.81)),
                "hr_z2": (int(reference_bpm * 0.81), int(reference_bpm * 0.90)),
                "hr_z3": (int(reference_bpm * 0.90), int(reference_bpm * 0.94)),
                "hr_z4": (int(reference_bpm * 0.94), int(reference_bpm * 1.00)),
                "hr_z5": (int(reference_bpm * 1.00), int(reference_bpm * 1.06)),
            }
        if zone_basis == "HRR":
            rest_hr = hr_rest if hr_rest else 60
            hr_reserve = reference_bpm - rest_hr
            return {
                "hr_z1": (int(hr_reserve * 0.50 + rest_hr), int(hr_reserve * 0.60 + rest_hr)),
                "hr_z2": (int(hr_reserve * 0.60 + rest_hr), int(hr_reserve * 0.70 + rest_hr)),
                "hr_z3": (int(hr_reserve * 0.70 + rest_hr), int(hr_reserve * 0.80 + rest_hr)),
                "hr_z4": (int(hr_reserve * 0.80 + rest_hr), int(hr_reserve * 0.90 + rest_hr)),
                "hr_z5": (int(hr_reserve * 0.90 + rest_hr), int(hr_reserve * 1.00 + rest_hr)),
            }
        return {}

    def _get_reference_bpm(
            self,
            zone_basis: str,
            reference_bpm: Optional[float] = None) -> Optional[float]:
        """Determine reference BPM for zone calculation."""
        if reference_bpm is not None:
            return reference_bpm

        hr_max = self.metrics.get("hr_max_bpm")
        if not hr_max:
            return None

        if zone_basis == "LTHR":
            return hr_max * 0.90
        return hr_max if zone_basis in ("HRmax", "HRR") else None

    def _compute_hr_zones(
            self,
            zone_basis: str = "HRmax",
            reference_bpm: Optional[float] = None,
            hr_rest: Optional[float] = None):
        """
        Compute time in HR zones using specified basis method.

        Args:
            zone_basis: "HRmax", "LTHR" (Lactate Threshold), or "HRR" (Heart Rate Reserve/Karvonen)
            reference_bpm: HRmax or LTHR value (if not provided, uses detected max HR)
            hr_rest: Resting HR for HRR method (if not provided, uses default 60 bpm)
        """
        hrs = self._get_record_data("heart_rate")
        if not hrs:
            return

        ref_bpm = self._get_reference_bpm(zone_basis, reference_bpm)
        if not ref_bpm:
            return

        zones = self._get_hr_zones(zone_basis, ref_bpm, hr_rest)
        if not zones:
            return

        # Calculate time in each zone
        total_sec = 0
        hrs_array = np.array(hrs)
        for i, (zone_name, (low, high)) in enumerate(zones.items(), 1):
            count = int(np.sum((hrs_array >= low) & (hrs_array <= high)))
            self.metrics[f"{zone_name}_sec"] = count
            self.metrics[f"hr_z{i}_low_bpm"] = float(low)
            self.metrics[f"hr_z{i}_high_bpm"] = float(high)
            total_sec += count

        self.metrics["hr_zone_total_sec"] = total_sec
        self.metrics["hr_z2_min"] = round(
            self.metrics.get("hr_z2_sec", 0) / 60, 1)
        self.metrics["hr_zone_model"] = "garmin_5"
        self.metrics["hr_zone_basis"] = zone_basis
        self.metrics["hr_zone_reference_bpm"] = float(ref_bpm)

    def _compute_power_zones(self):
        """Compute time in power zones (simplified 7-zone Coggan model)."""
        # FTP (Functional Threshold Power) should be configured per athlete,
        # defaulting to 250W
        ftp = 250

        powers = self._get_record_data("power")
        if not powers:
            return

        zones = {
            "pwr_z1": (0, int(ftp * 0.55)),
            "pwr_z2": (int(ftp * 0.55), int(ftp * 0.75)),
            "pwr_z3": (int(ftp * 0.75), int(ftp * 0.90)),
            "pwr_z4": (int(ftp * 0.90), int(ftp * 1.05)),
            "pwr_z5": (int(ftp * 1.05), int(ftp * 1.20)),
            "pwr_z6": (int(ftp * 1.20), int(ftp * 1.50)),
            "pwr_z7": (int(ftp * 1.50), 99999),
        }

        total_sec = 0
        powers_array = np.array(powers)
        for zone_name, (low, high) in zones.items():
            count = int(np.sum((powers_array >= low) & (powers_array < high)))
            self.metrics[f"{zone_name}_sec"] = count
            total_sec += count

        self.metrics["pwr_zone_total_sec"] = total_sec
        self.metrics["pwr_z2_min"] = round(
            self.metrics.get("pwr_z2_sec", 0) / 60, 1)
        low_aerobic = self.metrics.get(
            "pwr_z1_sec", 0) + self.metrics.get("pwr_z2_sec", 0)
        intensity = sum(
            self.metrics.get(
                f"pwr_z{i}_sec",
                0) for i in range(
                4,
                8))
        self.metrics["low_aerobic_min"] = round(low_aerobic / 60, 1)
        self.metrics["intensity_min"] = round(intensity / 60, 1)
        self.metrics["pwr_zone_model"] = "coggan_7"
        self.metrics["ftp_watts"] = ftp


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def compute_workout_id(source_item_id: Optional[str] = None,
                       file_sha256: Optional[str] = None,
                       file_path: Optional[str] = None,
                       file_name: Optional[str] = None,
                       start_time: Optional[str] = None) -> str:
    """
    Generate deterministic workout_id.

    Priority:
    1. source_item_id (OneDrive itemId)
    2. file_sha256
    3. file_path + file_name + start_time
    """
    if source_item_id:
        return hashlib.sha1(source_item_id.encode()).hexdigest()
    elif file_sha256:
        return hashlib.sha1(file_sha256.encode()).hexdigest()
    elif file_path and file_name and start_time:
        combined = f"{file_path}#{file_name}#{start_time}"
        return hashlib.sha1(combined.encode()).hexdigest()
    else:
        raise ValueError(
            "Must provide at least source_item_id, file_sha256, or file path info")
