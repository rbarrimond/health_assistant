"""Tests for GarminActivityIndexStorage operations."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.garmin_activity_index_storage import (
    GarminActivityIndexStorage,
)
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure



def _sample_payload(*, activity_id: int = 123) -> dict:
    return {
        "activityId": activity_id,
        "startTimeGMT": "2026-03-20T06:15:00.000Z",
        "activityName": "Morning Ride",
        "distance": 12345.6,
    }


def test_upsert_activity_payload_writes_table_entity() -> None:
    table_client = MagicMock()
    infrastructure = MagicMock(spec=StorageInfrastructure)
    infrastructure.get_table_client.return_value = table_client
    storage = GarminActivityIndexStorage(infrastructure)

    storage.upsert_activity_payload(
        athlete_id="rob",
        activity_payload=_sample_payload(),
        listed_at_utc=datetime(2026, 3, 22, 10, 30, tzinfo=timezone.utc),
    )

    table_client.upsert_entity.assert_called_once()
    entity = table_client.upsert_entity.call_args.args[0]
    assert entity["PartitionKey"] == "rob"
    assert entity["activity_id"] == "123"


def test_query_activity_payloads_by_lookback_deserializes_raw_payloads() -> None:
    table_client = MagicMock()
    table_client.query_entities.return_value = [
        {
            "raw_activity_payload_json": '{"activityId":123,"startTimeGMT":"2026-03-20T06:15:00.000Z"}'
        },
        {
            "raw_activity_payload_json": '{"activityId":456,"startTimeGMT":"2026-03-21T06:15:00.000Z"}'
        },
    ]
    infrastructure = MagicMock(spec=StorageInfrastructure)
    infrastructure.get_table_client.return_value = table_client
    storage = GarminActivityIndexStorage(infrastructure)

    payloads = storage.query_activity_payloads_by_lookback(
        athlete_id="rob",
        lookback_days=3,
        now_utc=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert [item["activityId"] for item in payloads] == [123, 456]


def test_get_latest_indexed_start_time_utc_returns_latest_value() -> None:
    table_client = MagicMock()
    table_client.query_entities.return_value = [
        {"source_start_time_utc": "2026-03-20T06:15:00+00:00"},
        {"source_start_time_utc": "2026-03-21T08:00:00+00:00"},
    ]
    infrastructure = MagicMock(spec=StorageInfrastructure)
    infrastructure.get_table_client.return_value = table_client
    storage = GarminActivityIndexStorage(infrastructure)

    latest = storage.get_latest_indexed_start_time_utc(athlete_id="rob")

    assert latest == "2026-03-21T08:00:00+00:00"


def test_get_indexed_day_coverage_returns_unique_days() -> None:
    table_client = MagicMock()
    table_client.query_entities.return_value = [
        {"source_start_time_utc": "2026-03-20T06:15:00+00:00"},
        {"source_start_time_utc": "2026-03-20T11:15:00+00:00"},
        {"source_start_time_utc": "2026-03-21T08:00:00+00:00"},
    ]
    infrastructure = MagicMock(spec=StorageInfrastructure)
    infrastructure.get_table_client.return_value = table_client
    storage = GarminActivityIndexStorage(infrastructure)

    coverage = storage.get_indexed_day_coverage(
        athlete_id="rob",
        lookback_days=3,
        now_utc=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
    )

    assert coverage == {"2026-03-20", "2026-03-21"}


def test_upsert_activity_payload_translates_storage_errors() -> None:
    table_client = MagicMock()
    table_client.upsert_entity.side_effect = HttpResponseError("boom")
    infrastructure = MagicMock(spec=StorageInfrastructure)
    infrastructure.get_table_client.return_value = table_client
    storage = GarminActivityIndexStorage(infrastructure)

    with pytest.raises(StorageError):
        storage.upsert_activity_payload(
            athlete_id="rob",
            activity_payload=_sample_payload(),
        )
