"""Storage coordinator that composes all domain storage classes."""

import logging
from typing import Optional

from TrainingAnalyticsPlatform.storage.aggregation_storage import AggregationStorage
from TrainingAnalyticsPlatform.storage.oauth_token_storage import OAuthTokenStorage
from TrainingAnalyticsPlatform.storage.physiometrics_storage import PhysiometricsStorage
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure
from TrainingAnalyticsPlatform.storage.webhook_dedup_storage import WebhookDedupStorage
from TrainingAnalyticsPlatform.storage.workout_storage import WorkoutStorage

logger = logging.getLogger(__name__)


class StorageCoordinator:
    """
    Coordinates all storage operations by composing domain-specific storage classes.
    
    This is the primary entry point for storage access, replacing the old monolithic
    WorkoutTableStorage class. It provides typed access to storage capabilities via
    properties that satisfy storage protocols.
    """

    def __init__(self, connection_string: Optional[str] = None):
        """Initialize storage coordinator with infrastructure and domain classes."""
        self._infrastructure = StorageInfrastructure(connection_string)
        
        self._workouts = WorkoutStorage(self._infrastructure)
        self._physiometrics = PhysiometricsStorage(self._infrastructure)
        self._oauth_tokens = OAuthTokenStorage(self._infrastructure)
        self._webhooks = WebhookDedupStorage(self._infrastructure)
        self._aggregation = AggregationStorage(self._infrastructure)

    # ---- Properties for typed access to domain storage classes ----

    @property
    def workouts(self) -> WorkoutStorage:
        """Access workout storage operations."""
        return self._workouts

    @property
    def physiometrics(self) -> PhysiometricsStorage:
        """Access physiometrics storage operations."""
        return self._physiometrics

    @property
    def oauth_tokens(self) -> OAuthTokenStorage:
        """Access OAuth token storage operations."""
        return self._oauth_tokens

    @property
    def webhooks(self) -> WebhookDedupStorage:
        """Access webhook deduplication operations."""
        return self._webhooks

    @property
    def aggregation(self) -> AggregationStorage:
        """Access training aggregation operations."""
        return self._aggregation

    # ---- Backward compatibility: expose infrastructure directly for rare cases ----

    @property
    def infrastructure(self) -> StorageInfrastructure:
        """Access storage infrastructure (table and blob clients)."""
        return self._infrastructure
