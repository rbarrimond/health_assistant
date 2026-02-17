"""Lazy dependency factories for Azure Functions endpoints.

This module centralizes construction of shared resources used by the HTTP layer.
It keeps domain objects free of environment wiring and cross-service coupling
while still providing lazy, cached initialization for performance.
"""

from __future__ import annotations

import logging
from functools import cached_property
from typing import Any, Dict

from azure.core.exceptions import AzureError

from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import (
    OneDriveSyncHandler,
    OneDriveSyncConfig,
)
from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer
from TrainingAnalyticsPlatform.storage.table_storage import WorkoutTableStorage
from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient
from TrainingAnalyticsPlatform.handlers import FitPayloadIngestionHandler

logger = logging.getLogger(__name__)


class FunctionAppDependencies:
    """Lazy, cached dependencies for Azure Functions endpoints.

    Use the module-level `dependencies` instance from request handlers to
    retrieve shared resources. Construction is centralized here so domain
    classes remain decoupled from environment configuration and other services.
    """

    @cached_property
    def storage(self) -> WorkoutTableStorage:
        """Return a cached storage instance, creating it on first use."""
        storage = WorkoutTableStorage()
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
    def onedrive_service(self) -> OneDriveSyncHandler:
        """Return a cached OneDrive sync handler instance, creating it on first use."""
        config = OneDriveSyncConfig.from_env()
        handler = OneDriveSyncHandler(
            config=config,
            storage=self.storage,
        )
        logger.info("OneDrive service initialized")
        return handler

    @cached_property
    def withings_client(self) -> WithingsClient:
        """Return a cached Withings client instance, creating it on first use."""
        return WithingsClient()

    def warmup(self) -> None:
        """Eagerly initialize core dependencies, deferring failures to runtime."""
        try:
            _ = self.storage
            _ = self.semantic_layer
        except (ValueError, AzureError, OSError) as exc:
            logger.warning("Deferred initialization: %s", exc)


dependencies = FunctionAppDependencies()
