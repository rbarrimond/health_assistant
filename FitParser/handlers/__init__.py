"""HTTP handlers - pure business logic, no Azure Functions framework."""

from .fit_upload_handler import FitUploadHandler
from .onedrive_sync_handler import OneDriveSyncHandler, OneDriveSyncRequest
from .query_handler import QueryHandler
from .physiometrics_handler import PhysiometricsHandler
from .withings_handler import WithingsHandler
from .config_handler import ConfigHandler
from .health_handler import HealthHandler

__all__ = [
    "FitUploadHandler",
    "OneDriveSyncHandler",
    "OneDriveSyncRequest",
    "QueryHandler",
    "PhysiometricsHandler",
    "WithingsHandler",
    "ConfigHandler",
    "HealthHandler",
]
