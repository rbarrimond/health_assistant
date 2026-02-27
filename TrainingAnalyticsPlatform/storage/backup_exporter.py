"""Backup export functionality for health data tables."""

import json
import logging
import os
from datetime import datetime, timezone

from azure.storage.blob import BlobClient

from TrainingAnalyticsPlatform.platform.config import Config
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)


class BackupExporter:
    """Exports table data to read-only blobs for daily backups."""

    def __init__(self, storage: StorageCoordinator):
        """Initialize exporter with storage client.
        
        Args:
            storage: StorageCoordinator instance with table clients
        """
        self.storage = storage
        self.config = Config()

    def export_all_tables(self) -> dict:
        """Export all tables to JSON blob backup.
        
        Returns:
            dict with export status: {"status": "success", "blob_url": "...", "tables": {...}}
        """
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
            export_data = {
                "export_timestamp": timestamp,
                "tables": {},
                "row_counts": {}
            }

            # Export each table
            for table_name in ["Workouts", "WorkoutLaps", "WeeklyRollups",
                                "IngestionState", "Physiometrics"]:
                try:
                    rows = self._export_table(table_name)
                    export_data["tables"][table_name] = rows
                    export_data["row_counts"][table_name] = len(rows)
                    logger.info("Exported %d rows from %s", len(rows), table_name)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("Failed to export %s: %s", table_name, e)
                    export_data["tables"][table_name] = []
                    export_data["row_counts"][table_name] = 0

            # Upload to blob
            blob_url = self._upload_backup_blob(export_data, timestamp)
            export_data["backup_blob_url"] = blob_url

            logger.info("Backup export completed: %s", blob_url)
            return {
                "status": "success",
                "blob_url": blob_url,
                "tables": export_data["row_counts"]
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Backup export failed: %s", e, exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }

    def _export_table(self, table_name: str) -> list:
        """Export a single table to list of dicts.
        
        Args:
            table_name: Name of the table to export
            
        Returns:
            List of table entities as dictionaries
        """
        table_client = self.storage.infrastructure.get_table_client(table_name)  # pylint: disable=protected-access
        rows = []

        # Query all entities (no filter = all rows)
        for entity in table_client.query_entities(""):
            # Convert entity to dict, removing internal Azure metadata
            row = dict(entity)
            # Remove internal timestamp fields
            row.pop("odata.metadata", None)
            row.pop("odata.type", None)
            rows.append(row)

        return rows

    def _upload_backup_blob(self, export_data: dict, timestamp: str) -> str:
        """Upload export JSON to blob storage.

        Args:
            export_data: Dictionary to serialize to JSON
            timestamp: Timestamp string for blob naming

        Returns:
            Blob URL (without SAS token for read-only access)
        """
        # Construct blob name: backups/YYYY-MM-DD/HH-MM-SSZ.json
        blob_name = f"backups/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}/{timestamp}.json"

        # Get connection string from environment
        connection_string = os.getenv("AzureWebJobsStorage")
        if not connection_string:
            raise ValueError("AzureWebJobsStorage environment variable is not set")

        blob_client = BlobClient.from_connection_string(
            connection_string,
            container_name="backups",
            blob_name=blob_name
        )

        # Upload JSON blob
        json_data = json.dumps(export_data, indent=2, default=str)
        blob_client.upload_blob(json_data, overwrite=False)

        return f"{blob_client.account_name}/backups/{blob_name}"
