"""Typed response models for HTTP handler return values.

These models provide explicit typed contracts for handler return shapes,
replacing raw Dict literals at the HTTP adapter boundary.

TypedDicts are used for response shapes because TypedDict instances ARE dicts
at runtime — callers such as function_app.py and _json_response need zero changes.

Mutable accumulator @dataclasses are used for sync summary accumulators that
are built up incrementally during a sync loop, then converted to TypedDicts
via .to_response() before returning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NotRequired, TypedDict


# ---------------------------------------------------------------------------
# Item-level response shapes
# ---------------------------------------------------------------------------


class GarminSyncItemResult(TypedDict):
    """Per-activity result entry in a Garmin sync summary."""

    activity_id: str
    activity_name: str
    status: str | None
    workout_id: str | None


class OneDriveSyncItemResult(TypedDict):
    """Per-file result entry in a OneDrive sync summary."""

    name: str | None
    id: str | None
    status: str
    message: str | None
    workout_id: str | None


# ---------------------------------------------------------------------------
# Summary-level response shapes
# ---------------------------------------------------------------------------


class GarminSyncSummaryResponse(TypedDict):
    """Top-level response shape for a completed Garmin sync operation."""

    status: str
    lookback_days: int
    force: bool
    found: int
    ingested: int
    skipped: int
    skipped_by_id: int
    failed: int
    errors: list[str]
    items: list[GarminSyncItemResult]
    list_window_days_used: int
    list_calls_made: int
    cache_hit_count: int
    cache_miss_days: int


class OneDriveSyncSummaryResponse(TypedDict):
    """Top-level response shape for a completed OneDrive sync operation."""

    status: str
    lookback_days: int
    folder_path: str
    sync_mode: str
    force: bool
    found: int
    ingested: int
    skipped: int
    failed: int
    errors: list[str]
    items: list[OneDriveSyncItemResult]


# ---------------------------------------------------------------------------
# Ingestion-level response shapes
# ---------------------------------------------------------------------------


class IngestionSuccessResponse(TypedDict):
    """Response shape for a successfully ingested FIT file."""

    status: str
    workout_id: str


class IngestionSkipResponse(TypedDict):
    """Response shape for a skipped FIT ingestion."""

    status: str
    workout_id: str | None
    message: str


# ---------------------------------------------------------------------------
# Async and management response shapes
# ---------------------------------------------------------------------------


class AsyncQueueResponse(TypedDict):
    """Response shape for a successfully queued async sync operation."""

    status: str
    athlete_id: str
    lookback_days: int
    force: bool
    mode: str
    operation_id: str
    queued_at_utc: str
    error: NotRequired[str | None]


class OneDriveResetResponse(TypedDict):
    """Response shape for a OneDrive delta token reset operation."""

    status: str
    scope: str
    athlete_id: NotRequired[str | None]
    reset_count: int
    reset_applied: NotRequired[bool | None]
    reset_at_utc: str


# ---------------------------------------------------------------------------
# Mutable accumulator dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GarminSyncAccumulator:
    """Mutable accumulator for Garmin sync loop counters and result items.

    Mutated incrementally during sync, then converted to an immutable
    GarminSyncSummaryResponse via .to_response() before returning.
    """

    status: str = "success"
    lookback_days: int = 0
    force: bool = False
    found: int = 0
    ingested: int = 0
    skipped: int = 0
    skipped_by_id: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    items: list[GarminSyncItemResult] = field(default_factory=list)
    list_window_days_used: int = 0
    list_calls_made: int = 0
    cache_hit_count: int = 0
    cache_miss_days: int = 0

    def to_response(self) -> GarminSyncSummaryResponse:
        """Convert accumulator state to a typed summary response dict."""
        return GarminSyncSummaryResponse(
            status=self.status,
            lookback_days=self.lookback_days,
            force=self.force,
            found=self.found,
            ingested=self.ingested,
            skipped=self.skipped,
            skipped_by_id=self.skipped_by_id,
            failed=self.failed,
            errors=self.errors,
            items=self.items,
            list_window_days_used=self.list_window_days_used,
            list_calls_made=self.list_calls_made,
            cache_hit_count=self.cache_hit_count,
            cache_miss_days=self.cache_miss_days,
        )


@dataclass
class OneDriveSyncAccumulator:
    """Mutable accumulator for OneDrive sync loop counters and result items.

    Mutated incrementally during sync, then converted to an immutable
    OneDriveSyncSummaryResponse via .to_response() before returning.
    """

    status: str = "success"
    lookback_days: int = 0
    folder_path: str = ""
    sync_mode: str = ""
    force: bool = False
    found: int = 0
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    items: list[OneDriveSyncItemResult] = field(default_factory=list)

    def to_response(self) -> OneDriveSyncSummaryResponse:
        """Convert accumulator state to a typed summary response dict."""
        return OneDriveSyncSummaryResponse(
            status=self.status,
            lookback_days=self.lookback_days,
            folder_path=self.folder_path,
            sync_mode=self.sync_mode,
            force=self.force,
            found=self.found,
            ingested=self.ingested,
            skipped=self.skipped,
            failed=self.failed,
            errors=self.errors,
            items=self.items,
        )
