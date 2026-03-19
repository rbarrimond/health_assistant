"""Typed contracts for async ingestion queue messages."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class AsyncIngestionWorkItem(BaseModel):
    """Queue payload describing async ingestion work."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(..., min_length=1)
    schema_version: str = Field(default="1.0", min_length=1)
    source: str = Field(..., min_length=1)
    athlete_id: str = Field(..., min_length=1)
    lookback_days: int = Field(..., ge=1)
    queued_at_utc: str = Field(..., min_length=1)
    correlation_id: Optional[str] = None
    request_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
