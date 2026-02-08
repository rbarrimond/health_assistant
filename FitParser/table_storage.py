"""Azure Table Storage client for workout data."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.data.tables import TableClient, TableServiceClient
from azure.identity import DefaultAzureCredential

from FitParser.fit_parser import compute_workout_id

# Constant for UTC timezone suffix replacement
UTC_SUFFIX = "+00:00"
INGEST_VERSION = "v2.2.2"

logger = logging.getLogger(__name__)


@dataclass
class WorkoutEntity:
    """Structured Workouts table entity."""

    partition_key: str
    row_key: str
    workout_id: str
    athlete_id: str
    source_system: str
    source_file_name: str
    source_file_path: str
    source_item_id: Optional[str]
    source_drive_id: Optional[str]
    source_etag: Optional[str]
    file_size_bytes: Optional[int]
    file_sha256: Optional[str]
    metrics: Dict = field(default_factory=dict)

    @classmethod
    def from_table_entity(cls, entity: Dict) -> "WorkoutEntity":
        """Create a WorkoutEntity from a raw Azure Table entity."""
        core_keys = {
            "PartitionKey",
            "RowKey",
            "workout_id",
            "athlete_id",
            "source_system",
            "source_file_name",
            "source_file_path",
            "source_item_id",
            "source_drive_id",
            "source_etag",
            "file_size_bytes",
            "file_sha256",
        }
        system_keys = {
            "Timestamp",
            "etag",
            "odata.etag",
        }
        metrics = {
            key: value
            for key, value in entity.items()
            if key not in core_keys | system_keys
        }

        return cls(
            partition_key=entity.get("PartitionKey", ""),
            row_key=entity.get("RowKey", ""),
            workout_id=entity.get("workout_id", ""),
            athlete_id=entity.get("athlete_id", ""),
            source_system=entity.get("source_system", ""),
            source_file_name=entity.get("source_file_name", ""),
            source_file_path=entity.get("source_file_path", ""),
            source_item_id=entity.get("source_item_id"),
            source_drive_id=entity.get("source_drive_id"),
            source_etag=entity.get("source_etag"),
            file_size_bytes=entity.get("file_size_bytes"),
            file_sha256=entity.get("file_sha256"),
            metrics=metrics,
        )

    def to_entity(self) -> Dict:
        """
        Convert the WorkoutEntity instance to a dictionary representation suitable 
        for Azure Table Storage.

        Returns:
            Dict: A dictionary containing the entity's data.
        """
        entity = {
            "PartitionKey": self.partition_key,
            "RowKey": self.row_key,
            "workout_id": self.workout_id,
            "athlete_id": self.athlete_id,
            "source_system": self.source_system,
            "source_file_name": self.source_file_name,
            "source_file_path": self.source_file_path,
            "source_item_id": self.source_item_id,
            "source_drive_id": self.source_drive_id,
            "source_etag": self.source_etag,
            "file_size_bytes": self.file_size_bytes,
            "file_sha256": self.file_sha256,
        }

        for key, value in self.metrics.items():
            if value is not None:
                entity[key] = value

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
    source_etag: Optional[str] = None
    file_sha256: Optional[str] = None
    ingest_version: Optional[str] = None
    ingested_at_utc: Optional[str] = None
    error_message: Optional[str] = None

    def to_entity(self) -> Dict:
        """
        Convert the IngestionStateEntity instance to a dictionary representation suitable 
        for Azure Table Storage.

        Returns:
            Dict: A dictionary containing the entity's data.
        """
        entity = {
            "PartitionKey": self.partition_key,
            "RowKey": self.row_key,
            "status": self.status,
            "first_seen_at_utc": self.first_seen_at_utc,
            "last_attempt_at_utc": self.last_attempt_at_utc,
            "retry_count": self.retry_count,
            "workout_id": self.workout_id,
        }
        if self.source_etag is not None:
            entity["source_etag"] = self.source_etag
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
        storage: "WorkoutTableStorage",
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict] = None,
    ):
        self.athlete_id = athlete_id
        self.file_info = file_info
        self.workout_id = workout_id
        self.storage = storage

        self.ingestion_key = ingestion_key or self._build_ingestion_key()
        self.existing_state = (
            existing_state
            if existing_state is not None
            else self.storage.get_ingestion_state(athlete_id, self.ingestion_key)
        )

    def _build_ingestion_key(self) -> str:
        """
        Generate a unique ingestion key based on file information or workout ID.

        Returns:
            str: The generated ingestion key.

        Raises:
            ValueError: If no valid key can be generated.
        """
        ingestion_key = (
            self.file_info.get("source_item_id")
            or self.file_info.get("file_sha256")
            or self.workout_id
        )

        if ingestion_key is None:
            logger.error("Ingestion key cannot be None. File info: %s", self.file_info)
            raise ValueError("Ingestion key cannot be None")

        return ingestion_key

    @property
    def is_ingested(self) -> bool:
        """
        Check if the ingestion state indicates the entity is already ingested.

        Returns:
            bool: True if ingested, False otherwise.
        """
        return bool(self.existing_state and self.existing_state.get("status") == "ingested")

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

        existing_etag = self.existing_state.get("source_etag")
        incoming_etag = self.file_info.get("source_etag")
        if incoming_etag and existing_etag:
            return incoming_etag == existing_etag

        existing_sha = self.existing_state.get("file_sha256")
        incoming_sha = self.file_info.get("file_sha256")
        return bool(incoming_sha and existing_sha and incoming_sha == existing_sha)

    def should_skip(self) -> bool:
        """Return True when an already-ingested file is unchanged and should be skipped."""
        return self.is_ingested and self.is_unchanged()

    @property
    def first_seen_at_utc(self) -> str:
        """
        Get the timestamp of the first time the entity was seen.

        Returns:
            str: The ISO 8601 formatted timestamp.
        """
        if self.existing_state and self.existing_state.get("first_seen_at_utc"):
            return self.existing_state["first_seen_at_utc"]
        return datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z")

    def build_state_entity(
        self,
        status: str,
        error: Optional[str] = None,
    ) -> IngestionStateEntity:
        """
        Build an IngestionStateEntity instance based on the current context.

        Args:
            status (str): The status of the ingestion.
            error (Optional[str]): An optional error message.

        Returns:
            IngestionStateEntity: The constructed ingestion state entity.
        """
        now_utc = datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z")
        return IngestionStateEntity(
            partition_key=self.athlete_id,
            row_key=self.ingestion_key,
            status=status,
            first_seen_at_utc=self.first_seen_at_utc,
            last_attempt_at_utc=now_utc,
            retry_count=self.next_retry_count(status),
            workout_id=self.workout_id,
            source_etag=self.file_info.get("source_etag"),
            file_sha256=self.file_info.get("file_sha256"),
            ingest_version=INGEST_VERSION,
            ingested_at_utc=now_utc if status == "ingested" else None,
            error_message=error,
        )


class WorkoutTableStorage:
    """Handle workout data storage in Azure Tables."""

    def __init__(self, connection_string: Optional[str] = None):
        """Initialize table storage client.

        Resolution order for local/dev and Azure:
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

        self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Create tables if they don't exist."""
        table_names = [
            "Workouts",
            "WeeklyRollups",
            "IngestionState",
            "Physiometrics",
            "WithingsTokens",
            "OneDriveTokens",
            "WebhookDeduplication",
            "AgentPreferences",
            "AgentObservations",
        ]
        for table_name in table_names:
            try:
                self.service_client.create_table_if_not_exists(table_name)
                logger.info("Table %s ready", table_name)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error creating table %s: %s", table_name, e)
                raise

    def _get_table_client(self, table_name: str) -> TableClient:
        """Get table client for specified table."""
        return self.service_client.get_table_client(table_name)

    def get_ingestion_context(
        self,
        athlete_id: str,
        file_info: Dict,
        workout_id: Optional[str] = None,
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict] = None,
    ) -> IngestionContext:
        """Create an ingestion context that encapsulates idempotency checks."""
        return IngestionContext(
            athlete_id=athlete_id,
            file_info=file_info,
            workout_id=workout_id,
            storage=self,
            ingestion_key=ingestion_key,
            existing_state=existing_state,
        )

    def store_workout(self, athlete_id: str, metrics: Dict,
                       source_info: Dict) -> str:
        """
        Store parsed workout metrics in Workouts table.

        Args:
            athlete_id: Athlete identifier (e.g., 'rob')
            metrics: Parsed metrics from FIT file
            source_info: OneDrive/source file info

        Returns:
            workout_id of stored entity
        """
        # Generate deterministic workout_id
        workout_id = compute_workout_id(
            source_item_id=source_info.get("source_item_id"),
            file_sha256=source_info.get("file_sha256"),
            file_path=source_info.get("source_file_path"),
            file_name=source_info.get("source_file_name"),
            start_time=metrics.get("start_time_utc"),
        )

        # Build partition and row keys
        start_time = metrics.get("start_time_utc", "")
        if start_time:
            # Extract YYYY-MM for partition
            # Azure Tables forbid '/', '\\', '#', '?' in PartitionKey/RowKey
            partition_key = f"{athlete_id}|{start_time[:7]}"
            # Format: YYYYMMDDTHHMMSSZ|workout_id
            row_key_time = start_time.replace("-", "").replace(":", "").replace("+", "")
            row_key = f"{row_key_time}|{workout_id[:12]}"
        else:
            # Fallback if no start time
            partition_key = f"{athlete_id}|unknown"
            row_key = workout_id[:20]

        entity = WorkoutEntity(
            partition_key=partition_key,
            row_key=row_key,
            workout_id=workout_id,
            athlete_id=athlete_id,
            source_system=source_info.get("source_system", "HealthFit"),
            source_file_name=source_info.get("source_file_name", ""),
            source_file_path=source_info.get("source_file_path", ""),
            source_item_id=source_info.get("source_item_id"),
            source_drive_id=source_info.get("source_drive_id"),
            source_etag=source_info.get("source_etag"),
            file_size_bytes=source_info.get("file_size_bytes"),
            file_sha256=source_info.get("file_sha256"),
            metrics=metrics,
        ).to_entity()

        # Store in table
        try:
            table_client = self._get_table_client("Workouts")
            table_client.upsert_entity(entity)
            logger.info("Stored workout %s for %s", workout_id, athlete_id)
            return workout_id
        except HttpResponseError as e:
            logger.error("Error storing workout %s: %s", workout_id, e)
            raise

    def record_ingestion_state(self, athlete_id: str, file_info: Dict,
                               status: str, error: Optional[str] = None,
                               workout_id: Optional[str] = None,
                               ingestion_key: Optional[str] = None,
                               existing_state: Optional[Dict] = None):
        """
        Record ingestion state for idempotency and debugging.

        Args:
            athlete_id: Athlete identifier
            file_info: Source file information
            status: 'ingested', 'failed', 'skipped'
            error: Error message if status is 'failed'
            workout_id: Associated workout_id if successful
            ingestion_key: Optional precomputed ingestion key
            existing_state: Optional preloaded ingestion state entity
        """
        context = IngestionContext(
            athlete_id=athlete_id,
            file_info=file_info,
            workout_id=workout_id,
            storage=self,
            ingestion_key=ingestion_key,
            existing_state=existing_state,
        )

        # Log ingestion key and retry count for debugging idempotency
        logger.debug("Generated ingestion key for state: %s", context.ingestion_key)
        logger.debug("Retry count for %s: %d", context.ingestion_key, context.next_retry_count(status))

        entity = context.build_state_entity(status=status, error=error).to_entity()

        # Log entity details for debugging
        logger.debug("Ingestion state entity: %s", entity)

        # Store in table
        try:
            table_client = self._get_table_client("IngestionState")
            table_client.upsert_entity(entity)
            logger.info("Recorded ingestion state for %s: %s", athlete_id, status)
        except HttpResponseError as e:
            logger.error("Error recording ingestion state for %s: %s", athlete_id, e)
            raise

    def get_ingestion_state(self, athlete_id: str, file_key: str) -> Optional[Dict]:
        """Check if file was already ingested."""
        try:
            table_client = self._get_table_client("IngestionState")
            entity = table_client.get_entity(partition_key=athlete_id, row_key=file_key)
            return entity
        except ResourceNotFoundError:
            # Entity doesn't exist yet - not an error
            return None
        except HttpResponseError as e:
            logger.warning("Error checking ingestion state for %s: %s", file_key, e)
            return None


    def update_weekly_rollup(self, athlete_id: str, year: str, week: str, rollup_data: Dict):
        """
        Update weekly rollup with aggregated metrics.

        Args:
            athlete_id: Athlete identifier
            year: Year (YYYY)
            week: ISO week (WW)
            rollup_data: Weekly aggregated data
        """
        entity = {
            "PartitionKey": f"{athlete_id}#{year}",
            "RowKey": f"{year}-{week:0>2}",
            "last_updated_at_utc": datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z"),
        }
        entity.update(rollup_data)

        try:
            table_client = self._get_table_client("WeeklyRollups")
            table_client.upsert_entity(entity)
            logger.info("Updated weekly rollup %s-W%s for %s", year, week, athlete_id)
        except HttpResponseError as e:
            logger.error("Error updating weekly rollup: %s", e)
            # Don't raise - rollups are secondary
    def store_physiometrics(self, athlete_id: str,
                           physiometrics_data: Dict,
                           effective_date: Optional[str] = None,
                           data_source: str = "manual") -> str:
        """
        Store physiometrics configuration in Physiometrics table.

        Args:
            athlete_id: Athlete identifier
            physiometrics_data: Complete physiometrics JSON
                (heart_rate, power config, body composition, etc.)
            effective_date: ISO date when this config takes effect (defaults to today)
            data_source: Source of data (manual, withings, chatgpt)

        Returns:
            Timestamp of update (ISO format)
        """
        timestamp = datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z")

        # Default effective_date to today if not provided
        if effective_date is None:
            effective_date = datetime.now(timezone.utc).date().isoformat()

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": timestamp,  # Timestamp as row key preserves history
            "updated_at_utc": timestamp,
            "effective_date": effective_date,
            "data_source": data_source,
            # Heart rate config
            "heart_rate_basis": (
                physiometrics_data.get("heart_rate", {}).get("basis", "HRmax")
            ),
            "heart_rate_lthr_bpm": physiometrics_data.get("heart_rate", {}).get(
                "lthr_bpm"
            ),
            "heart_rate_hr_max_bpm": physiometrics_data.get(
                "heart_rate", {}
            ).get("hr_max_bpm"),
            "heart_rate_resting_bpm": (
                physiometrics_data.get("heart_rate", {}).get("resting_hr_bpm") or 60
            ),
            # Power config
            "power_ftp_watts": physiometrics_data.get("power", {}).get(
                "ftp_watts"
            ),
            # Body composition (from Withings or manual entry)
            "weight_kg": physiometrics_data.get("weight_kg"),
            "fat_mass_kg": physiometrics_data.get("fat_mass_kg"),
            "muscle_mass_kg": physiometrics_data.get("muscle_mass_kg"),
            "bone_mass_kg": physiometrics_data.get("bone_mass_kg"),
            "body_fat_pct": physiometrics_data.get("body_fat_pct"),
            "visceral_fat_index": physiometrics_data.get("visceral_fat_index"),
            "metabolic_age_years": physiometrics_data.get("metabolic_age_years"),
            # Cycling VO2Max (manual entry from ChatGPT)
            "cycling_vo2max_ml_kg_min": physiometrics_data.get("cycling_vo2max_ml_kg_min"),
            # Store full JSON as string for auditability
            "full_config_json": json.dumps(physiometrics_data),
        }

        try:
            table_client = self._get_table_client("Physiometrics")
            table_client.upsert_entity(entity)
            logger.info(
                "Stored physiometrics for %s at %s", athlete_id, timestamp
            )
            return timestamp
        except HttpResponseError as e:
            logger.error("Error storing physiometrics: %s", e)
            raise

    def get_physiometrics(self, athlete_id: str) -> Optional[Dict]:
        """
        Get latest physiometrics configuration for athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Dict with physiometrics data, or None if not found
        """
        try:
            table_client = self._get_table_client("Physiometrics")
            # Query for latest entry (RowKey is timestamp, so sorting descending
            # gets newest first)
            query = f"PartitionKey eq '{athlete_id}'"
            entities = list(table_client.query_entities(query, top=1))

            if not entities:
                return None

            latest = entities[0]
            # Reconstruct physiometrics from full_config_json
            if latest.get("full_config_json"):
                return json.loads(latest["full_config_json"])

            # Fallback: reconstruct from individual fields
            result = {
                "heart_rate": {
                    "basis": latest.get("heart_rate_basis", "HRmax"),
                    "lthr_bpm": latest.get("heart_rate_lthr_bpm"),
                    "hr_max_bpm": latest.get("heart_rate_hr_max_bpm"),
                    "resting_hr_bpm": (
                        latest.get("heart_rate_resting_bpm") or 60
                    ),
                },
                "power": {"ftp_watts": latest.get("power_ftp_watts")},
            }

            # Add body composition fields if present
            for metric_field in ["weight_kg", "fat_mass_kg", "muscle_mass_kg", "bone_mass_kg"]:
                if latest.get(metric_field) is not None:
                    result[metric_field] = latest.get(metric_field)

            # Add metadata
            if latest.get("effective_date"):
                result["effective_date"] = latest.get("effective_date")
            if latest.get("data_source"):
                result["data_source"] = latest.get("data_source")

            return result
        except ResourceNotFoundError:
            return None
        except HttpResponseError as e:
            logger.warning(
                "Error retrieving physiometrics for %s: %s", athlete_id, e
            )
            return None

    def list_physiometrics_history(self, athlete_id: str,
                                  limit: int = 10) -> list:
        """
        List physiometrics configuration history for athlete.

        Args:
            athlete_id: Athlete identifier
            limit: Maximum number of entries to return

        Returns:
            List of dicts with physiometrics history (newest first)
        """
        try:
            table_client = self._get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}'"
            # Rows are stored with timestamp as key, so we iterate and sort
            entities = list(table_client.query_entities(query))
            # Sort by timestamp descending (newest first)
            entities.sort(key=lambda x: x.get("RowKey", ""), reverse=True)
            return entities[:limit]
        except HttpResponseError as e:
            logger.warning(
                "Error retrieving physiometrics history for %s: %s",
                athlete_id,
                e
            )
            return []

    def get_physiometrics_as_of(self, athlete_id: str,
                               target_date: str) -> Optional[Dict]:
        """
        Get physiometrics configuration effective on a specific date.

        Args:
            athlete_id: Athlete identifier
            target_date: ISO date string (e.g., "2026-01-15")

        Returns:
            Dict with physiometrics data effective on that date, or None
        """
        try:
            table_client = self._get_table_client("Physiometrics")
            # Query all entries for athlete where effective_date <= target_date
            query = f"PartitionKey eq '{athlete_id}' and effective_date le '{target_date}'"
            entities = list(table_client.query_entities(query))

            if not entities:
                # No config before this date, try latest regardless of date
                return self.get_physiometrics(athlete_id)

            # Sort by effective_date descending (most recent first)
            entities.sort(key=lambda x: x.get("effective_date", ""), reverse=True)
            latest = entities[0]

            # Reconstruct from full_config_json if available
            if latest.get("full_config_json"):
                return json.loads(latest["full_config_json"])

            # Fallback: reconstruct from individual fields (same as get_physiometrics)
            result = {
                "heart_rate": {
                    "basis": latest.get("heart_rate_basis", "HRmax"),
                    "lthr_bpm": latest.get("heart_rate_lthr_bpm"),
                    "hr_max_bpm": latest.get("heart_rate_hr_max_bpm"),
                    "resting_hr_bpm": latest.get("heart_rate_resting_bpm") or 60,
                },
                "power": {"ftp_watts": latest.get("power_ftp_watts")},
            }

            # Add body composition fields if present
            for metric_field in ["weight_kg", "fat_mass_kg", "muscle_mass_kg", "bone_mass_kg",
                         "body_fat_pct", "visceral_fat_index", "metabolic_age_years",
                         "cycling_vo2max_ml_kg_min"]:
                if latest.get(metric_field) is not None:
                    result[metric_field] = latest.get(metric_field)

            # Add metadata
            if latest.get("effective_date"):
                result["effective_date"] = latest.get("effective_date")
            if latest.get("data_source"):
                result["data_source"] = latest.get("data_source")

            return result

        except HttpResponseError as e:
            logger.warning(
                "Error retrieving physiometrics as of %s for %s: %s",
                target_date, athlete_id, e
            )
            return None

    def get_physiometrics_history(self, athlete_id: str,
                                  start_date: str,
                                  end_date: str,
                                  metrics: Optional[list] = None) -> list:
        """
        Get time-series physiometrics data for specified date range.

        Args:
            athlete_id: Athlete identifier
            start_date: ISO date string (inclusive)
            end_date: ISO date string (inclusive)
            metrics: List of metric names to return (None = all metrics)

        Returns:
            List of dicts with physiometrics data points, sorted by effective_date
        """
        try:
            table_client = self._get_table_client("Physiometrics")
            # Query entries within date range
            query = (f"PartitionKey eq '{athlete_id}' "
                    f"and effective_date ge '{start_date}' "
                    f"and effective_date le '{end_date}'")
            entities = list(table_client.query_entities(query))

            # Sort by effective_date ascending (oldest first for time series)
            entities.sort(key=lambda x: x.get("effective_date", ""))

            # If metrics specified, filter fields
            if metrics:
                result = []
                for entity in entities:
                    data_point = {
                        "effective_date": entity.get("effective_date"),
                        "updated_at_utc": entity.get("updated_at_utc"),
                        "data_source": entity.get("data_source"),
                    }
                    for metric in metrics:
                        if entity.get(metric) is not None:
                            data_point[metric] = entity.get(metric)
                    result.append(data_point)
                return result

            # Return all fields
            return entities

        except HttpResponseError as e:
            logger.warning(
                "Error retrieving physiometrics history for %s: %s",
                athlete_id, e
            )
            return []

    def update_single_metric(self, athlete_id: str,
                            metric_name: str,
                            value: float,
                            effective_date: Optional[str] = None,
                            data_source: str = "chatgpt") -> str:
        """
        Update a single physiometric value, preserving other fields.

        Args:
            athlete_id: Athlete identifier
            metric_name: Name of metric (e.g., "weight_kg", "cycling_vo2max_ml_kg_min")
            value: New value
            effective_date: ISO date when this takes effect (defaults to today)
            data_source: Source of update (chatgpt, manual, withings)

        Returns:
            Timestamp of update (ISO format)
        """
        # Get latest config to preserve other values
        latest_config = self.get_physiometrics(athlete_id) or {}

        # Update the specific metric
        latest_config[metric_name] = value

        # Store updated config
        return self.store_physiometrics(
            athlete_id=athlete_id,
            physiometrics_data=latest_config,
            effective_date=effective_date,
            data_source=data_source
        )

    # -------------------------------------------------------------------------
    # Withings OAuth Token Management
    # -------------------------------------------------------------------------

    def store_withings_tokens(self, athlete_id: str,
                             withings_userid: str,
                             access_token: str,
                             refresh_token: str,
                             expires_in: int,
                             scope: str) -> None:
        """
        Store Withings OAuth tokens for an athlete.

        Args:
            athlete_id: Athlete identifier
            withings_userid: Withings user ID
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            expires_in: Token lifetime in seconds
            scope: OAuth scope granted
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": withings_userid,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at_utc": expires_at.isoformat().replace(UTC_SUFFIX, "Z"),
            "scope": scope,
            "updated_at_utc": datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z"),
        }

        try:
            table_client = self._get_table_client("WithingsTokens")
            table_client.upsert_entity(entity)
            logger.info("Stored Withings tokens for %s (userid: %s)", athlete_id, withings_userid)
        except HttpResponseError as e:
            logger.error("Error storing Withings tokens: %s", e)
            raise

    def get_withings_tokens(self, athlete_id: str) -> Optional[Dict]:
        """
        Get Withings OAuth tokens for an athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Dict with token data, or None if not found
        """
        try:
            table_client = self._get_table_client("WithingsTokens")
            query = f"PartitionKey eq '{athlete_id}'"
            entities = list(table_client.query_entities(query, top=1))

            if not entities:
                return None

            return dict(entities[0])

        except HttpResponseError as e:
            logger.warning("Error retrieving Withings tokens for %s: %s", athlete_id, e)
            return None

    def refresh_withings_token(self, athlete_id: str,
                               withings_userid: str,
                               new_access_token: str,
                               new_refresh_token: str,
                               expires_in: int) -> None:
        """
        Update Withings tokens after refresh.

        Args:
            athlete_id: Athlete identifier
            withings_userid: Withings user ID
            new_access_token: New access token
            new_refresh_token: New refresh token
            expires_in: Token lifetime in seconds
        """
        # Get existing tokens to preserve scope
        existing = self.get_withings_tokens(athlete_id)
        scope = (
            str(existing.get("scope"))
            if existing and existing.get("scope")
            else "user.metrics,user.info"
        )

        # Store updated tokens
        self.store_withings_tokens(
            athlete_id=athlete_id,
            withings_userid=withings_userid,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            scope=scope
        )

    # -------------------------------------------------------------------------
    # OneDrive OAuth Token Management
    # -------------------------------------------------------------------------

    def store_onedrive_tokens(self, athlete_id: str,
                              access_token: str,
                              refresh_token: str,
                              expires_in: int,
                              scope: str,
                              drive_id: str | None = None) -> None:
        """
        Store OneDrive OAuth tokens for an athlete.

        Args:
            athlete_id: Athlete identifier
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            expires_in: Token lifetime in seconds
            scope: OAuth scope granted
            drive_id: Optional OneDrive drive id
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        entity = {
            "PartitionKey": athlete_id,
            "RowKey": "onedrive",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at_utc": expires_at.isoformat().replace(UTC_SUFFIX, "Z"),
            "scope": scope,
            "drive_id": drive_id or "",
            "updated_at_utc": datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z"),
        }

        try:
            table_client = self._get_table_client("OneDriveTokens")
            table_client.upsert_entity(entity)
            logger.info("Stored OneDrive tokens for %s", athlete_id)
        except HttpResponseError as e:
            logger.error("Error storing OneDrive tokens: %s", e)
            raise

    def get_onedrive_tokens(self, athlete_id: str) -> Optional[Dict]:
        """
        Get OneDrive OAuth tokens for an athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Dict with token data, or None if not found
        """
        try:
            table_client = self._get_table_client("OneDriveTokens")
            query = f"PartitionKey eq '{athlete_id}' and RowKey eq 'onedrive'"
            entities = list(table_client.query_entities(query, top=1))
            if not entities:
                return None
            return dict(entities[0])
        except HttpResponseError as e:
            logger.warning("Error retrieving OneDrive tokens for %s: %s", athlete_id, e)
            return None

    def refresh_onedrive_token(self, athlete_id: str,
                               new_access_token: str,
                               new_refresh_token: str,
                               expires_in: int,
                               scope: str | None = None,
                               drive_id: str | None = None) -> None:
        """
        Update OneDrive tokens after refresh.

        Args:
            athlete_id: Athlete identifier
            new_access_token: New access token
            new_refresh_token: New refresh token
            expires_in: Token lifetime in seconds
            scope: OAuth scope granted (optional)
            drive_id: Optional drive id
        """
        existing = self.get_onedrive_tokens(athlete_id)
        scope = scope or (
            str(existing.get("scope"))
            if existing and existing.get("scope")
            else "Files.ReadWrite offline_access"
        )
        drive_id = drive_id or (
            existing.get("drive_id")
            if existing and existing.get("drive_id")
            else None
        )
        self.store_onedrive_tokens(
            athlete_id=athlete_id,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            scope=scope,
            drive_id=drive_id,
        )

    # -------------------------------------------------------------------------
    # Webhook Deduplication
    # -------------------------------------------------------------------------

    def webhook_already_processed(self, athlete_id: str,
                                  withings_userid: str,
                                  enddate: str) -> bool:
        """
        Check if a Withings webhook has already been processed.

        Args:
            athlete_id: Athlete identifier
            withings_userid: Withings user ID
            enddate: Unix timestamp from webhook (as string)

        Returns:
            True if already processed, False otherwise
        """
        try:
            table_client = self._get_table_client("WebhookDeduplication")
            row_key = f"{withings_userid}_{enddate}"

            try:
                table_client.get_entity(partition_key=athlete_id, row_key=row_key)
                return True  # Entity exists, already processed
            except ResourceNotFoundError:
                return False  # Not processed yet

        except HttpResponseError as e:
            logger.warning("Error checking webhook deduplication: %s", e)
            return False  # On error, allow processing

    def mark_webhook_processed(self, athlete_id: str,
                               withings_userid: str,
                               enddate: str) -> None:
        """
        Mark a Withings webhook as processed.

        Args:
            athlete_id: Athlete identifier
            withings_userid: Withings user ID
            enddate: Unix timestamp from webhook (as string)
        """
        try:
            table_client = self._get_table_client("WebhookDeduplication")
            row_key = f"{withings_userid}_{enddate}"

            entity = {
                "PartitionKey": athlete_id,
                "RowKey": row_key,
                "processed_at_utc": datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z"),
                "withings_userid": withings_userid,
                "enddate": enddate,
            }

            table_client.upsert_entity(entity)
            logger.info("Marked webhook processed: %s", row_key)

        except HttpResponseError as e:
            logger.error("Error marking webhook as processed: %s", e)
            # Don't raise - this shouldn't block webhook processing

    def upsert_metrics(self, athlete_id: str, metrics_model) -> str:
        """
        Store parsed workout metrics from WorkoutMetricsModel or dict.

        Args:
            athlete_id: Athlete identifier (e.g., 'rob')
            metrics_model: WorkoutMetricsModel or dict with parsed metrics

        Returns:
            workout_id of stored entity
        """
        # If parser returns a raw dict, store directly.
        if isinstance(metrics_model, dict):
            metrics = metrics_model
        else:
            # Extract flat metrics dict from nested model structure
            metrics = self._flatten_workout_metrics(metrics_model)

        # Source info defaults
        source_info = {"source_system": "HealthFit"}

        # Call store_workout with the flat metrics dict
        return self.store_workout(athlete_id, metrics, source_info)

    def _flatten_workout_metrics(self, metrics_model) -> Dict:
        """
        Flatten nested WorkoutMetricsModel into flat dictionary for storage.

        Args:
            metrics_model: WorkoutMetricsModel with parsed metrics

        Returns:
            Flat dictionary with all metrics
        """
        metrics = {}

        # Session metrics
        if metrics_model.session:
            metrics.update({
                "sport": metrics_model.session.sport,
                "sub_sport": metrics_model.session.sub_sport,
                "apple_workout_type": metrics_model.session.apple_workout_type,
                "workout_name": metrics_model.session.workout_name,
                "device_name": metrics_model.session.device_name,
                "is_indoor": metrics_model.session.is_indoor,
                "start_time_utc": metrics_model.session.start_time_utc,
                "end_time_utc": metrics_model.session.end_time_utc,
                "timezone": metrics_model.session.timezone,
                "duration_sec": metrics_model.session.duration_sec,
                "moving_time_sec": metrics_model.session.moving_time_sec,
            })

        # Distance and elevation metrics
        if metrics_model.distance:
            metrics.update({
                "has_gps": metrics_model.distance.has_gps,
                "distance_m": metrics_model.distance.distance_m,
                "elevation_gain_m": metrics_model.distance.elevation_gain_m,
                "elevation_loss_m": metrics_model.distance.elevation_loss_m,
                "avg_speed_mps": metrics_model.distance.avg_speed_ms,
                "max_speed_mps": metrics_model.distance.max_speed_ms,
                "calories_kcal": metrics_model.distance.calories,
            })

        # Sample metrics
        if metrics_model.samples:
            metrics.update({
                "hr_avg_bpm": metrics_model.samples.hr_avg_bpm,
                "hr_max_bpm": metrics_model.samples.hr_max_bpm,
                "hr_samples_count": metrics_model.samples.hr_samples_count,
                "hr_missing_pct": metrics_model.samples.hr_missing_pct,
                "pwr_avg_watts": metrics_model.samples.pwr_avg_watts,
                "pwr_max_watts": metrics_model.samples.pwr_max_watts,
                "pwr_normalized_watts": metrics_model.samples.pwr_normalized_watts,
                "pwr_variability_index": metrics_model.samples.pwr_variability_index,
                "pwr_samples_count": metrics_model.samples.pwr_samples_count,
                "pwr_missing_pct": metrics_model.samples.pwr_missing_pct,
                "cad_avg_rpm": metrics_model.samples.cad_avg_rpm,
                "cad_max_rpm": metrics_model.samples.cad_max_rpm,
                "cad_samples_count": metrics_model.samples.cad_samples_count,
            })

        # HR zones
        if metrics_model.zones_hr:
            metrics.update({
                "hr_z1_sec": metrics_model.zones_hr.hr_z1_sec,
                "hr_z2_sec": metrics_model.zones_hr.hr_z2_sec,
                "hr_z3_sec": metrics_model.zones_hr.hr_z3_sec,
                "hr_z4_sec": metrics_model.zones_hr.hr_z4_sec,
                "hr_z5_sec": metrics_model.zones_hr.hr_z5_sec,
                "hr_z2_min": metrics_model.zones_hr.hr_z2_min,
                "hr_zone_basis": metrics_model.zones_hr.hr_zone_basis,
                "hr_zone_reference_bpm": metrics_model.zones_hr.hr_zone_reference_bpm,
                "hr_zone_total_sec": metrics_model.zones_hr.hr_zone_total_sec,
            })

        # Power zones
        if metrics_model.zones_power:
            metrics.update({
                "pwr_z1_sec": metrics_model.zones_power.pwr_z1_sec,
                "pwr_z2_sec": metrics_model.zones_power.pwr_z2_sec,
                "pwr_z3_sec": metrics_model.zones_power.pwr_z3_sec,
                "pwr_z4_sec": metrics_model.zones_power.pwr_z4_sec,
                "pwr_z5_sec": metrics_model.zones_power.pwr_z5_sec,
                "pwr_z6_sec": metrics_model.zones_power.pwr_z6_sec,
                "pwr_z7_sec": metrics_model.zones_power.pwr_z7_sec,
                "pwr_z2_min": metrics_model.zones_power.pwr_z2_min,
                "low_aerobic_min": metrics_model.zones_power.low_aerobic_min,
                "intensity_min": metrics_model.zones_power.intensity_min,
                "ftp_watts": metrics_model.zones_power.ftp_watts,
                "pwr_zone_model": metrics_model.zones_power.pwr_zone_model,
            })

        # Aerobic efficiency and HR resting
        metrics.update({
            "aerobic_efficiency_mphb": metrics_model.aerobic_efficiency_mphb,
            "hr_resting_bpm": metrics_model.hr_resting_bpm,
            "physiometrics_snapshot_timestamp": metrics_model.physiometrics_snapshot_timestamp,
        })

        return metrics
