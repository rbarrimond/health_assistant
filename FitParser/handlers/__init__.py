"""HTTP handlers - pure business logic, no Azure Functions framework."""

from .fit_payload_handler import FitPayloadIngestionHandler
from .ingestion_base_handler import FitIngestionBaseHandler
from .onedrive_sync_handler import (
    OneDriveSyncHandler,
    OneDriveSyncRequest,
    OneDriveSyncIngestionHandler,
    OneDriveSyncConfig,
)
from .query_handler import QueryHandler
from .physiometrics_handler import PhysiometricsHandler
from .withings_handler import WithingsHandler
from .config_handler import ConfigHandler
from .health_handler import HealthHandler
from .agent_memory_handler import AgentMemoryHandler

__all__ = [
    "FitPayloadIngestionHandler",
    "FitIngestionBaseHandler",
    "OneDriveSyncHandler",
    "OneDriveSyncRequest",
    "OneDriveSyncIngestionHandler",
    "OneDriveSyncConfig",
    "QueryHandler",
    "PhysiometricsHandler",
    "WithingsHandler",
    "ConfigHandler",
    "HealthHandler",
    "AgentMemoryHandler",
]
