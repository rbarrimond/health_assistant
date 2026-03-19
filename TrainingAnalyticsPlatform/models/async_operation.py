"""Typed contracts for async ingestion operation state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class AsyncIngestionOperationState(BaseModel):
    """Table row persisted for async ingestion operation lifecycle."""

    model_config = ConfigDict(extra="forbid")

    partition_key: str = Field(..., min_length=1)
    row_key: str = Field(..., min_length=1)
    athlete_id: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    lookback_days: int = Field(..., ge=1)
    status: str = Field(..., min_length=1)
    mode: str = Field(..., min_length=1)
    queued_at_utc: str = Field(..., min_length=1)
    created_at_utc: str = Field(..., min_length=1)
    updated_at_utc: str = Field(..., min_length=1)
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    etag: Optional[str] = None

    @classmethod
    def queued(
        cls,
        *,
        athlete_id: str,
        operation_id: str,
        source: str,
        lookback_days: int,
        mode: str,
        queued_at_utc: str,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> "AsyncIngestionOperationState":
        """Build initial queued state for operation."""
        now_utc = datetime.now(timezone.utc).isoformat()
        return cls(
            partition_key=athlete_id,
            row_key=operation_id,
            athlete_id=athlete_id,
            source=source,
            lookback_days=lookback_days,
            status="queued",
            mode=mode,
            queued_at_utc=queued_at_utc,
            created_at_utc=now_utc,
            updated_at_utc=now_utc,
            request_id=request_id,
            correlation_id=correlation_id,
            context=context or {},
        )

    def to_entity(self) -> Dict[str, Any]:
        """Convert model to Azure Table entity dictionary."""
        entity: Dict[str, Any] = {
            "PartitionKey": self.partition_key,
            "RowKey": self.row_key,
            "athlete_id": self.athlete_id,
            "source": self.source,
            "lookback_days": self.lookback_days,
            "status": self.status,
            "mode": self.mode,
            "queued_at_utc": self.queued_at_utc,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "context": json.dumps(self.context),
            "result": json.dumps(self.result),
        }
        if self.request_id is not None:
            entity["request_id"] = self.request_id
        if self.correlation_id is not None:
            entity["correlation_id"] = self.correlation_id
        if self.error is not None:
            entity["error"] = self.error
        if self.etag is not None:
            entity["etag"] = self.etag
        return entity

    @classmethod
    def from_entity(cls, entity: Dict[str, Any]) -> "AsyncIngestionOperationState":
        """Construct model from Azure Table entity."""
        context_raw = entity.get("context")
        context: Dict[str, Any] = {}
        if isinstance(context_raw, dict):
            context = context_raw
        elif isinstance(context_raw, str) and context_raw.strip():
            try:
                parsed_context = json.loads(context_raw)
                if isinstance(parsed_context, dict):
                    context = parsed_context
            except json.JSONDecodeError:
                context = {}

        result_raw = entity.get("result")
        result: Dict[str, Any] = {}
        if isinstance(result_raw, dict):
            result = result_raw
        elif isinstance(result_raw, str) and result_raw.strip():
            try:
                parsed_result = json.loads(result_raw)
                if isinstance(parsed_result, dict):
                    result = parsed_result
            except json.JSONDecodeError:
                result = {}

        return cls(
            partition_key=entity["PartitionKey"],
            row_key=entity["RowKey"],
            athlete_id=entity["athlete_id"],
            source=entity["source"],
            lookback_days=int(entity["lookback_days"]),
            status=entity["status"],
            mode=entity.get("mode", "unknown"),
            queued_at_utc=entity.get("queued_at_utc", ""),
            created_at_utc=entity.get("created_at_utc", ""),
            updated_at_utc=entity.get("updated_at_utc", ""),
            request_id=entity.get("request_id"),
            correlation_id=entity.get("correlation_id"),
            context=context,
            result=result,
            error=entity.get("error"),
            etag=entity.get("etag") or entity.get("_etag"),
        )
