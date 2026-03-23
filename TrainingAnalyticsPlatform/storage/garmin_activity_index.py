"""Garmin activity index entity contract and keying helpers.

Phase 1 scope:
- Define canonical persisted shape for raw Garmin list payloads.
- Define partition/row key strategy for athlete + time-window queries.

This module intentionally does not implement CRUD/query orchestration yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict


GARMIN_ACTIVITY_INDEX_TABLE = "GarminActivityIndex"
GARMIN_ACTIVITY_INDEX_PAYLOAD_SCHEMA_VERSION = "1.0.0"


def _sanitize_table_key_component(value: str) -> str:
    """Return a Table Storage-safe key component."""
    return (
        value.replace("/", "_")
        .replace("\\", "_")
        .replace("#", "_")
        .replace("?", "_")
    )


def normalize_garmin_timestamp(value: str) -> str:
    """Normalize Garmin timestamps to canonical UTC ISO-8601 string."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _row_key_from_timestamp_activity(
    source_start_time_utc: str,
    activity_id: str,
) -> str:
    """Build a lexicographically sortable row key (ascending UTC time)."""
    parsed = datetime.fromisoformat(source_start_time_utc.replace("Z", "+00:00"))
    timestamp_key = parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp_key}|{_sanitize_table_key_component(activity_id)}"


@dataclass(frozen=True)
class GarminActivityIndexEntity:
    """Canonical persisted row shape for Garmin list activity payloads."""

    partition_key: str
    row_key: str
    athlete_id: str
    activity_id: str
    source_start_time_utc: str
    last_listed_at_utc: str
    payload_schema_version: str
    raw_activity_payload_json: str

    @classmethod
    def from_activity_payload(
        cls,
        athlete_id: str,
        activity_payload: Dict[str, Any],
        *,
        listed_at_utc: datetime | None = None,
        payload_schema_version: str = GARMIN_ACTIVITY_INDEX_PAYLOAD_SCHEMA_VERSION,
    ) -> "GarminActivityIndexEntity":
        """Build entity preserving the exact Garmin activity payload as JSON."""
        raw_activity_id = activity_payload.get("activityId")
        raw_start_time_utc = activity_payload.get("startTimeGMT")

        if raw_activity_id is None:
            raise ValueError("Garmin activity payload missing required field: activityId")
        if raw_start_time_utc is None:
            raise ValueError("Garmin activity payload missing required field: startTimeGMT")

        activity_id = str(raw_activity_id)
        source_start_time_utc = normalize_garmin_timestamp(str(raw_start_time_utc))
        listed_at = listed_at_utc or datetime.now(timezone.utc)

        return cls(
            partition_key=_sanitize_table_key_component(athlete_id),
            row_key=_row_key_from_timestamp_activity(source_start_time_utc, activity_id),
            athlete_id=athlete_id,
            activity_id=activity_id,
            source_start_time_utc=source_start_time_utc,
            last_listed_at_utc=listed_at.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            payload_schema_version=payload_schema_version,
            raw_activity_payload_json=json.dumps(
                activity_payload,
                separators=(",", ":"),
                ensure_ascii=False,
                sort_keys=False,
                default=str,
            ),
        )

    def to_table_entity(self) -> Dict[str, Any]:
        """Convert entity to Azure Table Storage dictionary payload."""
        return {
            "PartitionKey": self.partition_key,
            "RowKey": self.row_key,
            "athlete_id": self.athlete_id,
            "activity_id": self.activity_id,
            "source_start_time_utc": self.source_start_time_utc,
            "last_listed_at_utc": self.last_listed_at_utc,
            "payload_schema_version": self.payload_schema_version,
            "raw_activity_payload_json": self.raw_activity_payload_json,
        }