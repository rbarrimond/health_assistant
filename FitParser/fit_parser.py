"""Parse FIT files and extract workout metrics."""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import fitparse

logger = logging.getLogger(__name__)


class FitParser:
    """Parser for FIT format workout files."""

    def __init__(self, file_path: str):
        """Initialize FIT parser with file path."""
        self.file_path = file_path
        self.fit = None
        self.metrics = {}

    def parse(self) -> Dict:
        """
        Parse FIT file and extract workout metrics.
        
        Returns:
            Dict with parsed workout data
        """
        try:
            self.fit = fitparse.Activity(self.file_path)
        except Exception as e:
            logger.error("Error parsing FIT file %s: %s", self.file_path, e)
            raise

        self.metrics = {
            # Identity
            "sport": self._get_sport(),
            "sub_sport": self._get_sub_sport(),
            "workout_name": self._get_workout_name(),
            "device_name": self._get_device_name(),
            "is_indoor": self._get_is_indoor(),
            
            # Temporal
            "start_time_utc": self._get_start_time(),
            "end_time_utc": self._get_end_time(),
            "timezone": self._get_timezone(),
            "duration_sec": self._get_duration(),
            "moving_time_sec": self._get_moving_time(),
            
            # GPS
            "has_gps": self._has_gps_data(),
            "distance_m": self._get_distance(),
            
            # Elevation
            "elevation_gain_m": self._get_elevation_gain(),
            "elevation_loss_m": self._get_elevation_loss(),
            
            # Speed
            "avg_speed_mps": self._get_avg_speed(),
            "max_speed_mps": self._get_max_speed(),
            
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
            "calories_kcal": self._get_calories(),
        }

        # Compute zone metrics if data available
        if self.metrics.get("hr_avg_bpm"):
            self._compute_hr_zones()
        if self.metrics.get("pwr_avg_watts"):
            self._compute_power_zones()

        return self.metrics

    def _get_record_data(self, field_name: str) -> List:
        """Extract all values for a field from record messages."""
        values = []
        for record in self.fit.records:
            data = record.get(field_name)
            if data:
                values.append(data.value)
        return values

    def _get_sport(self) -> Optional[str]:
        """Get sport type from file messages."""
        for file_msg in self.fit.messages:
            if file_msg.name == "file_id":
                sport = file_msg.get("type")
                if sport:
                    return sport.value.name.lower()
        return None

    def _get_sub_sport(self) -> Optional[str]:
        """Get sub-sport type."""
        for session in self.fit.messages:
            if session.name == "session":
                sub_sport = session.get("sub_sport")
                if sub_sport:
                    return sub_sport.value.name.lower()
        return None

    def _get_workout_name(self) -> Optional[str]:
        """Get workout/session name if available."""
        for session in self.fit.messages:
            if session.name == "session":
                name = session.get("session_name")
                if name:
                    return name.value
        return None

    def _get_device_name(self) -> Optional[str]:
        """Get device/manufacturer info."""
        for file_msg in self.fit.messages:
            if file_msg.name == "file_id":
                manufacturer = file_msg.get("manufacturer")
                if manufacturer:
                    return manufacturer.value.name
        return None

    def _get_is_indoor(self) -> Optional[bool]:
        """Determine if workout is indoor."""
        for session in self.fit.messages:
            if session.name == "session":
                indoor = session.get("indoor")
                if indoor:
                    return indoor.value
        return None

    def _get_start_time(self) -> Optional[str]:
        """Get workout start time as ISO string."""
        for session in self.fit.messages:
            if session.name == "session":
                timestamp = session.get("start_time")
                if timestamp:
                    dt = timestamp.value
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
        """Get timezone info if available."""
        # FIT files don't typically include timezone, would need external mapping
        return None

    def _get_duration(self) -> Optional[int]:
        """Get total elapsed time in seconds."""
        for session in self.fit.messages:
            if session.name == "session":
                elapsed = session.get("total_elapsed_time")
                if elapsed:
                    return int(elapsed.value)
        return None

    def _get_moving_time(self) -> Optional[int]:
        """Get moving time if available (for cycling usually equals duration)."""
        for session in self.fit.messages:
            if session.name == "session":
                timer = session.get("total_timer_time")
                if timer:
                    return int(timer.value)
        return None

    def _has_gps_data(self) -> bool:
        """Check if GPS data (lat/lon) exists in records."""
        for record in self.fit.records:
            if record.get("position_lat") and record.get("position_long"):
                return True
        return False

    def _get_distance(self) -> Optional[float]:
        """Get total distance in meters."""
        for session in self.fit.messages:
            if session.name == "session":
                distance = session.get("total_distance")
                if distance:
                    return float(distance.value)
        return None

    def _get_elevation_gain(self) -> Optional[float]:
        """Get total elevation gain in meters."""
        for session in self.fit.messages:
            if session.name == "session":
                elev = session.get("total_ascent")
                if elev:
                    return float(elev.value)
        return None

    def _get_elevation_loss(self) -> Optional[float]:
        """Get total elevation loss in meters."""
        for session in self.fit.messages:
            if session.name == "session":
                elev = session.get("total_descent")
                if elev:
                    return float(elev.value)
        return None

    def _get_avg_speed(self) -> Optional[float]:
        """Get average speed in m/s."""
        for session in self.fit.messages:
            if session.name == "session":
                speed = session.get("avg_speed")
                if speed:
                    return float(speed.value)
        return None

    def _get_max_speed(self) -> Optional[float]:
        """Get max speed in m/s."""
        for session in self.fit.messages:
            if session.name == "session":
                speed = session.get("max_speed")
                if speed:
                    return float(speed.value)
        return None

    def _get_hr_avg(self) -> Optional[float]:
        """Get average heart rate."""
        hrs = self._get_record_data("heart_rate")
        return round(sum(hrs) / len(hrs), 1) if hrs else None

    def _get_hr_max(self) -> Optional[float]:
        """Get max heart rate."""
        hrs = self._get_record_data("heart_rate")
        return float(max(hrs)) if hrs else None

    def _get_hr_samples_count(self) -> int:
        """Get count of HR samples."""
        return len(self._get_record_data("heart_rate"))

    def _get_hr_missing_pct(self) -> Optional[float]:
        """Calculate percent of missing HR samples."""
        duration = self._get_duration()
        samples = self._get_hr_samples_count()
        if duration and samples:
            expected = duration  # Typically sampled once per second
            return round((1 - samples / expected) * 100, 1) if expected > 0 else 0.0
        return None

    def _get_power_avg(self) -> Optional[float]:
        """Get average power."""
        powers = self._get_record_data("power")
        return round(sum(powers) / len(powers), 1) if powers else None

    def _get_power_max(self) -> Optional[float]:
        """Get max power."""
        powers = self._get_record_data("power")
        return float(max(powers)) if powers else None

    def _get_power_normalized(self) -> Optional[float]:
        """Compute Normalized Power (simplified 30s rolling avg)."""
        powers = self._get_record_data("power")
        if not powers or len(powers) < 30:
            return None
        
        # Simplified: use 4th power mean
        np_sum = sum(p ** 4 for p in powers) / len(powers)
        return round(np_sum ** 0.25, 1) if np_sum > 0 else None

    def _get_power_vi(self) -> Optional[float]:
        """Calculate Variability Index (NP / AP)."""
        np = self._get_power_normalized()
        ap = self._get_power_avg()
        if np and ap and ap > 0:
            return round(np / ap, 2)
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
            return round((1 - samples / expected) * 100, 1) if expected > 0 else 0.0
        return None

    def _get_cadence_avg(self) -> Optional[float]:
        """Get average cadence."""
        cads = self._get_record_data("cadence")
        return round(sum(cads) / len(cads), 1) if cads else None

    def _get_cadence_max(self) -> Optional[float]:
        """Get max cadence."""
        cads = self._get_record_data("cadence")
        return float(max(cads)) if cads else None

    def _get_cadence_samples_count(self) -> int:
        """Get count of cadence samples."""
        return len(self._get_record_data("cadence"))

    def _get_calories(self) -> Optional[float]:
        """Get total calories."""
        for session in self.fit.messages:
            if session.name == "session":
                calories = session.get("total_calories")
                if calories:
                    return float(calories.value)
        return None

    def _compute_hr_zones(self, zone_basis: str = "HRmax", reference_bpm: Optional[float] = None, 
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

        # Determine reference heart rate
        if reference_bpm is None:
            if zone_basis == "HRmax":
                reference_bpm = self.metrics.get("hr_max_bpm")
            elif zone_basis == "LTHR":
                # LTHR typically ~85-95% of HRmax, default to 90%
                hr_max = self.metrics.get("hr_max_bpm")
                reference_bpm = hr_max * 0.90 if hr_max else None
            elif zone_basis == "HRR":
                reference_bpm = self.metrics.get("hr_max_bpm")
        
        if not reference_bpm:
            return

        # Define zone boundaries based on method
        if zone_basis == "HRmax":
            # Standard 5-zone model based on % of HRmax
            zones = {
                "hr_z1": (int(reference_bpm * 0.50), int(reference_bpm * 0.60)),
                "hr_z2": (int(reference_bpm * 0.60), int(reference_bpm * 0.70)),
                "hr_z3": (int(reference_bpm * 0.70), int(reference_bpm * 0.80)),
                "hr_z4": (int(reference_bpm * 0.80), int(reference_bpm * 0.90)),
                "hr_z5": (int(reference_bpm * 0.90), int(reference_bpm * 1.00)),
            }
        elif zone_basis == "LTHR":
            # Zones based on % of LTHR (common in cycling)
            # Z1: <81%, Z2: 81-89%, Z3: 90-93%, Z4: 94-99%, Z5: 100-102%, Z6: 103-106%, Z7: >106%
            # Simplified to 5 zones here
            zones = {
                "hr_z1": (int(reference_bpm * 0.65), int(reference_bpm * 0.81)),
                "hr_z2": (int(reference_bpm * 0.81), int(reference_bpm * 0.90)),
                "hr_z3": (int(reference_bpm * 0.90), int(reference_bpm * 0.94)),
                "hr_z4": (int(reference_bpm * 0.94), int(reference_bpm * 1.00)),
                "hr_z5": (int(reference_bpm * 1.00), int(reference_bpm * 1.06)),
            }
        elif zone_basis == "HRR":
            # Karvonen method: HR = (HRmax - HRrest) * intensity% + HRrest
            if hr_rest is None:
                hr_rest = 60  # Default resting HR
            hr_reserve = reference_bpm - hr_rest
            zones = {
                "hr_z1": (int(hr_reserve * 0.50 + hr_rest), int(hr_reserve * 0.60 + hr_rest)),
                "hr_z2": (int(hr_reserve * 0.60 + hr_rest), int(hr_reserve * 0.70 + hr_rest)),
                "hr_z3": (int(hr_reserve * 0.70 + hr_rest), int(hr_reserve * 0.80 + hr_rest)),
                "hr_z4": (int(hr_reserve * 0.80 + hr_rest), int(hr_reserve * 0.90 + hr_rest)),
                "hr_z5": (int(hr_reserve * 0.90 + hr_rest), int(hr_reserve * 1.00 + hr_rest)),
            }
        else:
            return

        # Calculate time in each zone and store boundaries
        total_sec = 0
        for i, (zone_name, (low, high)) in enumerate(zones.items(), 1):
            count = sum(1 for hr in hrs if low <= hr <= high)
            sec = count
            self.metrics[f"{zone_name}_sec"] = sec
            self.metrics[f"hr_z{i}_low_bpm"] = float(low)
            self.metrics[f"hr_z{i}_high_bpm"] = float(high)
            total_sec += sec

        self.metrics["hr_zone_total_sec"] = total_sec
        self.metrics["hr_z2_min"] = round(self.metrics.get("hr_z2_sec", 0) / 60, 1)
        self.metrics["hr_zone_model"] = "garmin_5"
        self.metrics["hr_zone_basis"] = zone_basis
        self.metrics["hr_zone_reference_bpm"] = float(reference_bpm)

    def _compute_power_zones(self):
        """Compute time in power zones (simplified 7-zone Coggan model)."""
        # Default FTP assumed at 250W (would be configurable per athlete)
        ftp = 250  # TODO: make configurable
        
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
        for zone_name, (low, high) in zones.items():
            count = sum(1 for p in powers if low <= p < high)
            sec = count
            self.metrics[f"{zone_name}_sec"] = sec
            total_sec += sec

        self.metrics["pwr_zone_total_sec"] = total_sec
        self.metrics["pwr_z2_min"] = round(self.metrics.get("pwr_z2_sec", 0) / 60, 1)
        low_aerobic = self.metrics.get("pwr_z1_sec", 0) + self.metrics.get("pwr_z2_sec", 0)
        intensity = sum(self.metrics.get(f"pwr_z{i}_sec", 0) for i in range(4, 8))
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
        raise ValueError("Must provide at least source_item_id, file_sha256, or file path info")
