"""Blob processing audit trail for idempotency and replay."""

import base64
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from TrainingAnalyticsPlatform.storage.protocols import StorageInfrastructureProtocol

logger = logging.getLogger(__name__)


@dataclass
class SourceIngestionStateEntity:
    """Data model for blob ingestion state tracking."""

    blob_name: str
    athlete_id: str
    source_name: str
    status: str  # "fetched", "processed", "failed"
    created_utc: datetime
    last_updated_utc: datetime
    error_message: Optional[str] = None

    def to_table_entity(self) -> Dict[str, Any]:
        """Convert to Azure Table Storage entity."""
        entity = asdict(self)
        entity["PartitionKey"] = _partition_key_for_source_athlete(
            self.source_name,
            self.athlete_id,
        )
        entity["RowKey"] = _row_key_for_blob_name(self.blob_name)
        return entity

    @staticmethod
    def from_table_entity(entity: Dict[str, Any]) -> "SourceIngestionStateEntity":
        """Convert from Azure Table Storage entity."""
        created_utc = entity.get("created_utc")
        if created_utc is None:
            created_utc = datetime.now(timezone.utc)
        last_updated_utc = entity.get("last_updated_utc")
        if last_updated_utc is None:
            last_updated_utc = datetime.now(timezone.utc)
        
        return SourceIngestionStateEntity(
            blob_name=entity.get("RowKey", ""),
            athlete_id=entity.get("athlete_id", ""),
            source_name=entity.get("source_name", ""),
            status=entity.get("status", ""),
            created_utc=created_utc,
            last_updated_utc=last_updated_utc,
            error_message=entity.get("error_message"),
        )


class SourceIngestionStateStorage:
    """CRUD layer for blob processing state tracking."""

    def __init__(self, storage_client: StorageInfrastructureProtocol):
        """Initialize with table storage client.

        Args:
            storage_client: Azure Table Storage client
        """
        self.storage_client = storage_client

    def record_blob_fetched(
        self,
        source_name: str,
        athlete_id: str,
        blob_name: str,
    ) -> None:
        """Record blob as fetched from source.

        Args:
            source_name: Source identifier
            athlete_id: Athlete identifier
            blob_name: Blob name (including prefix, e.g., 'garmin/123/blob.json')
        """
        table_client = self.storage_client.get_table_client("SourceIngestionState")
        entity = SourceIngestionStateEntity(
            blob_name=blob_name,
            athlete_id=athlete_id,
            source_name=source_name,
            status="fetched",
            created_utc=datetime.now(timezone.utc),
            last_updated_utc=datetime.now(timezone.utc),
        )
        table_entity = entity.to_table_entity()
        table_client.upsert_entity(table_entity)

    def record_blob_processed(self, blob_name: str) -> None:
        """Record blob as successfully processed (upserted to table).

        Args:
            blob_name: Blob name
        """
        table_client = self.storage_client.get_table_client("SourceIngestionState")

        filter_str = f"blob_name eq '{_escape_odata_string(blob_name)}'"
        entities = list(table_client.query_entities(filter_str))
        for entity in entities:
            if entity.get("blob_name") == blob_name:
                entity["status"] = "processed"
                entity["last_updated_utc"] = datetime.now(timezone.utc)
                table_client.upsert_entity(entity)
                return

    def record_blob_failed(self, blob_name: str, error: str) -> None:
        """Record blob as failed (with error message).

        Args:
            blob_name: Blob name
            error: Error message
        """
        table_client = self.storage_client.get_table_client("SourceIngestionState")

        filter_str = f"blob_name eq '{_escape_odata_string(blob_name)}'"
        entities = list(table_client.query_entities(filter_str))
        for entity in entities:
            if entity.get("blob_name") == blob_name:
                entity["status"] = "failed"
                entity["error_message"] = error
                entity["last_updated_utc"] = datetime.now(timezone.utc)
                table_client.upsert_entity(entity)
                return

    def is_processed(self, blob_name: str) -> bool:
        """Check if blob has been successfully processed (idempotency check).

        Args:
            blob_name: Blob name

        Returns:
            True if blob status is 'processed', False otherwise
        """
        table_client = self.storage_client.get_table_client("SourceIngestionState")

        filter_str = f"blob_name eq '{_escape_odata_string(blob_name)}'"
        entities = list(table_client.query_entities(filter_str))
        for entity in entities:
            if entity.get("blob_name") == blob_name:
                return entity.get("status") == "processed"

        return False

    def get_fetched_blobs(
        self, source_name: str, athlete_id: str
    ) -> List[SourceIngestionStateEntity]:
        """Query all blobs for a source/athlete that are fetched but not yet processed.

        Args:
            source_name: Source identifier
            athlete_id: Athlete identifier

        Returns:
            List of fetched (not processed) blobs
        """
        table_client = self.storage_client.get_table_client("SourceIngestionState")

        partition_key = _partition_key_for_source_athlete(source_name, athlete_id)
        filter_str = f"PartitionKey eq '{partition_key}' and status eq 'fetched'"

        entities = list(table_client.query_entities(filter_str))
        return [SourceIngestionStateEntity.from_table_entity(e) for e in entities]


def _row_key_for_blob_name(blob_name: str) -> str:
    """Create a Table Storage-safe RowKey from a blob name."""
    encoded = base64.urlsafe_b64encode(blob_name.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _escape_odata_string(value: str) -> str:
    """Escape single quotes for OData filter literals."""
    return value.replace("'", "''")


def _sanitize_table_key_component(value: str) -> str:
    """Sanitize Azure Table key components by replacing forbidden characters."""
    return (
        value.replace("/", "_")
        .replace("\\", "_")
        .replace("#", "_")
        .replace("?", "_")
    )


def _partition_key_for_source_athlete(source_name: str, athlete_id: str) -> str:
    """Create a Table Storage-safe PartitionKey for source+athlete."""
    safe_source = _sanitize_table_key_component(source_name)
    safe_athlete = _sanitize_table_key_component(athlete_id)
    return f"{safe_source}|{safe_athlete}"
