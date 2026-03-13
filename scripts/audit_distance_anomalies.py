#!/usr/bin/env python3
"""Audit workout distance anomalies by reconciling Workouts vs WeeklyRollups in Azurite.

Usage:
  .venv/bin/python scripts/audit_distance_anomalies.py --athlete-id rob --weeks 12
"""

import argparse
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


@dataclass
class WorkoutRow:
    workout_id: str
    start_time_utc: datetime
    sport: Optional[str]
    distance_m: Optional[float]
    duration_sec: Optional[float]
    partition_key: str
    row_key: str


@dataclass
class RollupRow:
    partition_key: str
    row_key: str
    total_distance_km: Optional[float]
    workouts_count: Optional[int]
    last_updated_at_utc: Optional[str]
    week_start_local: Optional[str]
    week_end_local: Optional[str]


def _parse_iso_utc(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iter_month_partition_keys(athlete_id: str, start_utc: datetime, end_utc: datetime) -> List[str]:
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


def _week_key_for_local(dt_utc: datetime, athlete_tz: ZoneInfo) -> str:
    local = dt_utc.astimezone(athlete_tz)
    week_start_local = local - timedelta(
        days=local.weekday(),
        hours=local.hour,
        minutes=local.minute,
        seconds=local.second,
        microseconds=local.microsecond,
    )
    iso_year, iso_week, _ = week_start_local.isocalendar()
    return f"{iso_year}-{iso_week:02d}"


def _target_week_keys(athlete_tz: ZoneInfo, weeks: int) -> List[str]:
    now_local = datetime.now(timezone.utc).astimezone(athlete_tz)
    current_week_start_local = now_local - timedelta(
        days=now_local.weekday(),
        hours=now_local.hour,
        minutes=now_local.minute,
        seconds=now_local.second,
        microseconds=now_local.microsecond,
    )

    keys: List[str] = []
    for weeks_ago in range(1, weeks + 1):
        week_start_local = current_week_start_local - timedelta(days=7 * weeks_ago)
        iso_year, iso_week, _ = week_start_local.isocalendar()
        keys.append(f"{iso_year}-{iso_week:02d}")
    return keys


def resolve_athlete_timezone(storage: StorageCoordinator, athlete_id: str) -> ZoneInfo:
    semantic_layer = SemanticLayer(storage)
    timezone_name = semantic_layer._resolve_athlete_home_timezone(athlete_id)  # pylint: disable=protected-access
    if not timezone_name:
        raise RuntimeError(
            f"No athlete timezone configured for '{athlete_id}'. "
            "Set AgentPreferences/physiometrics timezone before running audit."
        )
    return ZoneInfo(timezone_name)


def fetch_workouts(
    storage: StorageCoordinator,
    athlete_id: str,
    start_utc: datetime,
    end_utc: datetime,
) -> List[WorkoutRow]:
    table = storage.infrastructure.get_table_client("Workouts")
    rows: List[WorkoutRow] = []
    partition_keys = _iter_month_partition_keys(athlete_id, start_utc, end_utc)

    for partition_key in partition_keys:
        entities = table.query_entities(f"PartitionKey eq '{partition_key}'")
        rows.extend(
            row
            for row in (
                _workout_row_from_entity(entity, start_utc, end_utc)
                for entity in entities
            )
            if row is not None
        )

    return rows


def _workout_row_from_entity(
    entity: Dict[str, object],
    start_utc: datetime,
    end_utc: datetime,
) -> Optional[WorkoutRow]:
    raw_start = entity.get("start_time_utc")
    if not isinstance(raw_start, str):
        return None

    start_time_utc = _parse_iso_utc(raw_start)
    if not (start_utc <= start_time_utc <= end_utc):
        return None

    return WorkoutRow(
        workout_id=str(entity.get("workout_id") or ""),
        start_time_utc=start_time_utc,
        sport=(str(entity.get("sport")) if entity.get("sport") is not None else None),
        distance_m=_optional_float(entity.get("distance_m")),
        duration_sec=_optional_float(entity.get("duration_sec")),
        partition_key=str(entity.get("PartitionKey") or ""),
        row_key=str(entity.get("RowKey") or ""),
    )


def fetch_weekly_rollups(
    storage: StorageCoordinator,
    athlete_id: str,
    target_week_keys: Set[str],
) -> Dict[str, List[RollupRow]]:
    table = storage.infrastructure.get_table_client("WeeklyRollups")
    by_week: Dict[str, List[RollupRow]] = defaultdict(list)

    years = sorted({int(k.split("-")[0]) for k in target_week_keys})
    for year in years:
        for row in _query_rollups_for_year(table, athlete_id, year, target_week_keys):
            by_week[row.row_key].append(row)

    return by_week


def _query_rollups_for_year(
    table,
    athlete_id: str,
    year: int,
    target_week_keys: Set[str],
) -> List[RollupRow]:
    rows: List[RollupRow] = []
    for delimiter in ("|", "#"):
        partition_key = f"{athlete_id}{delimiter}{year}"
        entities = table.query_entities(f"PartitionKey eq '{partition_key}'")
        rows.extend(
            row
            for row in (
                _rollup_row_from_entity(entity, partition_key, target_week_keys)
                for entity in entities
            )
            if row is not None
        )
    return rows


def _rollup_row_from_entity(
    entity: Dict[str, object],
    partition_key: str,
    target_week_keys: Set[str],
) -> Optional[RollupRow]:
    row_key = str(entity.get("RowKey") or "")
    if row_key not in target_week_keys:
        return None

    return RollupRow(
        partition_key=partition_key,
        row_key=row_key,
        total_distance_km=_optional_float(entity.get("total_distance_km")),
        workouts_count=_optional_int(entity.get("workouts_count")),
        last_updated_at_utc=_optional_str(entity.get("last_updated_at_utc")),
        week_start_local=_optional_str(entity.get("week_start_local")),
        week_end_local=_optional_str(entity.get("week_end_local")),
    )


def compute_expected_weekly_totals(
    workouts: List[WorkoutRow],
    athlete_tz: ZoneInfo,
    target_week_keys: Set[str],
) -> Tuple[Dict[str, float], Dict[str, int], Dict[str, List[WorkoutRow]]]:
    totals_m: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    by_week: Dict[str, List[WorkoutRow]] = defaultdict(list)

    for workout in workouts:
        week_key = _week_key_for_local(workout.start_time_utc, athlete_tz)
        if week_key not in target_week_keys:
            continue
        if workout.distance_m is None:
            continue
        totals_m[week_key] += workout.distance_m
        counts[week_key] += 1
        by_week[week_key].append(workout)

    expected_km = {week: round(total / 1000, 2) for week, total in totals_m.items()}
    return expected_km, counts, by_week


def analyze_workout_anomalies(workouts: List[WorkoutRow]) -> Dict[str, List[WorkoutRow]]:
    buckets: Dict[str, List[WorkoutRow]] = defaultdict(list)
    for workout in workouts:
        for bucket in _classify_workout_anomalies(workout):
            buckets[bucket].append(workout)
    return buckets


def _classify_workout_anomalies(workout: WorkoutRow) -> List[str]:
    if workout.distance_m is None:
        return ["missing_distance"]

    buckets: List[str] = []
    if workout.distance_m < 0:
        buckets.append("negative_distance")
    if workout.distance_m > 300_000:
        buckets.append("distance_over_300km")

    speed_kmh = _speed_kmh(workout)
    if speed_kmh is None:
        return buckets
    if speed_kmh > 90:
        buckets.append("speed_over_90kmh")
    if speed_kmh < 2 and workout.distance_m > 5000:
        buckets.append("speed_under_2kmh_with_distance")
    return buckets


def print_report(
    athlete_id: str,
    athlete_tz: ZoneInfo,
    weeks: int,
    target_week_keys: List[str],
    workouts: List[WorkoutRow],
    expected_km: Dict[str, float],
    expected_counts: Dict[str, int],
    rollups_by_week: Dict[str, List[RollupRow]],
    anomalies: Dict[str, List[WorkoutRow]],
) -> None:
    print("=" * 100)
    print("DISTANCE AUDIT REPORT")
    print("=" * 100)
    print(f"athlete_id: {athlete_id}")
    print(f"athlete_timezone: {athlete_tz.key}")
    print(f"weeks_audited (completed): {weeks}")
    print(f"workouts_loaded: {len(workouts)}")
    _print_distance_distribution(workouts)
    _print_cycling_unit_hypothesis(workouts)
    print()
    _print_week_comparison(target_week_keys, expected_km, expected_counts, rollups_by_week)
    _print_anomaly_buckets(anomalies)
    _print_largest_distances(workouts)
    _print_duplicate_week_rows(rollups_by_week)


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _speed_kmh(workout: WorkoutRow) -> Optional[float]:
    if workout.distance_m is None or workout.duration_sec in (None, 0):
        return None
    return (workout.distance_m / 1000) / (workout.duration_sec / 3600)


def _print_distance_distribution(workouts: List[WorkoutRow]) -> None:
    non_null_distances = [w.distance_m for w in workouts if w.distance_m is not None]
    if not non_null_distances:
        print("distance_m distribution: non_null=0")
        return

    min_m = min(non_null_distances)
    max_m = max(non_null_distances)
    med_m = median(non_null_distances)
    print(
        "distance_m distribution: "
        f"non_null={len(non_null_distances)} "
        f"min={round(min_m, 2)}m median={round(float(med_m), 2)}m max={round(max_m, 2)}m"
    )


def _print_cycling_unit_hypothesis(workouts: List[WorkoutRow]) -> None:
    cycling_with_duration = [
        row for row in workouts
        if row.sport == "cycling"
        and row.distance_m is not None
        and row.duration_sec not in (None, 0)
    ]
    if not cycling_with_duration:
        return

    speeds_if_m, speeds_if_km = _cycling_speed_hypotheses(cycling_with_duration)
    if not speeds_if_m or not speeds_if_km:
        return

    print(
        "unit hypothesis (cycling speeds): "
        f"meters_assumption median={round(float(median(speeds_if_m)), 2)} km/h, "
        f"kilometers_assumption median={round(float(median(speeds_if_km)), 2)} km/h"
    )


def _cycling_speed_hypotheses(workouts: List[WorkoutRow]) -> Tuple[List[float], List[float]]:
    speeds_if_m: List[float] = []
    speeds_if_km: List[float] = []
    for row in workouts:
        duration_h = float(row.duration_sec or 0) / 3600
        if duration_h <= 0:
            continue
        distance = float(row.distance_m or 0)
        speeds_if_m.append((distance / 1000) / duration_h)
        speeds_if_km.append(distance / duration_h)
    return speeds_if_m, speeds_if_km


def _print_week_comparison(
    target_week_keys: List[str],
    expected_km: Dict[str, float],
    expected_counts: Dict[str, int],
    rollups_by_week: Dict[str, List[RollupRow]],
) -> None:
    print("Week comparison (expected from Workouts vs persisted WeeklyRollups)")
    print("-" * 100)
    print(
        "week | expected_km | persisted_km | delta_km | expected_workouts | persisted_workouts | partition"
    )

    for week in target_week_keys:
        _print_week_comparison_row(
            week,
            expected_km.get(week),
            expected_counts.get(week, 0),
            rollups_by_week.get(week, []),
        )


def _print_week_comparison_row(
    week: str,
    expected: Optional[float],
    expected_count: int,
    persisted_rows: List[RollupRow],
) -> None:
    if not persisted_rows:
        print(
            f"{week} | {expected if expected is not None else '-'} | - | - | "
            f"{expected_count} | - | -"
        )
        return

    for row in sorted(
        persisted_rows,
        key=lambda item: item.last_updated_at_utc or "",
        reverse=True,
    ):
        delta = _delta_km(expected, row.total_distance_km)
        print(
            f"{week} | {expected if expected is not None else '-'} | "
            f"{row.total_distance_km if row.total_distance_km is not None else '-'} | "
            f"{delta if delta is not None else '-'} | "
            f"{expected_count} | {row.workouts_count if row.workouts_count is not None else '-'} | "
            f"{row.partition_key}"
        )


def _delta_km(expected: Optional[float], persisted: Optional[float]) -> Optional[float]:
    if expected is None or persisted is None:
        return None
    return round(persisted - expected, 2)


def _print_anomaly_buckets(anomalies: Dict[str, List[WorkoutRow]]) -> None:
    print()
    print("Workout-level anomaly buckets")
    print("-" * 100)
    if not anomalies:
        print("No heuristic anomalies detected in raw workout distances.")
        return

    for bucket, rows in sorted(anomalies.items()):
        print(f"{bucket}: {len(rows)}")
        for row in rows[:5]:
            print(
                f"  - {row.workout_id or row.row_key} | start={row.start_time_utc.isoformat()} "
                f"| distance_m={row.distance_m} | duration_sec={row.duration_sec} | sport={row.sport}"
            )
        if len(rows) > 5:
            print(f"  ... and {len(rows) - 5} more")


def _print_largest_distances(workouts: List[WorkoutRow]) -> None:
    print()
    print("Largest non-null workout distances")
    print("-" * 100)
    largest = sorted(
        [w for w in workouts if w.distance_m is not None],
        key=lambda row: row.distance_m or 0,
        reverse=True,
    )
    if not largest:
        print("No workouts with distance_m present.")
        return

    for row in largest[:10]:
        print(
            f"{row.workout_id or row.row_key} | {round(row.distance_m or 0, 2)}m "
            f"| start={row.start_time_utc.isoformat()} | sport={row.sport}"
        )


def _print_duplicate_week_rows(rollups_by_week: Dict[str, List[RollupRow]]) -> None:
    duplicate_week_rows = {
        week: rows for week, rows in rollups_by_week.items() if len(rows) > 1
    }
    print()
    print("Duplicate weekly rows across key formats")
    print("-" * 100)
    if not duplicate_week_rows:
        print("No duplicate week rows found.")
        return

    for week, rows in sorted(duplicate_week_rows.items()):
        partitions = ", ".join(sorted({r.partition_key for r in rows}))
        print(f"{week}: {len(rows)} rows -> {partitions}")



def main() -> None:
    parser = argparse.ArgumentParser(description="Audit workout distance anomalies from Azurite tables")
    parser.add_argument("--athlete-id", default="rob", help="Athlete id to audit")
    parser.add_argument("--weeks", type=int, default=12, help="Number of completed weeks to audit")
    args = parser.parse_args()

    if args.weeks < 1:
        raise ValueError("--weeks must be >= 1")

    storage = StorageCoordinator()
    athlete_tz = resolve_athlete_timezone(storage, args.athlete_id)

    target_week_keys = _target_week_keys(athlete_tz, args.weeks)
    # include one extra week and partial-current guard in source scan
    scan_start_utc = datetime.now(timezone.utc) - timedelta(days=(args.weeks + 2) * 7)
    scan_end_utc = datetime.now(timezone.utc)

    workouts = fetch_workouts(storage, args.athlete_id, scan_start_utc, scan_end_utc)
    expected_km, expected_counts, _ = compute_expected_weekly_totals(
        workouts,
        athlete_tz,
        set(target_week_keys),
    )
    rollups_by_week = fetch_weekly_rollups(storage, args.athlete_id, set(target_week_keys))
    anomalies = analyze_workout_anomalies(workouts)

    print_report(
        athlete_id=args.athlete_id,
        athlete_tz=athlete_tz,
        weeks=args.weeks,
        target_week_keys=target_week_keys,
        workouts=workouts,
        expected_km=expected_km,
        expected_counts=expected_counts,
        rollups_by_week=rollups_by_week,
        anomalies=anomalies,
    )


if __name__ == "__main__":
    main()
