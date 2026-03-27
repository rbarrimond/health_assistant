"""Compatibility shim for the Withings handler.

Canonical ownership now lives in
TrainingAnalyticsPlatform.handlers.wellness_sync.WithingsWellnessService.
This module is retained to preserve legacy imports and logger patch targets.
"""

import logging

from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator
from TrainingAnalyticsPlatform.handlers.wellness_sync import (
    WithingsWellnessService,
)


logger = logging.getLogger(__name__)

class WithingsHandler(WithingsWellnessService):
    """Backward-compatible Withings shim preserving module-local logger patching."""

    def __init__(self, withings_client: WithingsClient, storage: StorageCoordinator):
        super().__init__(withings_client, storage)
        self._logger = logger
