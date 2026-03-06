"""Handle Intervals.icu sync requests."""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.ingestion.wellness_adapters import (
    AdapterError,
    create_wellness_adapter,
)
from TrainingAnalyticsPlatform.integrations.intervals_client import IntervalsicuClient
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot
from TrainingAnalyticsPlatform.platform.exceptions import (
    ExternalServiceError,
    StorageError,
)
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

INTERVALS_SYNC_LOOKBACK_DAYS = "INTERVALS_SYNC_LOOKBACK_DAYS"


class IntervalsSyncHandler:
    """Fetch and ingest daily physiometrics from Intervals.icu."""

    def __init__(
        self,
        storage: StorageCoordinator,
        client: Optional[IntervalsicuClient] = None,
    ) -> None:
        """
        Initialize handler with storage and client.

        Args:
            storage: StorageCoordinator for persistence
            client: IntervalsicuClient instance (creates default if not provided)
        """
        self.storage = storage
        self.client = client or IntervalsicuClient()
        self.adapter = create_wellness_adapter("intervals")

    def handle(
        self,
        athlete_id: str,
        lookback_days: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Fetch and store physiometrics from Intervals.icu.

        Args:
            athlete_id: Athlete identifier in Intervals.icu
            lookback_days: How many days back to fetch (default from env or 30)

        Returns:
            Tuple of (response_dict, http_status_code)
        """
        if not athlete_id:
            logger.warning("Missing athlete_id for Intervals sync")
            return {"error": "athlete_id parameter required"}, 400

        # Determine lookback period
        if lookback_days is None:
            try:
                lookback_days = max(
                    1, int(os.getenv(INTERVALS_SYNC_LOOKBACK_DAYS, "30"))
                )
            except ValueError:
                lookback_days = 30

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)

        logger.info(
            "Syncing Intervals.icu data for athlete %s from %s to %s",
            athlete_id,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        try:
            wellness_records = self.client.get_athlete_wellness(
                athlete_id=athlete_id,
                oldest=start_date.isoformat(),
                newest=end_date.isoformat(),
            )

            if not wellness_records:
                logger.info("No measurements found for athlete %s", athlete_id)
                return {"message": "No measurements found", "count": 0}, 200

            stored_count, errors = self._process_wellness_records(athlete_id, wellness_records)

            return {
                "message": f"Synced {stored_count} wellness records",
                "count": stored_count,
                "errors": errors if errors else None,
            }, 200

        except ExternalServiceError as exc:
            logger.error("Intervals.icu API error: %s", exc)
            return {"error": f"Intervals.icu API error: {exc}"}, 502

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Unexpected error in Intervals sync: %s", exc, exc_info=True)
            return {"error": "Internal server error"}, 500

    def _process_wellness_records(
        self, athlete_id: str, wellness_records: Dict[str, Any] | list
    ) -> Tuple[int, list]:
        """Process and store a batch of wellness records.

        Args:
            athlete_id: Athlete identifier
            wellness_records: Single wellness dict or list of wellness dicts

        Returns:
            Tuple of (count stored, list of error messages)
        """
        stored_count = 0
        errors: list = []

        # Handle both single dict and list responses from API
        measurement_list = wellness_records if isinstance(wellness_records, list) else [wellness_records]

        for measurement in measurement_list:
            try:
                self._store_single_measurement(athlete_id, measurement)
                stored_count += 1
            except AdapterError as exc:
                msg = f"Adapter error for measurement: {exc}"
                logger.warning(msg)
                errors.append(msg)
            except StorageError as exc:
                msg = f"Storage error: {exc}"
                logger.error(msg)
                errors.append(msg)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                msg = f"Unexpected error processing measurement: {exc}"
                logger.error(msg, exc_info=True)
                errors.append(msg)

        return stored_count, errors

    def _store_single_measurement(
        self, athlete_id: str, measurement: Dict[str, Any]
    ) -> None:
        """Parse, validate, and store a single measurement.

        Args:
            athlete_id: Athlete identifier
            measurement: Raw measurement dict from API

        Raises:
            AdapterError: If adapter validation fails
            StorageError: If storage operation fails
        """
        # Validate and parse raw data
        parsed = self.adapter._do_parse(measurement)
        
        # Log presence of expected Intervals fields for diagnostics
        # (helps distinguish missing-column issues: are values null in source or dropped in storage?)
        has_hrv = parsed.get("hrv") is not None
        has_readiness = parsed.get("readiness") is not None
        has_nutrition = any(
            parsed.get(f) is not None 
            for f in ["calories_kcal", "carbs_g", "protein_g", "fat_g"]
        )
        has_resting_hr = parsed.get("rhr") is not None
        
        self.adapter.validate_semantic_contract(parsed)

        # Map to canonical physiometrics model
        snapshot: PhysiometricsSnapshot = self.adapter.map_to_canonical(
            parsed, athlete_id
        )

        # Convert snapshot to storage dict (explicit typed boundary)
        storage_dict = snapshot.to_storage_dict()

        # Store physiometrics
        self.storage.physiometrics.store_physiometrics(
            athlete_id=athlete_id,
            physiometrics_data=storage_dict,
            effective_date=snapshot.effective_date,
            data_source="intervals",
        )

        logger.info(
            "Stored physiometrics",
            extra={
                "athlete_id": athlete_id,
                "effective_date": snapshot.effective_date,
                "data_source": "intervals",
                "has_hrv": has_hrv,
                "has_readiness": has_readiness,
                "has_nutrition": has_nutrition,
                "has_resting_hr": has_resting_hr,
            },
        )

