#!/usr/bin/env python3
"""Backfill canonical GPS context into historical workout parquet blobs.

This repairs legacy workouts whose archived raw FIT payloads contain GPS context
(position/elevation) but whose canonical parquet substrate is missing one or more
of these columns:
- elevation_m
- position_lat
- position_long

The script is dry-run by default and only writes changes when --apply is passed.

Usage:
  PYTHONPATH="$PWD" .venv/bin/python scripts/backfill_canonical_gps_context.py
  PYTHONPATH="$PWD" .venv/bin/python scripts/backfill_canonical_gps_context.py --apply
  PYTHONPATH="$PWD" .venv/bin/python scripts/backfill_canonical_gps_context.py --athlete-id rob --apply
  PYTHONPATH="$PWD" .venv/bin/python scripts/backfill_canonical_gps_context.py --workout-id <id> --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from azure.core.exceptions import HttpResponseError  # noqa: E402

from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer  # noqa: E402
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator  # noqa: E402
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class BackfillCounters:
    scanned: int = 0
    candidates: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


def _load_local_settings() -> dict[str, Any]:
    settings_path = REPO_ROOT / "local.settings.json"
    if not settings_path.exists():
        return {}

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:  # pylint: disable=broad-exception-caught
        return {}

    values = data.get("Values", {})
    if isinstance(values, dict):
        for key, value in values.items():
            if isinstance(value, str) and key not in os.environ:
                os.environ[key] = value

    return data if isinstance(data, dict) else {}


def _resolve_storage_connection_string(
    settings: dict[str, Any],
    *,
    requested_mode: Optional[str],
) -> tuple[Optional[str], str]:
    storage_mode = (requested_mode or os.getenv("GARMIN_PROBE_STORAGE_MODE") or "runtime").strip().lower()

    if storage_mode == "remote":
        connection_strings = settings.get("ConnectionStrings")
        if not isinstance(connection_strings, dict):
            raise ValueError("remote mode requires local.settings.json ConnectionStrings")
        remote_connection = connection_strings.get("AzureWebJobsStorageRemote")
        if not isinstance(remote_connection, str) or not remote_connection.strip():
            raise ValueError("remote mode requires ConnectionStrings.AzureWebJobsStorageRemote")
        return remote_connection, "remote"

    values = settings.get("Values")
    if isinstance(values, dict):
        runtime_connection = values.get("AzureWebJobsStorage")
        if isinstance(runtime_connection, str) and runtime_connection.strip():
            return runtime_connection, "runtime"

    return os.getenv("AzureWebJobsStorage"), "runtime"


def _query_workout_entities(
    storage: StorageCoordinator,
    *,
    athlete_id: Optional[str],
    workout_id: Optional[str],
    limit: Optional[int],
) -> list[dict[str, Any]]:
    table_client = storage.infrastructure.get_table_client("Workouts")
    filters = ["has_gps eq true"]
    if athlete_id:
        filters.append(f"athlete_id eq '{athlete_id}'")
    if workout_id:
        filters.append(f"workout_id eq '{workout_id}'")

    query_filter = " and ".join(filters)
    entities = list(
        table_client.query_entities(
            query_filter=query_filter,
            select=[
                "PartitionKey",
                "RowKey",
                "workout_id",
                "athlete_id",
                "ingestion_id",
                "canonical_records_blob",
                "has_gps",
            ],
        )
    )
    if limit is not None:
        return entities[:limit]
    return entities


def _nonnull_count(df, column: str) -> int:
    if column not in df:
        return 0
    return int(df[column].notna().sum())


def _change_summary(before_df, after_df) -> dict[str, int]:
    return {
        column: max(0, _nonnull_count(after_df, column) - _nonnull_count(before_df, column))
        for column in ["elevation_m", "position_lat", "position_long"]
    }


def _run_backfill(
    *,
    storage: StorageCoordinator,
    athlete_id: Optional[str],
    workout_id: Optional[str],
    limit: Optional[int],
    apply: bool,
) -> BackfillCounters:
    counters = BackfillCounters()
    semantic_layer = SemanticLayer(storage)
    entities = _query_workout_entities(
        storage,
        athlete_id=athlete_id,
        workout_id=workout_id,
        limit=limit,
    )

    for entity in entities:
        counters.scanned += 1
        try:
            workout_entity = WorkoutEntity.from_table_entity(entity)
            blob_name = workout_entity.canonical_records_blob
            if not blob_name:
                counters.skipped += 1
                continue

            original_df = storage.workouts.load_canonical_records(blob_name)
            if original_df.empty or not semantic_layer._needs_raw_fit_hydration(original_df):  # pylint: disable=protected-access
                counters.skipped += 1
                continue

            hydrated_df = semantic_layer._hydrate_missing_elevation_from_raw_fit(workout_entity, original_df)  # pylint: disable=protected-access
            changes = _change_summary(original_df, hydrated_df)
            if not any(changes.values()):
                counters.skipped += 1
                continue

            counters.candidates += 1
            logger.info(
                "Backfill candidate workout_id=%s restored=%s",
                workout_entity.workout_id,
                changes,
            )

            if apply:
                storage.workouts.store_canonical_dataframe(blob_name, hydrated_df)
                counters.updated += 1
        except (HttpResponseError, ValueError, OSError) as exc:
            counters.errors += 1
            logger.error(
                "Backfill failed for workout entity",
                extra={
                    "workout_id": entity.get("workout_id"),
                    "athlete_id": entity.get("athlete_id"),
                    "error": str(exc),
                },
                exc_info=True,
            )

    return counters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--athlete-id", help="Limit backfill to one athlete")
    parser.add_argument("--workout-id", help="Limit backfill to one workout")
    parser.add_argument("--limit", type=int, help="Maximum workouts to inspect")
    parser.add_argument("--apply", action="store_true", help="Persist backfilled parquet changes")
    parser.add_argument(
        "--storage-mode",
        choices=["runtime", "remote"],
        help="Choose runtime or remote storage connection from local.settings.json",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = _load_local_settings()
    connection_string, resolved_mode = _resolve_storage_connection_string(
        settings,
        requested_mode=args.storage_mode,
    )
    storage = StorageCoordinator(connection_string=connection_string)

    logger.info(
        "Starting canonical GPS context backfill mode=%s apply=%s athlete_id=%s workout_id=%s limit=%s",
        resolved_mode,
        args.apply,
        args.athlete_id,
        args.workout_id,
        args.limit,
    )

    counters = _run_backfill(
        storage=storage,
        athlete_id=args.athlete_id,
        workout_id=args.workout_id,
        limit=args.limit,
        apply=args.apply,
    )

    logger.info(
        "Backfill complete scanned=%d candidates=%d updated=%d skipped=%d errors=%d",
        counters.scanned,
        counters.candidates,
        counters.updated,
        counters.skipped,
        counters.errors,
    )
    return 1 if counters.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
