"""Parse FIT files and extract workout metrics."""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, cast

import numpy as np
from .adapter import FitAdapter
from .apple_workout_types import AppleWorkoutTypeResolver
from .config import Config
from .models import Workout

logger = logging.getLogger(__name__)


class FitParser:
    """Parser for FIT format workout files."""

    def __init__(self, file_path: str, source_file_name: Optional[str] = None):
        """Initialize FIT parser with file path and optional source filename.

        Args:
            file_path: Path to the FIT file
            source_file_name: Optional original filename
                (e.g., from OneDrive) for metadata extraction
        """
        self.file_path = file_path
        self.source_file_name = source_file_name
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
        self._load_fit_sources()
        self._cache_messages()
        self.metrics = self._build_metrics()

        # Extract resting HR if available
        hr_resting = self._extract_hr_resting()
        if hr_resting:
            self.metrics["hr_resting_bpm"] = hr_resting

        # Capture physiometrics snapshot timestamp (before zone computation)
        # This links the workout to the exact config used
        self.metrics["physiometrics_snapshot_timestamp"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        # Compute zones if data available
        if self.metrics.get("hr_avg_bpm"):
            self._compute_hr_zones()
        if self.metrics.get("pwr_avg_watts"):
            self._compute_power_zones()

        # Compute aerobic efficiency metrics
        self._compute_aerobic_efficiency()

        return self.metrics

    def _load_fit_sources(self) -> None:
        """Load structured entities and raw fitparse for fallbacks."""
        try:
            adapter = FitAdapter(
                self.file_path,
                source_file_name=self.source_file_name,
            )
            self.workout = adapter.load_workout()
            self.fit = adapter.fit
        except Exception as e:
            logger.error("Error parsing FIT file %s: %s", self.file_path, e)
            raise

    def _build_metrics(self) -> Dict:
        """Assemble metric dictionary from mapped session or raw messages."""
        session = self.workout.session if self.workout else None
        return self._build_base_metrics(session) | self._build_sample_metrics()

    def _session_or_fallback(self, session_value, fallback_fn):
        """Return session value if present, otherwise call fallback function."""
        return session_value if session_value is not None else fallback_fn()

    def _build_session_metrics(self, session) -> Dict:
        """Build session-level time and identification metrics."""
        return {
            "sport": self._session_or_fallback(
                session.sport if session else None, self._get_sport
            ),
            "sub_sport": self._session_or_fallback(
                session.sub_sport if session else None, self._get_sub_sport
            ),
            "apple_workout_type": self._session_or_fallback(
                session.apple_workout_type if session else None,
                self._get_apple_workout_type
            ),
            "workout_name": self._session_or_fallback(
                session.workout_name if session else None,
                self._get_workout_name
            ),
            "device_name": self._get_device_name(),
            "is_indoor": self._session_or_fallback(
                session.is_indoor if session else None, self._get_is_indoor
            ),
            "start_time_utc": self._session_or_fallback(
                session.start_time_utc if session else None,
                self._get_start_time
            ),
            "end_time_utc": self._session_or_fallback(
                session.end_time_utc if session else None,
                self._get_end_time
            ),
            "timezone": self._session_or_fallback(
                session.timezone if session else None, self._get_timezone
            ),
            "duration_sec": self._session_or_fallback(
                session.duration_sec if session else None, self._get_duration
            ),
            "moving_time_sec": self._session_or_fallback(
                session.moving_time_sec if session else None,
                self._get_moving_time
            ),
        }

    def _build_distance_metrics(self, session) -> Dict:
        """Build distance, elevation, and speed metrics."""
        return {
            "has_gps": self._has_gps_data(),
            "distance_m": self._session_or_fallback(
                session.distance_m if session else None, self._get_distance
            ),
            "elevation_gain_m": self._session_or_fallback(
                session.elevation_gain_m if session else None,
                self._get_elevation_gain
            ),
            "elevation_loss_m": self._session_or_fallback(
                session.elevation_loss_m if session else None,
                self._get_elevation_loss
            ),
            "avg_speed_mps": self._session_or_fallback(
                session.avg_speed_mps if session else None, self._get_avg_speed
            ),
            "max_speed_mps": self._session_or_fallback(
                session.max_speed_mps if session else None, self._get_max_speed
            ),
            "calories_kcal": self._session_or_fallback(
                session.calories_kcal if session else None, self._get_calories
            ),
        }

    def _build_base_metrics(self, session) -> Dict:
        """Build combined base metrics from session and distance data."""
        metrics = self._build_session_metrics(session)
        metrics.update(self._build_distance_metrics(session))
        return metrics

    def _build_sample_metrics(self) -> Dict:
        """Build sample-based metrics from records."""
        return {
            "hr_avg_bpm": self._get_hr_avg(),
            "hr_max_bpm": self._get_hr_max(),
            "hr_samples_count": self._get_hr_samples_count(),
            "hr_missing_pct": self._get_hr_missing_pct(),
            "pwr_avg_watts": self._get_power_avg(),
            "pwr_max_watts": self._get_power_max(),
            "pwr_normalized_watts": self._get_power_normalized(),
            "pwr_variability_index": self._get_power_vi(),
            "pwr_samples_count": self._get_power_samples_count(),
            "pwr_missing_pct": self._get_power_missing_pct(),
            "cad_avg_rpm": self._get_cadence_avg(),
            "cad_max_rpm": self._get_cadence_max(),
            "cad_samples_count": self._get_cadence_samples_count(),
        }

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
        if sport:
            if hasattr(sport, "name"):
                return str(cast(Any, sport).name).lower()
            return str(sport).lower()
        return None

    def _get_sub_sport(self) -> Optional[str]:
        """Get sub-sport type."""
        session = self.session_msg
        sub_sport = self._get_field_from_msg(session, "sub_sport")
        if sub_sport:
            if hasattr(sub_sport, "name"):
                return str(cast(Any, sub_sport).name).lower()
            return str(sub_sport).lower()
        return None

    def _get_apple_workout_type(self) -> Optional[str]:
        """
        Get Apple Watch workout type using the resolver.
        
        Passes all available inputs to AppleWorkoutTypeResolver for
        clear, testable resolution logic.
        """
        resolver = AppleWorkoutTypeResolver(
            session_name=self._get_workout_name(),
            source_file_name=self.source_file_name,
            sport=self._get_sport(),
            sub_sport=self._get_sub_sport()
        )
        return resolver.resolve()

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

    def _compute_hr_zones(self):
        """
        Compute time in HR zones using configured basis method.
        Configuration is loaded from Config.hr_config().
        """
        hrs = self._get_record_data("heart_rate")
        if not hrs:
            return

        # Load HR configuration
        hr_cfg = Config.hr_config()
        zone_basis = hr_cfg.basis
        hr_rest = hr_cfg.resting_hr_bpm

        # Determine reference BPM based on zone basis
        if zone_basis == "LTHR":
            ref_bpm = hr_cfg.lthr_bpm
        elif zone_basis == "HRR":
            ref_bpm = hr_cfg.hr_max_bpm
        else:  # HRmax
            ref_bpm = hr_cfg.hr_max_bpm

        # Fallback to detected max HR if config value not available
        if not ref_bpm:
            ref_bpm = self.metrics.get("hr_max_bpm")
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

        # Map zone basis to researcher/author name
        basis_to_model = {
            "LTHR": "coggan",
            "HRmax": "karvonen",
            "HRR": "karvonen",
        }
        self.metrics["hr_zone_model"] = basis_to_model.get(zone_basis, "unknown")
        self.metrics["hr_zone_basis"] = zone_basis
        self.metrics["hr_zone_reference_bpm"] = float(ref_bpm)

    def _compute_power_zones(self):
        """Compute time in power zones (simplified 7-zone Coggan model)."""
        # Extract FTP from user profile or config, default to 250W
        ftp = self._extract_ftp()
        if not ftp:
            pwr_cfg = Config.power_config()
            ftp = pwr_cfg.ftp_watts or 250

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
        for i, (zone_name, (low, high)) in enumerate(zones.items(), 1):
            count = int(np.sum((powers_array >= low) & (powers_array < high)))
            self.metrics[f"{zone_name}_sec"] = count
            # Store zone boundaries for Power BI interpretability
            self.metrics[f"pwr_z{i}_low_w"] = float(low)
            self.metrics[f"pwr_z{i}_high_w"] = float(
                high if high != 99999 else ftp * 2)
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

        # Compute training load metrics
        self._compute_training_load(ftp)

    def _compute_training_load(self, ftp: float) -> None:
        """
        Compute training load metrics (TSS, IF).

        Args:
            ftp: Functional Threshold Power in watts
        """
        normalized_power = self.metrics.get("pwr_normalized_watts")
        duration_sec = self.metrics.get("duration_sec")

        if not normalized_power or not duration_sec or not ftp or ftp <= 0:
            return

        # Intensity Factor (IF) = NP / FTP
        intensity_factor = normalized_power / ftp
        self.metrics["intensity_factor"] = round(intensity_factor, 3)

        # Training Stress Score (TSS) = (duration_hours * NP * IF * 100) / FTP
        duration_hours = duration_sec / 3600
        tss = (duration_hours * normalized_power *
               intensity_factor * 100) / ftp
        self.metrics["tss"] = round(tss, 1)

    def _compute_aerobic_efficiency(self) -> None:
        """
        Compute aerobic efficiency and decoupling metrics.
        Requires minimum 30 minutes duration with HR and power data.
        """
        duration_sec = self.metrics.get("duration_sec")
        if not duration_sec or duration_sec < 1800:  # 30 minutes minimum
            return

        hrs = self._get_record_data("heart_rate")
        powers = self._get_record_data("power")

        if not hrs or not powers or len(hrs) < 30 or len(powers) < 30:
            return

        # Ensure equal lengths
        min_len = min(len(hrs), len(powers))
        hrs = hrs[:min_len]
        powers = powers[:min_len]

        # Split into halves
        mid_point = min_len // 2
        hrs_first = np.array(hrs[:mid_point])
        powers_first = np.array(powers[:mid_point])
        hrs_second = np.array(hrs[mid_point:])
        powers_second = np.array(powers[mid_point:])

        # Compute average HR and power for each half
        avg_hr_first = float(np.mean(hrs_first))
        avg_pwr_first = float(np.mean(powers_first))
        avg_hr_second = float(np.mean(hrs_second))
        avg_pwr_second = float(np.mean(powers_second))

        if avg_hr_first <= 0 or avg_hr_second <= 0:
            return

        # Efficiency Factor (EF) = Power / HR
        ef_first = avg_pwr_first / avg_hr_first
        ef_second = avg_pwr_second / avg_hr_second
        ef_overall = (avg_pwr_first + avg_pwr_second) / \
            (avg_hr_first + avg_hr_second)

        self.metrics["ef_first_half"] = round(ef_first, 3)
        self.metrics["ef_second_half"] = round(ef_second, 3)
        self.metrics["ef_overall"] = round(ef_overall, 3)

        # HR drift
        hr_drift = avg_hr_second - avg_hr_first
        self.metrics["hr_drift_bpm"] = round(hr_drift, 1)

        # Decoupling % = ((EF_second / EF_first) - 1) * 100
        # Negative decoupling = efficiency decreased (HR increased relative to
        # power)
        if ef_first > 0:
            decoupling_pct = ((ef_second / ef_first) - 1) * 100
            self.metrics["decoupling_pct"] = round(decoupling_pct, 2)

    def _extract_hr_resting(self) -> Optional[float]:
        """Extract resting heart rate from FIT file if available."""
        if not self.fit:
            return None

        # Check user profile messages for resting HR
        for msg in self.fit.get_messages("user_profile"):
            resting_hr = self._get_field_from_msg(msg, "resting_heart_rate")
            if resting_hr:
                return float(resting_hr)

        # Check monitoring messages (less common in workout files)
        for msg in self.fit.get_messages("monitoring"):
            resting_hr = self._get_field_from_msg(msg, "resting_heart_rate")
            if resting_hr:
                return float(resting_hr)

        return None

    def _extract_ftp(self) -> Optional[float]:
        """Extract FTP (Functional Threshold Power) from FIT file if available."""
        if not self.fit:
            return None

        # Check user profile messages for FTP
        for msg in self.fit.get_messages("user_profile"):
            ftp = self._get_field_from_msg(msg, "functional_threshold_power")
            if ftp:
                return float(ftp)

        return None


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
