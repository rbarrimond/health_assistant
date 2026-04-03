"""Typed request models for HTTP adapter delegation.

These models keep request coercion and validation close to handler-layer logic
so Azure route functions remain transport adapters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class PhysiometricsUpdateRequest:
    """Normalized payload for physiometrics update operations."""

    athlete_id: str | None
    effective_date: str | None
    source: str
    metric: str | None
    value: Any
    metrics: dict[str, Any] | None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PhysiometricsUpdateRequest":
        raw_metrics = payload.get("metrics")
        metrics = raw_metrics if isinstance(raw_metrics, dict) else None
        return cls(
            athlete_id=_as_optional_str(payload.get("athlete_id")),
            effective_date=_as_optional_str(payload.get("effective_date")),
            source=_as_optional_str(payload.get("source")) or "chatgpt",
            metric=_as_optional_str(payload.get("metric")),
            value=payload.get("value"),
            metrics=metrics,
        )

    @property
    def has_single_metric(self) -> bool:
        return self.metric is not None and self.value is not None

    @property
    def has_bulk_metrics(self) -> bool:
        return bool(self.metrics)


@dataclass(frozen=True)
class WithingsWebhookRequest:
    """Normalized Withings webhook fields from form/query sources."""

    userid: str
    appli: str
    startdate: str
    enddate: str

    @classmethod
    def from_sources(
        cls,
        form_values: Mapping[str, Any],
        params_values: Mapping[str, Any],
    ) -> "WithingsWebhookRequest":
        def _field(name: str) -> str:
            form_value = form_values.get(name)
            if form_value not in (None, ""):
                return str(form_value)
            param_value = params_values.get(name)
            return "" if param_value is None else str(param_value)

        return cls(
            userid=_field("userid"),
            appli=_field("appli"),
            startdate=_field("startdate"),
            enddate=_field("enddate"),
        )


@dataclass(frozen=True)
class GarminPhysiometricsSyncRequest:
    """Normalized Garmin physiometrics sync request."""

    athlete_id: str
    lookback_days: Any
    force: bool

    @classmethod
    def from_sources(
        cls,
        body: Mapping[str, Any],
        params: Mapping[str, Any],
        *,
        default_athlete_id: str,
    ) -> "GarminPhysiometricsSyncRequest":
        athlete_id = _as_optional_str(body.get("athlete_id"))
        if not athlete_id:
            athlete_id = _as_optional_str(params.get("athlete_id"))
        athlete_id = athlete_id or default_athlete_id

        lookback_days = body.get("lookback_days")
        if lookback_days is None:
            lookback_days = params.get("lookback_days")

        force_raw = body.get("force")
        if force_raw is None:
            force_raw = params.get("force")

        return cls(
            athlete_id=athlete_id,
            lookback_days=lookback_days,
            force=_coerce_bool(force_raw, default=False),
        )


@dataclass(frozen=True)
class IntervalsSyncRequest:
    """Normalized Intervals.icu sync request with source tracking."""

    intervals_athlete_id: str | None
    athlete_id: str
    lookback_days: int | None
    force: bool
    intervals_athlete_id_source: str
    athlete_id_source: str

    @classmethod
    def from_sources(
        cls,
        body: Mapping[str, Any],
        params: Mapping[str, Any],
        *,
        default_athlete_id: str,
        env_intervals_athlete_id: str | None,
    ) -> "IntervalsSyncRequest":
        intervals_athlete_id, intervals_source = _resolve_first(
            (body.get("intervals_athlete_id"), "request body"),
            (params.get("intervals_athlete_id"), "query parameter"),
            (env_intervals_athlete_id, "INTERVALS_ATHLETE_ID env"),
        )

        athlete_id, athlete_source = _resolve_first(
            (body.get("athlete_id"), "request body"),
            (params.get("athlete_id"), "query parameter"),
            (default_athlete_id, "DEFAULT_ATHLETE_ID fallback"),
        )

        raw_lookback = body.get("lookback_days")
        if raw_lookback is None:
            raw_lookback = params.get("lookback_days")

        return cls(
            intervals_athlete_id=_as_optional_str(intervals_athlete_id),
            athlete_id=_as_optional_str(athlete_id) or default_athlete_id,
            lookback_days=_parse_optional_int(raw_lookback),
            force=_coerce_bool(body.get("force", params.get("force")), default=False),
            intervals_athlete_id_source=intervals_source,
            athlete_id_source=athlete_source,
        )


@dataclass(frozen=True)
class WeeklyRollupComputeRequest:
    """Normalized payload for weekly rollup compute operation."""

    athletes: list[str]
    weeks: int

    @classmethod
    def from_sources(
        cls,
        body: Mapping[str, Any],
        params: Mapping[str, Any],
        *,
        default_athlete_id: str,
        list_athletes_with_workouts: Callable[[], list[str]],
    ) -> "WeeklyRollupComputeRequest":
        raw_weeks = body.get("weeks", params.get("weeks", 1))
        weeks = int(raw_weeks)
        if weeks < 1:
            raise ValueError("weeks must be >= 1")

        all_athletes = bool(body.get("all_athletes", False))
        requested_athlete_ids = body.get("athlete_ids")
        athlete_id = body.get("athlete_id") or params.get("athlete_id")

        athletes: list[str] = []
        if isinstance(requested_athlete_ids, list):
            athletes = [str(item) for item in requested_athlete_ids if str(item).strip()]
        elif athlete_id:
            athletes = [str(athlete_id)]
        elif all_athletes:
            athletes = list_athletes_with_workouts()

        if not athletes:
            athletes = [default_athlete_id]

        return cls(athletes=athletes, weeks=weeks)


def default_athlete_id() -> str:
    """Resolve default athlete id from environment with stable fallback."""
    return os.getenv("DEFAULT_ATHLETE_ID", "rob")


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _resolve_first(*candidates: tuple[Any, str]) -> tuple[Any, str]:
    for value, source in candidates:
        normalized = _as_optional_str(value)
        if normalized is not None:
            return normalized, source
    # Return last candidate source for deterministic logging fallback.
    return None, candidates[-1][1]
