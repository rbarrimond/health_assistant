#!/usr/bin/env python3
"""Backfill GarminActivityIndex with raw list_activities payloads only.

This script intentionally does NOT download FIT files or invoke ingestion handlers.
It fetches Garmin activities for a lookback window and upserts raw payloads into
GarminActivityIndex for schema exploration and cache warmup.

Usage:
  PYTHONPATH="$PWD" .venv/bin/python scripts/garmin_list_activity_index_backfill.py

Examples:
  PYTHONPATH="$PWD" ATHLETE_ID=rob GARMIN_PROBE_STORAGE_MODE=runtime \
    .venv/bin/python scripts/garmin_list_activity_index_backfill.py --lookback-days 120
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TrainingAnalyticsPlatform.integrations.garmin_client import (  # noqa: E402
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.platform.exceptions import GarminConnectRateLimitError  # noqa: E402
from TrainingAnalyticsPlatform.storage.oauth_token_storage import StorageError  # noqa: E402
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator  # noqa: E402


def _load_local_settings() -> dict[str, Any]:
    settings_path = REPO_ROOT / "local.settings.json"
    if not settings_path.exists():
        return {}

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    values = data.get("Values", {})
    if isinstance(values, dict):
        for key, value in values.items():
            if isinstance(value, str) and key not in os.environ:
                os.environ[key] = value

    return data if isinstance(data, dict) else {}


def _resolve_storage_connection_string(settings: dict[str, Any]) -> tuple[Optional[str], str]:
    storage_mode = os.getenv("GARMIN_PROBE_STORAGE_MODE", "runtime").strip().lower()
    if storage_mode == "remote":
        connection_strings = settings.get("ConnectionStrings")
        if not isinstance(connection_strings, dict):
            raise ValueError(
                "GARMIN_PROBE_STORAGE_MODE=remote requires local.settings.json ConnectionStrings"
            )
        remote_connection = connection_strings.get("AzureWebJobsStorageRemote")
        if not isinstance(remote_connection, str) or not remote_connection.strip():
            raise ValueError(
                "GARMIN_PROBE_STORAGE_MODE=remote requires ConnectionStrings.AzureWebJobsStorageRemote"
            )
        return remote_connection, "remote"

    values = settings.get("Values")
    if isinstance(values, dict):
        runtime_connection = values.get("AzureWebJobsStorage")
        if isinstance(runtime_connection, str) and runtime_connection.strip():
            return runtime_connection, "runtime"

    return os.getenv("AzureWebJobsStorage"), "runtime"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill GarminActivityIndex from Garmin list API")
    parser.add_argument(
        "--athlete-id",
        default=os.getenv("ATHLETE_ID") or os.getenv("DEFAULT_ATHLETE_ID", "rob"),
        help="Athlete id partition key (default: ATHLETE_ID/DEFAULT_ATHLETE_ID/rob)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=120,
        help="Lookback days for list_activities window (default: 120)",
    )
    parser.add_argument(
        "--refresh-token",
        action="store_true",
        help="Persist refreshed token after successful auth/list call",
    )
    return parser.parse_args()


def _safe_start_time(activity: dict[str, Any]) -> Optional[str]:
    raw = activity.get("startTimeGMT")
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def main() -> int:
    args = _parse_args()
    settings = _load_local_settings()
    try:
        storage_connection_string, storage_mode = _resolve_storage_connection_string(settings)
    except ValueError as exc:
        print(f"storage=error:{exc}")
        return 2

    lookback_days = max(1, args.lookback_days)
    athlete_id = str(args.athlete_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    print(f"athlete_id={athlete_id}")
    print(f"storage_mode={storage_mode}")
    print(f"lookback_days={lookback_days}")
    print(f"cutoff_utc={cutoff.isoformat()}")

    storage = StorageCoordinator(connection_string=storage_connection_string)

    try:
        stored_token = storage.oauth_tokens.get_garmin_tokens(athlete_id)
    except StorageError as exc:
        print(f"token_read=error:{type(exc).__name__}:{exc}")
        stored_token = None

    print(f"token_present={bool(stored_token)}")

    client = GarminConnectClient()

    try:
        client.authenticate(stored_token)
        print("authenticate=success")
    except GarminConnectRateLimitError as exc:
        print(f"authenticate=rate_limited:{exc}")
        return 3
    except GarminConnectError as exc:
        print(f"authenticate=error:{exc}")
        return 3
    except Exception as exc:
        print(f"authenticate=unexpected:{type(exc).__name__}:{exc}")
        return 3

    try:
        activities = client.list_activities(start_date=cutoff)
    except Exception as exc:
        print(f"list_activities=error:{type(exc).__name__}:{exc}")
        return 4

    total = len(activities)
    print(f"list_activities=success count={total}")

    upserted = 0
    skipped = 0
    start_times: list[str] = []
    covered_days: set[str] = set()

    for activity in activities:
        try:
            storage.garmin_activity_index.upsert_activity_payload(
                athlete_id=athlete_id,
                activity_payload=activity,
            )
            upserted += 1
            normalized = _safe_start_time(activity)
            if normalized:
                start_times.append(normalized)
                covered_days.add(normalized[:10])
        except StorageError as exc:
            skipped += 1
            activity_id = activity.get("activityId")
            print(f"upsert=error activity_id={activity_id} error={type(exc).__name__}:{exc}")

    if args.refresh_token:
        try:
            refreshed_token = client.dump_tokens()
            storage.oauth_tokens.store_garmin_tokens(athlete_id, refreshed_token)
            print(f"token_refresh=stored length={len(refreshed_token)}")
        except (GarminConnectError, StorageError) as exc:
            print(f"token_refresh=error:{type(exc).__name__}:{exc}")

    earliest = min(start_times) if start_times else None
    latest = max(start_times) if start_times else None

    print(f"upserted={upserted}")
    print(f"upsert_skipped={skipped}")
    print(f"unique_days={len(covered_days)}")
    print(f"earliest_start_time_utc={earliest}")
    print(f"latest_start_time_utc={latest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
