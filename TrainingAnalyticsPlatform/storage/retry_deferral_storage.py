"""Storage abstraction for deferred retry state tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from TrainingAnalyticsPlatform.models.retry import RateLimitDeferralState
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)

RATE_LIMIT_DEFERRALS_TABLE = "RateLimitDeferrals"


class RetryDeferralStorage:
    """Persist deferred retry state using Azure Table Storage."""

    def __init__(self, infrastructure: StorageInfrastructure):
        self._infra = infrastructure

    def get_state(self, *, athlete_id: str, operation_id: str) -> Optional[RateLimitDeferralState]:
        """Read current deferred state for operation, if present."""
        table_client = self._infra.get_table_client(RATE_LIMIT_DEFERRALS_TABLE)
        try:
            entity = table_client.get_entity(
                partition_key=athlete_id,
                row_key=operation_id,
            )
            return RateLimitDeferralState.from_entity(entity)
        except ResourceNotFoundError:
            return None
        except HttpResponseError as exc:
            logger.error(
                "Failed reading deferred retry state",
                extra={"athlete_id": athlete_id, "operation_id": operation_id},
                exc_info=True,
            )
            raise StorageError("Failed reading deferred retry state") from exc

    def upsert_state(self, state: RateLimitDeferralState) -> None:
        """Insert/update deferred retry state row."""
        table_client = self._infra.get_table_client(RATE_LIMIT_DEFERRALS_TABLE)
        try:
            table_client.upsert_entity(state.to_entity(), mode="merge")
        except HttpResponseError as exc:
            logger.error(
                "Failed upserting deferred retry state",
                extra={"athlete_id": state.athlete_id, "operation_id": state.row_key},
                exc_info=True,
            )
            raise StorageError("Failed upserting deferred retry state") from exc

    def mark_status(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        status: str,
        etag: Optional[str],
        increment_attempts: bool = False,
    ) -> RateLimitDeferralState:
        """Update state status with optimistic concurrency when ETag is provided."""
        table_client = self._infra.get_table_client(RATE_LIMIT_DEFERRALS_TABLE)
        current = self.get_state(athlete_id=athlete_id, operation_id=operation_id)
        if current is None:
            raise StorageError("Deferred retry state does not exist")

        updated_attempts = current.attempt_count + 1 if increment_attempts else current.attempt_count
        updated_at_utc = datetime.now(timezone.utc).isoformat()
        entity = {
            "PartitionKey": athlete_id,
            "RowKey": operation_id,
            "status": status,
            "updated_at_utc": updated_at_utc,
            "attempt_count": updated_attempts,
        }

        try:
            kwargs = {"mode": "merge"}
            if etag:
                kwargs["etag"] = etag
                kwargs["match_condition"] = MatchConditions.IfNotModified
            table_client.update_entity(entity=entity, **kwargs)
        except HttpResponseError as exc:
            logger.warning(
                "Deferred retry state update conflict/failure",
                extra={
                    "athlete_id": athlete_id,
                    "operation_id": operation_id,
                    "status": status,
                    "etag": etag,
                },
                exc_info=True,
            )
            raise StorageError("Failed updating deferred retry state") from exc

        refreshed = self.get_state(athlete_id=athlete_id, operation_id=operation_id)
        if refreshed is None:
            raise StorageError("Deferred retry state missing after update")
        return refreshed