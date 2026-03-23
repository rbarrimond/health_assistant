"""Contract tests for Garmin activity index entity model."""

from datetime import datetime, timezone

import pytest

from TrainingAnalyticsPlatform.storage.garmin_activity_index import (
    GARMIN_ACTIVITY_INDEX_PAYLOAD_SCHEMA_VERSION,
    GARMIN_ACTIVITY_INDEX_TABLE,
    GarminActivityIndexEntity,
)


def test_activity_index_contract_preserves_required_fields_and_payload_json() -> None:
    listed_at = datetime(2026, 3, 22, 10, 30, tzinfo=timezone.utc)
    payload = {
        "activityId": 123456,
        "startTimeGMT": "2026-03-20T06:15:00.000Z",
        "activityName": "Morning Ride",
        "distance": 42195.0,
    }

    entity = GarminActivityIndexEntity.from_activity_payload(
        athlete_id="rob",
        activity_payload=payload,
        listed_at_utc=listed_at,
    )

    table_entity = entity.to_table_entity()

    assert GARMIN_ACTIVITY_INDEX_TABLE == "GarminActivityIndex"
    assert table_entity["PartitionKey"] == "rob"
    assert table_entity["RowKey"].startswith("20260320T061500Z|")
    assert table_entity["activity_id"] == "123456"
    assert table_entity["source_start_time_utc"] == "2026-03-20T06:15:00+00:00"
    assert table_entity["last_listed_at_utc"] == "2026-03-22T10:30:00+00:00"
    assert (
        table_entity["payload_schema_version"]
        == GARMIN_ACTIVITY_INDEX_PAYLOAD_SCHEMA_VERSION
    )
    assert '"activityName":"Morning Ride"' in table_entity["raw_activity_payload_json"]


def test_activity_index_contract_raises_when_required_fields_missing() -> None:
    with pytest.raises(ValueError, match="activityId"):
        GarminActivityIndexEntity.from_activity_payload(
            athlete_id="rob",
            activity_payload={"startTimeGMT": "2026-03-20T06:15:00.000Z"},
        )

    with pytest.raises(ValueError, match="startTimeGMT"):
        GarminActivityIndexEntity.from_activity_payload(
            athlete_id="rob",
            activity_payload={"activityId": 123456},
        )
