"""Azure Table Storage client for workout data."""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional
import os

from azure.data.tables import TableClient, TableServiceClient
from azure.identity import DefaultAzureCredential

from FitParser.fit_parser import compute_workout_id

logger = logging.getLogger(__name__)


class WorkoutTableStorage:
    """Handle workout data storage in Azure Tables."""

    def __init__(self, connection_string: Optional[str] = None):
        """Initialize table storage client."""
        if connection_string:
            self.service_client = TableServiceClient.from_connection_string(connection_string)
        else:
            account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
            if not account_url:
                raise ValueError("AZURE_STORAGE_ACCOUNT_URL environment variable is required when connection_string is not provided")
            credential = DefaultAzureCredential()
            self.service_client = TableServiceClient(endpoint=account_url, credential=credential)

        self._ensure_tables_exist()

    def _ensure_tables_exist(self):
        """Create tables if they don't exist."""
        for table_name in ["Workouts", "WeeklyRollups", "IngestionState"]:
            try:
                self.service_client.create_table_if_not_exists(table_name)
                logger.info("Table %s ready", table_name)
            except Exception as e:
                logger.error("Error creating table %s: %s", table_name, e)
                raise

    def _get_table_client(self, table_name: str) -> TableClient:
        """Get table client for specified table."""
        return self.service_client.get_table_client(table_name)

    def store_workout(self, athlete_id: str, metrics: Dict, source_info: Dict) -> str:
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
            partition_key = f"{athlete_id}#{start_time[:7]}"
            # Format: YYYYMMDDTHHMMSSZ#workout_id
            row_key_time = start_time.replace("-", "").replace(":", "").replace("+", "")
            row_key = f"{row_key_time}#{workout_id[:12]}"
        else:
            # Fallback if no start time
            partition_key = f"{athlete_id}#unknown"
            row_key = workout_id[:20]

        # Build entity with all metrics
        entity = {
            "PartitionKey": partition_key,
            "RowKey": row_key,
            "workout_id": workout_id,
            "athlete_id": athlete_id,
            "source_system": source_info.get("source_system", "HealthFit"),
            "source_file_name": source_info.get("source_file_name", ""),
            "source_file_path": source_info.get("source_file_path", ""),
            "source_item_id": source_info.get("source_item_id"),
            "source_drive_id": source_info.get("source_drive_id"),
            "source_etag": source_info.get("source_etag"),
            "file_size_bytes": source_info.get("file_size_bytes"),
            "file_sha256": source_info.get("file_sha256"),
        }

        # Add metrics (filter out None values)
        for key, value in metrics.items():
            if value is not None:
                entity[key] = value

        # Add ingestion metadata
        now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entity["ingest_version"] = "v1.0.0"
        entity["ingested_at_utc"] = now_utc

        # Store in table
        try:
            table_client = self._get_table_client("Workouts")
            table_client.upsert_entity(entity)
            logger.info("Stored workout %s for %s", workout_id, athlete_id)
            return workout_id
        except Exception as e:
            logger.error("Error storing workout: %s", e)
            raise

    def record_ingestion_state(self, athlete_id: str, file_info: Dict, 
                               status: str, error: Optional[str] = None, 
                               workout_id: Optional[str] = None):
        """
        Record ingestion state for idempotency and debugging.
        
        Args:
            athlete_id: Athlete identifier
            file_info: Source file information
            status: 'ingested', 'failed', 'skipped'
            error: Error message if status is 'failed'
            workout_id: Associated workout_id if successful
        """
        # Use source_item_id as RowKey (primary idempotency key)
        row_key = file_info.get("source_item_id") or file_info.get("file_sha256") or file_info.get("source_file_name")
        
        entity = {
            "PartitionKey": athlete_id,
            "RowKey": row_key,
            "status": status,
            "first_seen_at_utc": file_info.get("first_seen_at_utc", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
            "last_attempt_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "workout_id": workout_id,
            "retry_count": 0,
        }

        if error:
            entity["last_error"] = error[:500]  # Truncate long errors

        try:
            table_client = self._get_table_client("IngestionState")
            table_client.upsert_entity(entity)
            logger.info("Recorded ingestion state for %s: %s", row_key, status)
        except Exception as e:
            logger.error("Error recording ingestion state: %s", e)
            # Don't raise - this shouldn't block the main ingestion

    def get_ingestion_state(self, athlete_id: str, file_key: str) -> Optional[Dict]:
        """Check if file was already ingested."""
        try:
            table_client = self._get_table_client("IngestionState")
            entity = table_client.get_entity(partition_key=athlete_id, row_key=file_key)
            return entity
        except Exception:
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
            "last_updated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        entity.update(rollup_data)

        try:
            table_client = self._get_table_client("WeeklyRollups")
            table_client.upsert_entity(entity)
            logger.info("Updated weekly rollup %s-W%s for %s", year, week, athlete_id)
        except Exception as e:
            logger.error("Error updating weekly rollup: %s", e)
            # Don't raise - rollups are secondary
