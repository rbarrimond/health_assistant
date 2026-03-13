#!/usr/bin/env python3
"""Audit per-workout distance provenance across Workouts table, metadata blob, and canonical records.

Usage:
  .venv/bin/python scripts/audit_distance_provenance.py --athlete-id rob --weeks 12
"""

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


@dataclass
class DistanceProvenanceRow:
    workout_id: str
    start_time_utc: datetime
    sport: Optional[str]
    partition_key: str
    row_key: str
    table_distance_m: Optional[float]
    metadata_identity_distance_m: Optional[float]
    metadata_session_distance_m: Optional[float]
    canonical_max_distance_m: Optional[float]
    canonical_last_distance_m: Optional[float]


def _parse_iso_utc(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iter_month_keys(athlete_id: str, start_utc: datetime, end_utc: datetime) -> List[str]:
    current = datetime(start_utc.year, start_utc.month, 1, tzinfo=timezone.utc)
    end_month = datetime(end_utc.year, end_utc.month, 1, tzinfo=timezone.utc)
    keys: List[str] = []
    while current <= end_month:
        keys.append(f"{athlete_id}|{current.strftime('%Y-%m')}")
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            current = datetime(current.year, current.month + 1, 1, tzinfo=timezone.utc)
    return keys


def _canonical_distance_stats(storage: StorageCoordinator, blob_name: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    if not blob_name:
        return None, None
    try:
        df = storage.infrastructure.load_parquet_blob(blob_name)
    except (HttpResponseError, ResourceNotFoundError, OSError, ValueError):
        return None, None

    if df.empty or "distance_m" not in df.columns:
        return None, None

    series = df["distance_m"].dropna()
    if series.empty:
        return None, None

    try:
        numeric = series.astype(float)
    except (TypeError, ValueError):
        return None, None

    return float(numeric.max()), float(numeric.iloc[-1])


def collect_rows(storage: StorageCoordinator, athlete_id: str, weeks: int) -> List[DistanceProvenanceRow]:
    workouts_table = storage.infrastructure.get_table_client("Workouts")
    start_utc = datetime.now(timezone.utc) - timedelta(days=(weeks + 2) * 7)
    end_utc = datetime.now(timezone.utc)

    rows: List[DistanceProvenanceRow] = []
    for partition_key in _iter_month_keys(athlete_id, start_utc, end_utc):
        entities = workouts_table.query_entities(f"PartitionKey eq '{partition_key}'")
        for entity in entities:
            start_text = entity.get("start_time_utc")
            workout_id = str(entity.get("workout_id") or "")
            if not isinstance(start_text, str) or not workout_id:
                continue

            start_time_utc = _parse_iso_utc(start_text)
            if not (start_utc <= start_time_utc <= end_utc):
                continue

            try:
                metadata = storage.workouts.load_metadata_json(workout_id)
            except (HttpResponseError, ResourceNotFoundError, OSError, ValueError):
                metadata = {}

            identity = metadata.get("identity") if isinstance(metadata, dict) else {}
            session = metadata.get("session") if isinstance(metadata, dict) else {}
            if not isinstance(identity, dict):
                identity = {}
            if not isinstance(session, dict):
                session = {}

            canonical_blob = entity.get("canonical_records_blob")
            canonical_max_distance_m, canonical_last_distance_m = _canonical_distance_stats(
                storage,
                str(canonical_blob) if canonical_blob else None,
            )

            rows.append(
                DistanceProvenanceRow(
                    workout_id=workout_id,
                    start_time_utc=start_time_utc,
                    sport=(str(entity.get("sport")) if entity.get("sport") is not None else None),
                    partition_key=str(entity.get("PartitionKey") or ""),
                    row_key=str(entity.get("RowKey") or ""),
                    table_distance_m=_safe_float(entity.get("distance_m")),
                    metadata_identity_distance_m=_safe_float(identity.get("distance_m")),
                    metadata_session_distance_m=_safe_float(session.get("distance_m")),
                    canonical_max_distance_m=canonical_max_distance_m,
                    canonical_last_distance_m=canonical_last_distance_m,
                )
            )

    rows.sort(key=lambda row: row.start_time_utc)
    return rows


def _format_value(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{round(value, 2)}"


def _ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def report(rows: List[DistanceProvenanceRow]) -> None:
    print("=" * 120)
    print("DISTANCE PROVENANCE AUDIT")
    print("=" * 120)
    print(f"rows: {len(rows)}")

    with_table = [r for r in rows if r.table_distance_m is not None]
    print(f"table_distance_present: {len(with_table)}")

    mismatches = []
    for row in rows:
        ti = row.table_distance_m
        mi = row.metadata_identity_distance_m
        ms = row.metadata_session_distance_m
        cm = row.canonical_max_distance_m
        cl = row.canonical_last_distance_m

        for label, candidate in (
            ("metadata_identity", mi),
            ("metadata_session", ms),
            ("canonical_max", cm),
            ("canonical_last", cl),
        ):
            if ti is None or candidate is None:
                continue
            ratio = _ratio(ti, candidate)
            if ratio is not None and (ratio < 0.95 or ratio > 1.05):
                mismatches.append((row, label, candidate, ratio))

    print(f"mismatch_pairs(>5% delta): {len(mismatches)}")

    thousand_like = [
        item for item in mismatches
        if item[3] is not None and (0.0008 <= item[3] <= 0.0012 or 800 <= item[3] <= 1200)
    ]
    print(f"likely_1000x_unit_mismatch_pairs: {len(thousand_like)}")
    print()

    print("Top likely 1000x mismatches")
    print("-" * 120)
    if not thousand_like:
        print("None detected.")
    else:
        for row, label, candidate, ratio in thousand_like[:20]:
            print(
                f"{row.start_time_utc.isoformat()} | {row.workout_id} | sport={row.sport} | "
                f"table={_format_value(row.table_distance_m)} | {label}={_format_value(candidate)} | ratio={round(ratio, 6)}"
            )

    print()
    print("Sample provenance rows")
    print("-" * 120)
    for row in rows[-20:]:
        print(
            f"{row.start_time_utc.isoformat()} | {row.workout_id} | {row.sport} | "
            f"table={_format_value(row.table_distance_m)} | "
            f"meta.identity={_format_value(row.metadata_identity_distance_m)} | "
            f"meta.session={_format_value(row.metadata_session_distance_m)} | "
            f"canonical.max={_format_value(row.canonical_max_distance_m)} | "
            f"canonical.last={_format_value(row.canonical_last_distance_m)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit distance provenance across storage layers")
    parser.add_argument("--athlete-id", default="rob")
    parser.add_argument("--weeks", type=int, default=12)
    args = parser.parse_args()

    if args.weeks < 1:
        raise ValueError("--weeks must be >= 1")

    storage = StorageCoordinator()
    rows = collect_rows(storage, args.athlete_id, args.weeks)
    report(rows)


if __name__ == "__main__":
    main()
