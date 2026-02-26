"""Canonical substrate models for 1 Hz time-series and lap data.

These models define the schema for Parquet-stored canonical workout data.
All analytics are computed from this substrate by CanonicalAnalyticsEngine.
"""

from datetime import datetime
from functools import cached_property
from typing import Any, Dict, List, Optional, cast

import pandas as pd
from fitdecode import FitDataMessage
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .constants import ISO_8601_UTC_DESC


class CanonicalRecord(BaseModel):
    """1 Hz time-series record for canonical substrate.

    This is the primary storage format for workout telemetry at 1 Hz resolution.
    Stored in Parquet format for efficient querying. All analytics are computed
    from this canonical substrate by CanonicalAnalyticsEngine.

    Core telemetry: power_watts, heart_rate_bpm, cadence_rpm, speed_mps
    Extended telemetry: distance_m, elevation_m, temperature_c,
    respiration_rate_brpm, lr_balance_pct, rr_interval_sec
    """

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
    rr_interval_sec: Optional[float] = Field(None, ge=0)

    @classmethod
    def from_fit_message(
        cls,
        msg: FitDataMessage,
        start_dt: Optional[datetime] = None,
    ) -> Optional["CanonicalRecord"]:
        """Build CanonicalRecord from FIT record message.

        Args:
            msg: FitDataMessage with name="record"
            start_dt: Workout start datetime for elapsed_sec calculation

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
        speed = msg.get_value("speed", fallback=None)
        distance = msg.get_value("distance", fallback=None)
        elevation = msg.get_value("altitude", fallback=None)
        temperature = msg.get_value("temperature", fallback=None)
        lr_balance = msg.get_value("left_right_balance", fallback=None)
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
            rr_interval_sec=None,  # Sourced from HRV messages, not record messages
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
    _start_dt: Optional[datetime] = PrivateAttr(default=None)

    def __init__(
        self,
        messages: List[FitDataMessage],
        start_dt: Optional[datetime] = None,
        **data,
    ):
        """Initialize with raw FIT messages.

        Args:
            messages: List of FitDataMessage instances (will be filtered to record messages)
            start_dt: Workout start datetime for elapsed_sec calculation
            **data: Additional Pydantic model fields
        """
        super().__init__(**data)
        self._messages = messages
        self._start_dt = start_dt

    @classmethod
    def from_fit_messages(
        cls,
        messages: List[FitDataMessage],
        start_dt: Optional[datetime] = None,
    ) -> "CanonicalRecordSet":
        """Create CanonicalRecordSet from FIT messages.

        Filters messages to only include record-type messages.

        Args:
            messages: All FIT messages from file
            start_dt: Workout start datetime for elapsed_sec calculation

        Returns:
            CanonicalRecordSet with filtered record messages
        """
        record_messages = [msg for msg in messages if msg.name == "record"]
        return cls(messages=record_messages, start_dt=start_dt)

    @cached_property
    def to_dataframe(self) -> pd.DataFrame:
        """Build DataFrame from canonical records.

        Lazily constructs and caches DataFrame conforming to CanonicalRecord schema.
        Ready for Parquet serialization.

        Returns:
            DataFrame with CanonicalRecord schema, empty if no valid records
        """
        records: List[Dict[str, Any]] = []
        for msg in self._messages:
            record = CanonicalRecord.from_fit_message(msg, self._start_dt)
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
