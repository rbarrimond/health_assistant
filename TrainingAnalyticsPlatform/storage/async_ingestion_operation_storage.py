"""Storage abstraction for async ingestion operation state tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from TrainingAnalyticsPlatform.models.async_operation import AsyncIngestionOperationState
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)

ASYNC_INGESTION_OPERATIONS_TABLE = "AsyncIngestionOperations"


class AsyncIngestionOperationStorage:
    """Persist async ingestion operation lifecycle in Azure Table Storage."""

    def __init__(self, infrastructure: StorageInfrastructure):
        self._infra = infrastructure

    def get_state(
        self,
        *,
        athlete_id: str,
        operation_id: str,
    ) -> Optional[AsyncIngestionOperationState]:
        """Read operation state row, if present."""
        table_client = self._infra.get_table_client(ASYNC_INGESTION_OPERATIONS_TABLE)
        try:
            entity = table_client.get_entity(partition_key=athlete_id, row_key=operation_id)
            return AsyncIngestionOperationState.from_entity(entity)
        except ResourceNotFoundError:
            return None
        except HttpResponseError as exc:
            logger.error(
                "Failed reading async ingestion operation state",
                extra={"athlete_id": athlete_id, "operation_id": operation_id},
                exc_info=True,
            )
            raise StorageError("Failed reading async ingestion operation state") from exc

    def upsert_state(self, state: AsyncIngestionOperationState) -> None:
        """Insert/update operation state row."""
        table_client = self._infra.get_table_client(ASYNC_INGESTION_OPERATIONS_TABLE)
        try:
            table_client.upsert_entity(state.to_entity(), mode="merge")
        except HttpResponseError as exc:
            logger.error(
                "Failed upserting async ingestion operation state",
                extra={"athlete_id": state.athlete_id, "operation_id": state.row_key},
                exc_info=True,
            )
            raise StorageError("Failed upserting async ingestion operation state") from exc

    def mark_status(
        self,
        *,
        athlete_id: str,
        operation_id: str,
        status: str,
        etag: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> AsyncIngestionOperationState:
        """Update operation status with optional optimistic concurrency."""
        table_client = self._infra.get_table_client(ASYNC_INGESTION_OPERATIONS_TABLE)
        entity: Dict[str, Any] = {
            "PartitionKey": athlete_id,
            "RowKey": operation_id,
            "status": status,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        if result is not None:
            entity["result"] = result
        if error is not None:
            entity["error"] = error

        try:
            kwargs: Dict[str, Any] = {"mode": "merge"}
            if etag:
                kwargs["etag"] = etag
                kwargs["match_condition"] = MatchConditions.IfNotModified
            table_client.update_entity(entity=entity, **kwargs)
        except HttpResponseError as exc:
            logger.warning(
                "Async ingestion operation state update conflict/failure",
                extra={
                    "athlete_id": athlete_id,
                    "operation_id": operation_id,
                    "status": status,
                    "etag": etag,
                },
                exc_info=True,
            )
            raise StorageError("Failed updating async ingestion operation state") from exc

        refreshed = self.get_state(athlete_id=athlete_id, operation_id=operation_id)
        if refreshed is None:
            raise StorageError("Async ingestion operation state missing after update")
        return refreshed
