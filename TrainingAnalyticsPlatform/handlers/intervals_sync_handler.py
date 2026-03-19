"""Handle Intervals.icu sync requests."""
import json
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
from TrainingAnalyticsPlatform.storage.source_ingestion_state import (
    SourceIngestionStateStorage,
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
        self.ingestion_state = SourceIngestionStateStorage(storage.infrastructure)

    def handle(
        self,
        intervals_athlete_id: str,
        athlete_id: str,
        lookback_days: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """
        Fetch and store physiometrics from Intervals.icu.

        Args:
            intervals_athlete_id: Athlete identifier in Intervals.icu (for API URL)
            athlete_id: Athlete identifier for storage partition
            lookback_days: How many days back to fetch (default from env or 30)

        Returns:
            Tuple of (response_dict, http_status_code)
        """
        if not intervals_athlete_id:
            logger.warning("Missing intervals_athlete_id for Intervals sync")
            return {"error": "intervals_athlete_id parameter required"}, 400
        
        if not athlete_id:
            logger.warning("Missing athlete_id for storage")
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
            "Syncing Intervals.icu data: fetching with intervals_athlete_id=%s, storing to athlete_id=%s from %s to %s",
            intervals_athlete_id,
            athlete_id,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        try:
            # Fetch using intervals_athlete_id (Intervals backend identity)
            wellness_records = self.client.get_athlete_wellness(
                athlete_id=intervals_athlete_id,
                oldest=start_date.isoformat(),
                newest=end_date.isoformat(),
            )

            blob_name = self._store_raw_payload(
                athlete_id=athlete_id,
                intervals_athlete_id=intervals_athlete_id,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                payload=wellness_records,
            )
            self.ingestion_state.record_blob_fetched(
                source_name="intervals",
                athlete_id=athlete_id,
                blob_name=blob_name,
            )

            if not wellness_records:
                logger.info("No measurements found for intervals_athlete_id=%s", intervals_athlete_id)
                self.ingestion_state.record_blob_processed(blob_name)
                return {
                    "message": "No measurements found",
                    "count": 0,
                    "records_fetched": 0,
                    "records_processed": 0,
                    "records_failed": 0,
                    "blob_name": blob_name,
                }, 200

            # Process and store using storage athlete_id
            stored_count, errors, fetched_count = self._process_wellness_records(
                athlete_id,
                wellness_records,
            )

            failed_count = len(errors)
            status = 207 if failed_count > 0 else 200
            if failed_count > 0:
                self.ingestion_state.record_blob_failed(
                    blob_name,
                    f"{failed_count} record(s) failed during Intervals ingestion",
                )
            else:
                self.ingestion_state.record_blob_processed(blob_name)

            return {
                "message": f"Synced {stored_count} wellness records",
                "count": stored_count,
                "records_fetched": fetched_count,
                "records_processed": stored_count,
                "records_failed": failed_count,
                "blob_name": blob_name,
                "errors": errors if errors else None,
            }, status

        except ExternalServiceError as exc:
            logger.error(
                "Intervals.icu API error",
                extra={
                    "intervals_athlete_id": intervals_athlete_id,
                    "athlete_id": athlete_id,
                    "source_system": "intervals",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return exc.to_response()

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Unexpected error in Intervals sync",
                extra={
                    "intervals_athlete_id": intervals_athlete_id,
                    "athlete_id": athlete_id,
                    "source_system": "intervals",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {"error": str(exc)}, 500

    def _process_wellness_records(
        self, athlete_id: str, wellness_records: Dict[str, Any] | list
    ) -> Tuple[int, list, int]:
        """Process and store a batch of wellness records.

        Args:
            athlete_id: Athlete identifier
            wellness_records: Single wellness dict or list of wellness dicts

        Returns:
            Tuple of (count stored, list of error messages, fetched count)
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

        return stored_count, errors, len(measurement_list)

    def _store_raw_payload(
        self,
        athlete_id: str,
        intervals_athlete_id: str,
        start_date: str,
        end_date: str,
        payload: Dict[str, Any] | list,
    ) -> str:
        """Persist raw Intervals fetch payload to external-sources container."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        blob_name = (
            f"physiometrics/{athlete_id}/intervals/daily/"
            f"{start_date}_to_{end_date}_{timestamp}.json"
        )
        envelope = {
            "source": "intervals",
            "athlete_id": athlete_id,
            "intervals_athlete_id": intervals_athlete_id,
            "start_date": start_date,
            "end_date": end_date,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self.storage.infrastructure.upload_external_source_json(blob_name, envelope)
        logger.info(
            "Stored Intervals raw payload",
            extra={
                "athlete_id": athlete_id,
                "intervals_athlete_id": intervals_athlete_id,
                "blob_name": blob_name,
            },
        )
        return blob_name

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
        has_hrv_sdnn = parsed.get("hrv_sdnn_ms") is not None
        has_spo2 = parsed.get("spo2_pct") is not None
        
        self.adapter.validate_semantic_contract(parsed)

        # Map to canonical physiometrics model
        snapshot: PhysiometricsSnapshot = self.adapter.map_to_canonical(
            parsed, athlete_id
        )

        # Convert snapshot to storage dict (explicit typed boundary)
        storage_dict = snapshot.to_storage_dict()
        storage_dict["sport_info_json"] = parsed.get("sport_info_json")
        storage_dict["raw_intervals_icu_json"] = json.dumps(measurement, default=str)

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
                "has_hrv_sdnn": has_hrv_sdnn,
                "has_spo2": has_spo2,
            },
        )

