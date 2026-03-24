"""Handle OneDrive sync requests and OneDrive sync ingestion."""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from TrainingAnalyticsPlatform.models.async_ingestion import AsyncIngestionWorkItem
from TrainingAnalyticsPlatform.models.async_operation import AsyncIngestionOperationState
from TrainingAnalyticsPlatform.integrations.onedrive_client import (
    OneDriveDeltaTokenExpiredError,
    OneDriveGraphClient,
)
from TrainingAnalyticsPlatform.handlers.ingestion_hashing import compute_bytes_hash
from TrainingAnalyticsPlatform.ingestion.fit_file_preprocessor import FitFilePreprocessor
from TrainingAnalyticsPlatform.platform.config import Config as PlatformConfig
from TrainingAnalyticsPlatform.platform.exceptions import (
    DeviceFilteredError,
    FitParsingError,
    HealthAssistantError,
    IngestionIdResolutionError,
    PreprocessingError,
    WorkoutIdCalculationError,
)
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator
from TrainingAnalyticsPlatform.storage.storage_infrastructure import IngestionContext

from .ingestion_base_handler import FitIngestionBaseHandler

logger = logging.getLogger(__name__)

ONEDRIVE_CLIENT_ID = "ONEDRIVE_CLIENT_ID"
ONEDRIVE_CLIENT_SECRET = "ONEDRIVE_CLIENT_SECRET"
ONEDRIVE_REDIRECT_URI = "ONEDRIVE_REDIRECT_URI"
ONEDRIVE_SCOPES = "ONEDRIVE_SCOPES"
ONEDRIVE_FOLDER_PATH = "ONEDRIVE_FOLDER_PATH"
ONEDRIVE_SYNC_LOOKBACK_DAYS = "ONEDRIVE_SYNC_LOOKBACK_DAYS"


@dataclass(frozen=True)
class OneDriveSyncConfig:
    """Configuration for OneDrive Personal sync (OAuth + folder + lookback)."""

    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str
    folder_path: str
    lookback_days: int

    @classmethod
    def from_env(cls) -> "OneDriveSyncConfig":
        """Build OneDrive sync config from environment variables."""
        client_id = os.getenv(ONEDRIVE_CLIENT_ID)
        client_secret = os.getenv(ONEDRIVE_CLIENT_SECRET)
        redirect_uri = os.getenv(ONEDRIVE_REDIRECT_URI)
        scopes = os.getenv(ONEDRIVE_SCOPES, "Files.ReadWrite offline_access")
        folder_path = os.getenv(ONEDRIVE_FOLDER_PATH, "/Apps/HealthFit")

        try:
            lookback_days = max(
                1, int(os.getenv(ONEDRIVE_SYNC_LOOKBACK_DAYS, "30"))
            )
        except ValueError:
            lookback_days = 30

        if not client_id or not client_secret or not redirect_uri:
            raise ValueError(
                "Missing OneDrive credentials. Set ONEDRIVE_CLIENT_ID, "
                "ONEDRIVE_CLIENT_SECRET, and ONEDRIVE_REDIRECT_URI."
            )

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=scopes,
            folder_path=folder_path,
            lookback_days=lookback_days,
        )


class OneDriveSyncIngestionHandler(FitIngestionBaseHandler):
    """Ingest a single OneDrive item."""

    _UNEXPECTED_ERROR_MESSAGE = "OneDrive ingestion failed"

    def __init__(
        self,
        storage: StorageCoordinator,
        client: OneDriveGraphClient,
    ) -> None:
        super().__init__(storage)
        self._client = client

    def handle(self, *args, **kwargs) -> tuple[Dict, int]:
        """
        Ingest a single OneDrive item.

        Required kwargs:
            athlete_id: Athlete identifier
            access_token: OneDrive OAuth access token
            item: OneDrive item dict
            drive_id: Optional OneDrive drive ID fallback
            force: Whether to bypass unchanged-content skip checks
        """
        athlete_id = kwargs["athlete_id"]
        access_token = kwargs["access_token"]
        item = kwargs["item"]
        drive_id = kwargs.get("drive_id")
        force = bool(kwargs.get("force", False))
        source_info: Optional[Dict] = None

        try:
            source_info, response = self._ingest_item(
                athlete_id=athlete_id,
                access_token=access_token,
                item=item,
                drive_id=drive_id,
                force=force,
            )
            return response
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return self._handle_ingestion_exception(athlete_id, source_info, exc)

    def _ingest_item(
        self,
        *,
        athlete_id: str,
        access_token: str,
        item: Dict,
        drive_id: str | None,
        force: bool,
    ) -> tuple[Dict, tuple[Dict, int]]:
        item_meta = self._extract_item_metadata(item, drive_id)
        source_info = self._build_source_info(item, item_meta)
        source_info["ingestion_id"] = self._resolve_ingestion_id(source_info)

        context = self.storage.workouts.get_ingestion_context(
            athlete_id,
            source_info,
            ingestion_key=source_info["ingestion_id"],
        )
        if isinstance(context, IngestionContext) and not force and context.should_skip():
            response = self._build_skip_response(athlete_id, source_info, context)
            return source_info, response

        raw_content = self._client.download_file(
            access_token=access_token,
            item_id=item["id"],
        )

        preprocessor = FitFilePreprocessor()
        preprocessed = preprocessor.preprocess(raw_content, item["name"])

        source_info["source_logical_file_name"] = preprocessed.logical_filename
        source_info["file_sha256"] = compute_bytes_hash(preprocessed.content)
        source_info["ingestion_id"] = self._resolve_ingestion_id(source_info)

        _, workout_id = self._parse_and_store(
            athlete_id,
            source_info,
            file_bytes=preprocessed.content,
        )
        return source_info, ({"status": "success", "workout_id": workout_id}, 200)

    def _build_skip_response(
        self,
        athlete_id: str,
        source_info: Dict,
        context: IngestionContext,
    ) -> tuple[Dict, int]:
        workout_id = (
            context.existing_state.get("workout_id")
            if context.existing_state
            else None
        )
        logger.debug(
            "Skipping unchanged OneDrive FIT with existing ingested state",
            extra={
                "athlete_id": athlete_id,
                "ingestion_key": context.ingestion_key,
                "workout_id": workout_id,
                "source_item_id": source_info.get("source_item_id"),
                "source_system": "onedrive",
                "status": "skipped_unchanged",
            },
        )
        return {
            "status": "skipped",
            "workout_id": workout_id,
            "message": "Unchanged content",
        }, 200

    def _handle_ingestion_exception(
        self,
        athlete_id: str,
        source_info: Optional[Dict],
        exc: Exception,
    ) -> tuple[Dict, int]:
        if isinstance(exc, IngestionIdResolutionError):
            logger.error(
                "OneDrive ingestion_id resolution failed",
                extra=self._onedrive_error_extra(athlete_id, source_info, exc),
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response(include_message_alias=True)

        if isinstance(exc, WorkoutIdCalculationError):
            logger.error(
                "OneDrive workout_id calculation failed",
                extra=self._onedrive_error_extra(
                    athlete_id,
                    source_info,
                    exc,
                    include_ingestion_id=True,
                ),
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response(include_message_alias=True)

        if isinstance(exc, PreprocessingError):
            logger.error(
                "OneDrive file preprocessing failed",
                extra=self._onedrive_error_extra(athlete_id, source_info, exc),
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response(include_message_alias=True)

        if isinstance(exc, FitParsingError):
            logger.error(
                "OneDrive FIT parsing failed",
                extra=self._onedrive_error_extra(
                    athlete_id,
                    source_info,
                    exc,
                    include_ingestion_id=True,
                ),
                exc_info=True,
            )
            self._record_failure(athlete_id, source_info, str(exc))
            return exc.to_response(include_message_alias=True)

        if isinstance(exc, DeviceFilteredError):
            logger.warning(
                "OneDrive ingestion filtered by device classification",
                extra=self._onedrive_error_extra(
                    athlete_id,
                    source_info,
                    exc,
                    include_reason=True,
                ),
            )
            return exc.to_response(include_message_alias=True)

        logger.error(
            self._UNEXPECTED_ERROR_MESSAGE,
            extra=self._onedrive_error_extra(
                athlete_id,
                source_info,
                exc,
                include_ingestion_id=True,
            ),
            exc_info=True,
        )
        self._record_failure(athlete_id, source_info, self._UNEXPECTED_ERROR_MESSAGE)
        return {"status": "error", "error": self._UNEXPECTED_ERROR_MESSAGE}, 500

    @staticmethod
    def _onedrive_error_extra(
        athlete_id: str,
        source_info: Optional[Dict],
        exc: Exception,
        *,
        include_ingestion_id: bool = False,
        include_reason: bool = False,
    ) -> Dict:
        extra = {
            "athlete_id": athlete_id,
            "source_system": "onedrive",
            "source_item_id": source_info.get("source_item_id") if source_info else None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if include_ingestion_id:
            extra["ingestion_id"] = source_info.get("ingestion_id") if source_info else None
        if include_reason:
            extra["reason"] = str(exc)
        return extra

    def _extract_item_metadata(self, item: Dict, drive_id: str | None) -> Dict:
        """Extract OneDrive fields used for ingest and state tracking."""
        parent_path = item.get("parentReference", {}).get("path", "")
        file_path = f"{parent_path}/{item['name']}" if parent_path else item["name"]
        return {
            "file_path": file_path,
            "source_item_id": f"onedrive:{item['id']}",
            "source_etag": item.get("eTag"),
            "source_ctag": item.get("cTag"),
            "source_modified_at_utc": item.get("lastModifiedDateTime"),
            "source_quickxor_hash": item.get("file", {}).get("hashes", {}).get("quickXorHash"),
            "source_drive_id": item.get("parentReference", {}).get("driveId") or drive_id,
        }

    def _build_source_info(self, item: Dict, item_meta: Dict) -> Dict:
        """Build source info metadata for ingestion state tracking."""
        return {
            "source_system": PlatformConfig.ONEDRIVE_SOURCE_SYSTEM,
            "source_file_name": item.get("name"),
            "source_file_path": item_meta["file_path"],
            "source_item_id": item_meta["source_item_id"],
            "source_drive_id": item_meta["source_drive_id"],
            "source_etag": item_meta["source_etag"],
            "source_ctag": item_meta["source_ctag"],
            "source_quickxor_hash": item_meta["source_quickxor_hash"],
            "source_modified_at_utc": item_meta["source_modified_at_utc"],
            "file_size_bytes": item.get("size"),
        }

    def _record_error(self, athlete_id: str, source_info: Dict, exc: Exception) -> None:
        self._record_failure(athlete_id, source_info, str(exc))

    @staticmethod
    def _resolve_ingestion_id(source_info: Dict) -> str:
        source_item_id = source_info.get("source_item_id")
        if source_item_id:
            return str(source_item_id)

        raise IngestionIdResolutionError("OneDrive ingestion requires source_item_id")


class OneDriveSyncRequest:
    """Encapsulates OneDrive sync request parsing."""

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
        days = self.body.get("lookback_days")
        if days is None:
            days = self.query_params.get("lookback_days")
        if days is None:
            days = self.body.get("days")
        if days is None:
            days = self.query_params.get("days")
        if days is None:
            return None
        try:
            return int(days)
        except (ValueError, TypeError):
            return None

    @property
    def async_mode(self) -> bool:
        """Extract async flag from body or query params."""
        async_param = self.body.get("async") or self.query_params.get("async")
        if async_param is None:
            return False
        return self._to_bool(async_param)

    @property
    def force(self) -> bool:
        """Extract force flag from body or query params."""
        force_param = self.body.get("force")
        if force_param is None:
            force_param = self.query_params.get("force")
        return self._to_bool(force_param)

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
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            return raw_value.lower() in {"1", "true", "yes", "y"}
        if isinstance(raw_value, int):
            return raw_value == 1
        return False


class OneDriveResetRequest:
    """Encapsulates OneDrive delta reset request parsing."""

    def __init__(self, body: Optional[Dict], query_params: Optional[Dict]):
        self.body = body or {}
        self.query_params = query_params or {}

    @property
    def athlete_id(self) -> str | None:
        """Extract athlete_id from body or query params if provided."""
        athlete_id = self.body.get("athlete_id") or self.query_params.get("athlete_id")
        if athlete_id is None:
            return None
        athlete_id_str = str(athlete_id).strip()
        return athlete_id_str or None

    @property
    def reset_all(self) -> bool:
        """Extract bulk reset flag from body or query params."""
        all_param = self.body.get("all")
        if all_param is None:
            all_param = self.query_params.get("all")
        return str(all_param).lower() in {"1", "true", "yes", "y"}


class OneDriveSyncHandler:
    """Orchestrates OneDrive sync workflow."""

    def __init__(
        self,
        config: OneDriveSyncConfig,
        storage: StorageCoordinator,
        *,
        client: OneDriveGraphClient | None = None,
        ingestion_handler: OneDriveSyncIngestionHandler | None = None,
        async_queue: Any | None = None,
    ):
        self._config = config
        self._storage = storage
        self._client = client or OneDriveGraphClient(
            client_id=config.client_id,
            client_secret=config.client_secret,
            redirect_uri=config.redirect_uri,
            scopes=config.scopes,
        )
        self._ingestion_handler = ingestion_handler or OneDriveSyncIngestionHandler(
            storage,
            self._client,
        )
        self._async_queue = async_queue

    def handle(self, *args, **kwargs) -> Tuple[Dict, int]:
        """
        Execute OneDrive sync.

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

    def handle_reset(self, req: OneDriveResetRequest) -> Tuple[Dict, int]:
        """Reset OneDrive delta token state for single athlete or all athletes."""
        reset_at_utc = datetime.now(timezone.utc).isoformat()

        if req.reset_all:
            try:
                reset_count = self._storage.oauth_tokens.reset_all_onedrive_delta_states()
                return {
                    "status": "success",
                    "scope": "bulk",
                    "reset_count": reset_count,
                    "reset_at_utc": reset_at_utc,
                }, 200
            except HealthAssistantError as exc:
                logger.error(
                    "OneDrive bulk delta reset failed with typed error",
                    extra={
                        "source_system": "onedrive",
                        "operation": "delta_reset",
                        "scope": "bulk",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    exc_info=True,
                )
                return exc.to_response(include_message_alias=True)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(
                    "OneDrive bulk delta reset failed",
                    extra={
                        "source_system": "onedrive",
                        "operation": "delta_reset",
                        "scope": "bulk",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    exc_info=True,
                )
                return {"error": "Delta reset failed"}, 500

        athlete_id = req.athlete_id
        if not athlete_id:
            return {
                "error": "Provide athlete_id or set all=true for bulk reset"
            }, 400

        try:
            reset_applied = self._storage.oauth_tokens.reset_onedrive_delta_state(
                athlete_id
            )
            return {
                "status": "success",
                "scope": "single",
                "athlete_id": athlete_id,
                "reset_count": 1 if reset_applied else 0,
                "reset_applied": reset_applied,
                "reset_at_utc": reset_at_utc,
            }, 200
        except HealthAssistantError as exc:
            logger.error(
                "OneDrive delta reset failed with typed error",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "operation": "delta_reset",
                    "scope": "single",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return exc.to_response(include_message_alias=True)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "OneDrive delta reset failed",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "operation": "delta_reset",
                    "scope": "single",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {"error": "Delta reset failed"}, 500

    @property
    def config(self) -> OneDriveSyncConfig:
        """Expose current sync configuration."""
        return self._config

    def build_authorize_url(self, *, state: str) -> str:
        """Build the OAuth authorization URL for OneDrive."""
        return self._client.build_authorize_url(state=state)

    def complete_authorization(self, *, athlete_id: str, code: str) -> Dict:
        """Exchange OAuth code, store tokens, and return token payload."""
        token_data = self._client.exchange_code(code)
        drive_id = self._client.get_drive_id(token_data["access_token"])
        self._storage.oauth_tokens.store_onedrive_tokens(
            athlete_id=athlete_id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_in=int(token_data.get("expires_in", 3600)),
            scope=token_data.get("scope", ""),
            drive_id=drive_id,
        )
        return token_data

    def _handle_sync(self, athlete_id: str, lookback_days: int, force: bool) -> Tuple[Dict, int]:
        """Execute synchronous sync."""
        try:
            result = self.sync(athlete_id=athlete_id, lookback_days=lookback_days, force=force)
            return result, 200
        except ValueError as exc:
            logger.warning(
                "OneDrive sync validation failed",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "force": force,
                    "source_system": "onedrive",
                    "error_type": "ValueError",
                    "error": str(exc),
                },
            )
            return {"error": str(exc)}, 400
        except HealthAssistantError as exc:
            logger.error(
                "OneDrive sync failed with typed error",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "force": force,
                    "source_system": "onedrive",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return exc.to_response(include_message_alias=True)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "OneDrive sync failed",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "force": force,
                    "source_system": "onedrive",
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
        force: bool,
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
        """Enqueue async OneDrive sync work item."""
        async_queue = self._async_queue
        if async_queue is None:
            logger.error(
                "OneDrive async queue unavailable",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "operation_id": operation_id,
                    "source_system": "onedrive",
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
            source="onedrive",
            lookback_days=lookback_days,
            mode="async_queue",
            queued_at_utc=queued_at_utc,
            request_id=request_id,
            correlation_id=correlation_id,
            context={"source_system": "onedrive", "mode": "async", "force": force},
        )

        try:
            self._storage.async_operations.upsert_state(operation_state)
            async_queue.enqueue(
                item=AsyncIngestionWorkItem(
                    operation_id=operation_id,
                    source="onedrive",
                    athlete_id=athlete_id,
                    lookback_days=lookback_days,
                    queued_at_utc=queued_at_utc,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    context={
                        "source_system": "onedrive",
                        "mode": "async",
                        "force": force,
                    },
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "OneDrive async queue enqueue failed",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": lookback_days,
                    "operation_id": operation_id,
                    "source_system": "onedrive",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "status": "error",
                "error": "Failed to queue async OneDrive sync",
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
        """Run async OneDrive sync via in-process daemon thread (fallback mode)."""

        operation_state = AsyncIngestionOperationState.queued(
            athlete_id=athlete_id,
            operation_id=operation_id,
            source="onedrive",
            lookback_days=lookback_days,
            mode="async_thread",
            queued_at_utc=queued_at_utc,
            request_id=request_id,
            correlation_id=correlation_id,
            context={"source_system": "onedrive", "mode": "async", "force": force},
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
                    "OneDrive async sync completed",
                    extra={
                        "athlete_id": athlete_id,
                        "lookback_days": lookback_days,
                        "force": force,
                        "source_system": "onedrive",
                        "operation_id": operation_id,
                        "found": result.get("found"),
                        "ingested": result.get("ingested"),
                        "skipped": result.get("skipped"),
                        "filtered": result.get("filtered"),
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
                    "OneDrive async sync failed",
                    extra={
                        "athlete_id": athlete_id,
                        "lookback_days": lookback_days,
                        "force": force,
                        "source_system": "onedrive",
                        "operation_id": operation_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    exc_info=True,
                )

        threading.Thread(target=_run_background_sync, daemon=True).start()

        return {
            "status": "queued",
            "athlete_id": athlete_id,
            "lookback_days": lookback_days,
            "force": force,
            "mode": "async_thread",
            "operation_id": operation_id,
            "queued_at_utc": queued_at_utc,
        }, 202

    def _extract_request(self, args: tuple, kwargs: dict) -> OneDriveSyncRequest:
        req = kwargs.get("req")
        if req is None and args:
            req = args[0]
        if not isinstance(req, OneDriveSyncRequest):
            raise TypeError("req must be a OneDriveSyncRequest")
        return req

    def sync(self, *, athlete_id: str, lookback_days: int, force: bool = False) -> Dict:
        """Sync OneDrive folder and ingest qualifying FIT files."""
        access_token = self._get_access_token(athlete_id)
        tokens = self._get_tokens(athlete_id)
        drive_id = tokens.get("drive_id") or None
        delta_link = tokens.get("delta_token") or None

        effective_delta_link = None if force else delta_link
        delta_mode = "force_full" if force else ("incremental" if delta_link else "seed")
        try:
            files, next_delta_link = self._client.list_files_delta(
                access_token=access_token,
                folder_path=self._config.folder_path,
                delta_link=effective_delta_link,
                extensions={".fit", ".fit.gz"},
            )
        except OneDriveDeltaTokenExpiredError:
            logger.warning(
                "OneDrive delta token expired; restarting delta sync from scratch",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "folder_path": self._config.folder_path,
                    "delta_mode": "fallback_reset",
                },
            )
            files, next_delta_link = self._client.list_files_delta(
                access_token=access_token,
                folder_path=self._config.folder_path,
                delta_link=None,
                extensions={".fit", ".fit.gz"},
            )
            delta_mode = "fallback_reset"

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cutoff_date = cutoff.date()
        pre_filter_count = len(files)
        files = [
            item for item in files
            if _is_within_lookback(item, cutoff_date, cutoff)
        ]
        logger.info(
            "OneDrive filename/date filter applied",
            extra={
                "athlete_id": athlete_id,
                "source_system": "onedrive",
                "files_after_filter": len(files),
                "files_before_filter": pre_filter_count,
                "lookback_days": lookback_days,
                "cutoff_date": cutoff_date.isoformat(),
                "folder_path": self._config.folder_path,
                "delta_mode": delta_mode,
            },
        )

        if next_delta_link:
            self._storage.oauth_tokens.update_onedrive_delta_state(
                athlete_id,
                delta_token=next_delta_link,
                delta_sync_state="active",
            )

        results = {
            "status": "success",
            "lookback_days": lookback_days,
            "folder_path": self._config.folder_path,
            "sync_mode": delta_mode,
            "force": force,
            "found": len(files),
            "ingested": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
            "items": [],
        }

        for item in files:
            try:
                body, status_code = self._ingestion_handler.handle(
                    athlete_id=athlete_id,
                    access_token=access_token,
                    item=item,
                    drive_id=drive_id,
                    force=force,
                )
                self._record_ingest_result(results, item, body, status_code)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._record_error_result(results, item, exc)

        # Update status based on results
        if results["failed"] > 0:
            if results["ingested"] > 0 or results["skipped"] > 0:
                results["status"] = "partial"
            else:
                results["status"] = "failed"
        elif results["ingested"] == 0:
            results["status"] = "skipped"

        return results

    def _record_ingest_result(
        self,
        results: Dict,
        item: Dict,
        body: Dict,
        status_code: int,
    ) -> None:
        if status_code == 200 and body.get("status") == "success":
            results["ingested"] += 1
        elif status_code == 200 and body.get("status") == "skipped":
            results["skipped"] += 1
        else:
            results["failed"] += 1
        results["items"].append({
            "name": item.get("name"),
            "id": item.get("id"),
            "status": body.get("status", "error"),
            "message": body.get("message") or body.get("error"),
            "workout_id": body.get("workout_id"),
        })

    def _record_error_result(self, results: Dict, item: Dict, exc: Exception) -> None:
        results["failed"] += 1
        results["errors"].append(str(exc))
        results["items"].append({
            "name": item.get("name"),
            "id": item.get("id"),
            "status": "error",
            "message": str(exc),
        })

    def _get_tokens(self, athlete_id: str) -> Dict:
        """Load stored OneDrive tokens for the athlete."""
        tokens = self._storage.oauth_tokens.get_onedrive_tokens(athlete_id)
        if not tokens:
            raise ValueError("No OneDrive tokens stored. Authorize first.")
        return tokens

    def _refresh_tokens(self, athlete_id: str, refresh_token: str) -> Dict:
        """Refresh access token and persist updated token values."""
        token_data = self._client.refresh_access_token(refresh_token)
        self._storage.oauth_tokens.refresh_onedrive_token(
            athlete_id=athlete_id,
            new_access_token=token_data["access_token"],
            new_refresh_token=token_data.get("refresh_token", refresh_token),
            expires_in=int(token_data.get("expires_in", 3600)),
            scope=token_data.get("scope"),
            delta_token=token_data.get("delta_token"),
        )
        return token_data

    def _get_access_token(self, athlete_id: str) -> str:
        """Return a valid access token, refreshing if near expiry."""
        tokens = self._get_tokens(athlete_id)
        expires_at = tokens.get("expires_at_utc")
        if expires_at:
            try:
                expires_at_dt = datetime.fromisoformat(
                    expires_at.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                if datetime.now(timezone.utc) >= (
                    expires_at_dt - timedelta(minutes=5)
                ):
                    token_data = self._refresh_tokens(
                        athlete_id, tokens["refresh_token"]
                    )
                    return token_data["access_token"]
            except ValueError:
                pass
        return tokens["access_token"]


def _parse_workout_date(file_name: str) -> date | None:
    """Extract a YYYY-MM-DD date from the filename, if present."""
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", file_name)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_modified_datetime(item: Dict) -> datetime | None:
    """Parse OneDrive lastModifiedDateTime into a timezone-aware datetime."""
    raw = item.get("lastModifiedDateTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def _is_within_lookback(item: Dict, cutoff_date: date, cutoff_dt: datetime) -> bool:
    """Determine whether a OneDrive item is within the lookback window."""
    name = item.get("name", "")
    workout_date = _parse_workout_date(name)
    if workout_date is not None:
        keep = workout_date >= cutoff_date
        logger.debug(
            "OneDrive lookback (filename): %s date=%s cutoff=%s keep=%s",
            name,
            workout_date.isoformat(),
            cutoff_date.isoformat(),
            keep,
        )
        return keep

    logger.debug("OneDrive lookback (filename): no date found in %s", name)
    modified_dt = _parse_modified_datetime(item)
    if modified_dt is not None:
        keep = modified_dt >= cutoff_dt
        logger.debug(
            "OneDrive lookback (modified): %s modified=%s cutoff=%s keep=%s",
            name,
            modified_dt.isoformat(),
            cutoff_dt.isoformat(),
            keep,
        )
        return keep

    logger.debug("OneDrive lookback (fallback): %s keep=True", name)
    return True
