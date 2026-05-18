"""Backfill cycling LTHR across a historical effective-date range.

This script updates Physiometrics rows (data source defaults to manual) so
as-of workout computations can resolve the intended cycling LTHR on each date.

Usage:
  python scripts/backfill_cycling_lthr_effective_dates.py \
    --start-date 2026-01-01 --end-date 2026-05-18 \
    --cycling-lthr-bpm 171

  python scripts/backfill_cycling_lthr_effective_dates.py \
    --start-date 2026-01-01 --end-date 2026-05-18 \
    --cycling-lthr-bpm 171 --apply
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


@dataclass
class BackfillResult:
    day: str
    previous_cycling_lthr: Optional[float]
    new_cycling_lthr: float
    changed: bool
    persisted: bool
    error: Optional[str] = None


def _load_local_settings_env() -> None:
    settings_path = Path("local.settings.json")
    if not settings_path.exists():
        return

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    values = payload.get("Values")
    if not isinstance(values, dict):
        return

    for key, value in values.items():
        if isinstance(value, str):
            os.environ.setdefault(key, value)


def _date_range(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill cycling LTHR for each effective_date in a range "
            "using Azure-backed Physiometrics storage"
        )
    )
    parser.add_argument("--athlete-id", default=os.getenv("DEFAULT_ATHLETE_ID", "rob"))
    parser.add_argument("--start-date", required=True, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--cycling-lthr-bpm", required=True, type=float)
    parser.add_argument(
        "--lthr-bpm",
        type=float,
        default=None,
        help="Optional generic LTHR to set alongside cycling LTHR",
    )
    parser.add_argument(
        "--basis",
        default="LTHR",
        help="Heart-rate basis to write in each row (default: LTHR)",
    )
    parser.add_argument(
        "--data-source",
        default="manual",
        choices=["manual", "chatgpt"],
        help="Data source value for persisted rows",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist writes. Without this flag, script runs as dry-run.",
    )
    return parser.parse_args()


def _build_payload_for_day(
    current_as_of: Optional[Dict[str, Any]],
    *,
    cycling_lthr_bpm: float,
    lthr_bpm: Optional[float],
    basis: str,
) -> tuple[Dict[str, Any], Optional[float], bool]:
    payload: Dict[str, Any] = copy.deepcopy(current_as_of) if isinstance(current_as_of, dict) else {}

    heart_rate = payload.get("heart_rate")
    if not isinstance(heart_rate, dict):
        heart_rate = {}

    previous_cycling_lthr = heart_rate.get("lthr_cycling_bpm")

    if basis:
        heart_rate["basis"] = basis
    heart_rate["lthr_cycling_bpm"] = cycling_lthr_bpm
    if lthr_bpm is not None:
        heart_rate["lthr_bpm"] = lthr_bpm

    payload["heart_rate"] = heart_rate

    changed = previous_cycling_lthr != cycling_lthr_bpm
    return payload, _to_optional_float(previous_cycling_lthr), changed


def _to_optional_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def main() -> int:
    args = _parse_args()

    try:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
    except ValueError:
        print("error: start-date and end-date must be YYYY-MM-DD")
        return 2

    if end < start:
        print("error: end-date must be >= start-date")
        return 2

    _load_local_settings_env()

    try:
        storage = StorageCoordinator()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"error: failed to initialize storage coordinator: {exc}")
        return 1

    results: list[BackfillResult] = []

    for current_day in _date_range(start, end):
        day_str = current_day.isoformat()
        try:
            existing = storage.physiometrics.get_physiometrics_as_of(
                athlete_id=args.athlete_id,
                target_date=day_str,
            )
            payload, previous_cycling_lthr, changed = _build_payload_for_day(
                existing,
                cycling_lthr_bpm=args.cycling_lthr_bpm,
                lthr_bpm=args.lthr_bpm,
                basis=args.basis,
            )

            persisted = False
            if args.apply:
                storage.physiometrics.store_physiometrics(
                    athlete_id=args.athlete_id,
                    physiometrics_data=payload,
                    effective_date=day_str,
                    data_source=args.data_source,
                )
                persisted = True

            results.append(
                BackfillResult(
                    day=day_str,
                    previous_cycling_lthr=previous_cycling_lthr,
                    new_cycling_lthr=args.cycling_lthr_bpm,
                    changed=changed,
                    persisted=persisted,
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            results.append(
                BackfillResult(
                    day=day_str,
                    previous_cycling_lthr=None,
                    new_cycling_lthr=args.cycling_lthr_bpm,
                    changed=False,
                    persisted=False,
                    error=str(exc),
                )
            )

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"mode={mode} athlete_id={args.athlete_id} source={args.data_source}")
    print(
        "date | previous_cycling_lthr | new_cycling_lthr | changed | persisted | status"
    )

    failures = 0
    changed_count = 0
    persisted_count = 0

    for result in results:
        status = "ok"
        if result.error:
            status = f"error: {result.error}"
            failures += 1
        if result.changed:
            changed_count += 1
        if result.persisted:
            persisted_count += 1

        print(
            f"{result.day} | {result.previous_cycling_lthr} | "
            f"{result.new_cycling_lthr} | {result.changed} | "
            f"{result.persisted} | {status}"
        )

    print(
        f"summary total_days={len(results)} changed_days={changed_count} "
        f"persisted_days={persisted_count} failures={failures}"
    )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
