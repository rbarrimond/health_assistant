"""Shared physiometrics resolution helpers.

These helpers centralize cross-source baseline selection so the semantic layer,
Config, and any consolidation paths apply the same recency semantics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


UTC_OFFSET = "+00:00"
BASELINE_SOURCE_PRECEDENCE: Dict[str, List[str]] = {
    "ftp_watts": ["manual", "chatgpt", "garmin"],
    "hr_lthr_bpm": ["manual", "chatgpt", "garmin"],
}


def parse_iso_timestamp(value: Optional[str]) -> datetime:
    """Parse ISO timestamp; fallback to minimum UTC time when missing/invalid."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    normalized = value.replace("Z", UTC_OFFSET)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def canonical_sources_from_row(row: Mapping[str, Any]) -> Set[str]:
    """Return canonical source IDs present in a physiometrics row."""
    sources: Set[str] = set()

    singular = row.get("data_source")
    if isinstance(singular, str) and singular.strip():
        sources.add(singular.strip().lower())

    csv_sources = row.get("data_sources")
    if isinstance(csv_sources, str) and csv_sources.strip():
        for value in csv_sources.split(","):
            normalized = value.strip().lower()
            if normalized:
                sources.add(normalized)

    return sources


def effective_date_from_row(row: Mapping[str, Any]) -> str:
    """Return a row's effective-date identity for ordering."""
    return str(row.get("effective_date") or row.get("RowKey") or "")


def resolve_row_metric_value(
    row: Mapping[str, Any],
    metric_name: str,
    field_aliases: Mapping[str, Sequence[str]],
) -> Optional[Any]:
    """Resolve a metric from canonical/storage alias columns."""
    candidate_fields = field_aliases.get(metric_name, (metric_name,))
    for field_name in candidate_fields:
        value = row.get(field_name)
        if value is not None:
            return value
    return None


def build_source_rows_by_source(
    rows: Iterable[Mapping[str, Any]],
    *,
    tracked_sources: Optional[Set[str]] = None,
    target_date: Optional[str] = None,
) -> Dict[str, List[Mapping[str, Any]]]:
    """Group rows by canonical source and sort newest-first within each source."""
    rows_by_source: Dict[str, List[Mapping[str, Any]]] = {}

    for row in rows:
        effective_date = str(row.get("effective_date") or "")
        if target_date and effective_date and effective_date > target_date:
            continue

        for source in canonical_sources_from_row(row):
            if tracked_sources is not None and source not in tracked_sources:
                continue
            rows_by_source.setdefault(source, []).append(row)

    for source_rows in rows_by_source.values():
        source_rows.sort(
            key=lambda row: (
                effective_date_from_row(row),
                parse_iso_timestamp(row.get("updated_at_utc")),
                str(row.get("RowKey") or ""),
            ),
            reverse=True,
        )

    return rows_by_source


def _metric_candidate_key(
    row: Mapping[str, Any],
    source: str,
    precedence_order: Mapping[str, int],
) -> Tuple[str, datetime, int, str]:
    """Build deterministic ordering key for a metric candidate."""
    return (
        effective_date_from_row(row),
        parse_iso_timestamp(row.get("updated_at_utc")),
        -precedence_order[source],
        str(row.get("RowKey") or ""),
    )


def _iter_metric_candidates(
    metric_name: str,
    preferred_sources: Sequence[str],
    source_rows_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    field_aliases: Mapping[str, Sequence[str]],
) -> Iterable[Tuple[Any, Mapping[str, Any], str]]:
    """Yield candidate metric values for all preferred sources."""
    for source in preferred_sources:
        for row in source_rows_by_source.get(source, ()): 
            value = resolve_row_metric_value(row, metric_name, field_aliases)
            if value is not None:
                yield value, row, source


def resolve_latest_metric_across_sources(
    metric_name: str,
    source_rows_by_source: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    field_aliases: Mapping[str, Sequence[str]],
    source_precedence: Optional[Mapping[str, Sequence[str]]] = None,
) -> Tuple[Optional[Any], Optional[Mapping[str, Any]], Optional[str]]:
    """Resolve a metric by cross-source recency, then source precedence as tie-breaker."""
    precedence_map = source_precedence or BASELINE_SOURCE_PRECEDENCE
    preferred_sources = list(precedence_map.get(metric_name, ()))
    if not preferred_sources:
        return None, None, None

    precedence_order = {source: index for index, source in enumerate(preferred_sources)}
    best: Optional[Tuple[Any, Mapping[str, Any], str]] = None
    best_key: Optional[Tuple[str, datetime, int, str]] = None

    for value, row, source in _iter_metric_candidates(
        metric_name,
        preferred_sources,
        source_rows_by_source,
        field_aliases=field_aliases,
    ):
        candidate_key = _metric_candidate_key(row, source, precedence_order)
        if best_key is None or candidate_key > best_key:
            best = (value, row, source)
            best_key = candidate_key

    if best is None:
        return None, None, None

    value, row, source = best
    return value, row, source