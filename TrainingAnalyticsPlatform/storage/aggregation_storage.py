"""Training aggregation operations."""

import logging
from datetime import datetime, timezone
from typing import Dict

from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)


class AggregationStorage:
    """Handle training aggregation operations."""

    def __init__(self, infrastructure: StorageInfrastructure):
        """Initialize with storage infrastructure."""
        self.infra = infrastructure

    def update_weekly_rollup(
        self,
        athlete_id: str,
        year: str,
        week: str,
        rollup_data: Dict,
    ) -> None:
        """Store or update aggregated weekly metrics."""

        entity = {
            "PartitionKey": f"{athlete_id}#{year}",
            "RowKey": f"{year}-{week}",
            "last_updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        entity.update(rollup_data)

        try:
            table_client = self.infra.get_table_client("WeeklyRollups")
            table_client.upsert_entity(entity)
            logger.info("Updated weekly rollup %s-W%s for %s", year, week, athlete_id)
        except HttpResponseError as e:
            logger.error("Error updating weekly rollup: %s", e)
            # Don't raise - rollups are secondary
