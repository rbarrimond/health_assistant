"""Unit tests for source ingestion state storage."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.storage.source_ingestion_state import (
    SourceIngestionStateEntity,
    SourceIngestionStateStorage,
)


def _build_storage(table_client: MagicMock) -> SourceIngestionStateStorage:
    infra = MagicMock()
    infra.get_table_client.return_value = table_client
    return SourceIngestionStateStorage(infra)


def test_to_table_entity_uses_rowkey_safe_encoding() -> None:
    """RowKey must be safe for Azure Table Storage key constraints."""
    entity = SourceIngestionStateEntity(
        blob_name="physiometrics/athlete-1/intervals/daily/2026-03-01_to_2026-03-16.json",
        athlete_id="athlete-1",
        source_name="intervals",
        status="fetched",
        created_utc=datetime.now(timezone.utc),
        last_updated_utc=datetime.now(timezone.utc),
    )

    table_entity = entity.to_table_entity()

    assert table_entity["PartitionKey"] == "intervals|athlete-1"
    assert table_entity["blob_name"] == entity.blob_name
    assert table_entity["RowKey"]
    assert "/" not in table_entity["RowKey"]
    assert "#" not in table_entity["RowKey"]
    assert "?" not in table_entity["RowKey"]


def test_to_table_entity_sanitizes_partition_key_forbidden_chars() -> None:
    """PartitionKey must exclude Azure-forbidden characters."""
    entity = SourceIngestionStateEntity(
        blob_name="physiometrics/athlete-1/intervals/daily/blob.json",
        athlete_id="athlete#1/segment?abc",
        source_name="inter/vals",
        status="fetched",
        created_utc=datetime.now(timezone.utc),
        last_updated_utc=datetime.now(timezone.utc),
    )

    table_entity = entity.to_table_entity()
    partition_key = table_entity["PartitionKey"]

    assert partition_key
    assert "/" not in partition_key
    assert "\\" not in partition_key
    assert "#" not in partition_key
    assert "?" not in partition_key


def test_record_blob_fetched_persists_original_blob_name_and_safe_rowkey() -> None:
    """Fetched records should preserve blob_name while using encoded RowKey."""
    table_client = MagicMock()
    storage = _build_storage(table_client)

    blob_name = "physiometrics/athlete-1/intervals/daily/2026-03-01_to_2026-03-16.json"
    storage.record_blob_fetched(
        source_name="intervals",
        athlete_id="athlete-1",
        blob_name=blob_name,
    )

    table_client.upsert_entity.assert_called_once()
    entity = table_client.upsert_entity.call_args[0][0]

    assert entity["blob_name"] == blob_name
    assert entity["RowKey"]
    assert "/" not in entity["RowKey"]


def test_record_blob_processed_queries_by_blob_name() -> None:
    """Processed update should locate entities using blob_name property."""
    table_client = MagicMock()
    blob_name = "physiometrics/athlete-1/intervals/daily/2026-03-01_to_2026-03-16.json"
    table_client.query_entities.return_value = [
        {
            "PartitionKey": "intervals#athlete-1",
            "RowKey": "encoded-key",
            "blob_name": blob_name,
            "status": "fetched",
        }
    ]

    storage = _build_storage(table_client)
    storage.record_blob_processed(blob_name)

    table_client.query_entities.assert_called_once_with(
        "blob_name eq 'physiometrics/athlete-1/intervals/daily/2026-03-01_to_2026-03-16.json'"
    )
    table_client.upsert_entity.assert_called_once()
    updated_entity = table_client.upsert_entity.call_args[0][0]
    assert updated_entity["status"] == "processed"
