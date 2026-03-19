"""Typed contracts for deferred retry queue and state coordination."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeferredRetryWorkItem(BaseModel):
    """Queue payload describing deferred retry execution work."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(..., min_length=1)
    schema_version: str = Field(default="1.0", min_length=1)
    athlete_id: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    lookback_days: int = Field(..., ge=1)
    idempotency_key: str = Field(..., min_length=1)
    queued_at_utc: str = Field(..., min_length=1)
    blocked_until_utc: str = Field(..., min_length=1)
    retry_after_raw: str = Field(..., min_length=1)
    retry_after_seconds: int = Field(..., ge=1)
    context: Dict[str, Any] = Field(default_factory=dict)


class RateLimitDeferralState(BaseModel):
    """Table row persisted for deferred retry state transitions."""

    model_config = ConfigDict(extra="forbid")

    partition_key: str = Field(..., min_length=1)
    row_key: str = Field(..., min_length=1)
    athlete_id: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    lookback_days: int = Field(..., ge=1)
    status: str = Field(..., min_length=1)
    retry_after_raw: str = Field(..., min_length=1)
    retry_after_seconds: int = Field(..., ge=1)
    blocked_until_utc: str = Field(..., min_length=1)
    created_at_utc: str = Field(..., min_length=1)
    updated_at_utc: str = Field(..., min_length=1)
    attempt_count: int = Field(default=0, ge=0)
    idempotency_key: str = Field(..., min_length=1)
    etag: Optional[str] = None

    def to_entity(self) -> Dict[str, Any]:
        """Convert model to Azure Table entity dictionary."""
        entity = {
            "PartitionKey": self.partition_key,
            "RowKey": self.row_key,
            "athlete_id": self.athlete_id,
            "source": self.source,
            "lookback_days": self.lookback_days,
            "status": self.status,
            "retry_after_raw": self.retry_after_raw,
            "retry_after_seconds": self.retry_after_seconds,
            "blocked_until_utc": self.blocked_until_utc,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "attempt_count": self.attempt_count,
            "idempotency_key": self.idempotency_key,
        }
        if self.etag:
            entity["etag"] = self.etag
        return entity

    @classmethod
    def from_entity(cls, entity: Dict[str, Any]) -> "RateLimitDeferralState":
        """Construct model from raw Azure Table entity."""
        return cls(
            partition_key=entity["PartitionKey"],
            row_key=entity["RowKey"],
            athlete_id=entity["athlete_id"],
            source=entity["source"],
            lookback_days=int(entity["lookback_days"]),
            status=entity["status"],
            retry_after_raw=entity["retry_after_raw"],
            retry_after_seconds=int(entity["retry_after_seconds"]),
            blocked_until_utc=entity["blocked_until_utc"],
            created_at_utc=entity["created_at_utc"],
            updated_at_utc=entity["updated_at_utc"],
            attempt_count=int(entity.get("attempt_count", 0)),
            idempotency_key=entity["idempotency_key"],
            etag=entity.get("etag") or entity.get("_etag"),
        )


class DeferredRetryDecision(BaseModel):
    """Coordinator decision returned to pre-sync execution layer."""

    model_config = ConfigDict(extra="forbid")

    deferred: bool = False
    operation_id: Optional[str] = None
    safe_to_retry_at_utc: Optional[str] = None
    retry_after_raw: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    reason: Optional[str] = None


def parse_retry_after_seconds(
    retry_after_raw: Optional[str],
    *,
    now_utc: Optional[datetime] = None,
) -> Optional[int]:
    """Parse Retry-After raw value to seconds.

    Supports either numeric delta-seconds or HTTP-date values.
    Returns None when parsing fails.
    """
    if retry_after_raw is None:
        return None

    value = retry_after_raw.strip()
    if not value:
        return None

    if value.isdigit():
        seconds = int(value)
        return seconds if seconds >= 0 else None

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    baseline = now_utc or datetime.now(timezone.utc)
    delta = parsed - baseline
    seconds = int(delta.total_seconds())
    return max(0, seconds)


def blocked_until_iso(*, retry_after_seconds: int, now_utc: Optional[datetime] = None) -> str:
    """Compute UTC ISO timestamp for when retry is safe."""
    baseline = now_utc or datetime.now(timezone.utc)
    return (baseline + timedelta(seconds=max(0, retry_after_seconds))).isoformat()