"""Webhook deduplication tracking."""

import logging
from datetime import datetime, timezone
from typing import Optional

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)


class WebhookDedupStorage:
    """Handle webhook deduplication markers."""

    def __init__(self, infrastructure: StorageInfrastructure):
        """Initialize with storage infrastructure."""
        self.infra = infrastructure

    def webhook_already_processed(
        self,
        athlete_id: str,
        withings_userid: str,
        enddate: str,
    ) -> bool:
        """Check if a Withings webhook has already been processed."""
        try:
            table_client = self.infra.get_table_client("WebhookDeduplication")

            try:
                row_key = f"{withings_userid}_{enddate}"
                table_client.get_entity(partition_key=athlete_id, row_key=row_key)
                return True  # Entity exists, already processed
            except ResourceNotFoundError:
                return False  # Not processed yet

        except HttpResponseError as e:
            logger.warning("Error checking webhook deduplication: %s", e)
            return False  # On error, allow processing

    def mark_webhook_processed(
        self,
        athlete_id: str,
        withings_userid: str,
        enddate: str,
    ) -> None:
        """Record webhook as processed."""
        processed_at = datetime.now(timezone.utc).isoformat()

        try:
            table_client = self.infra.get_table_client("WebhookDeduplication")

            row_key = f"{withings_userid}_{enddate}"
            entity = {
                "PartitionKey": athlete_id,
                "RowKey": row_key,
                "processed_at_utc": processed_at,
                "withings_userid": withings_userid,
                "enddate": enddate,
            }

            table_client.upsert_entity(entity)
            logger.info("Marked webhook processed: %s", row_key)

        except HttpResponseError as e:
            logger.error("Error marking webhook as processed: %s", e)
            # Don't raise - this shouldn't block webhook processing
