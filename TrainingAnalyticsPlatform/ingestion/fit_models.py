"""FIT ingestion models that normalize device files into canonical workout data.

This module defines the abstract FIT parsing contract (`BaseFitModel`) and source-
specific implementations used by ingestion handlers. Models parse FIT bytes once,
cache message state, and expose computed workout semantics (timing, sport typing,
distance/effort metrics, timezone, and device identity) for downstream canonical
metadata and record generation.

Primary outputs:
- Canonical record sets for parquet/storage pipelines
- Canonical metadata dictionaries used across ingestion and analytics
- Deterministic semantic identifiers for cross-source deduplication

Public interface:
- Factory: create_fit_model(source_metadata, file_bytes)
- Core model API: messages, semantic_workout_id, validate_semantic_contract,
  build_canonical_records, build_canonical_metadata, build_metadata_messages,
  build_laps_json, build_fit_analysis, raw_frames
- Concrete model types: HealthFitModel, GarminFitModel, PayloadFitModel
"""
# pylint: disable=too-many-lines, trailing-whitespace, line-too-long

import hashlib
import io
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone, tzinfo
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Optional, cast, overload
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fitdecode import (DefaultDataProcessor, FitDataMessage, FitReader,
                       StandardUnitsDataProcessor)
from fitdecode.cmd.fitjson import RecordJSONEncoder
from pydantic import BaseModel, ConfigDict, PrivateAttr, computed_field

from TrainingAnalyticsPlatform.models import CanonicalRecordSet
from TrainingAnalyticsPlatform.platform.exceptions import FitParsingError

from .apple_workout_types import (APPLE_WORKOUT_TYPES, INDOOR_CYCLE,
                                  INDOOR_WALK, OUTDOOR_CYCLE, OUTDOOR_WALK,
                                  AppleWorkoutTypeResolver)
from .code_mappings import (MANUFACTURER_CODES, MANUFACTURER_NAME_TO_CODE,
                            get_apple_product_name, get_favero_product_name,
                            get_garmin_product_name)
from .constants import LAPS_SCHEMA_VERSION, METADATA_SCHEMA_VERSION
from .fit_analyzer import FitStructureAnalyzer
from .timezone_utils import (format_utc_offset, infer_timezone_from_activity,
                             infer_timezone_from_session, resolve_timezone)

logger = logging.getLogger(__name__)

# Constants
ERROR_FILE_BYTES_REQUIRED = "file_bytes must be provided"
UTC_OFFSET_SUFFIX = "+00:00"


class BaseFitModel(BaseModel, ABC):
    """Abstract FIT parser that exposes canonical workout semantics.

    Contract:
        - Parses FIT bytes exactly once during initialization.
        - Exposes normalized computed fields for metadata and record generation.
        - Raises FitParsingError for invalid payloads or semantic-contract violations.
        - Requires subclasses to implement source-specific workout type and timezone hooks.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    _source_metadata: Dict[str, Any] = PrivateAttr(default_factory=dict)

    # Cached FIT data (initialized during model construction)
    _all_frames: List[Any] = PrivateAttr(default_factory=list)  # All frames for raw export
    _data_messages: List[FitDataMessage] = PrivateAttr(default_factory=list)  # Filtered FitDataMessage instances for semantic extraction
    _data_messages_by_type: Dict[str, List[FitDataMessage]] = PrivateAttr(default_factory=dict)
    _file_id_msg: Optional[FitDataMessage] = PrivateAttr(default=None)
    _session_msg: Optional[FitDataMessage] = PrivateAttr(default=None)
    _activity_msg: Optional[FitDataMessage] = PrivateAttr(default=None)
    
    def __init__(
        self,
        *,
        file_bytes: bytes,
        source_metadata: Optional[Dict[str, Any]] = None,
        **data: Any,
    ) -> None:
        """Initialize and parse a FIT payload into cached message state.

        Args:
            file_bytes: Raw FIT file bytes.
            source_metadata: Optional source context used by subclass-specific fallbacks.
            **data: Additional Pydantic initialization fields.

        Raises:
            FitParsingError: If `file_bytes` is empty or FIT parsing fails.
        """
        super().__init__(**data)

        self._source_metadata = cast(
            Dict[str, Any],
            source_metadata if isinstance(source_metadata, dict) else {},
        )
        if isinstance(file_bytes, bytearray):
            file_bytes = bytes(file_bytes)
        if not file_bytes:
            raise FitParsingError(ERROR_FILE_BYTES_REQUIRED)
        
        # Single parse with local buffer (garbage-collected after parse)
        all_frames, data_messages, messages_by_type = self._parse_fit_messages(file_bytes)
        self._all_frames = all_frames
        self._data_messages = data_messages
        self._data_messages_by_type = messages_by_type
        self._cache_core_messages()

    def _parse_fit_messages(
        self,
        file_bytes: bytes,
    ) -> tuple[List[Any], List[FitDataMessage], Dict[str, List[FitDataMessage]]]:
        """Parse FIT once: cache all frames for raw export + message indexes for semantics.
        
        Args:
            file_bytes: FIT file bytes (constructor-local, collectible after parse)
        
        Returns:
            Tuple of (all_frames, data_messages, messages_by_type) where:
            - all_frames: All frames for raw FIT export (with StandardUnitsDataProcessor)
            - data_messages: Filtered FitDataMessage instances for semantic extraction
            - messages_by_type: Message index for fast lookups
        """
        stream = io.BytesIO(file_bytes)
        try:
            all_frames: List[Any] = []
            data_messages: List[FitDataMessage] = []
            messages_by_type: Dict[str, List[FitDataMessage]] = {}

            try:
                with FitReader(
                    stream,
                    processor=StandardUnitsDataProcessor(),
                    keep_raw_chunks=True
                ) as reader:
                    for frame in reader:
                        all_frames.append(frame)
                        if isinstance(frame, FitDataMessage):
                            data_messages.append(frame)
                            messages_by_type.setdefault(frame.name, []).append(frame)
            except Exception as exc:
                raise FitParsingError(f"Failed to parse FIT data: {exc}") from exc

            return all_frames, data_messages, messages_by_type
        finally:
            stream.close()
    
    def _cache_core_messages(self) -> None:
        """Cache frequently-accessed FIT messages."""
        self._file_id_msg = (self._data_messages_by_type.get("file_id") or [None])[0]
        self._session_msg = (self._data_messages_by_type.get("session") or [None])[0]
        self._activity_msg = (self._data_messages_by_type.get("activity") or [None])[0]
        
    @property
    def messages(self) -> List[FitDataMessage]:
        """Public accessor for FIT data messages (FitDataMessage instances for semantic extraction)."""
        return self._data_messages
    
    # ========================================================================
    # Computed Fields (Pydantic @computed_field replacing _get_* methods)
    # ========================================================================
    
    # NOTE: file_id_msg and session_msg are accessed directly via
    # PrivateAttr (_file_id_msg, _session_msg) for internal use only.
    # They are not part of the computed field contract.
    
    @computed_field  # type: ignore[misc]
    @property
    def sport(self) -> Optional[str]:
        """Get normalized sport value for semantic identity.

        Priority:
        1. Sport message 'sport' field
        2. Session message 'sport' field
        """
        sport: Optional[Any] = None

        sport_message = (self._data_messages_by_type.get("sport") or [None])[0]
        if sport_message:
            sport = sport_message.get_value("sport", fallback=None)

        if sport is None and self._session_msg is not None:
            sport = self._session_msg.get_value("sport", fallback=None)

        if sport is not None:
            if hasattr(sport, "name"):
                return str(cast(Any, sport).name).strip().lower()
            return str(sport).strip().lower()
        raise FitParsingError(
            "Missing required FIT sport value in sport/session messages"
        )
    
    @computed_field  # type: ignore[misc]
    @property
    def sub_sport(self) -> Optional[str]:
        """Get normalized subsport value for semantic identity.

        Priority:
        1. Sport message 'sub_sport' field
        2. Session message 'sub_sport' field
        """
        sub_sport: Optional[Any] = None
        sport_message = (self._data_messages_by_type.get("sport") or [None])[0]

        if sport_message:
            sub_sport = sport_message.get_value("sub_sport", fallback=None)

        if sub_sport is None and self._session_msg is not None:
            sub_sport = self._session_msg.get_value("sub_sport", fallback=None)
        
        if sub_sport:
            if hasattr(sub_sport, "name"):
                return str(cast(Any, sub_sport).name).lower()
            return str(sub_sport).lower()
        return None
    
    def _get_workout_message_name(self) -> Optional[str]:
        """Extract name field from Workout FIT message if available."""
        workout_messages = self._data_messages_by_type.get("workout", [])
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
        4. Constructed name from FIT metadata: {sport}-{subsport}-{local_datetime}
        
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
        return self._constructed_workout_name()
    
    def _constructed_workout_name(self) -> Optional[str]:
        """Construct fallback workout name from daypart/type or FIT semantics."""
        daypart = self._workout_daypart()
        apple_type = self._apple_workout_type_from_fit_signals()
        if daypart and apple_type:
            return f"{daypart} {apple_type}"

        fallback_datetime = self._fallback_datetime_label()
        parts = [
            part for part in (self.sport, self.sub_sport, fallback_datetime)
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
        """Compute workout local datetime from canonical UTC start and timezone."""
        start = self.start_time_utc
        if not start:
            return None

        try:
            start_dt = datetime.fromisoformat(start.replace("Z", UTC_OFFSET_SUFFIX))
        except ValueError:
            return None

        tz_info = self._parse_timezone_info()
        if tz_info is None:
            if start_dt.tzinfo is None:
                return start_dt
            return start_dt.astimezone(timezone.utc)
        if start_dt.tzinfo is None:
            return start_dt
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
        """Get Apple Watch workout type using model-specific resolution hierarchy.

        Resolution order:
        1. Source-specific metadata (_source_specific_apple_workout_type)
           - HealthFitModel: Filename activity token (authoritative for HealthFit)
           - Others: None (defer to FIT signals)
        2. If source-specific returns None AND fallback is enabled:
           - Resolve from FIT sport/sub_sport via AppleWorkoutTypeResolver
        3. If source-specific returns None AND fallback is disabled:
           - Return None (no inference)

        This design allows models to override the default FIT-based resolution.
        For example, HealthFitModel uses only filename activity types and never
        falls back to FIT signals (even if sport/sub_sport messages are present).
        """
        source_specific = self._source_specific_apple_workout_type()
        if source_specific is not None:
            return source_specific
        if not self._allow_fit_apple_workout_fallback():
            return None
        resolver = AppleWorkoutTypeResolver(
            sport=self.sport,
            sub_sport=self.sub_sport,
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
        """Get canonical workout start time as ISO string in UTC.

        Priority:
        1. Event start timestamp
        2. Session start_time (with session timestamp fallback)
        3. First record timestamp
        """
        start_dt = self._start_time_from_event()
        if not start_dt:
            start_dt = self._start_time_from_session()
        if not start_dt and self._session_msg is None:
            start_dt = self._start_time_from_first_record()

        if not start_dt:
            return None

        return self._format_utc_timestamp(start_dt)

    @property
    def semantic_workout_id(self) -> Optional[str]:
        """Return a deterministic content-based ID for cross-source deduplication.

        The ID is a SHA1 hash of `start_time_utc` and normalized `sport`, so it is
        stable across re-parses and independent of source-specific metadata.

        Returns:
            40-character SHA1 hex digest, or None when `start_time_utc` is unavailable.

        Raises:
            FitParsingError: If a start time exists but sport cannot be derived.
        """
        normalized_sport = self.sport
        start_time = self.start_time_utc
        if not start_time:
            return None

        if normalized_sport is None:
            raise FitParsingError(
                "Missing required FIT sport value in sport/session messages"
            )

        normalized_sport = str(normalized_sport).strip().lower()
        combined = f"{start_time}#{normalized_sport}"
        return hashlib.sha1(combined.encode()).hexdigest()

    def _start_time_from_event(self) -> Optional[datetime]:
        """Return earliest event start timestamp, if present."""
        event_messages = self._data_messages_by_type.get("event", [])
        candidates: List[datetime] = []

        for event_msg in event_messages:
            event_type = self._field_to_lower(
                event_msg.get_value("event_type", fallback=None)
            )
            if not event_type or not event_type.startswith("start"):
                continue

            timestamp = event_msg.get_value("timestamp", fallback=None)
            if isinstance(timestamp, datetime):
                candidates.append(timestamp)

        if candidates:
            return min(candidates)
        return None

    def _start_time_from_session(self) -> Optional[datetime]:
        """Return session-derived UTC start using FIT UTC timestamp and elapsed time.

        Session `start_time` is local wall-clock context and is not used to
        derive canonical UTC start. Canonical session start is computed as:
            session.timestamp - total_elapsed_time
        """
        if self._session_msg is None:
            return None

        timestamp = self._session_msg.get_value("timestamp", fallback=None)
        duration = self._session_msg.get_value("total_elapsed_time", fallback=None)

        if not isinstance(timestamp, datetime):
            return None
        if not isinstance(duration, (int, float)):
            return None

        start_time = timestamp - timedelta(seconds=float(duration))
        return start_time

    def _start_time_from_first_record(self) -> Optional[datetime]:
        """Return the first record timestamp if present."""
        for record in self._data_messages_by_type.get("record", []):
            timestamp = record.get_value("timestamp", fallback=None)
            if isinstance(timestamp, datetime):
                return timestamp
        return None

    @abstractmethod
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """Return subclass-specific workout name lookup (e.g., from filename).
        
        Subclasses implement source-specific logic to extract workout names
        from non-FIT sources (e.g., HealthFit filename activity type).
        
        Returns:
            Workout name string or None if not available from this source.
        """
        raise NotImplementedError

    @abstractmethod
    def _source_specific_apple_workout_type(self) -> Optional[str]:
        """Return source-specific Apple workout type when explicitly encoded in metadata.

        This method is called first and has priority over FIT signal resolution.
        Subclasses can override to extract workout type from source-specific fields
        (e.g., HealthFit filename activity token).

        Returns None if workout type cannot be determined from source metadata.
        When None is returned, resolution falls back to FIT signals based on
        _allow_fit_apple_workout_fallback() setting.
        """
        raise NotImplementedError

    def _allow_fit_apple_workout_fallback(self) -> bool:
        """Return True if FIT sport/sub_sport can be used for Apple workout type fallback.

        Controls behavior when _source_specific_apple_workout_type() returns None:
        - True: Attempt to resolve apple_workout_type from FIT sport/sub_sport
        - False: Return None (no FIT-based fallback)

        Subclasses can override to disable FIT-based inference when the source has
        authoritative metadata (e.g., HealthFitModel uses filename activity type
        exclusively and does not fall back to FIT signals).
        """
        return True

    @abstractmethod
    def _source_specific_timezone_fallback(self) -> Optional[str]:
        """Return source-specific timezone offset fallback when available."""
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
    def _format_utc_timestamp(value: datetime) -> str:
        """Return UTC timestamp with explicit offset in ISO 8601 format."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()

    def _get_file_id_product(self) -> Optional[Any]:
        """Return normalized file_id product value, preferring garmin_product when required."""
        if self._file_id_msg is None:
            return None

        manufacturer = self._file_id_msg.get_value("manufacturer", fallback=None)
        product = self._file_id_msg.get_value("product", fallback=None)
        garmin_product = self._file_id_msg.get_value("garmin_product", fallback=None)

        manufacturer_code, _ = self._extract_code_and_name(manufacturer)
        if manufacturer_code == 1 and garmin_product is not None:
            return garmin_product
        return product

    def validate_semantic_contract(self) -> None:
        """Validate required FIT invariants before semantic extraction.

        Enforces file structure (`file_id`, `session`, `record`), activity type,
        timestamp consistency, and derivation of required semantic fields.

        Raises:
            FitParsingError: If any required FIT invariant is violated.
        """
        file_id_messages = self._data_messages_by_type.get("file_id", [])
        if len(file_id_messages) != 1:
            raise FitParsingError(
                "FIT semantic contract violation: expected exactly one file_id message"
            )

        file_id_type = self._field_to_lower(
            file_id_messages[0].get_value("type", fallback=None)
        )
        if file_id_type != "activity":
            raise FitParsingError(
                "FIT semantic contract violation: file_id.type must be activity"
            )

        session_messages = self._data_messages_by_type.get("session", [])
        if not session_messages:
            raise FitParsingError(
                "FIT semantic contract violation: missing required session message"
            )

        record_messages = self._data_messages_by_type.get("record", [])
        if not record_messages:
            raise FitParsingError(
                "FIT semantic contract violation: missing required record message"
            )

        self._validate_session_messages(session_messages)
        self._validate_record_timestamps(record_messages)
        self._validate_activity_summary(session_messages)

        # Enforce sport classification from FIT messages only.
        _ = self.sport

        if not self.start_time_utc:
            raise FitParsingError(
                "FIT semantic contract violation: unable to derive FIT-based UTC start timestamp"
            )

    def _validate_session_messages(self, session_messages: List[FitDataMessage]) -> None:
        """Validate required session fields and numeric constraints.

        Args:
            session_messages: Parsed `session` messages from the FIT file.

        Raises:
            FitParsingError: If required fields are missing, invalid, or negative.
        """
        for session in session_messages:
            session_timestamp = session.get_value("timestamp", fallback=None)
            if not isinstance(session_timestamp, datetime):
                raise FitParsingError(
                    "FIT semantic contract violation: session.timestamp is required"
                )

            total_elapsed_time = session.get_value("total_elapsed_time", fallback=None)
            if not isinstance(total_elapsed_time, (int, float)):
                raise FitParsingError(
                    "FIT semantic contract violation: session.total_elapsed_time is required"
                )
            if float(total_elapsed_time) < 0:
                raise FitParsingError(
                    "FIT semantic contract violation: session.total_elapsed_time must be non-negative"
                )

            total_timer_time = session.get_value("total_timer_time", fallback=None)
            if not isinstance(total_timer_time, (int, float)):
                raise FitParsingError(
                    "FIT semantic contract violation: session.total_timer_time is required"
                )

    def _validate_record_timestamps(self, record_messages: List[FitDataMessage]) -> None:
        """Validate record timestamps for presence and non-decreasing order.

        Args:
            record_messages: Parsed `record` messages from the FIT file.

        Raises:
            FitParsingError: If timestamps are missing, out of order, or incomparable.
        """
        previous_ts: Optional[datetime] = None
        for record in record_messages:
            timestamp = record.get_value("timestamp", fallback=None)
            if not isinstance(timestamp, datetime):
                raise FitParsingError(
                    "FIT semantic contract violation: record.timestamp is required"
                )

            if previous_ts is not None:
                try:
                    is_out_of_order = timestamp < previous_ts
                except TypeError as exc:
                    raise FitParsingError(
                        "FIT semantic contract violation: record timestamps must use consistent timezone awareness"
                    ) from exc
                if is_out_of_order:
                    raise FitParsingError(
                        "FIT semantic contract violation: record timestamps must be non-decreasing"
                    )

            previous_ts = timestamp

    def _validate_activity_summary(self, session_messages: List[FitDataMessage]) -> None:
        """Validate optional activity summary against parsed sessions.

        Args:
            session_messages: Parsed `session` messages used as canonical totals.

        Raises:
            FitParsingError: If activity/session counts or timer totals are inconsistent.
        """
        activity_messages = self._data_messages_by_type.get("activity", [])
        if not activity_messages:
            return

        activity_message = activity_messages[0]
        num_sessions = activity_message.get_value("num_sessions", fallback=None)
        if isinstance(num_sessions, (int, float)):
            if int(num_sessions) != len(session_messages):
                raise FitParsingError(
                    "FIT semantic contract violation: activity.num_sessions does not match parsed session count"
                )

        activity_total_timer = activity_message.get_value(
            "total_timer_time", fallback=None
        )
        if isinstance(activity_total_timer, (int, float)):
            session_total_timer = 0.0
            for session in session_messages:
                session_timer = session.get_value("total_timer_time", fallback=None)
                if not isinstance(session_timer, (int, float)):
                    return
                session_total_timer += float(session_timer)

            if abs(float(activity_total_timer) - session_total_timer) > 2.0:
                raise FitParsingError(
                    "FIT semantic contract violation: activity.total_timer_time does not approximately match session totals"
                )

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
    def local_tz_offset(self) -> Optional[str]:
        """Return the best-available local timezone offset.

        Prefers explicit device settings, then inferred offsets from activity/session
        timestamps, then a source-specific fallback.

        Returns:
            IANA timezone name or `UTC±HH:MM` offset string, or None.
        """
        try:
            offset_minutes = self._device_utc_offset_minutes()
            inferred_activity = self._inferred_timezone_activity()
            inferred_session = self._inferred_timezone_session()
            source_fallback = self._source_specific_timezone_fallback()
            
            resolved = resolve_timezone(
                tz_name=None,
                offset_minutes=offset_minutes,
                inferred_activity=inferred_activity,
                inferred_session=inferred_session,
            )
            if resolved is None and source_fallback:
                return source_fallback
            return resolved
        except (AttributeError, TypeError, ValueError):
            pass
        return None

    @computed_field  # type: ignore[misc]
    @property
    def timezone(self) -> Optional[str]:
        """Return canonical timezone identifier for the workout.

        Uses validated IANA names from source metadata when available; otherwise
        falls back to `local_tz_offset`.

        Returns:
            IANA timezone name, `UTC±HH:MM` offset string, or None.
        """
        for key in ("timezone", "source_timezone", "tz_name"):
            raw_value = self._metadata_dict.get(key)
            if not isinstance(raw_value, str):
                continue

            candidate = raw_value.strip()
            if not candidate:
                continue

            normalized = candidate.upper()
            if normalized == "UTC" or normalized.startswith("UTC+") or normalized.startswith("UTC-"):
                break

            try:
                ZoneInfo(candidate)
                return candidate
            except ZoneInfoNotFoundError:
                break

        return self.local_tz_offset
    
    def _device_utc_offset_minutes(self) -> Optional[int]:
        """Return device-configured UTC offset (minutes) from `device_settings`.

        Returns:
            Signed offset minutes, or None when unavailable.
        """
        device_settings_msg = (
            self._data_messages_by_type.get("device_settings") or [None]
        )[0]
        if device_settings_msg:
            offset = device_settings_msg.get_value("utc_offset", fallback=None)
            if isinstance(offset, (int, float)):
                return int(round(offset / 60))
        return None
    
    def _inferred_timezone_session(self) -> Optional[str]:
        """Infer timezone from session timing fields.

        Returns:
            Inferred IANA timezone name or `UTC±HH:MM` string, or None.
        """
        if self._session_msg is None:
            return None
        
        start_time = self._session_msg.get_value("start_time", fallback=None)
        timestamp = self._session_msg.get_value("timestamp", fallback=None)
        duration = self._session_msg.get_value("total_elapsed_time", fallback=None)
        
        if not isinstance(start_time, datetime):
            start_time = None
        if not isinstance(timestamp, datetime):
            timestamp = None
        if not isinstance(duration, (int, float)):
            return None
        
        duration_sec = int(duration)
        return infer_timezone_from_session(start_time, timestamp, duration_sec)
    
    def _inferred_timezone_activity(self) -> Optional[str]:
        """Infer timezone from activity timestamps.

        Returns:
            Inferred IANA timezone name or `UTC±HH:MM` string, or None.
        """
        activity_msg = (self._data_messages_by_type.get("activity") or [None])[0]
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
        if self._session_msg is None:
            return None
        
        elapsed = self._session_msg.get_value("total_elapsed_time", fallback=None)
        return int(elapsed) if isinstance(elapsed, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def moving_time_sec(self) -> Optional[int]:
        """Get moving time in seconds."""
        if self._session_msg is None:
            return None
        
        timer = self._session_msg.get_value("total_timer_time", fallback=None)
        return int(timer) if isinstance(timer, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def distance_m(self) -> Optional[float]:
        """Get total distance in meters."""
        if self._session_msg is None:
            return None
        
        distance = self._session_msg.get_value("total_distance", fallback=None)
        return float(distance) if isinstance(distance, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def elevation_gain_m(self) -> Optional[float]:
        """Get total elevation gain in meters."""
        if self._session_msg is None:
            return None
        
        elev = self._session_msg.get_value("total_ascent", fallback=None)
        return float(elev) if isinstance(elev, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def elevation_loss_m(self) -> Optional[float]:
        """Get total elevation loss in meters."""
        if self._session_msg is None:
            return None
        
        elev = self._session_msg.get_value("total_descent", fallback=None)
        return float(elev) if isinstance(elev, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def avg_speed_mps(self) -> Optional[float]:
        """Get average speed in m/s."""
        if self._session_msg is None:
            return None
        
        speed = self._session_msg.get_value("avg_speed", fallback=None)
        return float(speed) if isinstance(speed, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def max_speed_mps(self) -> Optional[float]:
        """Get max speed in m/s."""
        if self._session_msg is None:
            return None
        
        speed = self._session_msg.get_value("max_speed", fallback=None)
        return float(speed) if isinstance(speed, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @property
    def calories_kcal(self) -> Optional[float]:
        """Get total calories."""
        if self._session_msg is None:
            return None
        
        calories = self._session_msg.get_value("total_calories", fallback=None)
        return float(calories) if isinstance(calories, (int, float)) else None
    
    @computed_field  # type: ignore[misc]
    @cached_property
    def device_name(self) -> Optional[str]:
        """Return normalized human-readable device name (cached).

        Combines validated manufacturer and product labels from `file_id` metadata,
        including Garmin-specific product handling.

        Returns:
            Device name string, or None when identity fields are unavailable.
        """
        if self._file_id_msg is None:
            return None
        
        manufacturer = self._file_id_msg.get_value("manufacturer", fallback=None)
        product = self._file_id_msg.get_value("product", fallback=None)
        
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
    @cached_property
    def has_gps_data(self) -> bool:
        """Check if GPS data exists in records (cached)."""
        for record in self._data_messages_by_type.get("record", []):
            lat = record.get_value("position_lat", fallback=None)
            lon = record.get_value("position_long", fallback=None)
            if lat is not None and lon is not None:
                return True
        return False
    
    @computed_field  # type: ignore[misc]
    @cached_property
    def device_manufacturer_code(self) -> Optional[int]:
        """Return normalized manufacturer code from `file_id` (cached).

        Accepts enum, integer, or name-like values from fitdecode and normalizes to
        an integer code when possible.

        Returns:
            Manufacturer code, or None when unavailable/unmappable.
        """
        if self._file_id_msg is None:
            return None
        
        manufacturer = self._file_id_msg.get_value("manufacturer", fallback=None)
        code, name = self._extract_code_and_name(manufacturer)
        
        if code is None and name is not None:
            # Fallback: try to resolve string name to numeric code
            resolved = MANUFACTURER_NAME_TO_CODE.get(name.lower())
            if resolved is not None:
                logger.debug(
                    "Resolved manufacturer name '%s' to code %d",
                    name,
                    resolved,
                )
                return resolved
            logger.warning(
                "Unable to map manufacturer name '%s' to numeric code",
                name,
            )
        
        if code is None and manufacturer is not None:
            logger.warning(
                "[ingestion_id=%r, file_sha256=%r] Manufacturer field present but could not extract code. "
                "Raw value: %r (type=%s)",
                self._source_metadata.get("ingestion_id"),
                self._source_metadata.get("file_sha256"),
                manufacturer,
                type(manufacturer).__name__,
            )
        
        return code
    
    @computed_field  # type: ignore[misc]
    @cached_property
    def device_product_code(self) -> Optional[int]:
        """Return normalized product code from `file_id` (cached).

        Uses `_get_file_id_product()` to apply source-specific product selection
        (including Garmin overrides) before code extraction.

        Returns:
            Product code, or None when unavailable.
        """
        if self._file_id_msg is None:
            return None
        
        product = self._get_file_id_product()
        code, _ = self._extract_code_and_name(product)
        return code
    
    # ========================================================================
    # Device Validation Methods
    # ========================================================================
    
    @staticmethod
    def _extract_code_and_name(field: Optional[Any]) -> tuple[Optional[int], Optional[str]]:
        """Extract numeric code and enum name from a FIT field.
        
        Handles multiple input types:
        - None: returns (None, None)
        - int: returns (int, None)
        - fitdecode enum: returns (.value, .name)
        - str: returns (None, str) for potential reverse lookup
        
        Args:
            field: Raw field value from fitdecode
            
        Returns:
            Tuple of (numeric_code, string_name), either or both may be None
        """
        if field is None:
            return None, None
        
        if isinstance(field, int):
            return field, None
        
        if isinstance(field, str):
            # fitdecode sometimes returns string values; extract as name for reverse lookup
            return None, field
        
        code = None
        name = None
        
        # Handle fitdecode enum objects
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
        if not self._data_messages or (
            file_id_manufacturer is None and file_id_product is None
        ):
            return
        
        file_id_mfr_code, _ = self._extract_code_and_name(file_id_manufacturer)
        file_id_prod_code, _ = self._extract_code_and_name(file_id_product)
        
        for device_info_msg in self._data_messages_by_type.get("device_info", []):
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
    
    def build_canonical_records(self) -> CanonicalRecordSet:
        """Build canonical record set for parquet storage.
        
        Returns:
            CanonicalRecordSet containing typed records ready for DataFrame conversion
        """
        return CanonicalRecordSet.from_fit_messages(
            self._data_messages,
            self._canonical_start_dt(),
        )
    
    def _canonical_start_dt(self) -> Optional[datetime]:
        """Get start datetime for elapsed time calculations."""
        start_time = self.start_time_utc
        if not start_time:
            return None
        try:
            return datetime.fromisoformat(start_time.replace("Z", UTC_OFFSET_SUFFIX))
        except ValueError:
            return None
    
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
            "local_tz_offset": self.local_tz_offset,
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
        if self._file_id_msg is None:
            return metadata
        
        file_created = self._file_id_msg.get_value("time_created", fallback=None)
        if isinstance(file_created, datetime):
            metadata["file_time_created_utc"] = self._format_utc_timestamp(
                file_created
            )
        
        file_manufacturer = self._file_id_msg.get_value("manufacturer", fallback=None)
        if file_manufacturer is not None:
            manufacturer_name = getattr(file_manufacturer, "name", None)
            metadata["file_manufacturer"] = (
                str(manufacturer_name)
                if manufacturer_name is not None
                else str(file_manufacturer)
            )
        
        file_product = self._get_file_id_product()
        if file_product is not None:
            metadata["file_product"] = str(file_product)
            metadata["product_id"] = str(file_product)
        
        file_serial = self._file_id_msg.get_value("serial_number", fallback=None)
        if file_serial is not None:
            metadata["file_serial_number"] = str(file_serial)
        
        return metadata
    
    def _build_canonical_activity_metadata(self) -> Dict[str, Any]:
        """Extract activity-level metadata from activity message."""
        metadata: Dict[str, Any] = {}
        activity_msg = (self._data_messages_by_type.get("activity") or [None])[0]
        if not activity_msg:
            return metadata
        
        activity_timestamp = activity_msg.get_value("timestamp", fallback=None)
        if isinstance(activity_timestamp, datetime):
            metadata["activity_timestamp_utc"] = self._format_utc_timestamp(
                activity_timestamp
            )
        
        activity_local = activity_msg.get_value("local_timestamp", fallback=None)
        if isinstance(activity_local, datetime):
            metadata["activity_local_time"] = activity_local.isoformat()
        
        return metadata
    
    def raw_frames(self, as_json: bool = False) -> List[Any] | str:
        """Return raw FIT frames for archival storage.
        
        Args:
            as_json: If True, return JSON string via RecordJSONEncoder; 
                     if False (default), return frames list
        
        Returns:
            List of frames or JSON-serialized string depending on as_json flag
        """
        if as_json:
            return json.dumps(self._all_frames, cls=RecordJSONEncoder)
        return self._all_frames
    
    def build_metadata_messages(self) -> Dict[str, Any]:
        """Return structured FIT metadata.json with LLM enrichment placeholder."""
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
            typed_messages = self._data_messages_by_type.get(message_type)
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
        lap_messages = self._data_messages_by_type.get("lap", [])
        
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
        analyzer = FitStructureAnalyzer(messages=self._data_messages)
        return analyzer.analyze()

    # ========================================================================
    # Type-Checker Shims (organization-only, non-domain logic)
    # ========================================================================

    @property
    def _metadata_dict(self) -> Dict[str, Any]:
        """Access source_metadata as properly-typed dict for type checkers."""
        return self._source_metadata


class OneDriveFitModel(BaseFitModel, ABC):
    """Abstract base for OneDrive-backed FIT sources.

    Contract:
        - Accepts either in-memory bytes or a local file path.
        - Loads file contents when only `file_path` is provided.
        - Delegates semantic parsing and validation to BaseFitModel.
    """
    
    file_path: Optional[str] = None
    
    def __init__(
        self,
        *,
        file_bytes: Optional[bytes] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        **data: Any,
    ) -> None:
        """Load file_path into file_bytes before parent initialization."""
        if file_path and file_bytes is None:
            with open(file_path, "rb") as f:
                file_bytes = f.read()

        if file_bytes is None:
            raise FitParsingError(ERROR_FILE_BYTES_REQUIRED)

        super().__init__(
            file_bytes=file_bytes,
            source_metadata=source_metadata,
            file_path=file_path,
            **data,
        )
    
    @computed_field  # type: ignore[misc]
    @property
    def source_file_name(self) -> Optional[str]:
        """Extract filename from source metadata."""
        return self._metadata_dict.get("source_file_name")


class HealthFitModel(OneDriveFitModel):
    """OneDrive model for HealthFit exports from Apple ecosystem devices.

    Contract:
        - Parses HealthFit filenames using `YYYY-MM-DD-HHMMSS-{Activity}-{Source}.fit[.gz]`.
        - Treats filename activity token as primary Apple workout-type signal.
        - Falls back to FIT sport/sub-sport mapping when filename token is missing or unknown.
        - Provides filename-derived timezone fallback when FIT timezone signals are insufficient.
    """
    
    # HealthFit filename pattern: YYYY-MM-DD-HHMMSS-{ActivityType}-{Source}.fit[.gz]
    # Parsing treats final '-' token as source and all middle tokens as activity.
    # The YYYY-MM-DD-HHMMSS token is device-local recording time.
    # Note: .gz suffix is optional for backwards compatibility but ignored (decompression
    # happens in preprocessing layer before model instantiation).
    HEALTHFIT_FILENAME_PATTERN: ClassVar[re.Pattern] = re.compile(
        r'^(\d{4}-\d{2}-\d{2})-(\d{6}|Nodata)-(.+)\.fit(?:\.gz)?$'
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
    @cached_property
    def filename_components(self) -> Optional[Dict[str, str]]:
        """Parse HealthFit filename into components (cached after first access).

        The parsed ``date`` and ``time`` fields represent local time on the
        recording device.
        """
        if not self.source_file_name:
            return None
        
        match = self.HEALTHFIT_FILENAME_PATTERN.match(self.source_file_name)
        if not match:
            return None

        activity_and_source = match.group(3)
        if "-" not in activity_and_source:
            return None

        activity_raw, source_device = activity_and_source.rsplit("-", 1)
        activity_type = re.sub(r"\s+", " ", activity_raw.replace("-", " ")).strip()
        source_device = source_device.strip()

        if not activity_type or not source_device:
            return None
        
        return {
            "date": match.group(1),              # YYYY-MM-DD (device-local)
            "time": match.group(2),              # HHMMSS or "Nodata" (device-local)
            "apple_workout_type": activity_type, # e.g., "Indoor Cycling"
            "source_device": source_device,      # e.g., "RunGap"
        }
    
    @property
    def filename_date(self) -> Optional[str]:
        """Extract device-local date from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["date"]
        return None
    
    @property
    def filename_time(self) -> Optional[str]:
        """Extract device-local time from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["time"]
        return None
    
    @property
    def filename_apple_workout_type(self) -> Optional[str]:
        """Extract Apple Workout Type from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["apple_workout_type"]
        return None
    
    @property
    def filename_source_device(self) -> Optional[str]:
        """Extract source device from HealthFit filename."""
        if self.filename_components:
            return self.filename_components["source_device"]
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def inferred_timezone_filename(self) -> Optional[str]:
        """Infer timezone from HealthFit filename local time vs FIT UTC time.
        
        Compares filename's device-local datetime (YYYY-MM-DD-HHMMSS) with a FIT
        message-derived UTC timestamp (event/session/record) to calculate timezone
        offset as fallback when device_settings or activity/session inferences are
        missing.
        """
        if not self.filename_date or not self.filename_time or self.filename_time == "Nodata":
            return None

        fit_start_utc = self._fit_message_start_time_utc()
        if not fit_start_utc:
            return None
        
        try:
            # Parse device-local filename datetime
            local_dt_str = f"{self.filename_date} {self.filename_time}"
            local_dt = datetime.strptime(local_dt_str, "%Y-%m-%d %H%M%S")
            
            # Parse FIT UTC timestamp
            utc_dt = datetime.fromisoformat(fit_start_utc.replace("Z", UTC_OFFSET_SUFFIX))
            utc_dt_naive = utc_dt.replace(tzinfo=None)
            
            # Calculate offset in minutes
            offset_delta = local_dt - utc_dt_naive
            offset_minutes = int(offset_delta.total_seconds() / 60)
            
            return format_utc_offset(offset_minutes)
        except (ValueError, AttributeError, ImportError):
            return None

    def _fit_message_start_time_utc(self) -> Optional[str]:
        """Return UTC start from FIT messages only (no source-specific fallback)."""
        start_dt = self._start_time_from_event()
        if not start_dt:
            start_dt = self._start_time_from_session()
        if not start_dt and self._session_msg is None:
            start_dt = self._start_time_from_first_record()
        if not start_dt:
            return None
        return self._format_utc_timestamp(start_dt)

    def _source_specific_timezone_fallback(self) -> Optional[str]:
        """Return HealthFit filename-derived timezone offset when available."""
        return self.inferred_timezone_filename

    def _normalize_and_resolve_apple_type(self, raw_type: str) -> Optional[str]:
        """Normalize and resolve raw Apple workout type to canonical form.
        
        Args:
            raw_type: Raw Apple workout type string from filename
            
        Returns:
            Canonical Apple workout type or None if unrecognized
        """
        normalized = raw_type.strip().lower()
        
        # Check aliases first
        if normalized in self.HEALTHFIT_APPLE_TYPE_ALIASES:
            return self.HEALTHFIT_APPLE_TYPE_ALIASES[normalized]
        
        # Check against canonical types (excluding "Other")
        for apple_type in APPLE_WORKOUT_TYPES:
            if apple_type != "Other" and apple_type.lower() == normalized:
                return apple_type
        
        return None

    def _source_specific_apple_workout_type(self) -> Optional[str]:
        """Resolve Apple workout type deterministically from HealthFit filename."""
        raw_type = self.filename_apple_workout_type
        if not raw_type:
            return None
        return self._normalize_and_resolve_apple_type(raw_type)

    def _allow_fit_apple_workout_fallback(self) -> bool:
        """Allow FIT sport/sub_sport fallback for HealthFit when filename token is missing."""
        return True

    @computed_field  # type: ignore[misc]
    @property
    def apple_workout_type(self) -> Optional[str]:
        """Resolve Apple workout type with HealthFit-specific warning on FIT fallback."""
        raw_type = self.filename_apple_workout_type
        if raw_type:
            resolved = self._normalize_and_resolve_apple_type(raw_type)
            if resolved is not None:
                return resolved
            logger.warning(
                "HealthFit filename activity token unrecognized; "
                "falling back to FIT apple workout type resolution: token=%r, source_file=%r",
                raw_type,
                self.source_file_name,
            )
        else:
            logger.warning(
                "HealthFit filename activity token missing; "
                "falling back to FIT apple workout type resolution: source_file=%r",
                self.source_file_name,
            )

        resolver = AppleWorkoutTypeResolver(
            sport=self.sport,
            sub_sport=self.sub_sport,
        )
        return resolver.resolve()
    
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """Return HealthFit filename Apple Workout Type as workout name source."""
        return self.filename_apple_workout_type


class GarminFitModel(BaseFitModel):
    """FIT model for Garmin Connect ingests.

    Contract:
        - Uses Garmin source metadata for workout naming when available.
        - Uses base FIT-derived behavior for Apple workout type and timezone.
        - Does not provide Garmin-specific timezone fallback.
    """
    
    @computed_field  # type: ignore[misc]
    @property
    def normalized_source_system(self) -> str:
        """Return normalized source system name."""
        return "Garmin"
    
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """Return Garmin API activity name if available."""
        return self._metadata_dict.get("source_activity_name")

    def _source_specific_apple_workout_type(self) -> Optional[str]:
        """Garmin does not provide source-specific Apple workout types."""
        return None

    def _source_specific_timezone_fallback(self) -> Optional[str]:
        """Garmin has no source-specific timezone fallback."""
        return None


class PayloadFitModel(BaseFitModel):
    """FIT model for direct HTTP payload uploads.

    Contract:
        - Performs no source-specific workout-name, workout-type, or timezone overrides.
        - Relies on BaseFitModel semantics for all inferred metadata.
        - Emits normalized source system identifier as "HTTP".
    """
    
    def _get_subclass_specific_workout_name(self) -> Optional[str]:
        """No subclass-specific lookup for payload uploads."""
        return None

    def _source_specific_apple_workout_type(self) -> Optional[str]:
        """Payload uploads do not provide source-specific Apple workout types."""
        return None

    def _source_specific_timezone_fallback(self) -> Optional[str]:
        """Payload uploads do not provide source-specific timezone fallback."""
        return None
    
    @computed_field  # type: ignore[misc]
    @property
    def normalized_source_system(self) -> str:
        """Return fixed normalized source system for direct HTTP payloads."""
        return "HTTP"


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
        return cast(Any, GarminFitModel)(
            file_bytes=file_bytes,
            source_metadata=source_metadata,
        )
    
    # OneDrive: has OneDrive-specific fields (source_etag, source_drive_id)
    if source_metadata.get("source_etag") or source_metadata.get("source_drive_id"):
        # Check manufacturer code to determine if it's Apple Watch
        # For now, default to HealthFitModel (can enhance later with device detection)
        return cast(Any, HealthFitModel)(
            file_bytes=file_bytes,
            source_metadata=source_metadata,
        )
    
    # Default: payload upload or unknown source
    return cast(Any, PayloadFitModel)(
        file_bytes=file_bytes,
        source_metadata=source_metadata,
    )
