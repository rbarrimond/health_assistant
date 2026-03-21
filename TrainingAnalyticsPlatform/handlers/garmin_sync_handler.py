"""Handle Garmin Connect sync requests and ingestion."""
# pylint: disable=trailing-whitespace, line-too-long

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.models.async_ingestion import AsyncIngestionWorkItem
from TrainingAnalyticsPlatform.models.async_operation import AsyncIngestionOperationState
from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.handlers.ingestion_hashing import compute_bytes_hash
from TrainingAnalyticsPlatform.platform.exceptions import (
    ConfigError,
    DeviceFilteredError,
    FitParsingError,
    GarminConnectRateLimitError,
    HealthAssistantError,
    IngestionIdResolutionError,
    StorageError,
    WorkoutIdCalculationError,
)
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator
from TrainingAnalyticsPlatform.storage.storage_infrastructure import IngestionContext

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
            raise ConfigError(
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
        storage: StorageCoordinator,
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
        source_info: Optional[Dict] = None

        activity_id = str(activity.get("activityId"))
        activity_name = activity.get("activityName", "Unknown")

        logger.info(
            "Processing Garmin activity",
            extra={
                "athlete_id": athlete_id,
                "source_system": "garmin",
                "activity_id": activity_id,
                "activity_name": activity_name,
            },
        )

        try:
            # Build source info for ingestion tracking
            source_info = self._build_source_info(activity)
            source_info["ingestion_id"] = self._resolve_ingestion_id(source_info)

            # Download FIT file
            fit_bytes = self._client.download_activity_fit(activity_id)
        except GarminConnectError as exc:
            logger.error(
                "Failed to download FIT for Garmin activity",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "error_type": "GarminConnectError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "status": "error",
                "message": f"Failed to download FIT file: {exc}",
                "activity_id": activity_id,
            }, 500
        except IngestionIdResolutionError as exc:
            logger.error(
                "Garmin ingestion_id resolution failed",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "error_type": "IngestionIdResolutionError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response(
                extra={"activity_id": activity_id},
                include_message_alias=True,
            )

        # Compute hash for deduplication
        source_info["file_sha256"] = compute_bytes_hash(fit_bytes)
        source_info["ingestion_id"] = self._resolve_ingestion_id(source_info)
        # Check for unchanged ingestion state only after hash is available
        ingestion_key = source_info["ingestion_id"]
        context = IngestionContext(
            athlete_id=athlete_id,
            file_info=source_info,
            workout_id=None,
            storage=self.storage.workouts,
            ingestion_id=source_info.get("ingestion_id"),
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
            logger.debug(
                "Skipping unchanged Garmin FIT with existing ingested state",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "ingestion_key": context.ingestion_key,
                    "workout_id": workout_id,
                    "status": "skipped_unchanged",
                },
            )
            return {
                "status": "skipped",
                "workout_id": workout_id,
                "message": "Unchanged content",
            }, 200

        duplicate_workout_id = self._find_near_duplicate_workout(athlete_id, activity)
        if duplicate_workout_id:
            self.storage.workouts.record_ingestion_state(
                athlete_id,
                source_info,
                status="skipped_duplicate",
                workout_id=duplicate_workout_id,
                ingestion_id=source_info.get("ingestion_id"),
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
        try:
            _, workout_id = self._parse_and_store(
                athlete_id,
                source_info,
                file_bytes=fit_bytes,
            )
        except WorkoutIdCalculationError as exc:
            logger.error(
                "Garmin workout_id calculation failed",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "ingestion_id": source_info.get("ingestion_id") if source_info else None,
                    "error_type": "WorkoutIdCalculationError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response(
                extra={"activity_id": activity_id},
                include_message_alias=True,
            )
        except FitParsingError as exc:
            logger.error(
                "Garmin FIT parsing failed",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "ingestion_id": source_info.get("ingestion_id") if source_info else None,
                    "error_type": "FitParsingError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response(
                extra={"activity_id": activity_id},
                include_message_alias=True,
            )
        except DeviceFilteredError as exc:
            logger.warning(
                "Garmin ingestion filtered by device classification",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "error_type": "DeviceFilteredError",
                    "reason": str(exc),
                },
            )
            return exc.to_response(
                extra={"activity_id": activity_id},
                include_message_alias=True,
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
            "source_start_time_local": activity.get("startTimeLocal"),
            "source_duration_sec": activity.get("duration"),
            "source_distance_meters": activity.get("distance"),
        }

    @staticmethod
    def _resolve_ingestion_id(source_info: Dict) -> str:
        source_item_id = source_info.get("source_item_id")
        if source_item_id:
            return str(source_item_id)

        file_sha256 = source_info.get("file_sha256")
        if file_sha256:
            return str(file_sha256)

        raise IngestionIdResolutionError(
            "Cannot compute ingestion_id without source_item_id or file_sha256"
        )

    def _find_near_duplicate_workout(
        self,
        athlete_id: str,
        activity: Dict,
        *,
        window_seconds: int = 600,
        duration_tolerance_seconds: int = 180,
    ) -> Optional[str]:
        """Find existing workout within a rough start-time and duration window."""
        start_dt = self._parse_activity_start_time(activity)
        if not start_dt:
            return None

        duration_sec = self._parse_activity_duration(activity)
        partitions = self._get_search_partitions(athlete_id, start_dt)
        
        for partition_key in partitions:
            workout_id = self._search_partition_for_duplicate(
                partition_key, athlete_id, start_dt, duration_sec,
                window_seconds, duration_tolerance_seconds
            )
            if workout_id:
                return workout_id

        return None

    def _parse_activity_start_time(self, activity: Dict) -> Optional[datetime]:
        """Parse and validate activity start time."""
        start_time = activity.get("startTimeGMT")
        if not start_time:
            return None
        try:
            return datetime.fromisoformat(str(start_time).replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    def _parse_activity_duration(self, activity: Dict) -> Optional[float]:
        """Parse and validate activity duration."""
        duration = activity.get("duration")
        try:
            return float(duration) if duration is not None else None
        except (TypeError, ValueError):
            return None

    def _get_search_partitions(self, athlete_id: str, start_dt: datetime) -> set:
        """Generate partition keys to search (current month ±1 day)."""
        return {
            f"{athlete_id}|{start_dt.strftime('%Y-%m')}",
            f"{athlete_id}|{(start_dt - timedelta(days=1)).strftime('%Y-%m')}",
            f"{athlete_id}|{(start_dt + timedelta(days=1)).strftime('%Y-%m')}",
        }

    def _search_partition_for_duplicate(
        self,
        partition_key: str,
        athlete_id: str,
        start_dt: datetime,
        duration_sec: Optional[float],
        window_seconds: int,
        duration_tolerance_seconds: int,
    ) -> Optional[str]:
        """Search a single partition for matching workout."""
        table_client = self.storage.infrastructure.get_table_client("Workouts")
        query = f"PartitionKey eq '{partition_key}'"
        
        for entity in table_client.query_entities(query):
            if self._is_matching_workout(entity, athlete_id, start_dt, duration_sec, 
                                        window_seconds, duration_tolerance_seconds):
                return entity.get("workout_id")
        return None

    def _is_matching_workout(
        self,
        entity: Dict,
        athlete_id: str,
        start_dt: datetime,
        duration_sec: Optional[float],
        window_seconds: int,
        duration_tolerance_seconds: int,
    ) -> bool:
        """Check if entity matches the workout criteria."""
        if entity.get("athlete_id") != athlete_id:
            return False

        existing_dt = self._parse_entity_start_time(entity)
        if not existing_dt:
            return False

        if not self._is_within_time_window(start_dt, existing_dt, window_seconds):
            return False

        if not self._is_within_duration_tolerance(duration_sec, entity, duration_tolerance_seconds):
            return False

        return True

    def _parse_entity_start_time(self, entity: Dict) -> Optional[datetime]:
        """Parse entity start time safely."""
        existing_start = entity.get("start_time_utc")
        if not existing_start:
            return None
        try:
            return datetime.fromisoformat(
                str(existing_start).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except ValueError:
            return None

    def _is_within_time_window(self, start_dt: datetime, existing_dt: datetime, window_seconds: int) -> bool:
        """Check if two datetimes are within the specified window."""
        delta_sec = abs((existing_dt - start_dt).total_seconds())
        return delta_sec <= window_seconds

    def _is_within_duration_tolerance(
        self,
        duration_sec: Optional[float],
        entity: Dict,
        duration_tolerance_seconds: int,
    ) -> bool:
        """Check if durations match within tolerance."""
        existing_duration_raw = entity.get("duration_sec")
        if duration_sec is None or existing_duration_raw is None:
            return True

        if not isinstance(existing_duration_raw, (int, float, str)):
            return True
        
        try:
            existing_duration = float(existing_duration_raw)
            return abs(existing_duration - duration_sec) <= duration_tolerance_seconds
        except (TypeError, ValueError):
            return True


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
        lookback_days = self.body.get("lookback_days")
        if lookback_days is None:
            lookback_days = self.query_params.get("lookback_days")
        if lookback_days is None:
            return None
        try:
            return int(lookback_days)
        except (ValueError, TypeError):
            return None

    @property
    def async_mode(self) -> bool:
        """Extract async flag from body or query params."""
        async_flag = self.body.get("async") or self.query_params.get("async")
        return self._to_bool(async_flag)

    @property
    def force(self) -> bool:
        """Extract force flag from body or query params."""
        force_flag = self.body.get("force")
        if force_flag is None:
            force_flag = self.query_params.get("force")
        return self._to_bool(force_flag)

    @property
    def request_id(self) -> str | None:
        """Extract request identifier from body or query params when present."""
        request_id = self.body.get("request_id") or self.query_params.get("request_id")
        if request_id is None:
            return None
        normalized = str(request_id).strip()
        return normalized or None

    @property
    def correlation_id(self) -> str | None:
        """Extract correlation identifier from body or query params when present."""
        correlation_id = self.body.get("correlation_id") or self.query_params.get("correlation_id")
        if correlation_id is None:
            return None
        normalized = str(correlation_id).strip()
        return normalized or None

    @staticmethod
    def _to_bool(raw_value: object) -> bool:
        """Convert common bool-like values to bool."""
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            return raw_value.lower() in ("true", "1", "yes")
        if isinstance(raw_value, int):
            return raw_value == 1
        return False


class GarminSyncHandler:
    """Orchestrates Garmin Connect sync workflow."""

    def __init__(
        self,
        config: GarminSyncConfig,
        storage: StorageCoordinator,
        *,
        client: GarminConnectClient | None = None,
        ingestion_handler: GarminSyncIngestionHandler | None = None,
        async_queue: Any | None = None,
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
        self._async_queue = async_queue

    def handle(self, *args, **kwargs) -> Tuple[Dict, int]:
        """
        Execute Garmin Connect sync.

        Args:
            req: Parsed sync request

        Returns:
            (response_dict, HTTP status code)
        """
        req = self._extract_request(args, kwargs)
        lookback_days = (
            req.lookback_days
            if req.lookback_days is not None
            else self._config.lookback_days
        )
        if lookback_days < 0:
            return {"error": "lookback_days must be a non-negative integer"}, 400

        if req.async_mode:
            return self._handle_async(
                req.athlete_id,
                lookback_days,
                req.force,
                request_id=req.request_id,
                correlation_id=req.correlation_id,
            )

        return self._handle_sync(req.athlete_id, lookback_days, req.force)

    @property
    def config(self) -> GarminSyncConfig:
        """Expose current sync configuration."""
        return self._config

    @staticmethod
    def _is_rate_limited_error(exc: Exception) -> bool:
        if isinstance(exc, GarminConnectRateLimitError):
            return True
        text = str(exc).lower()
        return "rate limit" in text or "rate limited" in text or "throttle" in text

    def _persist_rate_limit_cooldown(self, athlete_id: str) -> None:
        """Write the in-process rate-limit expiry to Table Storage for cross-process coordination."""
        blocked_until = self._client.rate_limited_until
        if blocked_until is None:
            return
        try:
            self._storage.oauth_tokens.set_garmin_rate_limit_blocked_until(athlete_id, blocked_until)
        except StorageError:
            logger.warning(
                "Failed to persist Garmin rate-limit cooldown to storage",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

    def _handle_auth_error(self, athlete_id: str, exc: Exception) -> Dict:
        """Build an error response for a Garmin auth failure, persisting rate-limit state if needed."""
        if self._is_rate_limited_error(exc):
            self._persist_rate_limit_cooldown(athlete_id)
            logger.error(
                "Garmin authentication rate limited",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": "GarminConnectError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "status": "error",
                "message": f"Authentication failed: {exc}",
                "error_code": "GARMIN_RATE_LIMITED",
            }
        logger.error(
            "Failed to authenticate with Garmin Connect",
            extra={
                "athlete_id": athlete_id,
                "source_system": "garmin",
                "error_type": "GarminConnectError",
                "error": str(exc),
            },
            exc_info=True,
        )
        return {
            "status": "error",
            "message": f"Authentication failed: {exc}",
            "error_code": "GARMIN_AUTH_ERROR",
        }

    def _authenticate(self, athlete_id: str) -> Optional[Dict]:
        """Authenticate with Garmin, checking and persisting cross-process rate-limit state.

        Returns an error dict if the caller should abort, or None on success.
        """
        try:
            blocked_until = self._storage.oauth_tokens.get_garmin_rate_limit_blocked_until(athlete_id)
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
                    "status": "error",
                    "message": f"Authentication rate-limited until {blocked_until.isoformat()}",
                    "error_code": "GARMIN_RATE_LIMITED",
                }
        except StorageError:
            # Best-effort: proceed and let the auth attempt surface any live rate limit.
            logger.warning(
                "Could not read Garmin rate-limit cooldown from storage; proceeding with auth",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

        stored_token: Optional[str] = None
        try:
            stored_token = self._storage.oauth_tokens.get_garmin_tokens(athlete_id)
        except StorageError:
            logger.error(
                "Failed to retrieve stored Garmin tokens; will attempt fresh login",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

        try:
            self._client.authenticate(stored_token)
        except (GarminConnectRateLimitError, GarminConnectError) as exc:
            return self._handle_auth_error(athlete_id, exc)

        return None

    def sync(self, *, athlete_id: str, lookback_days: int, force: bool = False) -> Dict:
        """Sync Garmin activities and ingest FIT files."""
        auth_error = self._authenticate(athlete_id)
        if auth_error is not None:
            return auth_error

        # Calculate cutoff date
        cutoff = datetime.now() - timedelta(days=lookback_days)

        # List activities
        try:
            activities = self._client.list_activities(start_date=cutoff)
        except GarminConnectError as exc:
            logger.error(
                "Failed to list Garmin activities",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "lookback_days": lookback_days,
                    "error_type": "GarminConnectError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "status": "error",
                "message": f"Failed to list activities: {exc}",
            }

        logger.info(
            "Found Garmin activities within lookback window",
            extra={
                "athlete_id": athlete_id,
                "source_system": "garmin",
                "found_count": len(activities),
                "lookback_days": lookback_days,
                "cutoff_date": cutoff.date().isoformat(),
            },
        )

        results = {
            "status": "success",
            "lookback_days": lookback_days,
            "force": force,
            "found": len(activities),
            "ingested": 0,
            "skipped": 0,
            "skipped_by_id": 0,
            "failed": 0,
            "errors": [],
            "items": [],
        }

        for activity in activities:
            activity_id = str(activity.get("activityId", ""))
            if not force and activity_id and self._was_activity_previously_processed(
                athlete_id,
                activity_id,
            ):
                results["skipped"] += 1
                results["skipped_by_id"] += 1
                results["items"].append(
                    {
                        "activity_id": activity_id,
                        "activity_name": activity.get("activityName", "Unknown"),
                        "status": "skipped_seen_id",
                        "workout_id": None,
                    }
                )
                logger.debug(
                    "Skipping Garmin activity with previously processed activity_id",
                    extra={
                        "athlete_id": athlete_id,
                        "source_system": "garmin",
                        "activity_id": activity_id,
                        "status": "skipped_seen_id",
                    },
                )
                continue

            try:
                body, status_code = self._ingestion_handler.handle(
                    athlete_id=athlete_id,
                    activity=activity,
                )
                self._record_ingest_result(results, activity, body, status_code)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "Failed to ingest Garmin activity",
                    extra={
                        "athlete_id": athlete_id,
                        "source_system": "garmin",
                        "activity_id": activity.get("activityId"),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    exc_info=True,
                )
                self._record_error_result(results, activity, exc)

        # Persist tokens after sync so future invocations skip the SSO round-trip.
        # This also captures any OAuth2 refresh that garth performed during the sync.
        try:
            self._storage.oauth_tokens.store_garmin_tokens(
                athlete_id, self._client.dump_tokens()
            )
            logger.debug(
                "Garmin tokens persisted after sync",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )
        except (GarminConnectError, StorageError) as exc:
            logger.warning(
                "Failed to persist Garmin tokens after sync; session will not be cached",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

        return results

    def _handle_sync(self, athlete_id: str, lookback_days: int, force: bool = False) -> Tuple[Dict, int]:
        """Execute synchronous sync."""
        try:
            results = self.sync(
                athlete_id=athlete_id,
                lookback_days=lookback_days,
                force=force,
            )
            if results.get("status") == "error":
                if results.get("error_code") == "GARMIN_RATE_LIMITED":
                    return results, 429
                message = str(results.get("message", ""))
                if message.startswith("Authentication failed:"):
                    return results, 401
                return results, 500
            return results, 200
        except HealthAssistantError as exc:
            logger.error(
                "Garmin sync failed with typed error",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "lookback_days": lookback_days,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return exc.to_response(include_message_alias=True)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Garmin sync failed",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "lookback_days": lookback_days,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {"error": str(exc)}, 500

    def _handle_async(
        self,
        athlete_id: str,
        lookback_days: int,
        force: bool = False,
        *,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> Tuple[Dict, int]:
        """Queue asynchronous sync."""

        operation_id = str(uuid.uuid4())
        queued_at_utc = datetime.now(timezone.utc).isoformat()

        if self._async_queue is not None:
            return self._handle_async_queue(
                athlete_id=athlete_id,
                lookback_days=lookback_days,
                force=force,
                operation_id=operation_id,
                queued_at_utc=queued_at_utc,
                request_id=request_id,
                correlation_id=correlation_id,
            )

        return self._handle_async_thread(
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            force=force,
            operation_id=operation_id,
            queued_at_utc=queued_at_utc,
            request_id=request_id,
            correlation_id=correlation_id,
        )

    def _handle_async_queue(
        self,
        *,
        athlete_id: str,
        lookback_days: int,
        force: bool,
        operation_id: str,
        queued_at_utc: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> Tuple[Dict, int]:
        """Enqueue async Garmin sync work item."""
        async_queue = self._async_queue
        if async_queue is None:
            logger.error(
                "Garmin async queue unavailable",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "force": force,
                    "operation_id": operation_id,
                    "source_system": "garmin",
                },
            )
            return {
                "status": "error",
                "error": "Async queue is not configured",
                "operation_id": operation_id,
                "mode": "async_queue",
            }, 500

        operation_state = AsyncIngestionOperationState.queued(
            athlete_id=athlete_id,
            operation_id=operation_id,
            source="garmin",
            lookback_days=lookback_days,
            mode="async_queue",
            queued_at_utc=queued_at_utc,
            request_id=request_id,
            correlation_id=correlation_id,
            context={
                "source_system": "garmin",
                "mode": "async",
                "force": force,
            },
        )
        try:
            self._storage.async_operations.upsert_state(operation_state)
            async_queue.enqueue(
                item=AsyncIngestionWorkItem(
                    operation_id=operation_id,
                    source="garmin",
                    athlete_id=athlete_id,
                    lookback_days=lookback_days,
                    queued_at_utc=queued_at_utc,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    context={
                        "source_system": "garmin",
                        "mode": "async",
                        "force": force,
                    },
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "Garmin async queue enqueue failed",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "force": force,
                    "operation_id": operation_id,
                    "source_system": "garmin",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "status": "error",
                "error": "Failed to queue async Garmin sync",
                "operation_id": operation_id,
                "mode": "async_queue",
            }, 500

        return {
            "status": "queued",
            "athlete_id": athlete_id,
            "lookback_days": lookback_days,
            "force": force,
            "mode": "async_queue",
            "operation_id": operation_id,
            "queued_at_utc": queued_at_utc,
        }, 202

    def _handle_async_thread(
        self,
        *,
        athlete_id: str,
        lookback_days: int,
        force: bool,
        operation_id: str,
        queued_at_utc: str,
        request_id: str | None,
        correlation_id: str | None,
    ) -> Tuple[Dict, int]:
        """Run async Garmin sync via in-process daemon thread (fallback mode)."""

        operation_state = AsyncIngestionOperationState.queued(
            athlete_id=athlete_id,
            operation_id=operation_id,
            source="garmin",
            lookback_days=lookback_days,
            mode="async_thread",
            queued_at_utc=queued_at_utc,
            request_id=request_id,
            correlation_id=correlation_id,
            context={
                "source_system": "garmin",
                "mode": "async",
                "force": force,
            },
        )
        self._storage.async_operations.upsert_state(operation_state)

        def _run_background_sync() -> None:
            try:
                self._storage.async_operations.mark_status(
                    athlete_id=athlete_id,
                    operation_id=operation_id,
                    status="processing",
                )
                result = self.sync(
                    athlete_id=athlete_id,
                    lookback_days=lookback_days,
                    force=force,
                )
                self._storage.async_operations.mark_status(
                    athlete_id=athlete_id,
                    operation_id=operation_id,
                    status="succeeded",
                    result={
                        "status": result.get("status"),
                        "found": result.get("found"),
                        "ingested": result.get("ingested"),
                        "skipped": result.get("skipped"),
                        "failed": result.get("failed"),
                    },
                )
                logger.info(
                    "Garmin async sync completed",
                    extra={
                        "athlete_id": athlete_id,
                        "lookback_days": lookback_days,
                        "force": force,
                        "source_system": "garmin",
                        "operation_id": operation_id,
                        "status": result.get("status"),
                        "found": result.get("found"),
                        "ingested": result.get("ingested"),
                        "skipped": result.get("skipped"),
                        "failed": result.get("failed"),
                    },
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._storage.async_operations.mark_status(
                    athlete_id=athlete_id,
                    operation_id=operation_id,
                    status="failed",
                    error=str(exc),
                )
                logger.error(
                    "Garmin async sync failed",
                    extra={
                        "athlete_id": athlete_id,
                        "lookback_days": lookback_days,
                        "force": force,
                        "source_system": "garmin",
                        "operation_id": operation_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    exc_info=True,
                )

        thread = threading.Thread(
            target=_run_background_sync,
            kwargs={
            },
            daemon=True,
        )
        thread.start()
        return {
            "status": "queued",
            "athlete_id": athlete_id,
            "lookback_days": lookback_days,
            "force": force,
            "mode": "async_thread",
            "operation_id": operation_id,
            "queued_at_utc": queued_at_utc,
        }, 202

    def _was_activity_previously_processed(
        self,
        athlete_id: str,
        activity_id: str,
    ) -> bool:
        """Return True when an activity has an existing terminal ingestion state."""
        try:
            existing_state = self._storage.workouts.get_ingestion_state(
                athlete_id,
                activity_id,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to load Garmin ingestion state for activity prefilter",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return False

        if not existing_state:
            return False

        return existing_state.get("status") in {
            "ingested",
            "skipped",
            "skipped_duplicate",
            "filtered",
        }

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
                logger.info(
                    "Skipped Garmin activity",
                    extra={
                        "source_system": "garmin",
                        "activity_id": activity_id,
                        "activity_name": activity_name,
                        "status": "skipped",
                    },
                )
            else:
                results["ingested"] += 1
                logger.info(
                    "Ingested Garmin activity",
                    extra={
                        "source_system": "garmin",
                        "activity_id": activity_id,
                        "activity_name": activity_name,
                        "workout_id": body.get("workout_id"),
                        "status": "success",
                    },
                )
        else:
            results["failed"] += 1
            error_msg = body.get("message", "Unknown error")
            results["errors"].append(f"{activity_id}: {error_msg}")
            logger.error(
                "Failed to ingest Garmin activity",
                extra={
                    "source_system": "garmin",
                    "activity_id": activity_id,
                    "activity_name": activity_name,
                    "error": error_msg,
                    "status_code": status_code,
                },
            )

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
