"""Handle Garmin Connect sync requests and ingestion."""
# pylint: disable=trailing-whitespace, line-too-long

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.ingestion.fit_parser import compute_bytes_hash
from TrainingAnalyticsPlatform.storage.table_storage import IngestionContext, WorkoutTableStorage

from .ingestion_base_handler import FitIngestionBaseHandler

logger = logging.getLogger(__name__)

GARMIN_SYNC_LOOKBACK_DAYS = "GARMIN_SYNC_LOOKBACK_DAYS"
GARMIN_EMAIL = "GARMIN_EMAIL"
GARMIN_PASSWORD = "GARMIN_PASSWORD"


@dataclass(frozen=True)
class GarminSyncConfig:
    """Configuration for Garmin Connect sync (email/password + lookback)."""

    email: str
    password: str
    lookback_days: int

    @classmethod
    def from_env(cls) -> "GarminSyncConfig":
        """Build Garmin sync config from environment variables."""
        email = os.getenv(GARMIN_EMAIL)
        password = os.getenv(GARMIN_PASSWORD)

        if not email or not password:
            raise ValueError(
                "Missing Garmin credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD."
            )

        try:
            lookback_days = max(
                1, int(os.getenv(GARMIN_SYNC_LOOKBACK_DAYS, "30"))
            )
        except ValueError:
            lookback_days = 30

        return cls(
            email=email,
            password=password,
            lookback_days=lookback_days,
        )


class GarminSyncIngestionHandler(FitIngestionBaseHandler):
    """Ingest a single Garmin activity."""

    def __init__(
        self,
        storage: WorkoutTableStorage,
        client: GarminConnectClient,
    ) -> None:
        super().__init__(storage)
        self._client = client

    def handle(self, *args, **kwargs) -> tuple[Dict, int]:
        """
        Ingest a single Garmin activity.

        Required kwargs:
            athlete_id: Athlete identifier
            activity: Raw activity dict from Garmin Connect API
        """
        athlete_id = kwargs["athlete_id"]
        activity = kwargs["activity"]

        activity_id = str(activity.get("activityId"))
        activity_name = activity.get("activityName", "Unknown")

        logger.info(
            "Processing Garmin activity %s (%s) for athlete %s",
            activity_id,
            activity_name,
            athlete_id,
        )

        # Build source info for ingestion tracking
        source_info = self._build_source_info(activity)

        # Download FIT file
        try:
            fit_bytes = self._client.download_activity_fit(activity_id)
        except GarminConnectError as exc:
            logger.error(
                "Failed to download FIT for activity %s: %s", activity_id, exc
            )
            return {
                "status": "error",
                "message": f"Failed to download FIT file: {exc}",
                "activity_id": activity_id,
            }, 500

        # Compute hash for deduplication
        source_info["file_sha256"] = compute_bytes_hash(fit_bytes)

        # Check for unchanged ingestion state only after hash is available
        ingestion_key = f"garmin_{activity_id}"
        context = IngestionContext(
            athlete_id=athlete_id,
            file_info=source_info,
            workout_id=None,
            storage=self.storage,
            ingestion_key=ingestion_key,
        )
        skipped, workout_id = self._skip_if_unchanged(
            athlete_id,
            source_info,
            ingestion_key=context.ingestion_key,
            existing_state=context.existing_state,
        )
        if skipped:
            workout_id = (
                context.existing_state.get("workout_id")
                if context.existing_state
                else None
            )
            self.storage.record_ingestion_state(
                athlete_id,
                source_info,
                status="skipped",
                workout_id=workout_id,
                ingestion_key=context.ingestion_key,
                existing_state=context.existing_state,
            )
            return {
                "status": "skipped",
                "workout_id": workout_id,
                "message": "Unchanged content",
            }, 200

        duplicate_workout_id = self._find_near_duplicate_workout(athlete_id, activity)
        if duplicate_workout_id:
            self.storage.record_ingestion_state(
                athlete_id,
                source_info,
                status="skipped_duplicate",
                workout_id=duplicate_workout_id,
                ingestion_key=context.ingestion_key,
                existing_state=context.existing_state,
                error=f"duplicate_of:{duplicate_workout_id}",
            )
            return {
                "status": "skipped_duplicate",
                "workout_id": duplicate_workout_id,
                "message": "Potential duplicate workout detected by start-time window",
            }, 200

        # Parse and store
        _, workout_id = self._parse_and_store(
            athlete_id,
            source_info,
            file_bytes=fit_bytes,
            file_path=f"garmin_{activity_id}.fit",
        )
        
        return {"status": "success", "workout_id": workout_id}, 200

    def _build_source_info(self, activity: Dict) -> Dict:
        """Build source info metadata for ingestion state tracking."""
        activity_id = str(activity.get("activityId"))
        return {
            "source_system": "Garmin",
            "source_file_name": f"{activity_id}.fit",
            "source_file_path": f"/garmin/{activity_id}.fit",
            "source_item_id": activity_id,
            "source_activity_name": activity.get("activityName"),
            "source_activity_type": activity.get("activityType", {}).get("typeKey"),
            "source_start_time_utc": activity.get("startTimeGMT"),
            "source_duration_sec": activity.get("duration"),
            "source_distance_meters": activity.get("distance"),
        }

    def _find_near_duplicate_workout(
        self,
        athlete_id: str,
        activity: Dict,
        *,
        window_seconds: int = 600,
        duration_tolerance_seconds: int = 180,
    ) -> Optional[str]:
        """Find existing workout within a rough start-time and duration window."""
        start_time = activity.get("startTimeGMT")
        if not start_time:
            return None
        try:
            start_dt = datetime.fromisoformat(str(start_time).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

        duration = activity.get("duration")
        try:
            duration_sec = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_sec = None

        table_client = self.storage.get_table_client("Workouts")
        partitions = {
            f"{athlete_id}|{start_dt.strftime('%Y-%m')}",
            f"{athlete_id}|{(start_dt - timedelta(days=1)).strftime('%Y-%m')}",
            f"{athlete_id}|{(start_dt + timedelta(days=1)).strftime('%Y-%m')}",
        }

        for partition_key in partitions:
            query = f"PartitionKey eq '{partition_key}'"
            for entity in table_client.query_entities(query):
                if entity.get("athlete_id") != athlete_id:
                    continue
                existing_start = entity.get("start_time_utc")
                if not existing_start:
                    continue
                try:
                    existing_dt = datetime.fromisoformat(
                        str(existing_start).replace("Z", "+00:00")
                    ).astimezone(timezone.utc)
                except ValueError:
                    continue
                delta_sec = abs((existing_dt - start_dt).total_seconds())
                if delta_sec > window_seconds:
                    continue

                if duration_sec is not None and entity.get("duration_sec") is not None:
                    try:
                        existing_duration = float(entity.get("duration_sec"))
                    except (TypeError, ValueError):
                        existing_duration = None
                    if (
                        existing_duration is not None
                        and abs(existing_duration - duration_sec) > duration_tolerance_seconds
                    ):
                        continue
                return entity.get("workout_id")

        return None


class GarminSyncRequest:
    """Encapsulates Garmin sync request parsing."""

    def __init__(self, body: Optional[Dict], query_params: Optional[Dict]):
        self.body = body or {}
        self.query_params = query_params or {}

    @property
    def athlete_id(self) -> str:
        """Extract athlete_id from body or query params."""
        athlete_id = self.body.get("athlete_id") or self.query_params.get("athlete_id")
        return athlete_id or "rob"

    @property
    def lookback_days(self) -> int | None:
        """Extract and validate lookback days."""
        days = self.body.get("days") or self.query_params.get("days")
        if days is None:
            return None
        try:
            return int(days)
        except (ValueError, TypeError):
            return None

    @property
    def async_mode(self) -> bool:
        """Extract async flag from body or query params."""
        async_flag = self.body.get("async") or self.query_params.get("async")
        if isinstance(async_flag, bool):
            return async_flag
        if isinstance(async_flag, str):
            return async_flag.lower() in ("true", "1", "yes")
        return False


class GarminSyncHandler:
    """Orchestrates Garmin Connect sync workflow."""

    def __init__(
        self,
        config: GarminSyncConfig,
        storage: WorkoutTableStorage,
        *,
        client: GarminConnectClient | None = None,
        ingestion_handler: GarminSyncIngestionHandler | None = None,
    ):
        self._config = config
        self._storage = storage
        self._client = client or GarminConnectClient(
            email=config.email,
            password=config.password,
        )
        self._ingestion_handler = ingestion_handler or GarminSyncIngestionHandler(
            storage,
            self._client,
        )

    def handle(self, *args, **kwargs) -> Tuple[Dict, int]:
        """
        Execute Garmin Connect sync.

        Args:
            req: Parsed sync request

        Returns:
            (response_dict, HTTP status code)
        """
        req = self._extract_request(args, kwargs)
        lookback_days = req.lookback_days or self._config.lookback_days

        if req.async_mode:
            return self._handle_async(req.athlete_id, lookback_days)

        return self._handle_sync(req.athlete_id, lookback_days)

    @property
    def config(self) -> GarminSyncConfig:
        """Expose current sync configuration."""
        return self._config

    def sync(self, *, athlete_id: str, lookback_days: int) -> Dict:
        """Sync Garmin activities and ingest FIT files."""
        # Authenticate with Garmin Connect
        try:
            self._client.login()
        except GarminConnectError as exc:
            logger.error("Failed to authenticate with Garmin Connect: %s", exc)
            return {
                "status": "error",
                "message": f"Authentication failed: {exc}",
            }
        
        # Calculate cutoff date
        cutoff = datetime.now() - timedelta(days=lookback_days)

        # List activities
        try:
            activities = self._client.list_activities(start_date=cutoff, limit=100)
        except GarminConnectError as exc:
            logger.error("Failed to list Garmin activities: %s", exc)
            return {
                "status": "error",
                "message": f"Failed to list activities: {exc}",
            }

        logger.info(
            "Found %d Garmin activities within lookback_days=%s (cutoff=%s)",
            len(activities),
            lookback_days,
            cutoff.date().isoformat(),
        )

        results = {
            "status": "success",
            "lookback_days": lookback_days,
            "found": len(activities),
            "ingested": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
            "items": [],
        }

        for activity in activities:
            try:
                body, status_code = self._ingestion_handler.handle(
                    athlete_id=athlete_id,
                    activity=activity,
                )
                self._record_ingest_result(results, activity, body, status_code)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to ingest Garmin activity %s: %s",
                    activity.get("activityId"),
                    exc,
                    exc_info=True,
                )
                self._record_error_result(results, activity, exc)

        return results

    def _handle_sync(self, athlete_id: str, lookback_days: int) -> Tuple[Dict, int]:
        """Execute synchronous sync."""
        try:
            results = self.sync(athlete_id=athlete_id, lookback_days=lookback_days)
            return results, 200
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Garmin sync failed: %s", exc, exc_info=True)
            return {"error": str(exc)}, 500

    def _handle_async(self, athlete_id: str, lookback_days: int) -> Tuple[Dict, int]:
        """Queue asynchronous sync."""
        thread = threading.Thread(
            target=self.sync,
            kwargs={"athlete_id": athlete_id, "lookback_days": lookback_days},
            daemon=True,
        )
        thread.start()
        return {
            "status": "queued",
            "athlete_id": athlete_id,
            "lookback_days": lookback_days,
        }, 202

    def _extract_request(self, args: tuple, kwargs: dict) -> GarminSyncRequest:
        """Extract GarminSyncRequest from positional or keyword arguments."""
        if args and isinstance(args[0], GarminSyncRequest):
            return args[0]
        if "req" in kwargs and isinstance(kwargs["req"], GarminSyncRequest):
            return kwargs["req"]
        # Fallback: construct from kwargs
        return GarminSyncRequest(kwargs, {})

    def _record_ingest_result(
        self,
        results: Dict,
        activity: Dict,
        body: Dict,
        status_code: int,
    ) -> None:
        """Record the result of an individual activity ingestion."""
        activity_id = str(activity.get("activityId", "unknown"))
        activity_name = activity.get("activityName", "Unknown")
        
        if status_code == 200:
            if body.get("status") == "skipped":
                results["skipped"] += 1
                logger.info("Skipped Garmin activity %s (%s)", activity_id, activity_name)
            else:
                results["ingested"] += 1
                logger.info("Ingested Garmin activity %s (%s)", activity_id, activity_name)
        else:
            results["failed"] += 1
            error_msg = body.get("message", "Unknown error")
            results["errors"].append(f"{activity_id}: {error_msg}")
            logger.error("Failed to ingest %s: %s", activity_id, error_msg)

        results["items"].append({
            "activity_id": activity_id,
            "activity_name": activity_name,
            "status": body.get("status"),
            "workout_id": body.get("workout_id"),
        })

    def _record_error_result(self, results: Dict, activity: Dict, exc: Exception) -> None:
        """Record an exception during activity ingestion."""
        activity_id = str(activity.get("activityId", "unknown"))
        results["failed"] += 1
        results["errors"].append(f"{activity_id}: {str(exc)}")
