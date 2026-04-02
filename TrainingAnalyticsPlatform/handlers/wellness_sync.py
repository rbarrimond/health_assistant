"""HTTP handlers for wellness synchronization endpoints.

WellnessSyncHandler: Base class for wellness sync endpoints.
GarminTrainingSyncHandler: POST /api/garmin/training-state/sync
PhysiometricsCurrentHandler: GET /api/physiometrics/current
PhysiometricsHistoryHandler: GET /api/physiometrics/{athlete_id}/{metric_name}
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import azure.functions as func
from azure.storage.blob import ContainerClient

from TrainingAnalyticsPlatform.handlers.wellness_consolidation import \
    PhysiometricsConsolidationHandler
from TrainingAnalyticsPlatform.handlers.wellness_processors import \
    create_processor
from TrainingAnalyticsPlatform.ingestion.wellness_adapters import (
    AdapterError,
    create_wellness_adapter,
)
from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.integrations.intervals_client import IntervalsicuClient
from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot
from TrainingAnalyticsPlatform.platform.exceptions import (
    ExternalServiceError,
    HealthAssistantError,
    StorageError,
    ValidationError,
)
from TrainingAnalyticsPlatform.storage.protocols import StorageInfrastructureProtocol
from TrainingAnalyticsPlatform.storage.source_ingestion_state import \
    SourceIngestionStateStorage

logger = logging.getLogger(__name__)

# Content type constant
JSON_CONTENT_TYPE = "application/json"
HTML_CONTENT_TYPE = "text/html"
WITHINGS_ERROR_HTML = (
    "<html><body><h1>Error</h1>"
    "<p>Missing authorization code or state</p></body></html>"
)
ATHLETE_ID_REQUIRED_ERROR = {"error": "athlete_id parameter required"}
INTERVALS_SYNC_LOOKBACK_DAYS = "INTERVALS_SYNC_LOOKBACK_DAYS"
GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS = "GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS"


class WellnessSourceSyncContract(ABC):
    """Contract for wellness source sync handlers returning payload/status tuples."""

    @abstractmethod
    def handle(self, *args: Any, **kwargs: Any) -> Tuple[Dict[str, Any], int]:
        """Execute sync and return a response payload with HTTP status code."""
        raise NotImplementedError


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


class GarminPhysiometricsSyncHandler(WellnessSourceSyncContract):
    """Canonical wellness-module owner for Garmin physiometrics sync."""

    def __init__(
        self,
        storage: Any,
        client: Optional[GarminConnectClient] = None,
    ) -> None:
        self.storage = storage
        self.client = client or GarminConnectClient()
        self.adapter = create_wellness_adapter("garmin")
        self.ingestion_state = SourceIngestionStateStorage(storage.infrastructure)

    def handle(
        self,
        athlete_id: str,
        lookback_days: Optional[Union[int, str]] = None,
        *,
        force: bool = False,
    ) -> Tuple[Dict[str, Any], int]:
        """Fetch and store Garmin physiometrics snapshots by day."""
        if not athlete_id:
            logger.warning("Missing athlete_id for Garmin physiometrics sync")
            return ATHLETE_ID_REQUIRED_ERROR, 400

        parsed_lookback = self._parse_lookback_days(lookback_days)
        if parsed_lookback is None:
            return {"error": "lookback_days must be a non-negative integer"}, 400

        start_date, end_date = self._resolve_sync_window(parsed_lookback)

        logger.info(
            "Syncing Garmin physiometrics for athlete %s from %s to %s",
            athlete_id,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        auth_error = self._authenticate_client(athlete_id)
        if auth_error is not None:
            return auth_error

        stored_count = 0
        fetched_count = 0
        skipped_count = 0
        errors: list[Dict[str, Any]] = []

        stored_dates = self._prefetch_stored_dates(
            athlete_id=athlete_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            force=force,
        )

        for current_date in self._iter_dates(start_date, end_date):
            date_str = current_date.isoformat()
            if not force and date_str in stored_dates:
                skipped_count += 1
                logger.debug(
                    "Skipping previously stored Garmin physiometrics date",
                    extra={"athlete_id": athlete_id, "effective_date": date_str},
                )
                continue
            success, error, abort = self._ingest_date(athlete_id, date_str)
            if success:
                fetched_count += 1
                stored_count += 1
            if error is not None:
                errors.append(error)
            if abort:
                break

        failed_count = len(errors)
        status = 207 if failed_count > 0 else 200

        self._persist_tokens(athlete_id)

        return {
            "message": f"Synced {stored_count} Garmin physiometrics records",
            "count": stored_count,
            "records_fetched": fetched_count,
            "records_processed": stored_count,
            "records_skipped": skipped_count,
            "records_failed": failed_count,
            "errors": errors or None,
        }, status

    def _ingest_date(
        self, athlete_id: str, date_str: str
    ) -> tuple[bool, Optional[Dict[str, Any]], bool]:
        """Attempt to fetch and store one day of physiometrics.

        Returns:
            success: True when the record was stored successfully.
            error: Failure dict when an error occurred, else None.
            abort: True when the sync loop should terminate immediately.
        """
        blob_name: Optional[str] = None
        try:
            blob_name = self._process_single_day(athlete_id, date_str)
            return True, None, False
        except GarminConnectError as exc:
            issue = self._build_failure(
                date_str=date_str,
                error=str(exc),
                recoverable=self._is_recoverable_garmin_failure(exc),
                **self._classify_garmin_failure(exc),
            )
            logger.warning("Garmin physiometrics sync error: %s", issue["message"])
            self._record_blob_failure(blob_name, str(issue["message"]))
            if self._is_fatal_garmin_error(exc):
                logger.error(
                    "Garmin physiometrics sync aborted due to fatal Garmin error",
                    extra={
                        "athlete_id": athlete_id,
                        "effective_date": date_str,
                        "error": str(exc),
                    },
                )
                return False, issue, True
            return False, issue, False
        except (AdapterError, StorageError) as exc:
            issue = self._build_failure(
                date_str=date_str,
                error=str(exc),
                error_code="OPERATIONAL_ERROR",
                category=type(exc).__name__,
                recoverable=True,
            )
            logger.warning("Garmin physiometrics sync error: %s", issue["message"])
            self._record_blob_failure(blob_name, str(issue["message"]))
            return False, issue, False
        except Exception as exc:  # pylint: disable=broad-exception-caught
            issue = self._build_failure(
                date_str=date_str,
                error=f"unexpected error: {exc}",
                error_code="INTERNAL_SERVER_ERROR",
                category=type(exc).__name__,
                recoverable=False,
            )
            logger.error("Garmin physiometrics sync unexpected error", exc_info=True)
            self._record_blob_failure(blob_name, str(issue["message"]))
            return False, issue, False

    def _persist_rate_limit_cooldown(self, athlete_id: str) -> None:
        """Write the in-process rate-limit expiry to Table Storage for cross-process coordination."""
        blocked_until = self.client.rate_limited_until
        if blocked_until is None:
            return
        try:
            self.storage.oauth_tokens.set_garmin_rate_limit_blocked_until(athlete_id, blocked_until)
        except StorageError:
            logger.warning(
                "Failed to persist Garmin rate-limit cooldown to storage",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

    def _authenticate_client(self, athlete_id: str) -> Optional[Tuple[Dict[str, Any], int]]:
        """Authenticate Garmin client using stored token when possible.

        Returns an HTTP response tuple when authentication fails, else None.
        Checks and persists a shared cross-process rate-limit cooldown via Table Storage.
        """
        # Guard: honour any cross-process rate-limit cooldown before hitting Garmin.
        try:
            blocked_until = self.storage.oauth_tokens.get_garmin_rate_limit_blocked_until(athlete_id)
            if blocked_until is not None:
                logger.warning(
                    "Garmin auth rate-limited (cross-process cooldown active)",
                    extra={
                        "athlete_id": athlete_id,
                        "source_system": "garmin",
                        "blocked_until_utc": blocked_until.isoformat(),
                    },
                )
                return {
                    "error": f"Authentication rate-limited until {blocked_until.isoformat()}",
                    "error_code": "GARMIN_RATE_LIMITED",
                }, 429
        except StorageError:
            # Best-effort: proceed and let the auth attempt surface any live rate limit.
            logger.warning(
                "Could not read Garmin rate-limit cooldown from storage; proceeding with auth",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

        stored_token: Optional[str] = None
        try:
            stored_token = self.storage.oauth_tokens.get_garmin_tokens(athlete_id)
        except StorageError:
            logger.warning(
                "Failed to retrieve stored Garmin tokens; will attempt fresh login",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

        try:
            self.client.authenticate(stored_token)
            return None
        except GarminConnectError as exc:
            if self._is_rate_limited_error(exc):
                self._persist_rate_limit_cooldown(athlete_id)
                logger.error(
                    "Garmin login rate limited for physiometrics sync",
                    extra={
                        "athlete_id": athlete_id,
                        "source_system": "garmin",
                        "error": str(exc),
                    },
                    exc_info=True,
                )
                return {
                    "error": str(exc),
                    "error_code": "GARMIN_RATE_LIMITED",
                }, 429
            logger.error(
                "Failed to authenticate with Garmin Connect for physiometrics sync",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": "GarminConnectError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "error": f"Authentication failed: {exc}",
                "error_code": "GARMIN_AUTH_ERROR",
            }, 401

    @staticmethod
    def _is_rate_limited_error(exc: GarminConnectError) -> bool:
        text = str(exc).lower()
        return "rate limit" in text or "rate limited" in text or "throttle" in text

    @classmethod
    def _is_fatal_garmin_error(cls, exc: GarminConnectError) -> bool:
        text = str(exc).lower()
        if cls._is_rate_limited_error(exc):
            return True
        fatal_markers = (
            "not authenticated",
            "authentication failed",
            "failed to restore garmin session",
            "invalid garmin credentials",
            "missing credentials",
        )
        return any(marker in text for marker in fatal_markers)

    @classmethod
    def _classify_garmin_failure(cls, exc: GarminConnectError) -> Dict[str, str]:
        if cls._is_rate_limited_error(exc):
            return {
                "error_code": "GARMIN_RATE_LIMITED",
                "category": "garmin-auth",
            }
        if cls._is_fatal_garmin_error(exc):
            return {
                "error_code": "GARMIN_AUTH_ERROR",
                "category": "garmin-auth",
            }
        return {
            "error_code": "GARMIN_UPSTREAM_ERROR",
            "category": "garmin-upstream",
        }

    @classmethod
    def _is_recoverable_garmin_failure(cls, exc: GarminConnectError) -> bool:
        return not cls._is_fatal_garmin_error(exc)

    @staticmethod
    def _build_failure(
        *,
        date_str: str,
        error: str,
        error_code: str,
        category: str,
        recoverable: bool,
    ) -> Dict[str, Any]:
        """Build unified error detail object per openapi.operations.yaml contract."""
        now_utc = datetime.now(timezone.utc)
        # Format as ISO-8601 with Z suffix: "2026-03-20T10:30:45Z"
        timestamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "error_code": error_code,
            "recoverable": recoverable,
            "message": f"{date_str}: {error}",
            "timestamp": timestamp,
        }

    def _persist_tokens(self, athlete_id: str) -> None:
        """Persist current Garmin token state for reuse in future invocations."""
        try:
            self.storage.oauth_tokens.store_garmin_tokens(
                athlete_id, self.client.dump_tokens()
            )
            logger.debug(
                "Garmin tokens persisted after physiometrics sync",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )
        except (GarminConnectError, StorageError) as exc:
            logger.warning(
                "Failed to persist Garmin tokens after physiometrics sync; session will not be cached",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

    def _prefetch_stored_dates(
        self,
        *,
        athlete_id: str,
        start_date_iso: str,
        end_date_iso: str,
        force: bool,
    ) -> set[str]:
        """Prefetch already stored effective dates for skip optimization."""
        if force:
            return set()

        try:
            existing = self.storage.physiometrics.get_physiometrics_history(
                athlete_id,
                start_date_iso,
                end_date_iso,
            )
            return {
                str(entity.get("effective_date"))
                for entity in existing
                if entity.get("effective_date")
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to prefetch stored Garmin physiometrics dates; continuing without skip optimization",
                extra={
                    "athlete_id": athlete_id,
                    "effective_start": start_date_iso,
                    "effective_end": end_date_iso,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return set()

    def _parse_lookback_days(
        self,
        lookback_days: Optional[Union[int, str]],
    ) -> Optional[int]:
        """Resolve sync lookback with env fallback and validation."""
        if lookback_days is None:
            raw_value = os.getenv(GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS, "7")
        else:
            raw_value = lookback_days

        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            if lookback_days is None:
                return 7
            return None

    @staticmethod
    def _resolve_sync_window(lookback_days: int) -> tuple[date, date]:
        """Resolve physiometrics sync date window.

        Semantics:
        - lookback_days == 0 -> sync today only
        - lookback_days > 0 -> sync exactly N completed days ending yesterday
        """
        today = datetime.now(timezone.utc).date()
        if lookback_days == 0:
            return today, today

        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=lookback_days - 1)
        return start_date, end_date

    def _process_single_day(self, athlete_id: str, date_str: str) -> str:
        """Fetch, archive, parse, and persist one Garmin physiometrics day."""
        summary = self.client.get_user_summary(date_str)
        training_status = self.client.get_training_status(date_str)
        training_readiness, morning_training_readiness = self._fetch_training_readiness_payloads(date_str)

        blob_name = self._store_raw_payload(
            athlete_id=athlete_id,
            effective_date=date_str,
            summary=summary,
            training_status=training_status,
            training_readiness=training_readiness,
            morning_training_readiness=morning_training_readiness,
        )
        self.ingestion_state.record_blob_fetched(
            source_name="garmin",
            athlete_id=athlete_id,
            blob_name=blob_name,
        )

        parsed = self.adapter._do_parse(
            {
                "summary": summary,
                "training_status": training_status,
                "training_readiness": training_readiness,
                "morning_training_readiness": morning_training_readiness,
            }
        )
        self.adapter.validate_semantic_contract(parsed)
        snapshot = self.adapter.map_to_canonical(parsed, athlete_id)
        storage_dict = snapshot.to_storage_dict()
        storage_dict["ext_json"] = parsed.get("ext_json")

        self._log_storage_metric_presence(
            athlete_id=athlete_id,
            effective_date=snapshot.effective_date,
            storage_dict=storage_dict,
        )
        self.storage.physiometrics.store_physiometrics(
            athlete_id=athlete_id,
            physiometrics_data=storage_dict,
            effective_date=snapshot.effective_date,
            data_source="garmin",
        )
        self.ingestion_state.record_blob_processed(blob_name)
        return blob_name

    def _fetch_training_readiness_payloads(
        self,
        date_str: str,
    ) -> Tuple[
        Optional[Union[Dict[str, Any], list[Dict[str, Any]]]],
        Optional[Dict[str, Any]],
    ]:
        """Fetch Garmin readiness payloads; degrade gracefully when unavailable."""
        training_readiness: Optional[Union[Dict[str, Any], list[Dict[str, Any]]]] = None
        morning_training_readiness: Optional[Dict[str, Any]] = None

        try:
            training_readiness = self.client.get_training_readiness(date_str)
        except GarminConnectError:
            logger.warning(
                "Garmin training readiness unavailable for date",
                extra={"effective_date": date_str},
                exc_info=True,
            )

        try:
            morning_training_readiness = self.client.get_morning_training_readiness(date_str)
        except GarminConnectError:
            logger.warning(
                "Garmin morning training readiness unavailable for date",
                extra={"effective_date": date_str},
                exc_info=True,
            )

        return training_readiness, morning_training_readiness

    def _store_raw_payload(
        self,
        athlete_id: str,
        effective_date: str,
        summary: Dict[str, Any],
        training_status: Dict[str, Any],
        training_readiness: Optional[Union[Dict[str, Any], list[Dict[str, Any]]]],
        morning_training_readiness: Optional[Dict[str, Any]],
    ) -> str:
        """Persist one Garmin daily physiometrics fetch envelope to blob storage."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        blob_name = (
            f"physiometrics/{athlete_id}/garmin/daily/"
            f"{effective_date}_{timestamp}.json"
        )
        envelope = {
            "source": "garmin",
            "athlete_id": athlete_id,
            "effective_date": effective_date,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "summary": summary,
                "training_status": training_status,
                "training_readiness": training_readiness,
                "morning_training_readiness": morning_training_readiness,
            },
        }
        self.storage.infrastructure.upload_external_source_json(blob_name, envelope)
        logger.info(
            "Stored Garmin physiometrics raw payload",
            extra={
                "athlete_id": athlete_id,
                "effective_date": effective_date,
                "blob_name": blob_name,
            },
        )
        return blob_name

    def _record_blob_failure(self, blob_name: Optional[str], message: str) -> None:
        """Record Garmin blob processing failure when archival already succeeded."""
        if blob_name:
            self.ingestion_state.record_blob_failed(blob_name, message)

    @staticmethod
    def _log_storage_metric_presence(
        athlete_id: str,
        effective_date: str,
        storage_dict: Dict[str, Any],
    ) -> None:
        """Log the Garmin metrics that reached the storage boundary."""
        logger.info(
            "Prepared Garmin physiometrics storage payload",
            extra={
                "athlete_id": athlete_id,
                "effective_date": effective_date,
                "has_cycling_vo2max": storage_dict.get("cycling_vo2max_ml_kg_min") is not None,
                "has_running_vo2max": storage_dict.get("running_vo2max_ml_kg_min") is not None,
                "has_training_load": storage_dict.get("training_load") is not None,
                "has_readiness": storage_dict.get("readiness_score") is not None,
                "has_training_status_label": storage_dict.get("training_status_label") is not None,
                "has_load_focus": any(
                    storage_dict.get(k) is not None
                    for k in ["load_focus_low_aerobic_pct", "load_focus_high_aerobic_pct", "load_focus_anaerobic_pct"]
                ),
                "has_ext_json": bool(storage_dict.get("ext_json")),
            },
        )

    @staticmethod
    def _iter_dates(start_date: date, end_date: date):
        """Yield each date in the inclusive range [start_date, end_date]."""
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)


class IntervalsSyncHandler(WellnessSourceSyncContract):
    """Canonical wellness-module owner for Intervals.icu sync.

    This class preserves legacy runtime contracts while owning the
    implementation in the wellness module.
    """

    def __init__(
        self,
        storage: Any,
        client: Optional[IntervalsicuClient] = None,
    ) -> None:
        self.storage = storage
        self.client = client or IntervalsicuClient()
        self.adapter = create_wellness_adapter("intervals")
        self.ingestion_state = SourceIngestionStateStorage(storage.infrastructure)

    def handle(
        self,
        intervals_athlete_id: str,
        athlete_id: str,
        lookback_days: Optional[int] = None,
        force: bool = False,
    ) -> Tuple[Dict[str, Any], int]:
        """Fetch and store physiometrics from Intervals.icu."""
        if not intervals_athlete_id:
            logger.warning("Missing intervals_athlete_id for Intervals sync")
            return {"error": "intervals_athlete_id parameter required"}, 400

        if not athlete_id:
            logger.warning("Missing athlete_id for storage")
            return ATHLETE_ID_REQUIRED_ERROR, 400

        if lookback_days is None:
            try:
                lookback_days = max(1, int(os.getenv(INTERVALS_SYNC_LOOKBACK_DAYS, "30")))
            except ValueError:
                lookback_days = 30
        elif lookback_days < 0:
            return {"error": "lookback_days must be a non-negative integer"}, 400

        start_date, end_date = self._resolve_sync_window(lookback_days)

        logger.info(
            "Syncing Intervals.icu data: fetching with intervals_athlete_id=%s, storing to athlete_id=%s from %s to %s",
            intervals_athlete_id,
            athlete_id,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        try:
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
                    "force": force,
                    "records_fetched": 0,
                    "records_processed": 0,
                    "records_failed": 0,
                    "blob_name": blob_name,
                }, 200

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
                "force": force,
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

    @staticmethod
    def _resolve_sync_window(lookback_days: int) -> tuple[date, date]:
        """Resolve physiometrics sync date window.

        Semantics:
        - lookback_days == 0 -> sync today only
        - lookback_days > 0 -> sync exactly N completed days ending yesterday
        """
        today = datetime.now(timezone.utc).date()
        if lookback_days == 0:
            return today, today

        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=lookback_days - 1)
        return start_date, end_date

    def _process_wellness_records(
        self, athlete_id: str, wellness_records: Dict[str, Any] | list
    ) -> Tuple[int, list, int]:
        """Process and store a batch of wellness records."""
        stored_count = 0
        errors: list = []

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
        """Parse, validate, and store a single measurement."""
        parsed = self.adapter._do_parse(measurement)

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

        snapshot: PhysiometricsSnapshot = self.adapter.map_to_canonical(parsed, athlete_id)

        storage_dict = snapshot.to_storage_dict()
        storage_dict["sport_info_json"] = parsed.get("sport_info_json")
        storage_dict["raw_intervals_icu_json"] = json.dumps(measurement, default=str)

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


class WithingsWellnessService:
    """Canonical wellness-module owner for Withings OAuth and webhook flows."""

    def __init__(self, withings_client: WithingsClient, storage: Any) -> None:
        self.client = withings_client
        self.storage = storage
        self._logger = logger

    def get_authorization_url(self, athlete_id: str) -> tuple[Dict[str, Any], int]:
        """Generate Withings OAuth authorization URL."""
        if not athlete_id:
            return ATHLETE_ID_REQUIRED_ERROR, 400

        try:
            auth_url, _ = self.client.get_authorization_url(athlete_id)

            return {
                "authorization_url": auth_url,
                "instructions": "Open this URL in your browser to authorize Withings access",
                "athlete_id": athlete_id,
            }, 200
        except ValidationError as exc:
            self._logger.error(
                "Invalid Withings authorization request: %s",
                exc,
                exc_info=True,
            )
            return {"error": str(exc)}, 400
        except HealthAssistantError as exc:
            self._logger.error(
                "Error generating Withings auth URL: %s",
                exc,
                exc_info=True,
            )
            return {"error": "Failed to generate authorization URL"}, 500
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logger.error(
                "Error generating Withings auth URL: %s",
                exc,
                exc_info=True,
            )
            return {"error": "Failed to generate authorization URL"}, 500

    def handle_oauth_callback(
        self,
        code: str,
        state: str,
        webhook_callback_url: str,
    ) -> tuple[str, int, str]:
        """Process OAuth callback and store tokens."""
        if not code or not state:
            return WITHINGS_ERROR_HTML, 400, HTML_CONTENT_TYPE

        try:
            token_data = self.client.exchange_auth_code(code, state)

            self.storage.oauth_tokens.store_withings_tokens(
                athlete_id=token_data["athlete_id"],
                withings_userid=str(token_data["userid"]),
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_in=token_data["expires_in"],
                scope=token_data["scope"],
            )

            callback_url = os.getenv(
                "WITHINGS_WEBHOOK_URL",
                webhook_callback_url,
            )
            parsed_callback_url = urlparse(callback_url)
            callback_port = parsed_callback_url.port
            webhook_subscription_skipped = callback_port not in (None, 80, 443)
            if webhook_subscription_skipped:
                self._logger.warning(
                    "Skipping Withings webhook subscription due to unsupported callback port",
                    extra={
                        "callback_url": callback_url,
                        "callback_port": callback_port,
                    },
                )
            else:
                self.client.subscribe_to_notifications(
                    access_token=token_data["access_token"],
                    callback_url=callback_url,
                )

            self._logger.info(
                "Successfully connected Withings for athlete %s (userid: %s)",
                token_data["athlete_id"],
                token_data["userid"],
            )

            success_html = f"""<html>
                <body>
                    <h1>Success!</h1>
                    <p>Withings connected for athlete {token_data['athlete_id']}.</p>
                    <p>Weight measurements will now sync automatically.</p>
                    {
                        '<p>Webhook subscription was skipped because callback URL port must be 80 or 443.</p>'
                        if webhook_subscription_skipped else ''
                    }
                    <p>You can close this window and return to the chat.</p>
                </body>
                </html>"""

            return success_html, 200, HTML_CONTENT_TYPE

        except ValidationError as exc:
            self._logger.error(
                "Invalid Withings callback payload: %s",
                exc,
                exc_info=True,
            )
            error_html = (
                "<html><body><h1>Error</h1>"
                f"<p>{exc}</p>"
                "</body></html>"
            )
            return error_html, 400, HTML_CONTENT_TYPE
        except HealthAssistantError as exc:
            self._logger.error(
                "Error in Withings callback: %s",
                exc,
                exc_info=True,
            )
            error_html = (
                "<html><body><h1>Error</h1>"
                f"<p>Failed to connect Withings account: {exc}</p>"
                "</body></html>"
            )
            return error_html, 500, HTML_CONTENT_TYPE
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logger.error(
                "Error in Withings callback: %s",
                exc,
                exc_info=True,
            )
            error_html = (
                "<html><body><h1>Error</h1>"
                f"<p>Failed to connect Withings account: {exc}</p>"
                "</body></html>"
            )
            return error_html, 500, HTML_CONTENT_TYPE

    def process_webhook(
        self,
        userid: str,
        appli: str,
        startdate: str,
        enddate: str,
    ) -> tuple[str, int]:
        """Process Withings webhook notification."""
        try:
            if not all([userid, appli, startdate, enddate]):
                self._logger.warning("Invalid Withings webhook payload: missing fields")
                return "Missing required fields", 400

            if appli != "1":
                self._logger.info("Ignoring non-weight notification (appli=%s)", appli)
                return "OK", 200

            self._logger.info(
                "Received Withings webhook: userid=%s, startdate=%s, enddate=%s",
                userid,
                startdate,
                enddate,
            )

            return "OK", 200

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logger.error(
                "Error processing Withings webhook: %s",
                exc,
                exc_info=True,
            )
            return "Temporary processing failure", 503
