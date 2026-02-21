"""Parse FIT files and extract workout metrics."""
# pylint: disable=too-many-lines, trailing-whitespace

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from .fit_message_utils import load_fit_messages
from .constants import LAPS_SCHEMA_VERSION, METADATA_SCHEMA_VERSION
from .fit_analyzer import FitStructureAnalyzer
from .apple_workout_types import AppleWorkoutTypeResolver
from .code_mappings import (
    get_apple_product_name,
    get_garmin_product_name,
    get_favero_product_name,
    MANUFACTURER_CODES,
)
from .timezone_utils import (
    infer_timezone_from_activity,
    infer_timezone_from_session,
    resolve_timezone,
)

logger = logging.getLogger(__name__)


class FitParser:
    """Parser for FIT format workout files."""

    def __init__(
        self,
        file_path: Optional[str] = None,
        source_file_name: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        source_activity_name: Optional[str] = None,
    ):
        """Initialize FIT parser with file path or in-memory bytes.

        Args:
            file_path: Path to the FIT file
            source_file_name: Optional original filename
                (e.g., from OneDrive) for metadata extraction
            file_bytes: Optional in-memory FIT bytes
            source_activity_name: Optional activity name from source system
                (e.g., Garmin Connect API activityName)
        """
        if not file_path and file_bytes is None:
            raise ValueError("file_path or file_bytes must be provided")

        self.file_path = file_path or "<in-memory>"
        self.file_bytes = file_bytes
        self.source_file_name = source_file_name
        self.source_activity_name = source_activity_name
        self.messages = None
        self._file_id_msg = None
        self._session_msg = None

    @property
    def file_id_msg(self):
        """Cached file_id message (None if unavailable)."""
        return self._file_id_msg

    @property
    def session_msg(self):
        """Cached session message (None if unavailable)."""
        return self._session_msg

    def _load_fit_sources(self) -> None:
        """Load FIT messages from file or bytes."""
        try:
            file_input = self.file_bytes if self.file_bytes is not None else self.file_path
            self.messages, _ = load_fit_messages(file_input)
        except Exception as e:
            logger.error("Error parsing FIT file %s: %s", self.file_path, e)
            raise

    def _cache_messages(self) -> None:
        """Cache frequently-accessed FIT messages for efficiency."""
        if not self.messages:
            return
        for message in self.messages:
            if message["name"] == "file_id" and not self._file_id_msg:
                self._file_id_msg = message
            elif message["name"] == "session" and not self._session_msg:
                self._session_msg = message

    def _get_messages(self, message_name: Optional[str] = None) -> List[Dict]:
        """Filter messages by name, or return all if name is None."""
        if not self.messages:
            return []
        if message_name is None:
            return list(self.messages)
        return [msg for msg in self.messages if msg["name"] == message_name]

    def _get_field_from_msg(self, msg: Optional[Dict], field_name: str) -> Optional[Any]:
        """Safely get a field value from a FIT message dict."""
        if not msg:
            return None
        fields = msg.get("fields", {})
        field = fields.get(field_name)
        if field:
            value = field.value
            if isinstance(value, datetime) and value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value
        return None

    def _extract_record_payload(self, record) -> Optional[Dict[str, Any]]:
        """Extract a minimal record payload from a FIT record message."""
        payload = {
            "heart_rate": self._get_field_from_msg(record, "heart_rate"),
            "power": self._get_field_from_msg(record, "power"),
            "cadence": self._get_field_from_msg(record, "cadence"),
            "position_lat": self._get_field_from_msg(record, "position_lat"),
            "position_long": self._get_field_from_msg(record, "position_long"),
        }
        trimmed = {k: v for k, v in payload.items() if v is not None}
        return trimmed or None

    def extract_lap_records(self) -> List[Dict[str, Any]]:
        """Extract lap summaries and per-lap record payloads.

        Returns:
            List of dicts: {"lap_index": int, "summary": {...}, "records": [...]}
        """
        if not self.messages:
            self._load_fit_sources()

        laps = self._get_messages("lap")
        if not laps:
            return []

        lap_windows = self._build_lap_windows(laps)
        self._assign_records_to_laps(lap_windows)
        return self._finalize_lap_records(lap_windows)

    def extract_canonical_records(self) -> List[Dict[str, Any]]:
        """Extract Section I canonical substrate records for parquet storage."""
        if not self.messages:
            self._load_fit_sources()
        start_dt = self._canonical_start_dt()

        records: List[Dict[str, Any]] = []
        for record in self._get_messages("record"):
            payload = self._build_canonical_record(record, start_dt)
            if payload:
                records.append(payload)

        return records

    def extract_canonical_laps(self) -> List[Dict[str, Any]]:
        """Extract lap summaries for parquet storage."""
        if not self.messages:
            self._load_fit_sources()

        laps = self._get_messages("lap")
        if not laps:
            return []

        canonical_laps: List[Dict[str, Any]] = []
        for idx, msg in enumerate(laps):
            start_time = self._get_field_from_msg(msg, "start_time")
            start_iso = None
            if isinstance(start_time, datetime):
                start_iso = start_time.astimezone(timezone.utc).isoformat()

            total_elapsed = self._get_field_from_msg(msg, "total_elapsed_time")
            total_timer = self._get_field_from_msg(msg, "total_timer_time")
            total_distance = self._get_field_from_msg(msg, "total_distance")
            total_calories = self._get_field_from_msg(msg, "total_calories")

            canonical_laps.append({
                "lap_index": idx,
                "start_time_utc": start_iso,
                "elapsed_sec": float(total_elapsed) if total_elapsed is not None else None,
                "moving_time_sec": float(total_timer) if total_timer is not None else None,
                "distance_m": float(total_distance) if total_distance is not None else None,
                "calories_kcal": float(total_calories) if total_calories is not None else None,
                "avg_heart_rate_bpm": self._get_field_from_msg(msg, "avg_heart_rate"),
                "max_heart_rate_bpm": self._get_field_from_msg(msg, "max_heart_rate"),
                "avg_power_watts": self._get_field_from_msg(msg, "avg_power"),
                "max_power_watts": self._get_field_from_msg(msg, "max_power"),
                "avg_cadence_rpm": self._get_field_from_msg(msg, "avg_cadence"),
                "max_cadence_rpm": self._get_field_from_msg(msg, "max_cadence"),
            })

        return canonical_laps

    def extract_canonical_metadata(self) -> Dict[str, Any]:
        """Extract canonical FIT metadata from file, device, event, activity, session."""
        if not self.messages:
            self._load_fit_sources()
        metadata: Dict[str, Any] = {}
        metadata.update(self._build_canonical_session_metadata())
        metadata.update(self._build_canonical_file_metadata())
        metadata.update(self._build_canonical_activity_metadata())

        return {k: v for k, v in metadata.items() if v is not None}

    def extract_raw_fit_json(self) -> Dict[str, Any]:
        """Return a decoded-only JSON representation of the full FIT file."""
        if not self.messages:
            self._load_fit_sources()

        messages = []
        message_index: Dict[str, int] = {}
        for message in self._get_messages():
            msg_type = message["name"]
            message_index[msg_type] = message_index.get(msg_type, 0) + 1
            messages.append(
                self._serialize_message(
                    message,
                    msg_type=msg_type,
                    msg_index=message_index[msg_type],
                )
            )

        metadata = {
            "source_file": self.source_file_name or self.file_path,
            "exported_at_utc": datetime.now(timezone.utc).isoformat(),
            "message_counts": message_index,
            "total_messages": len(messages),
        }

        return {
            "metadata": metadata,
            "messages": messages,
        }

    def extract_metadata_messages(self) -> Dict[str, Any]:
        """Return structured FIT metadata.json with raw messages and LLM enrichment placeholder.
        
        Returns:
            Dict with schema_version, extracted_at_utc, raw_fit_messages, and llm_enrichment fields.
            The llm_enrichment section has status='pending' until enriched by LLM.
        """
        if not self.messages:
            self._load_fit_sources()

        message_types = [
            "file_id",
            "file_creator",
            "device_info",
            "sport",
            "session",
            "activity",
            "event",
            "workout",
        ]

        raw_fit_messages: Dict[str, Any] = {}
        for message_type in message_types:
            messages = [
                self._serialize_message(message)
                for message in self._get_messages(message_type)
            ]
            if messages:
                raw_fit_messages[message_type] = messages

        # LLM enrichment placeholder - filled in by enrich_metadata_with_llm()
        llm_enrichment = {
            "status": "pending",  # 'complete' after LLM enrichment
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

    def extract_laps_json(self) -> Dict[str, Any]:
        """Return uncompressed lap messages JSON artifact with schema metadata.
        
        Returns:
            Dict with schema_version, extracted_at_utc, and laps array.
        """
        if not self.messages:
            self._load_fit_sources()

        laps = [
            self._serialize_message(message)
            for message in self._get_messages("lap")
        ]
        return {
            "schema_version": LAPS_SCHEMA_VERSION,
            "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
            "laps": laps,
        }

    def extract_fit_analysis(self) -> Dict[str, Any]:
        """Return deterministic FIT structural analysis payload."""
        if not self.messages:
            self._load_fit_sources()
        analyzer = FitStructureAnalyzer(self.messages)
        return analyzer.analyze()

    def enrich_metadata_with_llm(
        self,
        metadata_json: Dict[str, Any],
        fit_analysis: Dict[str, Any],
        llm_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Enrich metadata.json with semantic interpretation from LLM.
        
        Calls GPT-4o-mini to analyze raw_fit_messages + fit_analysis and provide
        semantic interpretation: inferred workout name, activity classification,
        virtual indicators, and anomalies.
        
        Args:
            metadata_json: Output from extract_metadata_messages()
            fit_analysis: Output from extract_fit_analysis()
            llm_client: Optional Azure OpenAI client. If None, returns metadata unchanged.
        
        Returns:
            metadata_json with llm_enrichment.status='complete' and filled fields.
            If llm_client is None, returns with status='skipped'.
        """
        if not llm_client:
            metadata_json["llm_enrichment"]["status"] = "skipped"
            return metadata_json

        _ = fit_analysis
        # LLM enrichment pending; prompt and output contract not finalized yet.
       
        logger.debug("LLM enrichment not yet implemented; returning metadata with pending status")
        return metadata_json

    @staticmethod
    def _serialize_message(
        message: Dict[str, Any],
        msg_type: Optional[str] = None,
        msg_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Serialize a FIT message dict to JSON-friendly format.
        
        Args:
            message: Dict with "name", "frame", "fields" keys from load_fit_messages
            msg_type: Optional override for message type name
            msg_index: Optional message index in sequence
        """
        frame = message.get("frame")
        fields_dict = message.get("fields", {})

        msg_payload = {
            "message_type": msg_type or message.get("name", "unknown"),
            "fields": {},
        }

        if msg_index is not None:
            msg_payload["message_index"] = msg_index

        # Serialize standard fields
        for field_name, field in fields_dict.items():
            msg_payload["fields"][field_name] = {
                "value": field.value,
                "units": getattr(field, "units", None),
            }

        # Serialize developer fields if present
        if frame and hasattr(frame, "developer_fields"):
            for field in frame.developer_fields:
                msg_payload["fields"][f"dev_{field.name}"] = {
                    "value": field.value,
                    "units": getattr(field, "units", None),
                }

        return msg_payload

    def _canonical_start_dt(self) -> Optional[datetime]:
        start_time = self._get_start_time()
        if not start_time:
            return None
        try:
            return datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _build_canonical_record(
        self,
        record,
        start_dt: Optional[datetime],
    ) -> Optional[Dict[str, Any]]:
        timestamp = self._normalize_record_timestamp(
            self._get_field_from_msg(record, "timestamp")
        )
        if not timestamp:
            return None

        timestamp_utc = timestamp.astimezone(timezone.utc).isoformat()
        elapsed_sec = None
        if start_dt is not None:
            elapsed_sec = (timestamp - start_dt).total_seconds()

        power = self._get_field_from_msg(record, "power")
        heart_rate = self._get_field_from_msg(record, "heart_rate")
        cadence = self._get_field_from_msg(record, "cadence")
        speed = (
            self._get_field_from_msg(record, "enhanced_speed")
            or self._get_field_from_msg(record, "speed")
        )
        distance = (
            self._get_field_from_msg(record, "enhanced_distance")
            or self._get_field_from_msg(record, "distance")
        )
        elevation = (
            self._get_field_from_msg(record, "enhanced_altitude")
            or self._get_field_from_msg(record, "altitude")
        )

        return {
            "timestamp_utc": timestamp_utc,
            "elapsed_sec": float(elapsed_sec) if elapsed_sec is not None else None,
            "power_watts": float(power) if power is not None else None,
            "heart_rate_bpm": float(heart_rate) if heart_rate is not None else None,
            "cadence_rpm": float(cadence) if cadence is not None else None,
            "speed_mps": float(speed) if speed is not None else None,
            "distance_m": float(distance) if distance is not None else None,
            "elevation_m": float(elevation) if elevation is not None else None,
        }

    def _build_canonical_session_metadata(self) -> Dict[str, Any]:
        return {
            "sport": self._get_sport(),
            "sub_sport": self._get_sub_sport(),
            "apple_workout_type": None,
            "workout_name": self._get_workout_name(),
            "is_indoor": self._get_is_indoor(),
            "start_time_utc": self._get_start_time(),
            "timezone": self._get_timezone(),
            "duration_sec": self._get_duration(),
            "moving_time_sec": self._get_moving_time(),
            "distance_m": self._get_distance(),
            "elevation_gain_m": self._get_elevation_gain(),
            "elevation_loss_m": self._get_elevation_loss(),
            "avg_speed_mps": self._get_avg_speed(),
            "max_speed_mps": self._get_max_speed(),
            "calories_kcal": self._get_calories(),
            "device_name": self._get_device_name(),
        }

    def _build_canonical_file_metadata(self) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        file_created = self._get_field_from_msg(
            self.file_id_msg,
            "time_created",
        )
        if isinstance(file_created, datetime):
            metadata["file_time_created_utc"] = (
                file_created.astimezone(timezone.utc).isoformat()
            )

        file_manufacturer = self._get_field_from_msg(
            self.file_id_msg,
            "manufacturer",
        )
        if file_manufacturer is not None:
            metadata["file_manufacturer"] = (
                str(file_manufacturer.name)
                if hasattr(file_manufacturer, "name")
                else str(file_manufacturer)
            )

        file_product = self._get_field_from_msg(self.file_id_msg, "product")
        if file_product is not None:
            metadata["file_product"] = str(file_product)

        file_serial = self._get_field_from_msg(self.file_id_msg, "serial_number")
        if file_serial is not None:
            metadata["file_serial_number"] = str(file_serial)

        return metadata

    def _build_canonical_activity_metadata(self) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        activity_msg = None
        for msg in self._get_messages("activity"):
            activity_msg = msg
            break
        if not activity_msg:
            return metadata

        activity_timestamp = self._get_field_from_msg(activity_msg, "timestamp")
        if isinstance(activity_timestamp, datetime):
            metadata["activity_timestamp_utc"] = (
                activity_timestamp.astimezone(timezone.utc).isoformat()
            )

        activity_local = (
            self._get_raw_field_from_msg(activity_msg, "local_time")
            or self._get_raw_field_from_msg(activity_msg, "local_timestamp")
        )
        if isinstance(activity_local, datetime):
            metadata["activity_local_time"] = activity_local.isoformat()

        return metadata

    def _build_lap_windows(self, laps: List) -> List[Dict[str, Any]]:
        summary_fields = [
            "start_time",
            "total_elapsed_time",
            "total_timer_time",
            "total_distance",
            "total_calories",
            "avg_heart_rate",
            "max_heart_rate",
            "avg_power",
            "max_power",
            "avg_cadence",
            "max_cadence",
        ]

        lap_windows: List[Dict[str, Any]] = []
        for idx, msg in enumerate(laps):
            summary: Dict[str, Any] = {}
            start_time = self._get_field_from_msg(msg, "start_time")
            end_time = None
            total_elapsed = self._get_field_from_msg(msg, "total_elapsed_time")
            if isinstance(start_time, datetime) and total_elapsed is not None:
                end_time = start_time + timedelta(seconds=float(total_elapsed))

            for field in summary_fields:
                value = self._get_field_from_msg(msg, field)
                if isinstance(value, datetime):
                    value = value.astimezone(timezone.utc).isoformat()
                if value is not None:
                    summary[field] = value

            lap_windows.append({
                "lap_index": idx,
                "start_time": start_time,
                "end_time": end_time,
                "summary": summary,
                "records": [],
                "record_index": 0,
            })

        return lap_windows

    def _assign_records_to_laps(self, lap_windows: List[Dict[str, Any]]) -> None:
        if not self.messages:
            return

        current_idx = 0
        for record in self._get_messages("record"):
            timestamp = self._normalize_record_timestamp(
                self._get_field_from_msg(record, "timestamp")
            )
            current_idx = self._advance_lap_index(
                timestamp,
                lap_windows,
                current_idx,
            )

            payload = self._extract_record_payload(record)
            if not payload:
                continue

            payload["record_index"] = lap_windows[current_idx]["record_index"]
            lap_windows[current_idx]["record_index"] += 1
            lap_windows[current_idx]["records"].append(payload)

    def _advance_lap_index(
        self,
        timestamp: Optional[datetime],
        lap_windows: List[Dict[str, Any]],
        current_idx: int,
    ) -> int:
        while timestamp and current_idx < len(lap_windows) - 1:
            end_time = lap_windows[current_idx].get("end_time")
            if end_time and timestamp >= end_time:
                current_idx += 1
                continue
            break
        return current_idx

    @staticmethod
    def _normalize_record_timestamp(
        timestamp: Optional[datetime],
    ) -> Optional[datetime]:
        if isinstance(timestamp, datetime):
            return timestamp.astimezone(timezone.utc)
        return timestamp

    @staticmethod
    def _finalize_lap_records(
        lap_windows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        lap_records: List[Dict[str, Any]] = []
        for lap in lap_windows:
            lap_records.append({
                "lap_index": lap["lap_index"],
                "summary": lap["summary"],
                "records": lap["records"],
            })
        return lap_records

    def _get_raw_field_from_msg(self, msg, field_name: str) -> Optional[Any]:
        """Return raw field value (no timezone coercion)."""
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
            workout_name=self._get_workout_name(),
            sport=self._get_sport(),
            sub_sport=self._get_sub_sport()
        )
        return resolver.resolve()

    def _get_workout_name(self) -> Optional[str]:
        """Get workout name from activity message or construct from sport/subsport/ID.
        
        Priority:
        1. Activity message name field
        2. Session message session_name field
        3. Constructed name: {sport}-{subsport}-{activityID}
        4. Filename stem (last resort)
        """
        for candidate in (
            self._get_activity_workout_name(),
            self._get_session_workout_name(),
            self._get_constructed_workout_name(),
            self._get_filename_stem_workout_name(),
        ):
            if candidate:
                return candidate
        return None

    def _get_activity_workout_name(self) -> Optional[str]:
        activity_msgs = self._get_messages("activity")
        if not activity_msgs:
            return None
        activity_msg = activity_msgs[0]
        for field_name in ("event_name", "name"):
            name = self._get_field_from_msg(activity_msg, field_name)
            if name is not None:
                return str(name)
        return None

    def _get_session_workout_name(self) -> Optional[str]:
        session = self.session_msg
        name = self._get_field_from_msg(session, "session_name")
        return str(name) if name is not None else None

    def _get_constructed_workout_name(self) -> Optional[str]:
        sport_name = self._get_sport_name()
        sub_sport_name = self._get_sub_sport_name()
        activity_id = self._get_activity_id()

        parts = [part for part in (sport_name, sub_sport_name, activity_id) if part]
        if parts:
            return "-".join(str(part) for part in parts)
        return None

    def _get_filename_stem_workout_name(self) -> Optional[str]:
        if not self.source_file_name:
            return None
        file_name = Path(self.source_file_name).name
        if file_name.lower().endswith(".gz"):
            file_name = file_name[:-3]
        return Path(file_name).stem or None
    
    def _get_activity_id(self) -> Optional[str]:
        """Extract activity ID from file_id message or source_file_name."""
        # Try to get from file_id message if available
        if self.file_id_msg:
            file_id = self._get_field_from_msg(self.file_id_msg, "file_id")
            if file_id is not None:
                return str(file_id)
        
        # Try to extract numeric ID from filename (e.g., "12345.fit")
        if self.source_file_name:
            file_name = Path(self.source_file_name).stem
            # Check if filename is a pure number (Garmin activity ID)
            if file_name.isdigit():
                return file_name
        
        return None
    
    def _get_sport_name(self) -> Optional[str]:
        """Extract sport name from session or file_id message."""
        if self.session_msg:
            sport = self._get_field_from_msg(self.session_msg, "sport")
            if sport is not None:
                sport_name = getattr(sport, "name", None)
                if sport_name:
                    return str(sport_name)
                return str(sport)
        
        # Fallback to file_id sport
        if self.file_id_msg:
            sport = self._get_field_from_msg(self.file_id_msg, "type")
            if sport is not None:
                sport_name = getattr(sport, "name", None)
                if sport_name:
                    return str(sport_name)
                return str(sport)
        
        return None
    
    def _get_sub_sport_name(self) -> Optional[str]:
        """Extract subsport name from session message."""
        if self.session_msg:
            sub_sport = self._get_field_from_msg(self.session_msg, "sub_sport")
            if sub_sport is not None:
                subsport_name = getattr(sub_sport, "name", None)
                if subsport_name:
                    return str(subsport_name)
                return str(sub_sport)
        
        return None

    def _extract_code_and_name(self, field: Optional[Any]) -> tuple[Optional[int], Optional[str]]:
        """Extract numeric code and enum name from a FIT field.

        Args:
            field: fitdecode field object or int

        Returns:
            Tuple of (code, name) where both may be None
        """
        code = None
        name = None

        if field is None:
            return None, None
        if isinstance(field, int):
            return field, None

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

        # Get manufacturer code
        if manufacturer is None:
            return product_name or str(product_code)

        manufacturer_code, _ = self._extract_code_and_name(manufacturer)

        if manufacturer_code is None:
            return product_name or str(product_code)

        # Determine which product code mapping to use
        expected_product_name = None
        if manufacturer_code == 32:  # Apple
            expected_product_name = get_apple_product_name(product_code)
        elif manufacturer_code == 1:  # Garmin
            expected_product_name = get_garmin_product_name(product_code)
        elif manufacturer_code == 263:  # Favero Electronics
            expected_product_name = get_favero_product_name(product_code)

        # Log if we have a mismatch
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

    def _get_device_name(self) -> Optional[str]:
        """Get device/manufacturer and product info with mismatch detection.

        Validates that FIT manufacturer/product codes match our code_mappings
        and logs any discrepancies for investigation. Also checks device_info
        messages for collisions with the file_id device.
        """
        file_msg = self.file_id_msg
        manufacturer = self._get_field_from_msg(file_msg, "manufacturer")
        product = self._get_field_from_msg(file_msg, "product")

        parts: List[str] = []

        # Validate and get manufacturer name
        mfr_name = self._validate_and_get_manufacturer_name(manufacturer)
        if mfr_name:
            parts.append(mfr_name)

        # Validate and get product name
        prod_name = self._validate_and_get_product_name(product, manufacturer)
        if prod_name:
            parts.append(prod_name)

        # Validate device_info entries for collisions with file_id device
        self._validate_device_info_collisions(manufacturer, product)

        if parts:
            return " ".join(parts)
        return None

    def _log_product_collision(
        self,
        file_id_mfr_code: int,
        file_id_prod_code: Optional[int],
        device_mfr_code: int,
        device_prod_code: Optional[int],
    ) -> None:
        """Log product code collision or mismatch between file_id and device_info.

        Args:
            file_id_mfr_code: Manufacturer code from file_id message
            file_id_prod_code: Product code from file_id message (may be None)
            device_mfr_code: Manufacturer code from device_info message
            device_prod_code: Product code from device_info message (may be None)
        """
        # Both have product codes - check if they match
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

        # device_info missing product code
        if not device_prod_code and file_id_prod_code:
            logger.warning(
                "Device collision: file_id (mfr=%d, prod=%d) has product code, "
                "but device_info message only has manufacturer (mfr=%d)",
                file_id_mfr_code,
                file_id_prod_code,
                device_mfr_code,
            )
            return

        # file_id missing product code
        if device_prod_code and not file_id_prod_code:
            logger.warning(
                "Device collision: device_info (mfr=%d, prod=%d) "
                "has product code, but file_id only has manufacturer (mfr=%d)",
                device_mfr_code,
                device_prod_code,
                file_id_mfr_code,
            )

    def _validate_device_info_collisions(
        self,
        file_id_manufacturer: Optional[Any],
        file_id_product: Optional[Any],
    ) -> None:
        """Check device_info messages for collisions with the file_id device.

        If a device_info entry appears to be the same device as in file_id,
        validate consistency and log any mismatches.
        """
        if not self.messages or (
            file_id_manufacturer is None and file_id_product is None
        ):
            return

        # Extract numeric codes from file_id
        file_id_mfr_code, _ = self._extract_code_and_name(file_id_manufacturer)
        file_id_prod_code, _ = self._extract_code_and_name(file_id_product)

        # Check all device_info messages for collisions
        for device_info_msg in self._get_messages("device_info"):
            device_mfr = self._get_field_from_msg(device_info_msg, "manufacturer")
            device_prod = self._get_field_from_msg(device_info_msg, "product")

            # Extract numeric codes from device_info
            device_mfr_code, _ = self._extract_code_and_name(device_mfr)
            device_prod_code, _ = self._extract_code_and_name(device_prod)

            # Check if manufacturer codes match (collision candidate)
            if (
                device_mfr_code is not None
                and file_id_mfr_code is not None
                and device_mfr_code == file_id_mfr_code
            ):
                # Manufacturer collision detected - delegate product analysis
                self._log_product_collision(
                    file_id_mfr_code,
                    file_id_prod_code,
                    device_mfr_code,
                    device_prod_code,
                )

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
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        return None

    def _get_timezone(self) -> Optional[str]:
        """Get timezone if present; default to 'UTC'.

        Prefers explicit `time_zone` message name; otherwise uses device
        settings offsets when available. FIT timestamps are UTC by spec,
        so the default is 'UTC'.
        """
        try:
            if not self.messages:
                return "UTC"

            tz_name = self._get_time_zone_name()
            offset_minutes = self._get_device_utc_offset_minutes()
            inferred_activity = self._infer_timezone_from_activity_times()
            inferred_session = self._infer_timezone_from_session_times()
            return resolve_timezone(
                tz_name,
                offset_minutes,
                inferred_activity,
                inferred_session,
            )
        except (AttributeError, TypeError, ValueError):
            # Be defensive; timezone is non-critical
            pass
        return "UTC"

    def _get_time_zone_name(self) -> Optional[str]:
        """Return time zone name from FIT messages, if present."""
        if not self.messages:
            return None
        for msg in self._get_messages("time_zone"):
            name = self._get_field_from_msg(msg, "name")
            if name:
                return str(name)
        return None

    def _get_device_utc_offset_minutes(self) -> Optional[int]:
        """Return device UTC offset in minutes from settings, if present."""
        if not self.messages:
            return None
        for msg in self._get_messages("device_settings"):
            offset = (
                self._get_field_from_msg(msg, "utc_offset")
                or self._get_field_from_msg(msg, "timezone_offset")
            )
            if isinstance(offset, (int, float)):
                # offset is typically seconds; convert to minutes
                return int(round(offset / 60))
        return None

    def _infer_timezone_from_session_times(self) -> Optional[str]:
        """Infer timezone from session timestamp vs local start time."""
        session = self.session_msg
        if not session:
            return None

        start_time = self._get_raw_field_from_msg(session, "start_time")
        timestamp = self._get_field_from_msg(session, "timestamp")
        duration = self._get_field_from_msg(session, "total_elapsed_time")

        if duration is None:
            return None

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
        if not self.messages:
            return None
        activity_msg = None
        for msg in self._get_messages("activity"):
            activity_msg = msg
            break
        if not activity_msg:
            return None

        local_time = (
            self._get_raw_field_from_msg(activity_msg, "local_time")
            or self._get_raw_field_from_msg(activity_msg, "local_timestamp")
        )
        timestamp = self._get_field_from_msg(activity_msg, "timestamp")
        return infer_timezone_from_activity(local_time, timestamp)

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
        for record in self._get_messages("record"):
            fields = record.get("fields", {})
            lat = fields.get("position_lat")
            lon = fields.get("position_long")
            if lat is not None and lon is not None:
                if lat.value is not None and lon.value is not None:
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

    def _get_calories(self) -> Optional[float]:
        """Get total calories from session message."""
        session = self.session_msg
        calories = self._get_field_from_msg(session, "total_calories")
        return float(calories) if calories is not None else None


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def compute_bytes_hash(file_bytes: bytes) -> str:
    """Compute SHA256 hash of in-memory bytes."""
    sha256_hash = hashlib.sha256()
    sha256_hash.update(file_bytes)
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
