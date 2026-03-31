"""HTTP handlers - pure business logic, no Azure Functions framework."""

from .fit_payload_handler import FitPayloadIngestionHandler
from .ingestion_base_handler import FitIngestionBaseHandler
from .onedrive_sync_handler import (
    OneDriveSyncHandler,
    OneDriveSyncRequest,
    OneDriveResetRequest,
    OneDriveSyncIngestionHandler,
    OneDriveSyncConfig,
)
from .garmin_sync_handler import (
    GarminSyncHandler,
    GarminSyncRequest,
    GarminSyncIngestionHandler,
    GarminSyncConfig,
)
from .wellness_sync import GarminPhysiometricsSyncHandler, IntervalsSyncHandler
from .wellness_sync import WithingsWellnessService as WithingsHandler
from .weekly_rollup_presync_handler import WeeklyRollupPreSyncHandler
from .planning_context_presync_handler import PlanningContextPreSyncHandler
from .query_handler import QueryHandler
from .physiometrics_handler import PhysiometricsHandler
from .config_handler import ConfigHandler
from .health_handler import HealthHandler
from .agent_memory_handler import AgentMemoryHandler

__all__ = [
    "FitPayloadIngestionHandler",
    "FitIngestionBaseHandler",
    "OneDriveSyncHandler",
    "OneDriveSyncRequest",
    "OneDriveResetRequest",
    "OneDriveSyncIngestionHandler",
    "OneDriveSyncConfig",
    "GarminSyncHandler",
    "GarminSyncRequest",
    "GarminSyncIngestionHandler",
    "GarminSyncConfig",
    "GarminPhysiometricsSyncHandler",
    "IntervalsSyncHandler",
    "WeeklyRollupPreSyncHandler",
    "PlanningContextPreSyncHandler",
    "QueryHandler",
    "PhysiometricsHandler",
    "WithingsHandler",
    "ConfigHandler",
    "HealthHandler",
    "AgentMemoryHandler",
]
