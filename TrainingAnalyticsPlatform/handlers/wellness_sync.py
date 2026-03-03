"""HTTP handlers for wellness synchronization endpoints.

WellnessSyncHandler: Base class for wellness sync endpoints.
GarminTrainingSyncHandler: POST /api/garmin/training-state/sync
PhysiometricsCurrentHandler: GET /api/physiometrics/current
PhysiometricsHistoryHandler: GET /api/physiometrics/{athlete_id}/{metric_name}
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import azure.functions as func
from azure.storage.blob import ContainerClient

from TrainingAnalyticsPlatform.handlers.wellness_consolidation import \
    PhysiometricsConsolidationHandler
from TrainingAnalyticsPlatform.handlers.wellness_processors import \
    create_processor
from TrainingAnalyticsPlatform.storage.protocols import StorageInfrastructureProtocol
from TrainingAnalyticsPlatform.storage.source_ingestion_state import \
    SourceIngestionStateStorage

logger = logging.getLogger(__name__)

# Content type constant
JSON_CONTENT_TYPE = "application/json"


class WellnessSyncHandler(ABC):
    """Base class for wellness sync endpoints."""

    def __init__(
        self,
        blob_client: ContainerClient,
        table_storage: StorageInfrastructureProtocol,
        source_name: str,
    ):
        """Initialize sync handler.

        Args:
            blob_client: Azure Blob Storage container client
            table_storage: Azure Table Storage client
            source_name: Source identifier (e.g., 'garmin', 'withings')
        """
        self.blob_client = blob_client
        self.table_storage = table_storage
        self.source_name = source_name
        self.ingestion_state = SourceIngestionStateStorage(table_storage)

    @abstractmethod
    def fetch_source_data(self, athlete_id: str, **kwargs) -> Dict[str, Any]:
        """Fetch raw data from source API.

        Args:
            athlete_id: Athlete identifier
            **kwargs: Source-specific arguments

        Returns:
            Raw API response (dict)
        """
        pass

    def handle_sync(
        self, req: func.HttpRequest, athlete_id: str, **kwargs
    ) -> func.HttpResponse:
        """Orchestrate sync: fetch → store blob → record ingestion state → process.

        Args:
            req: HTTP request
            athlete_id: Athlete identifier
            **kwargs: Source-specific arguments

        Returns:
            HTTP response
        """
        try:
            # Fetch from source
            logger.info("Fetching %s data for athlete %s", self.source_name, athlete_id)
            raw_data = self.fetch_source_data(athlete_id, **kwargs)

            # Store blob
            timestamp_utc = datetime.now(timezone.utc).isoformat()
            blob_name = (
                f"{self.source_name}/{athlete_id}/"
                f"{timestamp_utc.replace(':', '-')}.json"
            )
            blob_content = json.dumps(raw_data, default=str).encode("utf-8")

            logger.info("Storing blob: %s", blob_name)
            self.blob_client.upload_blob(blob_name, blob_content, overwrite=True)

            # Record fetched state
            self.ingestion_state.record_blob_fetched(
                source_name=self.source_name,
                athlete_id=athlete_id,
                blob_name=blob_name,
            )

            # Process blob
            processor = create_processor(
                self.source_name,
                self.table_storage,
                self.ingestion_state,
            )

            logger.info("Processing blob: %s", blob_name)
            processor.process(blob_name, raw_data)

            return func.HttpResponse(
                json.dumps({
                    "status": "success",
                    "source": self.source_name,
                    "athlete_id": athlete_id,
                    "blob_name": blob_name,
                }),
                status_code=200,
                mimetype=JSON_CONTENT_TYPE,
            )

        except Exception as e:
            logger.exception(
                "Error syncing %s data for athlete %s", self.source_name, athlete_id
            )
            return func.HttpResponse(
                json.dumps({
                    "status": "error",
                    "message": str(e),
                    "source": self.source_name,
                }),
                status_code=500,
                mimetype=JSON_CONTENT_TYPE,
            )


class GarminTrainingSyncHandler(WellnessSyncHandler):
    """Sync Garmin training state data."""

    def __init__(
        self,
        blob_client: ContainerClient,
        table_storage: StorageInfrastructureProtocol,
        garmin_client: Any,  # GarminConnectClient (injected at runtime)
    ):
        """Initialize Garmin sync handler.

        Args:
            blob_client: Blob container client for external-sources
            table_storage: Table storage client
            garmin_client: Garmin Connect API client
        """
        super().__init__(blob_client, table_storage, "garmin")
        self.garmin_client = garmin_client

    def fetch_source_data(self, athlete_id: str, **kwargs) -> Dict[str, Any]:
        """Fetch latest Garmin training metrics.

        Args:
            athlete_id: Garmin athlete/user ID
            **kwargs: Unused

        Returns:
            Dict with keys: ftp_watts, vo2max_running, vo2max_cycling, lthr, max_hr, etc.
        """
        # Placeholder: production would call self.garmin_client.get_user_summary(athlete_id)
        logger.info("Fetching Garmin training data for athlete %s", athlete_id)

        # Example response shape
        return {
            "userId": int(athlete_id),
            "displayName": f"Athlete {athlete_id}",
            "stats": {
                "maxHeartRate": 190,
                "restingHeartRate": 52,
                "vo2MaxRunning": {"value": 52.8},
                "vo2MaxCycling": {"value": 72.5},
                "functionThreshold": 325,  # watts
                "trainingLoad": {"load": 42},
                "bodyComposition": {
                    "weight": 72.5,
                },
                "readiness": {"score": 75},
            },
            "fetchedAtUtc": datetime.now(timezone.utc).isoformat(),
        }


class WithingsPhysiometricsSyncHandler(WellnessSyncHandler):
    """Sync Withings body metrics data."""

    def __init__(
        self,
        blob_client: ContainerClient,
        table_storage: StorageInfrastructureProtocol,
        withings_client: Any,  # WithingsOpenAPIClient (injected)
    ):
        """Initialize Withings sync handler.

        Args:
            blob_client: Blob container client
            table_storage: Table storage client
            withings_client: Withings OpenAPI client
        """
        super().__init__(blob_client, table_storage, "withings")
        self.withings_client = withings_client

    def fetch_source_data(self, athlete_id: str, **kwargs) -> Dict[str, Any]:
        """Fetch Withings measures for athlete.

        Args:
            athlete_id: Withings user ID
            **kwargs: Optional start_date, end_date

        Returns:
            Dict with measures list
        """
        logger.info("Fetching Withings data for athlete %s", athlete_id)

        # Placeholder: production would call self.withings_client.get_measures(user_id, ...)
        return {
            "status": 0,
            "body": {
                "measuregrps": [
                    {
                        "grpid": 12345,
                        "attrib": 0,
                        "date": int(datetime.now(timezone.utc).timestamp()),
                        "created": int(datetime.now(timezone.utc).timestamp()),
                        "measures": [
                            {
                                "value": 72500,  # weight in grams
                                "type": 1,  # Type 1 = weight
                                "unit": -3,  # -3 = kg (divide by 10^3)
                            },
                            {
                                "value": 25,  # body fat %
                                "type": 6,  # Type 6 = body fat
                                "unit": 0,  # 0 = percentage (divide by 10^2)
                            },
                        ],
                    }
                ]
            },
            "fetchedAtUtc": datetime.now(timezone.utc).isoformat(),
        }


class PhysiometricsCurrentHandler:
    """GET /api/physiometrics/current - Retrieve latest physiometrics.

    Returns consolidated physiometrics for today or latest date.
    """

    def __init__(self, table_storage: StorageInfrastructureProtocol):
        """Initialize handler.

        Args:
            table_storage: Table storage client
        """
        self.table_storage = table_storage
        self.consolidator = PhysiometricsConsolidationHandler(table_storage)

    def handle(self, athlete_id: str) -> func.HttpResponse:
        """Handle GET request for current physiometrics.

        Args:
            athlete_id: Athlete identifier

        Returns:
            HTTP response with JSON
        """
        try:
            today = datetime.now(timezone.utc).date().isoformat()

            consolidated = self.consolidator.consolidate_day(athlete_id, today)

            return func.HttpResponse(
                json.dumps(consolidated.dict(exclude_none=True), default=str),
                status_code=200,
                mimetype=JSON_CONTENT_TYPE,
            )
        except Exception as e:
            logger.exception("Error fetching current physiometrics for %s", athlete_id)
            return func.HttpResponse(
                json.dumps({"status": "error", "message": str(e)}),
                status_code=500,
                mimetype=JSON_CONTENT_TYPE,
            )


class PhysiometricsHistoryHandler:
    """GET /api/physiometrics/{athlete_id}/{metric_name} - Retrieve historical data.

    Returns time-series of metric for athlete (optionally filtered by date range).
    """

    def __init__(self, table_storage: StorageInfrastructureProtocol):
        """Initialize handler.

        Args:
            table_storage: Table storage client
        """
        self.table_storage = table_storage

    def handle(
        self,
        req: func.HttpRequest,
        athlete_id: str,
        metric_name: str,
    ) -> func.HttpResponse:
        """Handle GET request for metric history.

        Args:
            req: HTTP request with optional query params:
                - start_date: YYYY-MM-DD (min)
                - end_date: YYYY-MM-DD (max)
                - limit: Max results (default 100)
            athlete_id: Athlete identifier
            metric_name: Metric name (e.g., 'weight_kg', 'hrv_ln_rmssd')

        Returns:
            HTTP response with array of {date, value, sources}
        """
        try:
            start_date = req.params.get("start_date")
            end_date = req.params.get("end_date")
            limit = int(req.params.get("limit", "100"))

            phys_table = self.table_storage.get_table_client("Physiometrics")

            # Query physiometrics for athlete
            filter_str = f"PartitionKey eq '{athlete_id}'"
            entities = list(phys_table.query_entities(filter_str))

            # Filter by date range if provided
            if start_date:
                entities = [e for e in entities if e.get("effective_date", "") >= start_date]
            if end_date:
                entities = [e for e in entities if e.get("effective_date", "") <= end_date]

            # Sort by date descending
            entities.sort(key=lambda e: e.get("effective_date", ""), reverse=True)

            # Extract metric time series
            timeseries = []
            for entity in entities[:limit]:
                value = entity.get(metric_name)
                if value is not None:
                    timeseries.append({
                        "date": entity.get("effective_date"),
                        "value": value,
                        "sources": entity.get("data_sources", "").split(","),
                    })

            return func.HttpResponse(
                json.dumps(timeseries, default=str),
                status_code=200,
                mimetype=JSON_CONTENT_TYPE,
            )
        except Exception as e:
            logger.exception(
                "Error fetching %s history for %s", metric_name, athlete_id
            )
            return func.HttpResponse(
                json.dumps({"status": "error", "message": str(e)}),
                status_code=500,
                mimetype=JSON_CONTENT_TYPE,
            )
