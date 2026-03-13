"""Training aggregation operations."""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict

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
            "PartitionKey": f"{athlete_id}|{year}",
            "RowKey": f"{year}-{week}",
            "last_updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        entity.update(self._sanitize_rollup_data(rollup_data))

        try:
            table_client = self.infra.get_table_client("WeeklyRollups")
            table_client.upsert_entity(entity)
            logger.info("Updated weekly rollup %s-W%s for %s", year, week, athlete_id)
        except HttpResponseError as e:
            logger.error("Error updating weekly rollup: %s", e)
            # Don't raise - rollups are secondary

    def _sanitize_rollup_data(self, rollup_data: Dict[str, Any]) -> Dict[str, Any]:
        """Return Azure Table-safe rollup payload values."""
        sanitized: Dict[str, Any] = {}
        for key, value in rollup_data.items():
            if value is None:
                continue

            if isinstance(value, (dict, list, tuple, set)):
                logger.warning(
                    "Skipping unsupported weekly rollup property type",
                    extra={
                        "property": key,
                        "value_type": type(value).__name__,
                    },
                )
                continue

            if isinstance(value, float) and not math.isfinite(value):
                logger.warning(
                    "Skipping non-finite weekly rollup numeric value",
                    extra={
                        "property": key,
                        "value": value,
                    },
                )
                continue

            sanitized[key] = value

        return sanitized
