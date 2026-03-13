"""Canonical substrate models for 1 Hz time-series and lap data.

These models define the schema for Parquet-stored canonical workout data.
All analytics are computed from this substrate by CanonicalAnalyticsEngine.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple, cast

import pandas as pd
from fitdecode import FitDataMessage
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from .constants import ISO_8601_UTC_DESC

logger = logging.getLogger(__name__)


class CanonicalRecord(BaseModel):
    """1 Hz time-series record for canonical substrate.

    This is the primary storage format for workout telemetry at 1 Hz resolution.
    Stored in Parquet format for efficient querying. All analytics are computed
    from this canonical substrate by CanonicalAnalyticsEngine.

    Core telemetry: power_watts, heart_rate_bpm, cadence_rpm, speed_mps
    Extended telemetry: distance_m, elevation_m, temperature_c,
    respiration_rate_brpm, lr_balance_pct, rr_interval_sec
    """

    @staticmethod
    def _numeric_with_unit_confirmation(
        msg: FitDataMessage,
        field_name: str,
        *,
        expected_units: Tuple[str, ...],
        conversion_by_unit: Optional[Dict[str, float]] = None,
    ) -> Optional[float]:
        """Read a numeric FIT field and normalize based on fitdecode-reported units."""
        value = msg.get_value(field_name, fallback=None)
        if not isinstance(value, (int, float)):
            return None

        normalized_value = float(value)
        field_units: Optional[str] = None

        try:
            field_data = msg.get_field(field_name)
            units = getattr(field_data, "units", None)
            if isinstance(units, str) and units.strip():
                field_units = units.strip().lower()
        except (AttributeError, KeyError, TypeError):
            field_units = None
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to inspect FIT units metadata for canonical record field",
                extra={"field_name": field_name},
                exc_info=True,
            )
            field_units = None

        expected_units_normalized = {unit.lower() for unit in expected_units}
        conversion_map = {k.lower(): v for k, v in (conversion_by_unit or {}).items()}

        if field_units is None or field_units in expected_units_normalized:
            return normalized_value

        if field_units in conversion_map:
            return normalized_value * conversion_map[field_units]

        logger.warning(
            "Unexpected FIT units for canonical record field",
            extra={
                "field_name": field_name,
                "field_units": field_units,
                "expected_units": sorted(expected_units_normalized),
            },
        )
        return normalized_value

    timestamp_utc: str = Field(description=ISO_8601_UTC_DESC)
    elapsed_sec: Optional[float] = Field(None, ge=0)
    power_watts: Optional[float] = Field(None, ge=0)
    heart_rate_bpm: Optional[float] = Field(None, ge=0)
    cadence_rpm: Optional[float] = Field(None, ge=0)
    speed_mps: Optional[float] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)
    elevation_m: Optional[float] = Field(None)
    temperature_c: Optional[float] = Field(None)
    respiration_rate_brpm: Optional[float] = Field(None, ge=0)
    lr_balance_pct: Optional[float] = Field(None, ge=0, le=100)
    rr_intervals_sec: Tuple[float, ...] = Field(default=())

    @field_validator("rr_intervals_sec", mode="before")
    @classmethod
    def validate_rr_intervals(cls, v: Any) -> Tuple[float, ...]:
        """Validate rr_intervals_sec: ensure tuple type and all elements are non-negative."""
        if v is None:
            return ()
        if isinstance(v, (list, tuple)):
            # Convert to tuple and validate each element
            intervals = tuple(float(x) for x in v)
            for interval in intervals:
                if interval < 0:
                    raise ValueError("All RR intervals must be non-negative")
            return intervals
        raise ValueError("rr_intervals_sec must be a tuple or list of floats")

    @classmethod
    def from_fit_message(
        cls,
        msg: FitDataMessage,
        start_dt: Optional[datetime] = None,
        rr_intervals_sec: Tuple[float, ...] = (),
    ) -> Optional["CanonicalRecord"]:
        """Build CanonicalRecord from FIT record message.

        Args:
            msg: FitDataMessage with name="record"
            start_dt: Workout start datetime for elapsed_sec calculation
            rr_intervals_sec: RR intervals (in seconds) grouped to this record's 1Hz timestamp

        Returns:
            CanonicalRecord instance, or None if timestamp is invalid
        """
        timestamp = msg.get_value("timestamp", fallback=None)
        if not isinstance(timestamp, datetime):
            return None

        timestamp_utc = timestamp.isoformat()

        elapsed_sec = None
        if start_dt is not None:
            try:
                elapsed_sec = (timestamp - start_dt).total_seconds()
            except TypeError:
                elapsed_sec = None

        # Extract telemetry with safe fallback
        power = msg.get_value("power", fallback=None)
        heart_rate = msg.get_value("heart_rate", fallback=None)
        cadence = msg.get_value("cadence", fallback=None)
        speed = cls._numeric_with_unit_confirmation(
            msg,
            "speed",
            expected_units=("m/s",),
            conversion_by_unit={"km/h": 1 / 3.6},
        )
        distance = cls._numeric_with_unit_confirmation(
            msg,
            "distance",
            expected_units=("m",),
            conversion_by_unit={"km": 1000.0},
        )
        elevation = msg.get_value("altitude", fallback=None)
        temperature = msg.get_value("temperature", fallback=None)

        # FIT record message left_right_balance is uint8 with bits 0-6 containing
        # the percentage value (0-127 range) and bit 7 containing a right-side flag.
        # Use get_raw_value() to bypass enum rendering (0x80 → 'right', 0x7F → 'mask')
        # and work with the numeric byte directly for masking.
        lr_balance = None
        lr_balance_raw = msg.get_raw_value("left_right_balance", fallback=None)
        if lr_balance_raw is not None and isinstance(lr_balance_raw, (int, float)):
            raw_value = int(lr_balance_raw)
            masked_value = raw_value & 0x7F  # Extract bits 0-6 (percentage, 0-127)
            if masked_value != raw_value:
                logger.debug(
                    "Normalized left/right balance from FIT raw byte",
                    extra={
                        "fit_field_decode": {
                            "field": "left_right_balance",
                            "raw_byte": raw_value,
                            "masked_percentage": masked_value,
                        }
                    },
                )
            lr_balance = float(masked_value)

        # Note: respiration_rate and rr_interval require special handling
        # respiration_rate is rare and device-specific
        # rr_interval comes from HRV messages, not record messages

        return cls(
            timestamp_utc=timestamp_utc,
            elapsed_sec=elapsed_sec,
            power_watts=cast(Optional[float], power),
            heart_rate_bpm=cast(Optional[float], heart_rate),
            cadence_rpm=cast(Optional[float], cadence),
            speed_mps=cast(Optional[float], speed),
            distance_m=cast(Optional[float], distance),
            elevation_m=cast(Optional[float], elevation),
            temperature_c=cast(Optional[float], temperature),
            respiration_rate_brpm=None,  # Requires device-specific handling
            lr_balance_pct=cast(Optional[float], lr_balance),
            rr_intervals_sec=rr_intervals_sec,
        )



class CanonicalRecordSet(BaseModel):
    """DTO container for canonical record time-series data.

    Wraps raw FIT record messages and provides typed conversion to CanonicalRecord
    instances and DataFrame for Parquet storage. Enforces the "single source of
    truth" contract between FIT messages, typed records, and storage schema.

    This class owns the transformation from FitDataMessage → CanonicalRecord → DataFrame.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _messages: List[FitDataMessage] = PrivateAttr()
    _all_messages: List[FitDataMessage] = PrivateAttr()
    _start_dt: Optional[datetime] = PrivateAttr(default=None)

    def __init__(
        self,
        messages: List[FitDataMessage],
        start_dt: Optional[datetime] = None,
        all_messages: Optional[List[FitDataMessage]] = None,
        **data,
    ):
        """Initialize with raw FIT messages.

        Args:
            messages: List of FitDataMessage instances (will be filtered to record messages)
            start_dt: Workout start datetime for elapsed_sec calculation
            all_messages: Complete list of all FIT messages (used for HRV context)
            **data: Additional Pydantic model fields
        """
        super().__init__(**data)
        self._messages = messages
        self._all_messages = all_messages or messages
        self._start_dt = start_dt

    @classmethod
    def from_fit_messages(
        cls,
        messages: List[FitDataMessage],
        start_dt: Optional[datetime] = None,
    ) -> "CanonicalRecordSet":
        """Create CanonicalRecordSet from FIT messages.

        Filters messages to only include record-type messages but retains
        all messages for HRV context.

        Args:
            messages: All FIT messages from file
            start_dt: Workout start datetime for elapsed_sec calculation

        Returns:
            CanonicalRecordSet with filtered record messages
        """
        record_messages = [msg for msg in messages if msg.name == "record"]
        return cls(messages=record_messages, start_dt=start_dt, all_messages=messages)

    def _build_hrv_interval_map(  # noqa: S3776,C901
        self,
        all_messages: List[FitDataMessage],
    ) -> Dict[int, Tuple[float, ...]]:
        """Build order-preserving map of 1Hz floor timestamps to RR interval tuples.

        Processes HRV messages to extract RR intervals (already in seconds from fitdecode),
        reconstructs beat timestamps, and groups by 1Hz canonical time grid.

        **Preservation Invariants:**
        - Stream order: Iterates HRV messages in original list order
        - Field order: Within each message, extracts time0, time1, ... in sorted key order
        - No re-ordering: Uses defaultdict to maintain insertion order (Python 3.7+)
        - No drops: Beats outside record range are assigned to nearest floor timestamp

        Args:
            all_messages: Complete FIT message list (needed for anchoring derivation)

        Returns:
            Dict mapping int(floor(beat_timestamp)) → Tuple[float, ...] of intervals,
            preserving original order within each second
        """
        hrv_messages = [msg for msg in all_messages if msg.name == "hrv"]
        if not hrv_messages:
            return {}

        # Build record message index for fallback anchoring (used when HRV lacks timestamp)
        record_messages = [msg for msg in all_messages if msg.name == "record"]
        record_timestamps: List[datetime] = []
        for msg in record_messages:
            ts = msg.get_value("timestamp", fallback=None)
            if isinstance(ts, datetime):
                record_timestamps.append(ts)

        # Map: floor(beat_timestamp_seconds) → list of RR intervals (preserving order)
        intervals_by_floor: Dict[int, List[float]] = defaultdict(list)

        for hrv_idx, hrv_msg in enumerate(hrv_messages):
            hrv_timestamp = hrv_msg.get_value("timestamp", fallback=None)

            # **Mode 1: HRV message includes timestamp (authoritative)**
            if isinstance(hrv_timestamp, datetime):
                # Reconstruct beat timestamps from cumulative sum of RR intervals
                current_beat_ts = hrv_timestamp.timestamp()

                # Extract time fields matching pattern time\d+ (not timestamp!)
                # Sort by numeric suffix to preserve field order (time0, time1, ...)
                time_fields = []
                for field in hrv_msg.fields:
                    match = re.match(r"^time(\d+)$", field.name)
                    if match:
                        time_fields.append(
                            (int(match.group(1)), field.name, field.value)
                        )

                # Sort by numeric index
                time_fields = sorted(time_fields, key=lambda x: x[0])

                for _idx, _fname, rr_sec in time_fields:
                    if not isinstance(rr_sec, (int, float)) or rr_sec <= 0:
                        continue

                    current_beat_ts += rr_sec
                    floor_sec = int(current_beat_ts)
                    intervals_by_floor[floor_sec].append(float(rr_sec))

            # **Mode 2: HRV message lacks timestamp (derive from preceding record)**
            else:
                if not record_timestamps:
                    logger.warning(
                        "HRV message %d lacks timestamp and no record messages "
                        "exist; skipping",
                        hrv_idx,
                    )
                    continue

                # Anchor to record immediately preceding this HRV message
                # Find last record with timestamp ≤ current processing position
                anchor_ts = record_timestamps[-1].timestamp()
                current_beat_ts = anchor_ts

                time_fields = []
                for field in hrv_msg.fields:
                    match = re.match(r"^time(\d+)$", field.name)
                    if match:
                        time_fields.append(
                            (int(match.group(1)), field.name, field.value)
                        )

                # Sort by numeric index
                time_fields = sorted(time_fields, key=lambda x: x[0])

                for _idx, _fname, rr_sec in time_fields:
                    if not isinstance(rr_sec, (int, float)) or rr_sec <= 0:
                        continue

                    current_beat_ts += rr_sec
                    floor_sec = int(current_beat_ts)
                    intervals_by_floor[floor_sec].append(float(rr_sec))

        # Convert lists to tuples to match return type signature
        return {floor: tuple(intervals) for floor, intervals in intervals_by_floor.items()}

    @cached_property
    def to_dataframe(self) -> pd.DataFrame:
        """Build DataFrame from canonical records.

        Lazily constructs and caches DataFrame conforming to CanonicalRecord schema.
        Ready for Parquet serialization.

        Returns:
            DataFrame with CanonicalRecord schema, empty if no valid records
        """
        records: List[Dict[str, Any]] = []

        # Build HRV interval map once for all records
        hrv_map = self._build_hrv_interval_map(self._all_messages)

        for msg in self._messages:
            # Extract timestamp for HRV lookup
            timestamp = msg.get_value("timestamp", fallback=None)
            rr_intervals = ()
            if isinstance(timestamp, datetime):
                floor_sec = int(timestamp.timestamp())
                rr_intervals = hrv_map.get(floor_sec, ())

            record = CanonicalRecord.from_fit_message(
                msg, self._start_dt, rr_intervals_sec=rr_intervals
            )
            if record:
                records.append(record.model_dump())

        if not records:
            return pd.DataFrame()

        return pd.DataFrame(records)


class CanonicalLap(BaseModel):
    """Lap-level summary record for canonical substrate.

    Deprecated: prefer laps.json artifacts for lap payloads.
    Stores lap summaries in Parquet format for querying multi-lap workouts.
    Complements CanonicalRecord time-series data with segment-level aggregates.
    """

    lap_index: int = Field(ge=0)
    start_time_utc: Optional[str] = Field(None, description=ISO_8601_UTC_DESC)
    elapsed_sec: Optional[float] = Field(None, ge=0)
    moving_time_sec: Optional[float] = Field(None, ge=0)
    distance_m: Optional[float] = Field(None, ge=0)
    calories_kcal: Optional[float] = Field(None, ge=0)
    avg_heart_rate_bpm: Optional[float] = Field(None, ge=0)
    max_heart_rate_bpm: Optional[float] = Field(None, ge=0)
    avg_power_watts: Optional[float] = Field(None, ge=0)
    max_power_watts: Optional[float] = Field(None, ge=0)
    avg_cadence_rpm: Optional[float] = Field(None, ge=0)
    max_cadence_rpm: Optional[float] = Field(None, ge=0)
