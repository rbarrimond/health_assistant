"""Pydantic models for FIT file parsing and metadata extraction."""
# pylint: disable=too-many-lines, trailing-whitespace, line-too-long

import hashlib
import io
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, Literal, Optional, cast, overload
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import fitdecode
from fitdecode.cmd.fitjson import RecordJSONEncoder
from pydantic import BaseModel, computed_field, ConfigDict, Field

from .constants import LAPS_SCHEMA_VERSION, METADATA_SCHEMA_VERSION
from .apple_workout_types import (
    APPLE_WORKOUT_TYPES,
    AppleWorkoutTypeResolver,
    INDOOR_CYCLE,
    INDOOR_WALK,
    OUTDOOR_CYCLE,
    OUTDOOR_WALK,
)
from .fit_analyzer import FitStructureAnalyzer
from .code_mappings import (
    get_apple_product_name,
    get_garmin_product_name,
    get_favero_product_name,
    MANUFACTURER_CODES,
)
from .timezone_utils import (
    format_utc_offset,
    infer_timezone_from_activity,
    infer_timezone_from_session,
    resolve_timezone,
)

logger = logging.getLogger(__name__)

# Constants
ERROR_FILE_BYTES_REQUIRED = "file_bytes must be provided"
UTC_OFFSET_SUFFIX = "+00:00"


class BaseFitModel(BaseModel, ABC):
    """Base model for FIT file parsing with fitdecode integration.
    
    Encapsulates FIT file loading, message indexing, and metadata extraction
    using Pydantic computed fields. Subclasses handle source-specific quirks.
    """
    
    file_bytes: Optional[bytes] = None
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    @property
    def _metadata_dict(self) -> Dict[str, Any]:
        """Access source_metadata as properly-typed dict for type checkers."""
        # At runtime source_metadata is always a dict, but type checkers see FieldInfo
        return cast(Dict[str, Any], self.source_metadata)
    
    # Cached FIT messages (lazy-loaded)
    _messages: List[fitdecode.FitDataMessage] = []
    _messages_by_type: Dict[str, List[fitdecode.FitDataMessage]] = {}
    _rr_interval_by_second: Dict[int, float] = {}
    _file_id_msg: Optional[fitdecode.FitDataMessage] = None
    _session_msg: Optional[fitdecode.FitDataMessage] = None
    _messages_loaded: bool = False
    
    def __init__(self, **data: Any) -> None:
        """Initialize computed state after model creation."""
        super().__init__(**data)
        
        if self.file_bytes is None:
            raise ValueError(ERROR_FILE_BYTES_REQUIRED)
        
        # Initialize mutable default fields
        if not self._messages:
            object.__setattr__(self, '_messages', [])
        if not self._messages_by_type:
            object.__setattr__(self, '_messages_by_type', {})
        if not self._rr_interval_by_second:
            object.__setattr__(self, '_rr_interval_by_second', {})
    
    def _load_fit_messages(self) -> None:
        """Load FIT messages from in-memory bytes (lazy initialization)."""
        if self._messages_loaded:
            return
        
        stream = None
        
        try:
            if self.file_bytes is None:
                raise ValueError(ERROR_FILE_BYTES_REQUIRED)
            stream = io.BytesIO(self.file_bytes)
            
            messages: List[fitdecode.FitDataMessage] = []
            messages_by_type: Dict[str, List[fitdecode.FitDataMessage]] = {}
            
            try:
                with fitdecode.FitReader(
                    stream,
                    processor=fitdecode.DefaultDataProcessor(),
                ) as reader:
                    for frame in reader:
                        if not isinstance(frame, fitdecode.FitDataMessage):
                            continue
                        messages.append(frame)
                        messages_by_type.setdefault(frame.name, []).append(frame)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to parse FIT data: {exc}"
                ) from exc
            
            # Cache parsed messages
            self._messages = messages
            self._messages_by_type = messages_by_type
            self._cache_core_messages()
            self._messages_loaded = True
            
        finally:
            if stream:
                stream.close()
    
    def _cache_core_messages(self) -> None:
        """Cache frequently-accessed FIT messages."""
        self._file_id_msg = (self._messages_by_type.get("file_id") or [None])[0]
        self._session_msg = (self._messages_by_type.get("session") or [None])[0]
    
    def _ensure_message_index(self) -> None:
        """Ensure messages are loaded and indexed."""
        if not self._messages_loaded:
            self._load_fit_messages()
    
    def _ensure_rr_interval_index(self) -> None:
        """Build RR interval index for HRV data."""
        if self._rr_interval_by_second or not self._messages_loaded:
            return
        
        self._ensure_message_index()
        for timestamp_sec, rr_ms in self._iter_hrv_rr_entries():
            self._rr_interval_by_second[timestamp_sec] = rr_ms
    
    def _iter_hrv_rr_entries(self) -> Iterable[tuple[int, float]]:
        """Yield (timestamp_sec, rr_interval_ms) tuples from HRV messages."""
        for hrv_msg in self._messages_by_type.get("hrv", []):
            timestamp = hrv_msg.get_value("timestamp", fallback=None)
            if not isinstance(timestamp, datetime):
                continue
            
            timestamp_sec = int(timestamp.timestamp())
            
            # HRV messages can have multiple RR intervals
            for field in hrv_msg.fields:
                if field.name.startswith("time"):
                    rr_value = field.value
                    if isinstance(rr_value, (int, float)) and rr_value > 0:
                        yield timestamp_sec, float(rr_value)
    
    @staticmethod
    def _coerce_float(value: Any) -> Optional[float]:
        """Coerce value to float, return None if not numeric."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None
    
    @staticmethod
    def _get_record_value(
        record: fitdecode.FitDataMessage,
        *field_names: str,
    ) -> Optional[Any]:
        """Get first available field value from record."""
        for field_name in field_names:
            value = record.get_value(field_name, fallback=None)
            if value is not None:
                return value
        return None
    
    @property
    def messages(self) -> List[fitdecode.FitDataMessage]:
        """Public accessor for FIT messages."""
        self._ensure_message_index()
        return self._messages
    
    # ========================================================================
    # Computed Fields (Pydantic @computed_field replacing _get_* methods)
    # ========================================================================
    
    @computed_field  # type: ignore[misc]
    @property
    def file_id_msg(self) -> Optional[fitdecode.FitDataMessage]:
        """Cached file_id message."""
        self._ensure_message_index()
        return self._file_id_msg
    
    @computed_field  # type: ignore[misc]
    @property
    def session_msg(self) -> Optional[fitdecode.FitDataMessage]:
        """Cached session message."""
        self._ensure_message_index()
        return self._session_msg
    
    @computed_field  # type: ignore[misc]
    @property
    def sport(self) -> Optional[str]:
        """Get normalized sport value for semantic identity.

        Priority:
        1. Session message `sport`
        2. File ID message `type`
        """
        sport: Optional[Any] = None
        if self.session_msg is not None:
            sport = self.session_msg.get_value("sport", fallback=None)

        if sport is None and self.file_id_msg is not None:
            sport = self.file_id_msg.get_value("type", fallback=None)

        if sport is not None:
            if hasattr(sport, "name"):
                return str(cast(Any, sport).name).strip().lower()
            return str(sport).strip().lower()
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def sub_sport(self) -> Optional[str]:
        """Get sub-sport type."""
        if self.session_msg is None:
            return None
        
        sub_sport = self.session_msg.get_value("sub_sport", fallback=None)
        if sub_sport:
            if hasattr(sub_sport, "name"):
                return str(cast(Any, sub_sport).name).lower()
            return str(sub_sport).lower()
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def sport_name(self) -> Optional[str]:
        """Extract sport name from session or file_id message."""
        if self.session_msg:
            sport = self.session_msg.get_value("sport", fallback=None)
            if sport is not None:
                sport_name = getattr(sport, "name", None)
                if sport_name:
                    return str(sport_name)
                return str(sport)
        
        if self.file_id_msg:
            sport = self.file_id_msg.get_value("type", fallback=None)
            if sport is not None:
                sport_name = getattr(sport, "name", None)
                if sport_name:
                    return str(sport_name)
                return str(sport)
        
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def sub_sport_name(self) -> Optional[str]:
        """Extract subsport name from session message."""
        if self.session_msg:
            sub_sport = self.session_msg.get_value("sub_sport", fallback=None)
            if sub_sport is not None:
                subsport_name = getattr(sub_sport, "name", None)
                if subsport_name:
                    return str(subsport_name)
                return str(sub_sport)
        
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def activity_id(self) -> Optional[str]:
        """Extract activity ID from source metadata or filename."""
        # Check if filename is a pure number (Garmin activity ID pattern)
        source_file_name = self._metadata_dict.get("source_file_name")
        if source_file_name:
            file_name = Path(source_file_name).stem
            if file_name.isdigit():
                return file_name
        
        return None
    
    def _get_workout_message_name(self) -> Optional[str]:
        """Extract name field from Workout FIT message if available."""
        workout_messages = self._messages_by_type.get("workout", [])
        if not workout_messages:
            return None
        
        for workout_msg in workout_messages:
            for field_name in ("wkt_name", "name"):
                name_val = workout_msg.get_value(field_name, fallback=None)
                if name_val:
                    return str(name_val)
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def workout_name(self) -> Optional[str]:
        """Get workout name with priority-based lookup.
        
        Priority (in order of preference):
        1. Workout message name field (from FIT file if available)
        2. API source activity name (e.g., Garmin Connect API activityName)
        3. Subclass-specific lookup (e.g., HealthFit filename activity type)
        4. Constructed name from FIT metadata: {sport}-{subsport}-{activityID}
        
        This property ensures consistent naming priority across all source types.
        """
        # Priority 1: Workout message name field
        workout_msg_name = self._get_workout_message_name()
        if workout_msg_name:
            return workout_msg_name
        
        # Priority 2: API-sourced name
        source_activity_name = self._metadata_dict.get("source_activity_name")
        if source_activity_name:
            return source_activity_name
        
        # Priority 3: Subclass-specific lookup
        subclass_name = self._get_subclass_specific_workout_name()
        if subclass_name:
            return subclass_name
        
        # Priority 4: Constructed from FIT metadata
        return self.constructed_workout_name
    
    @computed_field  # type: ignore[misc]
    @property
    def constructed_workout_name(self) -> Optional[str]:
        """Construct fallback workout name from daypart/type or FIT semantics."""
        daypart = self._workout_daypart()
        apple_type = self._apple_workout_type_from_fit_signals()
        if daypart and apple_type:
            return f"{daypart} {apple_type}"

        fallback_datetime = self._fallback_datetime_label()
        parts = [
            part for part in (self.sport_name, self.sub_sport_name, fallback_datetime)
            if part
        ]
        if parts:
            return "-".join(str(part) for part in parts)
        return None

    def _apple_workout_type_from_fit_signals(self) -> Optional[str]:
        """Resolve Apple workout type from FIT sport/sub_sport only."""
        resolved = AppleWorkoutTypeResolver(
            sport=self.sport,
            sub_sport=self.sub_sport,
        ).resolve()
        if not resolved or resolved == "Other":
            return None
        return resolved

    def _parse_timezone_info(self) -> Optional[tzinfo]:
        """Return a tzinfo based on resolved timezone string when possible."""
        tz_name = self.timezone
        if not tz_name:
            return None

        if tz_name == "UTC":
            return timezone.utc

        match = re.match(r"^UTC([+-])(\d{2}):(\d{2})$", tz_name)
        if match:
            sign = 1 if match.group(1) == "+" else -1
            hours = int(match.group(2))
            minutes = int(match.group(3))
            offset = timedelta(hours=hours, minutes=minutes) * sign
            return timezone(offset)

        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            return None

    def _local_start_datetime(self) -> Optional[datetime]:
        """Compute workout local datetime from precise UTC start and timezone."""
        start = self.start_time_utc_precise
        if not start:
            return None

        try:
            start_dt = datetime.fromisoformat(start.replace("Z", UTC_OFFSET_SUFFIX))
        except ValueError:
            return None

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        tz_info = self._parse_timezone_info()
        if tz_info is None:
            return start_dt.astimezone(timezone.utc)
        return start_dt.astimezone(tz_info)

    def _workout_daypart(self) -> Optional[str]:
        """Return daypart label using local workout start time."""
        local_start = self._local_start_datetime()
        if local_start is None:
            return None

        hour = local_start.hour
        if 5 <= hour <= 11:
            return "Morning"
        if 12 <= hour <= 16:
            return "Afternoon"
        if 17 <= hour <= 20:
            return "Evening"
        return "Night"

    def _fallback_datetime_label(self) -> Optional[str]:
        """Return formatted local datetime string for fallback naming."""
        local_start = self._local_start_datetime()
        if local_start is None:
            return None
        return local_start.strftime("%Y-%m-%d %H:%M")
    
    @computed_field  # type: ignore[misc]
    @property
    def apple_workout_type(self) -> Optional[str]:
        """Get Apple Watch workout type using the resolver."""
        resolver = AppleWorkoutTypeResolver(
            sport=self.sport,
            sub_sport=self.sub_sport
        )
        return resolver.resolve()
    
    @computed_field  # type: ignore[misc]
    @property
    def is_indoor(self) -> Optional[bool]:
        """Infer indoor status from activity name."""
        workout_name = self.workout_name
        if not workout_name:
            return None
        
        indoor_keywords = {'zwift', 'peloton', 'indoor', 'trainer', 'stationary'}
        name_lower = workout_name.lower()
        
        for keyword in indoor_keywords:
            if keyword in name_lower:
                return True
        
        return False
    
    @computed_field  # type: ignore[misc]
    @property
    def start_time_utc(self) -> Optional[str]:
        """Get workout start time as ISO string."""
        if self.session_msg is None:
            return None
        
        timestamp = self.session_msg.get_value("start_time", fallback=None)
        if timestamp and isinstance(timestamp, datetime):
            dt = timestamp
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        return None

    @computed_field  # type: ignore[misc]
    @property
    def start_time_utc_precise(self) -> Optional[str]:
        """Get precise workout start time as ISO string.

        Priority:
        1. Event start timestamp
        2. Session start_time
        3. Source-specific UTC time (filename, API, etc.)
        4. First record timestamp
        """
        start_dt = self._start_time_from_event()
        if not start_dt:
            start_dt = self._start_time_from_session()
        if not start_dt:
            candidate = self._start_time_from_source_specific_utc()  # type: ignore[misc]
            if candidate:
                start_dt = candidate
        if not start_dt:
            start_dt = self._start_time_from_first_record()

        if not start_dt:
            return None

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        return start_dt.astimezone(timezone.utc).isoformat()

    @property
    def semantic_workout_id(self) -> Optional[str]:
        """Generate deterministic semantic workout ID from start time + sport.
        
        Used for deduplication across sources. Computed from the most precise
        start time available (from start_time_utc_precise) and normalized sport.
        
        Returns:
            SHA1 hex digest of "{start_time_utc_precise}#{normalized_sport}" or None
            if start_time or sport unavailable.
        """
        if not self.start_time_utc_precise or not self.sport:
            return None
        
        normalized_sport = str(self.sport).strip().lower()
        combined = f"{self.start_time_utc_precise}#{normalized_sport}"
        return hashlib.sha1(combined.encode()).hexdigest()

    def _start_time_from_event(self) -> Optional[datetime]:
        """Return earliest event start timestamp, if present."""
        self._ensure_message_index()
        event_messages = self._messages_by_type.get("event", [])
        candidates: List[datetime] = []

        for event_msg in event_messages:
            event_type = self._field_to_lower(
                event_msg.get_value("event_type", fallback=None)
            )
            if not event_type or not event_type.startswith("start"):
                continue

            timestamp = event_msg.get_value("timestamp", fallback=None)
            if isinstance(timestamp, datetime):
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                candidates.append(timestamp)

        if candidates:
            return min(candidates)
        return None

    def _start_time_from_session(self) -> Optional[datetime]:
        """Return session start time if available.

        Uses `start_time` first, then falls back to session `timestamp`.
        """
        if self.session_msg is None:
            return None

        timestamp = self.session_msg.get_value("start_time", fallback=None)
        if not isinstance(timestamp, datetime):
            timestamp = self.session_msg.get_value("timestamp", fallback=None)

        if isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return timestamp
        return None

    def _start_time_from_first_record(self) -> Optional[datetime]:
        """Return the first record timestamp if present."""
        self._ensure_message_index()
        for record in self._messages_by_type.get("record", []):
            timestamp = record.get_value("timestamp", fallback=None)
            if isinstance(timestamp, datetime):
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                return timestamp
        return None

    @abstractmethod
    def _start_time_from_source_specific_utc(self) -> Optional[datetime]:
        """Return source-specific UTC start time (e.g., from filename, API metadata).
        
        Subclasses implement source-specific logic to extract precise start times
        from non-FIT sources (e.g., HealthFit filename, Garmin API).
        
        Returns:
            UTC datetime or None if not available from this source.
        """
    
    @abstractmethod
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """Return subclass-specific workout name lookup (e.g., from filename).
        
        Subclasses implement source-specific logic to extract workout names
        from non-FIT sources (e.g., HealthFit filename activity type).
        
        Returns:
            Workout name string or None if not available from this source.
        """
        raise NotImplementedError

    @staticmethod
    def _field_to_lower(value: Optional[Any]) -> Optional[str]:
        """Normalize FIT enum fields to lowercase strings."""
        if value is None:
            return None

        name = getattr(value, "name", None)
        if name is not None:
            return str(name).lower()
        return str(value).lower()

    @staticmethod
    def _parse_utc_offset_minutes(value: Optional[str]) -> Optional[int]:
        """Parse UTC offset strings like 'UTC+02:00' into minutes."""
        if not value:
            return None

        normalized = value.strip().upper()
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
            hours_str, minutes_str = offset.split(":", 1)
        else:
            hours_str, minutes_str = offset, "0"

        try:
            hours = int(hours_str)
            minutes = int(minutes_str)
        except ValueError:
            return None

        return sign * (hours * 60 + minutes)
    
    @computed_field  # type: ignore[misc]
    @property
    def timezone(self) -> Optional[str]:
        """Get timezone from device settings or infer from times."""
        try:
            self._ensure_message_index()
            if not self._messages:
                return "UTC"
            
            offset_minutes = self.device_utc_offset_minutes
            inferred_activity = self.inferred_timezone_activity
            inferred_session = self.inferred_timezone_session
            
            return resolve_timezone(
                tz_name=None,
                offset_minutes=offset_minutes,
                inferred_activity=inferred_activity,
                inferred_session=inferred_session,
            )
        except (AttributeError, TypeError, ValueError):
            pass
        return "UTC"
    
    @computed_field  # type: ignore[misc]
    @property
    def device_utc_offset_minutes(self) -> Optional[int]:
        """Return device UTC offset in minutes from settings."""
        self._ensure_message_index()
        device_settings_msg = (
            self._messages_by_type.get("device_settings") or [None]
        )[0]
        if device_settings_msg:
            offset = device_settings_msg.get_value("utc_offset", fallback=None)
            if isinstance(offset, (int, float)):
                return int(round(offset / 60))
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def inferred_timezone_session(self) -> Optional[str]:
        """Infer timezone from session timestamp vs local start time."""
        if self.session_msg is None:
            return None
        
        start_time = self.session_msg.get_value("start_time", fallback=None)
        timestamp = self.session_msg.get_value("timestamp", fallback=None)
        duration = self.session_msg.get_value("total_elapsed_time", fallback=None)
        
        if not isinstance(start_time, datetime):
            start_time = None
        if not isinstance(timestamp, datetime):
            timestamp = None
        if not isinstance(duration, (int, float)):
            return None
        
        duration_sec = int(duration)
        return infer_timezone_from_session(start_time, timestamp, duration_sec)
    
    @computed_field  # type: ignore[misc]
    @property
    def inferred_timezone_activity(self) -> Optional[str]:
        """Infer timezone from activity local_time vs UTC timestamp."""
        self._ensure_message_index()
        activity_msg = (self._messages_by_type.get("activity") or [None])[0]
        if not activity_msg:
            return None
        
        local_time = activity_msg.get_value("local_timestamp", fallback=None)
        timestamp = activity_msg.get_value("timestamp", fallback=None)
        
        if not isinstance(local_time, datetime):
            local_time = None
        if not isinstance(timestamp, datetime):
            timestamp = None
        
        return infer_timezone_from_activity(local_time, timestamp)
    
    @computed_field  # type: ignore[misc]
    @property
    def duration_sec(self) -> Optional[int]:
        """Get total elapsed time in seconds."""
        if self.session_msg is None:
            return None
        
        elapsed = self.session_msg.get_value("total_elapsed_time", fallback=None)
        return int(elapsed) if isinstance(elapsed, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def moving_time_sec(self) -> Optional[int]:
        """Get moving time in seconds."""
        if self.session_msg is None:
            return None
        
        timer = self.session_msg.get_value("total_timer_time", fallback=None)
        return int(timer) if isinstance(timer, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def distance_m(self) -> Optional[float]:
        """Get total distance in meters."""
        if self.session_msg is None:
            return None
        
        distance = self.session_msg.get_value("total_distance", fallback=None)
        return float(distance) if isinstance(distance, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def elevation_gain_m(self) -> Optional[float]:
        """Get total elevation gain in meters."""
        if self.session_msg is None:
            return None
        
        elev = self.session_msg.get_value("total_ascent", fallback=None)
        return float(elev) if isinstance(elev, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def elevation_loss_m(self) -> Optional[float]:
        """Get total elevation loss in meters."""
        if self.session_msg is None:
            return None
        
        elev = self.session_msg.get_value("total_descent", fallback=None)
        return float(elev) if isinstance(elev, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def avg_speed_mps(self) -> Optional[float]:
        """Get average speed in m/s."""
        if self.session_msg is None:
            return None
        
        speed = self.session_msg.get_value("avg_speed", fallback=None)
        return float(speed) if isinstance(speed, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def max_speed_mps(self) -> Optional[float]:
        """Get max speed in m/s."""
        if self.session_msg is None:
            return None
        
        speed = self.session_msg.get_value("max_speed", fallback=None)
        return float(speed) if isinstance(speed, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def calories_kcal(self) -> Optional[float]:
        """Get total calories."""
        if self.session_msg is None:
            return None
        
        calories = self.session_msg.get_value("total_calories", fallback=None)
        return float(calories) if isinstance(calories, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def device_name(self) -> Optional[str]:
        """Get device/manufacturer and product info with validation."""
        if self.file_id_msg is None:
            return None
        
        manufacturer = self.file_id_msg.get_value("manufacturer", fallback=None)
        product = self.file_id_msg.get_value("product", fallback=None)
        
        parts: List[str] = []
        
        mfr_name = self._validate_and_get_manufacturer_name(manufacturer)
        if mfr_name:
            parts.append(mfr_name)
        
        prod_name = self._validate_and_get_product_name(product, manufacturer)
        if prod_name:
            parts.append(prod_name)
        
        self._validate_device_info_collisions(manufacturer, product)
        
        if parts:
            return " ".join(parts)
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def has_gps_data(self) -> bool:
        """Check if GPS data exists in records."""
        self._ensure_message_index()
        for record in self._messages_by_type.get("record", []):
            lat = record.get_value("position_lat", fallback=None)
            lon = record.get_value("position_long", fallback=None)
            if lat is not None and lon is not None:
                return True
        return False
    
    # ========================================================================
    # Device Validation Methods
    # ========================================================================
    
    @staticmethod
    def _extract_code_and_name(field: Optional[Any]) -> tuple[Optional[int], Optional[str]]:
        """Extract numeric code and enum name from a FIT field."""
        if field is None:
            return None, None
        if isinstance(field, int):
            return field, None
        
        code = None
        name = None
        
        if hasattr(field, "value"):
            code = field.value
        if hasattr(field, "name"):
            name = str(field.name)
        
        return code, name
    
    def _validate_and_get_manufacturer_name(
        self,
        manufacturer: Optional[Any],
    ) -> Optional[str]:
        """Validate manufacturer code and return name from code_mappings."""
        if manufacturer is None:
            return None
        
        manufacturer_code, manufacturer_name = self._extract_code_and_name(manufacturer)
        
        if manufacturer_code is None:
            return manufacturer_name or str(manufacturer)
        
        expected_name = MANUFACTURER_CODES.get(manufacturer_code)
        if expected_name and manufacturer_name:
            if expected_name.lower() != manufacturer_name.lower().replace("_", ""):
                logger.warning(
                    "Manufacturer code mismatch for code %d: "
                    "fitdecode says '%s', code_mappings says '%s'",
                    manufacturer_code,
                    manufacturer_name,
                    expected_name,
                )
        
        return expected_name if expected_name else str(manufacturer_code)
    
    def _validate_and_get_product_name(
        self,
        product: Optional[Any],
        manufacturer: Optional[Any],
    ) -> Optional[str]:
        """Validate product code and return name from code_mappings."""
        if product is None:
            return None
        
        product_code, product_name = self._extract_code_and_name(product)
        
        if product_code is None:
            return product_name or str(product)
        
        if manufacturer is None:
            return product_name or str(product_code)
        
        manufacturer_code, _ = self._extract_code_and_name(manufacturer)
        
        if manufacturer_code is None:
            return product_name or str(product_code)
        
        expected_product_name = None
        if manufacturer_code == 32:  # Apple
            expected_product_name = get_apple_product_name(product_code)
        elif manufacturer_code == 1:  # Garmin
            expected_product_name = get_garmin_product_name(product_code)
        elif manufacturer_code == 263:  # Favero Electronics
            expected_product_name = get_favero_product_name(product_code)
        
        if expected_product_name and product_name:
            if expected_product_name.lower() != product_name.lower().replace("_", ""):
                logger.warning(
                    "Product code mismatch for manufacturer %d, product code %d: "
                    "fitdecode says '%s', code_mappings says '%s'",
                    manufacturer_code,
                    product_code,
                    product_name,
                    expected_product_name,
                )
            return expected_product_name
        
        return product_name or str(product_code)
    
    def _validate_device_info_collisions(
        self,
        file_id_manufacturer: Optional[Any],
        file_id_product: Optional[Any],
    ) -> None:
        """Check device_info messages for collisions with file_id device."""
        if not self._messages or (
            file_id_manufacturer is None and file_id_product is None
        ):
            return
        
        self._ensure_message_index()
        
        file_id_mfr_code, _ = self._extract_code_and_name(file_id_manufacturer)
        file_id_prod_code, _ = self._extract_code_and_name(file_id_product)
        
        for device_info_msg in self._messages_by_type.get("device_info", []):
            device_mfr = device_info_msg.get_value("manufacturer", fallback=None)
            device_prod = device_info_msg.get_value("product", fallback=None)
            
            device_mfr_code, _ = self._extract_code_and_name(device_mfr)
            device_prod_code, _ = self._extract_code_and_name(device_prod)
            
            if (
                device_mfr_code is not None
                and file_id_mfr_code is not None
                and device_mfr_code == file_id_mfr_code
            ):
                self._log_product_collision(
                    file_id_mfr_code,
                    file_id_prod_code,
                    device_mfr_code,
                    device_prod_code,
                )
    
    def _log_product_collision(
        self,
        file_id_mfr_code: int,
        file_id_prod_code: Optional[int],
        device_mfr_code: int,
        device_prod_code: Optional[int],
    ) -> None:
        """Log product code collision between file_id and device_info."""
        if device_prod_code and file_id_prod_code:
            if device_prod_code == file_id_prod_code:
                logger.info(
                    "Device collision detected: file_id device (mfr=%d, prod=%d) "
                    "also appears in device_info message",
                    file_id_mfr_code,
                    file_id_prod_code,
                )
            else:
                logger.warning(
                    "Device manufacturer collision: file_id has product %d, "
                    "but device_info message has product %d "
                    "(same manufacturer %d)",
                    file_id_prod_code,
                    device_prod_code,
                    file_id_mfr_code,
                )
            return
        
        if not device_prod_code and file_id_prod_code:
            logger.warning(
                "Device collision: file_id (mfr=%d, prod=%d) has product code, "
                "but device_info message only has manufacturer (mfr=%d)",
                file_id_mfr_code,
                file_id_prod_code,
                device_mfr_code,
            )
            return
        
        if device_prod_code and not file_id_prod_code:
            logger.warning(
                "Device collision: device_info (mfr=%d, prod=%d) "
                "has product code, but file_id only has manufacturer (mfr=%d)",
                device_mfr_code,
                device_prod_code,
                file_id_mfr_code,
            )
    
    # ========================================================================
    # Canonical Format Builders
    # ========================================================================
    
    def build_canonical_records(self) -> List[Dict[str, Any]]:
        """Extract canonical substrate records for parquet storage."""
        self._ensure_message_index()
        
        start_dt = self._canonical_start_dt()
        
        records: List[Dict[str, Any]] = []
        for record in self._messages:
            if record.name != "record":
                continue
            payload = self._build_canonical_record(record, start_dt)
            if payload:
                records.append(payload)
        
        return records
    
    def _canonical_start_dt(self) -> Optional[datetime]:
        """Get start datetime for elapsed time calculations."""
        start_time = self.start_time_utc
        if not start_time:
            return None
        try:
            return datetime.fromisoformat(start_time.replace("Z", UTC_OFFSET_SUFFIX))
        except ValueError:
            return None
    
    @staticmethod
    def _normalize_record_timestamp(
        timestamp: Optional[datetime],
    ) -> Optional[datetime]:
        """Normalize record timestamp to UTC."""
        if isinstance(timestamp, datetime):
            return timestamp.astimezone(timezone.utc)
        return timestamp
    
    def _build_canonical_record(
        self,
        record: fitdecode.FitDataMessage,
        start_dt: Optional[datetime],
    ) -> Optional[Dict[str, Any]]:
        """Build canonical record from FIT record message."""
        raw_timestamp = record.get_value("timestamp", fallback=None)
        timestamp = self._normalize_record_timestamp(
            raw_timestamp if isinstance(raw_timestamp, datetime) else None
        )
        if not timestamp:
            return None
        
        timestamp_utc = timestamp.astimezone(timezone.utc).isoformat()
        elapsed_sec = None
        if start_dt is not None:
            elapsed_sec = (timestamp - start_dt).total_seconds()
        
        power = self._get_record_value(record, "power")
        heart_rate = self._get_record_value(record, "heart_rate")
        cadence = self._get_record_value(record, "cadence")
        speed = self._get_record_value(record, "speed")
        distance = record.get_value("distance", fallback=None)
        elevation = self._get_record_value(record, "altitude")
        temperature = self._get_record_value(record, "temperature")
        lr_balance = self._get_record_value(record, "left_right_balance")
        
        return {
            "timestamp_utc": timestamp_utc,
            "elapsed_sec": self._coerce_float(elapsed_sec),
            "power_watts": self._coerce_float(power),
            "heart_rate_bpm": self._coerce_float(heart_rate),
            "cadence_rpm": self._coerce_float(cadence),
            "speed_mps": self._coerce_float(speed),
            "distance_m": self._coerce_float(distance),
            "elevation_m": self._coerce_float(elevation),
            "temperature_c": self._coerce_float(temperature),
            "lr_balance_pct": self._coerce_float(lr_balance),
        }
    
    def build_canonical_metadata(self) -> Dict[str, Any]:
        """Extract canonical FIT metadata from session, file, and activity."""
        metadata: Dict[str, Any] = {}
        metadata.update(self._build_canonical_session_metadata())
        metadata.update(self._build_canonical_file_metadata())
        metadata.update(self._build_canonical_activity_metadata())
        
        return {k: v for k, v in metadata.items() if v is not None}
    
    def _build_canonical_session_metadata(self) -> Dict[str, Any]:
        """Build session-level metadata dictionary."""
        return {
            "sport": self.sport,
            "sub_sport": self.sub_sport,
            "apple_workout_type": self.apple_workout_type,
            "workout_name": self.workout_name,
            "is_indoor": self.is_indoor,
            "start_time_utc": self.start_time_utc,
            "start_time_utc_precise": self.start_time_utc_precise,
            "timezone": self.timezone,
            "duration_sec": self.duration_sec,
            "moving_time_sec": self.moving_time_sec,
            "distance_m": self.distance_m,
            "elevation_gain_m": self.elevation_gain_m,
            "elevation_loss_m": self.elevation_loss_m,
            "avg_speed_mps": self.avg_speed_mps,
            "max_speed_mps": self.max_speed_mps,
            "calories_kcal": self.calories_kcal,
            "device_name": self.device_name,
        }
    
    def _build_canonical_file_metadata(self) -> Dict[str, Any]:
        """Extract file-level metadata from file_id message."""
        metadata: Dict[str, Any] = {}
        if self.file_id_msg is None:
            return metadata
        
        file_created = self.file_id_msg.get_value("time_created", fallback=None)
        if isinstance(file_created, datetime) and file_created.tzinfo is None:
            file_created = file_created.replace(tzinfo=timezone.utc)
        if isinstance(file_created, datetime):
            metadata["file_time_created_utc"] = (
                file_created.astimezone(timezone.utc).isoformat()
            )
        
        file_manufacturer = self.file_id_msg.get_value("manufacturer", fallback=None)
        if file_manufacturer is not None:
            manufacturer_name = getattr(file_manufacturer, "name", None)
            metadata["file_manufacturer"] = (
                str(manufacturer_name)
                if manufacturer_name is not None
                else str(file_manufacturer)
            )
        
        file_product = self.file_id_msg.get_value("product", fallback=None)
        if file_product is not None:
            metadata["file_product"] = str(file_product)
        
        file_serial = self.file_id_msg.get_value("serial_number", fallback=None)
        if file_serial is not None:
            metadata["file_serial_number"] = str(file_serial)
        
        return metadata
    
    def _build_canonical_activity_metadata(self) -> Dict[str, Any]:
        """Extract activity-level metadata from activity message."""
        metadata: Dict[str, Any] = {}
        self._ensure_message_index()
        activity_msg = (self._messages_by_type.get("activity") or [None])[0]
        if not activity_msg:
            return metadata
        
        activity_timestamp = activity_msg.get_value("timestamp", fallback=None)
        if isinstance(activity_timestamp, datetime) and activity_timestamp.tzinfo is None:
            activity_timestamp = activity_timestamp.replace(tzinfo=timezone.utc)
        if isinstance(activity_timestamp, datetime):
            metadata["activity_timestamp_utc"] = (
                activity_timestamp.astimezone(timezone.utc).isoformat()
            )
        
        activity_local = activity_msg.get_value("local_timestamp", fallback=None)
        if isinstance(activity_local, datetime):
            metadata["activity_local_time"] = activity_local.isoformat()
        
        return metadata
    
    @overload
    def build_raw_fit(self) -> Dict[str, Any]:
        ...

    @overload
    def build_raw_fit(
        self,
        return_dict: Literal[True],
        return_json: Literal[False],
    ) -> Dict[str, Any]:
        ...

    @overload
    def build_raw_fit(
        self,
        return_dict: Literal[False],
        return_json: Literal[True],
    ) -> str:
        ...

    @overload
    def build_raw_fit(
        self,
        return_dict: Literal[True],
        return_json: Literal[True],
    ) -> tuple[str, Dict[str, Any]]:
        ...

    def build_raw_fit(
        self, return_dict: bool = True, return_json: bool = False
    ) -> Dict[str, Any] | str | tuple[str, Dict[str, Any]]:
        """Return full-fidelity FIT data as dict, JSON string, or both.
        
        Args:
            return_dict: Return dict with frames and metadata (default True)
            return_json: Return JSON-serialized string (default False)
        
        Returns:
            - return_dict=True, return_json=False: Dict with frames and metadata
            - return_dict=False, return_json=True: JSON string
            - return_dict=True, return_json=True: Tuple of (json_string, dict)
        """
        if not self.file_bytes:
            raise ValueError(ERROR_FILE_BYTES_REQUIRED)
        
        stream = io.BytesIO(self.file_bytes)
        
        frames = []
        with fitdecode.FitReader(
            stream,
            processor=fitdecode.StandardUnitsDataProcessor(),
            keep_raw_chunks=True
        ) as reader:
            for frame in reader:
                frames.append(frame)
        
        # Serialize with RecordJSONEncoder for full fidelity
        json_str = json.dumps(frames, cls=RecordJSONEncoder)
        frames_dict = json.loads(json_str)
        
        source_file_name = self._metadata_dict.get("source_file_name")
        metadata = {
            "source_file": source_file_name or "<in-memory>",
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "total_frames": len(frames),
        }
        
        result_dict = {
            "metadata": metadata,
            "frames": frames_dict,
        }
        
        if return_dict and return_json:
            return (json_str, result_dict)
        elif return_json:
            return json_str
        else:
            return result_dict
    
    def build_metadata_messages(self) -> Dict[str, Any]:
        """Return structured FIT metadata.json with LLM enrichment placeholder."""
        self._ensure_message_index()
        
        message_types = {
            "file_id",
            "file_creator",
            "device_info",
            "sport",
            "session",
            "activity",
            "event",
            "workout",
        }
        
        raw_fit_messages: Dict[str, Any] = {}
        for message_type in message_types:
            typed_messages = self._messages_by_type.get(message_type)
            if not typed_messages:
                continue
            
            # Use RecordJSONEncoder for consistency
            json_str = json.dumps(typed_messages, cls=RecordJSONEncoder)
            raw_fit_messages[message_type] = json.loads(json_str)
        
        llm_enrichment = {
            "status": "pending",
            "inferred_workout_name": None,
            "primary_activity": None,
            "confidence_score": None,
            "has_virtual_indicators": None,
            "device_classifier": None,
            "anomalies": [],
            "semantic_flags": {},
        }
        
        return {
            "metadata_schema_version": METADATA_SCHEMA_VERSION,
            "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
            "raw_fit_messages": raw_fit_messages,
            "llm_enrichment": llm_enrichment,
        }
    
    def build_laps_json(self) -> Dict[str, Any]:
        """Return lap messages JSON artifact with schema metadata."""
        self._ensure_message_index()
        
        lap_messages = self._messages_by_type.get("lap", [])
        
        # Use RecordJSONEncoder for consistency
        json_str = json.dumps(lap_messages, cls=RecordJSONEncoder)
        laps = json.loads(json_str)
        
        return {
            "schema_version": LAPS_SCHEMA_VERSION,
            "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
            "laps": laps,
        }

    def build_fit_analysis(self) -> Dict[str, Any]:
        """Return FIT structure analysis using FitStructureAnalyzer."""
        self._ensure_message_index()
        analyzer = FitStructureAnalyzer(messages=self._messages)
        return analyzer.analyze()


class OneDriveFitModel(BaseFitModel, ABC):
    """Abstract model for OneDrive-sourced FIT files.
    
    Handles OneDrive-specific file I/O and metadata extraction.
    Concrete subclasses implement app-specific logic (HealthFit, RunGap, etc.).
    """
    
    file_path: Optional[str] = None
    
    def __init__(self, **data: Any) -> None:
        """Load file_path into file_bytes before parent initialization."""
        # If file_path provided, load it into file_bytes upfront
        if data.get("file_path") and not data.get("file_bytes"):
            with open(data["file_path"], "rb") as f:
                data["file_bytes"] = f.read()
        
        super().__init__(**data)
    
    @computed_field  # type: ignore[misc]
    @property
    def source_file_name(self) -> Optional[str]:
        """Extract filename from source metadata."""
        return self._metadata_dict.get("source_file_name")


class HealthFitModel(OneDriveFitModel):
    """Concrete model for Apple Watch FIT files exported via HealthFit.
    
    Handles HealthFit-specific filename parsing, timezone inference from local time,
    and device source classification (true Apple Watch vs HealthKit synced).
    HealthFit uses pattern: YYYY-MM-DD-HHMMSS-{ActivityType}-{Source}.fit[.gz].
    Hyphens are field separators; Apple activity labels are expected as spaced
    tokens (e.g., "Indoor Cycling"), not hyphenated tokens.
    The YYYY-MM-DD-HHMMSS filename timestamp is device-local wall-clock time
    for the recording device, not UTC.
    """
    
    # HealthFit filename pattern: YYYY-MM-DD-HHMMSS-{ActivityType}-{Source}.fit[.gz]
    # ActivityType token excludes '-' because '-' is the field delimiter.
    # The YYYY-MM-DD-HHMMSS token is device-local recording time.
    HEALTHFIT_FILENAME_PATTERN: ClassVar[re.Pattern] = re.compile(
        r'^(\d{4}-\d{2}-\d{2})-(\d{6}|Nodata)-([^-]+)-(.+?)\.fit(\.gz)?$'
    )
    HEALTHFIT_APPLE_TYPE_ALIASES: ClassVar[Dict[str, str]] = {
        "indoor cycling": INDOOR_CYCLE,
        "outdoor cycling": OUTDOOR_CYCLE,
        "indoor walking": INDOOR_WALK,
        "outdoor walking": OUTDOOR_WALK,
    }
    
    @computed_field  # type: ignore[misc]
    @property
    def normalized_source_system(self) -> str:
        """Return normalized source system name."""
        return "HealthFit"

    @computed_field  # type: ignore[misc]
    @property
    def sport(self) -> Optional[str]:
        """Get normalized sport with HealthFit filename fallback.

        Priority:
        1. FIT-derived sport from base model
        2. HealthFit filename activity type
        """
        fit_sport = super().sport
        if fit_sport:
            return fit_sport

        if not self.filename_activity_type:
            return None

        normalized = re.sub(r"[^a-z0-9]+", "_", self.filename_activity_type.strip().lower())
        normalized = normalized.strip("_")
        return normalized or None
    
    @computed_field  # type: ignore[misc]
    @property
    def filename_components(self) -> Optional[Dict[str, str]]:
        """Parse HealthFit filename into components.

        The parsed ``date`` and ``time`` fields represent local time on the
        recording device.
        """
        if not self.source_file_name:
            return None
        
        match = self.HEALTHFIT_FILENAME_PATTERN.match(self.source_file_name)
        if not match:
            return None
        
        return {
            "date": match.group(1),           # YYYY-MM-DD (device-local)
            "time": match.group(2),           # HHMMSS or "Nodata" (device-local)
            "activity_type": match.group(3),  # e.g., "Indoor Cycling"
            "source_device": match.group(4),  # e.g., "Robert's Apple Watch 7"
            "is_gzipped": "true" if match.group(5) is not None else "false",
        }
    
    @computed_field  # type: ignore[misc]
    @property
    def filename_date(self) -> Optional[str]:
        """Extract device-local date from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["date"]
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def filename_time(self) -> Optional[str]:
        """Extract device-local time from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["time"]
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def filename_activity_type(self) -> Optional[str]:
        """Extract activity type from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["activity_type"]
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def filename_source_device(self) -> Optional[str]:
        """Extract source device from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["source_device"]
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def is_gzipped(self) -> bool:
        """Check if file is gzipped based on HealthFit filename."""
        if self.filename_components:
            return self.filename_components["is_gzipped"] == "true"
        return False
    
    @computed_field  # type: ignore[misc]
    @property
    def inferred_timezone_filename(self) -> Optional[str]:
        """Infer timezone from HealthFit filename local time vs FIT UTC time.
        
        Compares filename's device-local datetime (YYYY-MM-DD-HHMMSS) with session
        start_time_utc to calculate timezone offset as fallback when device_settings
        or activity local_timestamp fields are missing.
        """
        if not self.filename_date or not self.filename_time or self.filename_time == "Nodata":
            return None
        
        if not self.start_time_utc:
            return None
        
        try:
            # Parse device-local filename datetime
            local_dt_str = f"{self.filename_date} {self.filename_time}"
            local_dt = datetime.strptime(local_dt_str, "%Y-%m-%d %H%M%S")
            
            # Parse FIT UTC timestamp
            utc_dt = datetime.fromisoformat(self.start_time_utc.replace("Z", UTC_OFFSET_SUFFIX))
            utc_dt_naive = utc_dt.replace(tzinfo=None)
            
            # Calculate offset in minutes
            offset_delta = local_dt - utc_dt_naive
            offset_minutes = int(offset_delta.total_seconds() / 60)
            
            return format_utc_offset(offset_minutes)
        except (ValueError, AttributeError, ImportError):
            return None

    def _start_time_from_source_specific_utc(self) -> Optional[datetime]:
        """Return UTC start time derived from HealthFit filename.
        
        Converts filename device-local datetime (YYYY-MM-DD-HHMMSS) to UTC using
        inferred timezone offset for source-specific dedup key generation.
        """
        if not self.filename_date or not self.filename_time or self.filename_time == "Nodata":
            return None

        try:
            local_dt_str = f"{self.filename_date} {self.filename_time}"
            local_dt = datetime.strptime(local_dt_str, "%Y-%m-%d %H%M%S")
        except ValueError:
            return None

        offset_minutes = self.device_utc_offset_minutes
        if offset_minutes is None:
            for inferred in (self.inferred_timezone_activity, self.inferred_timezone_session):
                parsed = self._parse_utc_offset_minutes(inferred)
                if parsed is not None:
                    offset_minutes = parsed
                    break

        if offset_minutes is None:
            offset_minutes = 0

        utc_dt = local_dt - timedelta(minutes=offset_minutes)
        return utc_dt.replace(tzinfo=timezone.utc)
    
    @computed_field  # type: ignore[misc]
    @property
    def timezone(self) -> Optional[str]:
        """Override to add HealthFit filename-based timezone inference fallback.
        
        Priority order:
        1. Device UTC offset (from device_settings message)
        2. Activity local_timestamp vs UTC timestamp
        3. Session start_time vs timestamp
        4. HealthFit filename local time vs FIT UTC time (NEW fallback)
        5. Default to "UTC"
        """
        try:
            self._ensure_message_index()
            if not self._messages:
                return "UTC"
            
            offset_minutes = self.device_utc_offset_minutes
            inferred_activity = self.inferred_timezone_activity
            inferred_session = self.inferred_timezone_session
            inferred_filename = self.inferred_timezone_filename
            
            # Use base resolve_timezone with filename as additional fallback
            resolved = resolve_timezone(
                tz_name=None,
                offset_minutes=offset_minutes,
                inferred_activity=inferred_activity,
                inferred_session=inferred_session,
            )
            
            # If base resolution didn't find anything, use filename inference
            if resolved == "UTC" and inferred_filename:
                return inferred_filename
            
            return resolved
        except (AttributeError, TypeError, ValueError, ImportError):
            pass
        return "UTC"
    
    @computed_field  # type: ignore[misc]
    @property
    def is_healthkit_synced(self) -> bool:
        """Detect if workout was synced into HealthKit from another app.
        
        HealthFit exports synced workouts with device_name="iPhone" (sentinel value).
        Direct Apple Watch exports have device_name containing "Apple Watch" or "Watch".
        
        Returns:
            True if device is "iPhone" (synced via HealthKit)
            False if Apple Watch (true source workout)
            False if device_name missing/None (conservatively assume true source)
        """
        if self.device_name is None:
            return False
        
        device_lower = self.device_name.lower()
        return "iphone" in device_lower
    
    @computed_field  # type: ignore[misc]
    @property
    def is_apple_watch_source(self) -> bool:
        """Check if workout originated from Apple Watch (not synced via HealthKit).
        
        Returns:
            True if Apple Watch is the source
            False if HealthKit synced (iPhone sentinel)
        """
        return not self.is_healthkit_synced
    
    @computed_field  # type: ignore[misc]
    @property
    def device_source_type(self) -> str:
        """Classify device source for downstream filtering.
        
        Returns:
            "apple_watch" - Native Apple Watch export (true source)
            "healthkit_synced" - Synced from another app via HealthKit (iPhone sentinel)
            "unknown" - Device not detected or missing
        """
        if self.device_name is None:
            return "unknown"
        
        device_lower = self.device_name.lower()
        
        if "iphone" in device_lower:
            return "healthkit_synced"
        if "watch" in device_lower:
            return "apple_watch"
        
        return "unknown"
    
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """Return HealthFit filename activity type as workout name source."""
        return self.filename_activity_type

    @computed_field  # type: ignore[misc]
    @property
    def apple_workout_type(self) -> Optional[str]:
        """Resolve Apple workout type deterministically from HealthFit filename.

        HealthFit is the only source with explicit Apple workout type encoded in
        filename activity token (e.g., ``Indoor Cycling``). Resolution is done
        directly in `HealthFitModel` (source-owned semantics) with no fallback
        to generic resolver inference.
        """
        activity_type = self.filename_activity_type
        if not activity_type:
            return None

        normalized = activity_type.strip().lower()
        alias_mapped = self.HEALTHFIT_APPLE_TYPE_ALIASES.get(normalized)
        if alias_mapped:
            return alias_mapped

        for apple_type in APPLE_WORKOUT_TYPES:
            if apple_type != "Other" and apple_type.lower() == normalized:
                return apple_type

        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def workout_name(self) -> Optional[str]:
        """Override to prioritize HealthFit filename activity type."""
        # Priority 1: Workout message name
        workout_msg_name = self._get_workout_message_name()
        if workout_msg_name:
            return workout_msg_name
        
        # Priority 2: Source activity name
        source_activity_name = self._metadata_dict.get("source_activity_name")
        if source_activity_name:
            return source_activity_name
        
        # Priority 3: Filename activity type (HealthFit pattern)
        if self.filename_activity_type:
            return self.filename_activity_type
        
        # Priority 4: Constructed from FIT metadata
        return self.constructed_workout_name


class GarminFitModel(BaseFitModel):
    """Concrete model for Garmin Connect FIT files.
    
    Handles Garmin-specific metadata where API activity name takes precedence
    over FIT session name.
    """
    
    @computed_field  # type: ignore[misc]
    @property
    def normalized_source_system(self) -> str:
        """Return normalized source system name."""
        return "Garmin"
    
    def _start_time_from_source_specific_utc(self) -> Optional[datetime]:
        """No source-specific start time extraction for Garmin."""
        return None
    
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """Return Garmin API activity name if available."""
        return self._metadata_dict.get("source_activity_name")


class PayloadFitModel(BaseFitModel):
    """Concrete model for direct HTTP payload uploads.
    
    Accepts flexible source metadata with minimal validation.
    """
    
    def _start_time_from_source_specific_utc(self) -> Optional[datetime]:
        """No source-specific start time extraction for direct payloads."""
        return None
    
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """No subclass-specific lookup for payload uploads."""
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def normalized_source_system(self) -> str:
        """Return normalized source system name (default to HealthFit)."""
        return self._metadata_dict.get("source_system", "HealthFit")


def create_fit_model(
    source_metadata: Dict[str, Any],
    file_bytes: bytes,
) -> BaseFitModel:
    """Factory function to create appropriate FIT model based on source metadata.
    
    Args:
        source_metadata: Dict containing source-specific metadata fields
        file_bytes: In-memory FIT bytes (required)
    
    Returns:
        Appropriate concrete FIT model instance
    """
    # Garmin: has source_activity_name and typically numeric source_item_id
    source_activity_name = source_metadata.get("source_activity_name")
    source_item_id = source_metadata.get("source_item_id", "")
    
    if source_activity_name and str(source_item_id).isdigit():
        return GarminFitModel(
            file_bytes=file_bytes,
            source_metadata=source_metadata,
        )
    
    # OneDrive: has OneDrive-specific fields (source_etag, source_drive_id)
    if source_metadata.get("source_etag") or source_metadata.get("source_drive_id"):
        # Check manufacturer code to determine if it's Apple Watch
        # For now, default to HealthFitModel (can enhance later with device detection)
        return HealthFitModel(
            file_bytes=file_bytes,
            source_metadata=source_metadata,
        )
    
    # Default: payload upload or unknown source
    return PayloadFitModel(
        file_bytes=file_bytes,
        source_metadata=source_metadata,
    )
