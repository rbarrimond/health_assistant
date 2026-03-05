"""Handle Garmin physiometrics sync requests."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, Union

from TrainingAnalyticsPlatform.ingestion.wellness_adapters import (
    AdapterError,
    create_wellness_adapter,
)
from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS = "GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS"


class GarminPhysiometricsSyncHandler:
    """Fetch and ingest daily physiometrics from Garmin summary + training status."""

    def __init__(
        self,
        storage: StorageCoordinator,
        client: Optional[GarminConnectClient] = None,
    ) -> None:
        self.storage = storage
        self.client = client or GarminConnectClient()
        self.adapter = create_wellness_adapter("garmin")

    def handle(
        self,
        athlete_id: str,
        lookback_days: Optional[Union[int, str]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """Fetch and store Garmin physiometrics snapshots by day."""
        if not athlete_id:
            logger.warning("Missing athlete_id for Garmin physiometrics sync")
            return {"error": "athlete_id parameter required"}, 400

        if lookback_days is None:
            try:
                lookback_days = max(
                    1, int(os.getenv(GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS, "7"))
                )
            except ValueError:
                lookback_days = 7
        else:
            try:
                lookback_days = max(1, int(lookback_days))
            except (TypeError, ValueError):
                return {"error": "lookback_days must be a positive integer"}, 400

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        logger.info(
            "Syncing Garmin physiometrics for athlete %s from %s to %s",
            athlete_id,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        stored_count = 0
        errors: list[str] = []

        for current_date in self._iter_dates(start_date, end_date):
            date_str = current_date.isoformat()
            try:
                summary = self.client.get_user_summary(date_str)
                training_status = self.client.get_training_status(date_str)

                snapshot = self.adapter.adapt(
                    {
                        "summary": summary,
                        "training_status": training_status,
                    },
                    athlete_id,
                )

                self.storage.physiometrics.store_physiometrics(
                    athlete_id=athlete_id,
                    physiometrics_data=snapshot.to_storage_dict(),
                    effective_date=snapshot.effective_date,
                    data_source="garmin",
                )
                stored_count += 1
            except (GarminConnectError, AdapterError, StorageError) as exc:
                message = f"{date_str}: {exc}"
                logger.warning("Garmin physiometrics sync error: %s", message)
                errors.append(message)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                message = f"{date_str}: unexpected error: {exc}"
                logger.error("Garmin physiometrics sync unexpected error", exc_info=True)
                errors.append(message)

        return {
            "message": f"Synced {stored_count} Garmin physiometrics records",
            "count": stored_count,
            "errors": errors if errors else None,
        }, 200

    @staticmethod
    def _iter_dates(start_date, end_date):
        """Yield each date in the inclusive range [start_date, end_date]."""
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)
