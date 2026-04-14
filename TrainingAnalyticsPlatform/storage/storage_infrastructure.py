"""Storage infrastructure for Azure Table and Blob client management."""

import gzip
import io
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field
from azure.data.tables import TableClient, TableServiceClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from TrainingAnalyticsPlatform.ingestion.constants import INGEST_VERSION
from TrainingAnalyticsPlatform.models import CanonicalRecordSet
from TrainingAnalyticsPlatform.platform.exceptions import (
    IngestionIdResolutionError,
)

CANONICAL_SCHEMA_VERSION = "2.0.3"
WORKOUTS_CONTAINER = "workouts"
EXTERNAL_SOURCES_CONTAINER = "external-sources"

logger = logging.getLogger(__name__)

MANAGED_TABLE_NAMES = (
    "Workouts",
    "WeeklyRollups",
    "IngestionState",
    "Physiometrics",
    "WithingsTokens",
    "OneDriveTokens",
    "GarminTokens",
    "WebhookDeduplication",
    "AgentPreferences",
    "AgentObservations",
    "SourceIngestionState",
    "TrainingState",
    "RateLimitDeferrals",
    "AsyncIngestionOperations",
    "GarminActivityIndex",
)


class WorkoutEntity(BaseModel):
    """Structured Workouts table entity (queryable subset).
    
    Schema: 2.0.0 - Pydantic validation with semantic constraints
    
    Properties are the queryable subset needed for identity, filtering, and sorting.
    All other enrichment and derived metrics live in the metadata.json blob (source of truth).
    Ingestion state and provenance tracking belong in IngestionState table.
    """

    model_config = ConfigDict(extra="forbid")

    partition_key: str = Field(..., min_length=1)
    row_key: str = Field(..., min_length=1)
    workout_id: str = Field(..., min_length=1)
    athlete_id: str = Field(..., min_length=1)
    ingestion_id: str = Field(..., min_length=1, description="Link to IngestionState table")
    canonical_schema_version: Optional[str] = None
    canonical_records_blob: Optional[str] = None
    records_count: Optional[int] = Field(None, ge=0)
    laps_count: Optional[int] = Field(None, ge=0)
    # Identity fields (queryable from metadata.identity zone)
    start_time_utc: Optional[str] = Field(None, description="ISO 8601 UTC timestamp")
    sport: Optional[str] = None
    sub_sport: Optional[str] = None
    duration_sec: Optional[float] = Field(None, gt=0, description="Total elapsed time (session.total_elapsed_time)")
    distance_m: Optional[float] = Field(None, ge=0)
    # Device identity (extracted cleanly from FIT file_id)
    device_manufacturer: Optional[str] = Field(None, description="e.g., Apple, Garmin, Wahoo")
    device_model: Optional[str] = Field(None, description="Full device name/model")
    # Capabilities (computed during ingestion from record messages)
    has_power: bool = False
    has_hr: bool = False
    has_gps: bool = False

    @classmethod
    def from_table_entity(cls, entity: Dict[str, Any]) -> "WorkoutEntity":
        """Create a WorkoutEntity from a raw Azure Table entity."""
        return cls(
            partition_key=entity.get("PartitionKey", ""),
            row_key=entity.get("RowKey", ""),
            workout_id=entity.get("workout_id", ""),
            ingestion_id=entity.get("ingestion_id", ""),
            athlete_id=entity.get("athlete_id", ""),
            canonical_schema_version=entity.get("canonical_schema_version"),
            canonical_records_blob=entity.get("canonical_records_blob"),
            records_count=entity.get("records_count"),
            laps_count=entity.get("laps_count"),
            start_time_utc=entity.get("start_time_utc"),
            sport=entity.get("sport"),
            sub_sport=entity.get("sub_sport"),
            duration_sec=entity.get("duration_sec"),
            distance_m=entity.get("distance_m"),
            device_manufacturer=entity.get("device_manufacturer"),
            device_model=entity.get("device_model"),
            has_power=entity.get("has_power", False),
            has_hr=entity.get("has_hr", False),
            has_gps=entity.get("has_gps", False),
        )

    def to_entity(self) -> Dict[str, Any]:
        """Convert WorkoutEntity to dictionary for Azure Table Storage.

        Returns:
            Dict formatted for table upsert operation
        """
        entity = {
            "PartitionKey": self.partition_key,
            "RowKey": self.row_key,
            "workout_id": self.workout_id,
            "ingestion_id": self.ingestion_id,
            "athlete_id": self.athlete_id,
            "canonical_schema_version": self.canonical_schema_version,
            "canonical_records_blob": self.canonical_records_blob,
            "records_count": self.records_count,
            "laps_count": self.laps_count,
            "start_time_utc": self.start_time_utc,
            "sport": self.sport,
            "sub_sport": self.sub_sport,
            "duration_sec": self.duration_sec,
            "distance_m": self.distance_m,
            "device_manufacturer": self.device_manufacturer,
            "device_model": self.device_model,
            "has_power": self.has_power,
            "has_hr": self.has_hr,
            "has_gps": self.has_gps,
        }

        return entity


@dataclass
class IngestionStateEntity:
    """Structured IngestionState table entity."""

    partition_key: str
    row_key: str
    status: str
    first_seen_at_utc: str
    last_attempt_at_utc: str
    retry_count: int
    workout_id: Optional[str]
    ingestion_id: Optional[str] = None
    source_file_name: Optional[str] = None
    source_drive_id: Optional[str] = None
    source_etag: Optional[str] = None
    source_ctag: Optional[str] = None
    source_quickxor_hash: Optional[str] = None
    source_modified_at_utc: Optional[str] = None
    source_activity_name: Optional[str] = None
    file_sha256: Optional[str] = None
    ingest_version: Optional[str] = None
    ingested_at_utc: Optional[str] = None
    error_message: Optional[str] = None

    def to_entity(self) -> Dict:
        """Convert to dictionary representation for Azure Table Storage."""
        entity = {
            "PartitionKey": self.partition_key,
            "RowKey": self.row_key,
            "status": self.status,
            "first_seen_at_utc": self.first_seen_at_utc,
            "last_attempt_at_utc": self.last_attempt_at_utc,
            "retry_count": self.retry_count,
            "workout_id": self.workout_id,
        }
        if self.ingestion_id is not None:
            entity["ingestion_id"] = self.ingestion_id
        if self.source_file_name is not None:
            entity["source_file_name"] = self.source_file_name
        if self.source_drive_id is not None:
            entity["source_drive_id"] = self.source_drive_id
        if self.source_etag is not None:
            entity["source_etag"] = self.source_etag
        if self.source_ctag is not None:
            entity["source_ctag"] = self.source_ctag
        if self.source_quickxor_hash is not None:
            entity["source_quickxor_hash"] = self.source_quickxor_hash
        if self.source_modified_at_utc is not None:
            entity["source_modified_at_utc"] = self.source_modified_at_utc
        if self.source_activity_name is not None:
            entity["source_activity_name"] = self.source_activity_name
        if self.file_sha256 is not None:
            entity["file_sha256"] = self.file_sha256
        if self.ingest_version:
            entity["ingest_version"] = self.ingest_version
        if self.ingested_at_utc:
            entity["ingested_at_utc"] = self.ingested_at_utc
        if self.error_message:
            entity["error_message"] = self.error_message
        return entity


class IngestionContext:
    """Utility object for ingestion idempotency state and keying."""

    def __init__(
        self,
        athlete_id: str,
        file_info: Dict,
        workout_id: Optional[str],
        storage,  # WorkoutStorage-like object with get_ingestion_state
        ingestion_id: Optional[str] = None,
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict] = None,
    ):
        self.athlete_id = athlete_id
        self.file_info = file_info
        self.workout_id = workout_id
        self.ingestion_id = ingestion_id
        self.storage = storage

        self.ingestion_key = ingestion_key or self._build_ingestion_key()
        self.existing_state = (
            existing_state
            if existing_state is not None
            else self.storage.get_ingestion_state(athlete_id, self.ingestion_key)
        )

    def _build_ingestion_key(self) -> str:
        """Generate a unique ingestion key based on file information or workout ID."""
        ingestion_key = self.ingestion_id or self.file_info.get("ingestion_id")

        if ingestion_key is None:
            logger.error(
                "ingestion_id is required for ingestion state keying. File info: %s",
                self.file_info,
            )
            raise IngestionIdResolutionError(
                "ingestion_id is required for ingestion state keying"
            )

        return ingestion_key

    @property
    def is_ingested(self) -> bool:
        """Check if the ingestion state indicates the entity is already ingested."""
        return bool(self.existing_state and self.existing_state.get("status") == "ingested")

    @property
    def is_terminal(self) -> bool:
        """Check if the ingestion state represents a terminal (non-reingest) outcome."""
        return bool(
            self.existing_state
            and self.existing_state.get("status")
            in {"ingested", "skipped", "skipped_duplicate", "filtered"}
        )

    @property
    def retry_count(self) -> int:
        """Get the current retry count stored in the ingestion state."""
        if not self.existing_state:
            return 0
        return int(self.existing_state.get("retry_count", 0))

    def next_retry_count(self, status: str) -> int:
        """
        Compute the next retry count for the given status.

        Only increment on failures so idempotent re-processing does not inflate retries.
        """
        base_count = self.retry_count
        if status == "failed":
            return base_count + 1
        return base_count

    def is_unchanged(self) -> bool:
        """Check whether the incoming file metadata matches the last ingested state."""
        if not self.existing_state:
            return False

        existing_ctag = self.existing_state.get("source_ctag")
        incoming_ctag = self.file_info.get("source_ctag")
        if incoming_ctag and existing_ctag:
            return incoming_ctag == existing_ctag

        existing_qx = self.existing_state.get("source_quickxor_hash")
        incoming_qx = self.file_info.get("source_quickxor_hash")
        if incoming_qx and existing_qx:
            return incoming_qx == existing_qx

        existing_sha = self.existing_state.get("file_sha256")
        incoming_sha = self.file_info.get("file_sha256")
        if incoming_sha and existing_sha:
            return incoming_sha == existing_sha

        existing_etag = self.existing_state.get("source_etag")
        incoming_etag = self.file_info.get("source_etag")
        if incoming_etag and existing_etag:
            return incoming_etag == existing_etag

        existing_modified = self.existing_state.get("source_modified_at_utc")
        incoming_modified = self.file_info.get("source_modified_at_utc")
        if incoming_modified and existing_modified:
            return incoming_modified == existing_modified

        return False

    def should_skip(self) -> bool:
        """Return True only when an already-ingested file is unchanged."""
        return self.is_ingested and self.is_unchanged()

    @property
    def first_seen_at_utc(self) -> str:
        """Get the timestamp of the first time the entity was seen."""
        if self.existing_state and self.existing_state.get("first_seen_at_utc"):
            return self.existing_state["first_seen_at_utc"]
        return datetime.now(timezone.utc).isoformat()

    def build_state_entity(
        self,
        status: str,
        error: Optional[str] = None,
    ) -> IngestionStateEntity:
        """Build an IngestionStateEntity instance based on the current context."""
        now_utc = datetime.now(timezone.utc).isoformat()
        state_fields = {
            "source_etag": self.file_info.get("source_etag"),
            "source_ctag": self.file_info.get("source_ctag"),
            "source_quickxor_hash": self.file_info.get("source_quickxor_hash"),
            "source_modified_at_utc": self.file_info.get("source_modified_at_utc"),
            "file_sha256": self.file_info.get("file_sha256"),
            "source_file_name": self.file_info.get("source_file_name"),
            "source_drive_id": self.file_info.get("source_drive_id"),
            "source_activity_name": self.file_info.get("source_activity_name"),
        }
        if status == "skipped" and self.existing_state:
            for key in state_fields:
                existing_value = self.existing_state.get(key)
                if existing_value is not None:
                    state_fields[key] = existing_value

        ingested_at_utc = None
        if status == "ingested":
            ingested_at_utc = now_utc
        elif status == "skipped" and self.existing_state:
            ingested_at_utc = self.existing_state.get("ingested_at_utc")

        return IngestionStateEntity(
            partition_key=self.athlete_id,
            row_key=self.ingestion_key,
            status=status,
            first_seen_at_utc=self.first_seen_at_utc,
            last_attempt_at_utc=now_utc,
            retry_count=self.next_retry_count(status),
            workout_id=self.workout_id,
            ingestion_id=self.ingestion_id,
            source_file_name=state_fields["source_file_name"],
            source_drive_id=state_fields["source_drive_id"],
            source_etag=state_fields["source_etag"],
            source_ctag=state_fields["source_ctag"],
            source_quickxor_hash=state_fields["source_quickxor_hash"],
            source_modified_at_utc=state_fields["source_modified_at_utc"],
            source_activity_name=state_fields["source_activity_name"],
            file_sha256=state_fields["file_sha256"],
            ingest_version=INGEST_VERSION,
            ingested_at_utc=ingested_at_utc,
            error_message=error,
        )


class StorageInfrastructure:
    """Shared Azure Table Storage and Blob Storage infrastructure."""

    def __init__(self, connection_string: Optional[str] = None):
        """Initialize storage infrastructure.

        Resolution order:
        1) Explicit `connection_string` arg
        2) Env `AZURE_TABLES_CONNECTION_STRING`
        3) Env `AZURE_STORAGE_CONNECTION_STRING`
        4) Env `AzureWebJobsStorage` (Functions local dev)
        5) Fallback to `AZURE_STORAGE_ACCOUNT_URL` + DefaultAzureCredential
        """
        conn = (
            connection_string
            or os.getenv("AZURE_TABLES_CONNECTION_STRING")
            or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            or os.getenv("AzureWebJobsStorage")
        )

        if conn:
            self.service_client = TableServiceClient.from_connection_string(
                conn,
                connection_verify=True,
            )
        else:
            account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
            if not account_url:
                msg = (
                    "No connection string found. Provide "
                    "AZURE_TABLES_CONNECTION_STRING, "
                    "AZURE_STORAGE_CONNECTION_STRING, AzureWebJobsStorage, "
                    "or AZURE_STORAGE_ACCOUNT_URL."
                )
                raise ValueError(msg)
            credential = DefaultAzureCredential()
            self.service_client = TableServiceClient(
                endpoint=account_url,
                credential=credential,
                connection_verify=True,
            )

        self._blob_service_client = self._build_blob_service_client(conn)
        self._ensure_tables_exist()
        self._ensure_blob_containers()

    def _build_blob_service_client(
        self, table_connection_string: Optional[str]
    ) -> BlobServiceClient:
        """Build BlobServiceClient from available connection strings."""
        blob_conn = (
            os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            or os.getenv("AzureWebJobsStorage")
            or table_connection_string
        )
        if blob_conn:
            return BlobServiceClient.from_connection_string(blob_conn)

        account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
        if not account_url:
            msg = (
                "No storage connection available for blobs. Provide "
                "AZURE_STORAGE_CONNECTION_STRING, AzureWebJobsStorage, "
                "or AZURE_STORAGE_ACCOUNT_URL."
            )
            raise ValueError(msg)
        return BlobServiceClient(
            account_url=account_url,
            credential=DefaultAzureCredential(),
        )

    def _ensure_tables_exist(self):
        """Create tables if they don't exist."""
        for table_name in MANAGED_TABLE_NAMES:
            try:
                self.service_client.create_table_if_not_exists(table_name)
                logger.info("Table %s ready", table_name)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error creating table %s: %s", table_name, e)
                raise

    def _ensure_blob_containers(self) -> None:
        """Create required blob containers if they don't exist."""
        for container_name in (WORKOUTS_CONTAINER, EXTERNAL_SOURCES_CONTAINER):
            try:
                container_client = self._blob_service_client.get_container_client(
                    container_name
                )
                container_client.create_container()
                logger.info("Blob container %s ready", container_name)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                if "ContainerAlreadyExists" in str(exc):
                    continue
                logger.error("Error creating blob container %s: %s", container_name, exc)
                raise

    def get_table_client(self, table_name: str) -> TableClient:
        """Get table client for specified table."""
        if table_name in MANAGED_TABLE_NAMES:
            try:
                self.service_client.create_table_if_not_exists(table_name)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to ensure table exists before access",
                    extra={"table_name": table_name},
                    exc_info=True,
                )
                raise
        return self.service_client.get_table_client(table_name)

    def get_blob_client(self):
        """Get blob container client for workouts container."""
        return self._blob_service_client.get_container_client(WORKOUTS_CONTAINER)

    def get_external_sources_blob_client(self):
        """Get blob container client for external sources payload archive."""
        return self._blob_service_client.get_container_client(EXTERNAL_SOURCES_CONTAINER)

    # ---- Blob naming helpers ----

    def lap_blob_name(self, workout_id: str, lap_index: int) -> str:
        """Format lap blob path."""
        return f"{workout_id}/laps/lap-{lap_index:04d}.json"

    def canonical_records_blob_name(self, workout_id: str) -> str:
        """Format canonical parquet blob path."""
        return f"{workout_id}/canonical.parquet"

    def raw_fit_blob_name(self, workout_id: str) -> str:
        """Format raw FIT gzip blob path."""
        return f"{workout_id}/raw_fit.json.gz"

    def fit_analysis_blob_name(self, workout_id: str) -> str:
        """Format FIT analysis JSON blob path."""
        return f"{workout_id}/fit_analysis.json"

    def metadata_blob_name(self, workout_id: str) -> str:
        """Format metadata JSON blob path."""
        return f"{workout_id}/metadata.json"

    def laps_blob_name(self, workout_id: str) -> str:
        """Format laps JSON blob path."""
        return f"{workout_id}/laps.json"

    # ---- Blob I/O operations ----

    def upload_json_blob(self, blob_name: str, payload: Dict) -> str:
        """Upload uncompressed JSON to blob."""
        return self.upload_json_blob_to_container(WORKOUTS_CONTAINER, blob_name, payload)

    def upload_json_blob_to_container(
        self,
        container_name: str,
        blob_name: str,
        payload: Dict,
    ) -> str:
        """Upload uncompressed JSON to a specific blob container."""
        body = json.dumps(payload, separators=(",", ":"), default=str)
        blob_client = self._blob_service_client.get_blob_client(
            container=container_name,
            blob=blob_name,
        )
        blob_client.upload_blob(body, overwrite=True)
        return blob_name

    def upload_external_source_json(self, blob_name: str, payload: Dict) -> str:
        """Upload JSON payload to the external-sources container."""
        return self.upload_json_blob_to_container(
            EXTERNAL_SOURCES_CONTAINER,
            blob_name,
            payload,
        )

    def load_json_blob(self, blob_name: str, *, gzipped: bool = False) -> Dict:
        """Load JSON from blob (with optional gzip decompression)."""
        blob_client = self._blob_service_client.get_blob_client(
            container=WORKOUTS_CONTAINER,
            blob=blob_name,
        )
        payload = blob_client.download_blob().readall()
        if gzipped:
            payload = gzip.decompress(payload)
        return json.loads(payload)

    def upload_json_gzip(self, blob_name: str, payload: Dict) -> str:
        """Upload gzip-compressed JSON to blob."""
        body = json.dumps(payload, separators=(",", ":"), default=str)
        compressed = gzip.compress(body.encode("utf-8"))
        blob_client = self._blob_service_client.get_blob_client(
            container=WORKOUTS_CONTAINER,
            blob=blob_name,
        )
        blob_client.upload_blob(compressed, overwrite=True)
        return blob_name

    def upload_parquet_blob(
        self,
        workout_id: str,
        record_set: CanonicalRecordSet,
    ) -> Optional[str]:
        """Store canonical records to parquet blob."""
        df = record_set.to_dataframe
        if df.empty:
            return None

        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        buffer.seek(0)

        blob_name = self.canonical_records_blob_name(workout_id)
        blob_client = self._blob_service_client.get_blob_client(
            container=WORKOUTS_CONTAINER,
            blob=blob_name,
        )
        blob_client.upload_blob(buffer.getvalue(), overwrite=True)
        return blob_name

    def load_parquet_blob(self, blob_name: str) -> pd.DataFrame:
        """Load parquet blob into a DataFrame."""
        if not blob_name:
            return pd.DataFrame()
        blob_client = self._blob_service_client.get_blob_client(
            container=WORKOUTS_CONTAINER,
            blob=blob_name,
        )
        payload = blob_client.download_blob().readall()
        return pd.read_parquet(io.BytesIO(payload))

    def upload_dataframe_parquet_blob(self, blob_name: str, df: pd.DataFrame) -> str:
        """Persist a pandas DataFrame to an existing workout parquet blob path."""
        if not blob_name:
            raise ValueError("blob_name is required")
        if df.empty:
            raise ValueError("cannot upload empty canonical DataFrame")

        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        buffer.seek(0)

        blob_client = self._blob_service_client.get_blob_client(
            container=WORKOUTS_CONTAINER,
            blob=blob_name,
        )
        blob_client.upload_blob(buffer.getvalue(), overwrite=True)
        return blob_name
