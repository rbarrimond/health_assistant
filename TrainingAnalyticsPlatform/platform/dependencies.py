"""Lazy dependency factories for Azure Functions endpoints.

This module centralizes construction of shared resources used by the HTTP layer.
It keeps domain objects free of environment wiring and cross-service coupling
while still providing lazy, cached initialization for performance.
"""

from __future__ import annotations

import logging
import os
from functools import cached_property
from typing import Any, Dict, Optional

from azure.core.exceptions import AzureError

from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import (
    OneDriveSyncHandler,
    OneDriveSyncConfig,
)
from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import (
    GarminSyncHandler,
    GarminSyncConfig,
)
from TrainingAnalyticsPlatform.handlers.intervals_sync_handler import IntervalsSyncHandler
from TrainingAnalyticsPlatform.handlers.garmin_physiometrics_sync_handler import (
    GarminPhysiometricsSyncHandler,
)
from TrainingAnalyticsPlatform.handlers.weekly_rollup_presync_handler import (
    WeeklyRollupPreSyncHandler,
)
from TrainingAnalyticsPlatform.handlers.planning_context_presync_handler import (
    PlanningContextPreSyncHandler,
)
from TrainingAnalyticsPlatform.handlers.deferred_retry_coordinator import (
    DeferredRetryCoordinator,
)
from TrainingAnalyticsPlatform.handlers.async_ingestion_lifecycle_service import (
    AsyncIngestionLifecycleService,
)
from TrainingAnalyticsPlatform.handlers.deferred_retry_lifecycle_service import (
    DeferredRetryLifecycleService,
)
from TrainingAnalyticsPlatform.handlers.async_ingestion_operation_executor import (
    AsyncIngestionOperationExecutor,
)
from TrainingAnalyticsPlatform.handlers.deferred_retry_operation_executor import (
    DeferredRetryOperationExecutor,
)
from TrainingAnalyticsPlatform.handlers.source_handler_registry import (
    AsyncIngestionSourceHandler,
    DeferredRetrySourceHandler,
    SourceHandlerRegistry,
)
from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator
from TrainingAnalyticsPlatform.integrations.async_ingestion_queue import AsyncIngestionQueue
from TrainingAnalyticsPlatform.integrations.deferred_retry_queue import DeferredRetryQueue
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient
from TrainingAnalyticsPlatform.integrations.garmin_client import GarminConnectClient
from TrainingAnalyticsPlatform.integrations.intervals_client import IntervalsicuClient
from TrainingAnalyticsPlatform.handlers import FitPayloadIngestionHandler

logger = logging.getLogger(__name__)


class FunctionAppDependencies:
    """Lazy, cached dependencies for Azure Functions endpoints.

    Use the module-level `dependencies` instance from request handlers to
    retrieve shared resources. Construction is centralized here so domain
    classes remain decoupled from environment configuration and other services.
    """

    @cached_property
    def storage(self) -> StorageCoordinator:
        """Return a cached storage coordinator instance, creating it on first use."""
        storage = StorageCoordinator()
        logger.info("Storage initialized")
        return storage

    @cached_property
    def semantic_layer(self) -> SemanticLayer:
        """Return a cached semantic layer instance, creating it on first use."""
        semantic_layer = SemanticLayer(self.storage)
        logger.info("Semantic layer initialized")
        return semantic_layer

    def ingest_fit_payload(self, payload: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
        """Ingest a FIT payload using the shared storage instance."""
        handler = FitPayloadIngestionHandler(self.storage)
        return handler.handle(payload)

    @cached_property
    def onedrive_async_queue(self) -> Optional[AsyncIngestionQueue]:
        """Return async ingestion queue adapter for OneDrive when enabled."""
        if not self._is_onedrive_async_queue_enabled():
            logger.info("OneDrive async queue disabled by configuration")
            return None

        queue = AsyncIngestionQueue()
        logger.info("OneDrive async queue initialized")
        return queue

    @cached_property
    def onedrive_service(self) -> OneDriveSyncHandler:
        """Return a cached OneDrive sync handler instance, creating it on first use."""
        config = OneDriveSyncConfig.from_env()
        handler = OneDriveSyncHandler(
            config=config,
            storage=self.storage,
            async_queue=self.onedrive_async_queue,
        )
        logger.info("OneDrive service initialized")
        return handler

    @cached_property
    def withings_client(self) -> WithingsClient:
        """Return a cached Withings client instance, creating it on first use."""
        return WithingsClient()

    @cached_property
    def garmin_service(self) -> GarminSyncHandler:
        """Return a cached Garmin sync handler instance, creating it on first use."""
        config = GarminSyncConfig.from_env()
        handler = GarminSyncHandler(
            config=config,
            storage=self.storage,
            async_queue=self.garmin_async_queue,
        )
        logger.info("Garmin service initialized")
        return handler

    @cached_property
    def garmin_async_queue(self) -> Optional[AsyncIngestionQueue]:
        """Return async ingestion queue adapter for Garmin when enabled."""
        if not self._is_garmin_async_queue_enabled():
            logger.info("Garmin async queue disabled by configuration")
            return None

        queue = AsyncIngestionQueue()
        logger.info("Garmin async queue initialized")
        return queue

    @cached_property
    def garmin_client(self) -> GarminConnectClient:
        """Return a cached Garmin Connect client instance, creating it on first use."""
        return GarminConnectClient()

    @cached_property
    def intervals_service(self) -> IntervalsSyncHandler:
        """Return a cached Intervals.icu sync handler instance, creating it on first use."""
        client = IntervalsicuClient()
        handler = IntervalsSyncHandler(
            storage=self.storage,
            client=client,
        )
        logger.info("Intervals.icu service initialized")
        return handler

    @cached_property
    def garmin_physiometrics_service(self) -> GarminPhysiometricsSyncHandler:
        """Return a cached Garmin physiometrics sync handler instance."""
        handler = GarminPhysiometricsSyncHandler(
            storage=self.storage,
            client=self.garmin_client,
        )
        logger.info("Garmin physiometrics service initialized")
        return handler

    @cached_property
    def deferred_retry_queue(self) -> DeferredRetryQueue:
        """Return deferred retry queue adapter."""
        queue = DeferredRetryQueue()
        logger.info("Deferred retry queue initialized")
        return queue

    @cached_property
    def deferred_retry_coordinator(self) -> Optional[DeferredRetryCoordinator]:
        """Return deferred retry coordinator service."""
        if not self._is_deferred_retry_enabled():
            logger.info("Deferred retry coordinator disabled by configuration")
            return None

        coordinator = DeferredRetryCoordinator.from_env(
            queue=self.deferred_retry_queue,
            storage=self.storage.retry_deferrals,
        )
        logger.info("Deferred retry coordinator initialized")
        return coordinator

    @cached_property
    def async_ingestion_lifecycle(self) -> AsyncIngestionLifecycleService:
        """Return lifecycle service for async ingestion operation transitions."""
        return AsyncIngestionLifecycleService(storage=self.storage.async_operations)

    @cached_property
    def deferred_retry_lifecycle(self) -> DeferredRetryLifecycleService:
        """Return lifecycle service for deferred retry operation transitions."""
        return DeferredRetryLifecycleService(storage=self.storage.retry_deferrals)

    @cached_property
    def async_ingestion_executor(self) -> AsyncIngestionOperationExecutor:
        """Return async ingestion queue operation executor."""
        return AsyncIngestionOperationExecutor(
            lifecycle=self.async_ingestion_lifecycle,
            source_registry=self.async_ingestion_source_registry,
        )

    @cached_property
    def deferred_retry_executor(self) -> DeferredRetryOperationExecutor:
        """Return deferred retry queue operation executor."""
        return DeferredRetryOperationExecutor(
            queue=self.deferred_retry_queue,
            lifecycle=self.deferred_retry_lifecycle,
            coordinator=self.deferred_retry_coordinator,
            source_registry=self.deferred_retry_source_registry,
        )

    @cached_property
    def async_ingestion_source_registry(self) -> SourceHandlerRegistry[AsyncIngestionSourceHandler]:
        """Return source registry for async ingestion queue execution."""
        return SourceHandlerRegistry(
            handlers={
                "onedrive": lambda athlete_id, lookback_days, force: self.onedrive_service.sync(
                    athlete_id=athlete_id,
                    lookback_days=lookback_days,
                    force=force,
                ),
                "garmin": lambda athlete_id, lookback_days, force: self.garmin_service.sync(
                    athlete_id=athlete_id,
                    lookback_days=lookback_days,
                    force=force,
                ),
            }
        )

    @cached_property
    def deferred_retry_source_registry(self) -> SourceHandlerRegistry[DeferredRetrySourceHandler]:
        """Return source registry for deferred retry queue execution."""
        return SourceHandlerRegistry(
            handlers={
                "onedrive_workouts": lambda athlete_id, lookback_days: self.onedrive_service.handle(
                    OneDriveSyncRequest(
                        {
                            "athlete_id": athlete_id,
                            "days": lookback_days,
                            "async": False,
                        },
                        {},
                    )
                ),
                "garmin_activities": lambda athlete_id, lookback_days: self.garmin_service.handle(
                    GarminSyncRequest(
                        {
                            "athlete_id": athlete_id,
                            "lookback_days": lookback_days,
                            "async": False,
                        },
                        {},
                    )
                ),
                "garmin_physiometrics": lambda athlete_id, lookback_days: self.garmin_physiometrics_service.handle(
                    athlete_id,
                    lookback_days,
                    force=False,
                ),
                "intervals_physiometrics": self._execute_intervals_physiometrics_retry,
            }
        )

    def _execute_intervals_physiometrics_retry(
        self,
        athlete_id: str,
        lookback_days: int,
    ) -> tuple[Dict[str, Any], int]:
        """Execute deferred retry source for intervals physiometrics."""
        intervals_athlete_id = os.getenv("INTERVALS_ATHLETE_ID")
        if not intervals_athlete_id:
            return {"error": "INTERVALS_ATHLETE_ID is not configured"}, 424

        return self.intervals_service.handle(
            intervals_athlete_id=intervals_athlete_id,
            athlete_id=athlete_id,
            lookback_days=lookback_days,
        )

    @staticmethod
    def _is_deferred_retry_enabled() -> bool:
        """Return whether deferred retry queue integration is enabled."""
        return os.getenv("DEFERRED_RETRY_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _is_onedrive_async_queue_enabled() -> bool:
        """Return whether OneDrive async queue mode is enabled."""
        return os.getenv("ONEDRIVE_ASYNC_QUEUE_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _is_garmin_async_queue_enabled() -> bool:
        """Return whether Garmin async queue mode is enabled."""
        return os.getenv("GARMIN_ASYNC_QUEUE_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @cached_property
    def weekly_rollup_pre_sync_service(self) -> WeeklyRollupPreSyncHandler:
        """Return weekly rollup pre-sync orchestration service."""
        handler = WeeklyRollupPreSyncHandler.from_env(
            onedrive_service=self.onedrive_service,
            garmin_service=self.garmin_service,
            garmin_physiometrics_service=self.garmin_physiometrics_service,
            intervals_service=self.intervals_service,
            deferred_retry_coordinator=self.deferred_retry_coordinator,
        )
        logger.info("Weekly rollup pre-sync service initialized")
        return handler

    @cached_property
    def planning_context_pre_sync_service(self) -> PlanningContextPreSyncHandler:
        """Return planning context pre-sync orchestration service."""
        handler = PlanningContextPreSyncHandler.from_env(
            onedrive_service=self.onedrive_service,
            garmin_service=self.garmin_service,
            garmin_physiometrics_service=self.garmin_physiometrics_service,
            intervals_service=self.intervals_service,
            deferred_retry_coordinator=self.deferred_retry_coordinator,
        )
        logger.info("Planning context pre-sync service initialized")
        return handler

    def warmup(self) -> None:
        """Eagerly initialize core dependencies, deferring failures to runtime."""
        try:
            _ = self.storage
            _ = self.semantic_layer
        except (ValueError, AzureError, OSError) as exc:
            logger.warning("Deferred initialization: %s", exc)

        for queue in (
            self.onedrive_async_queue,
            self.garmin_async_queue,
            self.deferred_retry_queue,
        ):
            if queue is not None:
                try:
                    queue.bootstrap()
                except StorageError as exc:
                    logger.warning("Queue bootstrap deferred to runtime: %s", exc)


dependencies = FunctionAppDependencies()
