#!/usr/bin/env python3
"""Inspect live Garmin physiometrics endpoints for FTP/LTHR-related fields.

Usage:
  PYTHONPATH="$PWD" .venv/bin/python scripts/inspect_garmin_training_baselines.py

Examples:
  PYTHONPATH="$PWD" .venv/bin/python scripts/inspect_garmin_training_baselines.py --lookback-days 7
  PYTHONPATH="$PWD" GARMIN_PROBE_STORAGE_MODE=remote \
    .venv/bin/python scripts/inspect_garmin_training_baselines.py --date 2026-04-13
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
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
    parser = argparse.ArgumentParser(
        description="Inspect live Garmin physiometrics endpoints for FTP/LTHR fields"
    )
    parser.add_argument(
        "--athlete-id",
        default=os.getenv("ATHLETE_ID") or os.getenv("DEFAULT_ATHLETE_ID", "rob"),
        help="Athlete id used to restore stored Garmin token",
    )
    parser.add_argument(
        "--date",
        help="Inspect a single date (YYYY-MM-DD). Defaults to today UTC.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="When --date is omitted, inspect this many days ending today UTC (default: 7)",
    )
    parser.add_argument(
        "--refresh-token",
        action="store_true",
        help="Persist refreshed Garmin token after a successful run",
    )
    return parser.parse_args()


def _parse_date(raw_value: str) -> date:
    return datetime.strptime(raw_value, "%Y-%m-%d").date()


def _iter_dates(target_date: Optional[str], lookback_days: int) -> list[str]:
    if target_date:
        return [_parse_date(target_date).isoformat()]

    today = datetime.now(timezone.utc).date()
    window = max(1, lookback_days)
    return [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(window)
    ]


def _get_path(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _walk_matches(payload: Any, needle_parts: Iterable[str], prefix: str = "") -> list[tuple[str, Any]]:
    matches: list[tuple[str, Any]] = []

    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else key
            lower_key = key.lower()
            if any(part in lower_key for part in needle_parts):
                matches.append((path, value))
            matches.extend(_walk_matches(value, needle_parts, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            path = f"{prefix}[{index}]"
            matches.extend(_walk_matches(value, needle_parts, path))

    return matches


def _extract_candidate_fields(summary: dict[str, Any], training_status: dict[str, Any]) -> dict[str, Any]:
    stats = summary.get("stats", summary)
    return {
        "stats.functionThreshold": _get_path(stats, ("functionThreshold",)),
        "training_status.lactateThresholdHeartRate": _get_path(
            training_status, ("lactateThresholdHeartRate",)
        ),
        "training_status.lactateThreshold.heartRate": _get_path(
            training_status, ("lactateThreshold", "heartRate")
        ),
        "training_status.recoveryMetrics.lactateThresholdHeartRate": _get_path(
            training_status, ("recoveryMetrics", "lactateThresholdHeartRate")
        ),
        "training_status.recoveryMetrics.lthr": _get_path(
            training_status, ("recoveryMetrics", "lthr")
        ),
    }


def _fetch_endpoint_payloads(client: GarminConnectClient, date_str: str) -> dict[str, Any]:
    payloads: dict[str, Any] = {}

    for name, fetcher in (
        ("user_summary", client.get_user_summary),
        ("training_status", client.get_training_status),
        ("training_readiness", client.get_training_readiness),
        ("morning_training_readiness", client.get_morning_training_readiness),
    ):
        try:
            payload = fetcher(date_str)
            payloads[name] = payload
            if name in {"training_readiness", "morning_training_readiness"}:
                state = "present" if payload is not None else "none"
                print(f"{name}={state}")
            else:
                print(f"{name}=success")
        except Exception as exc:
            payloads[name] = None
            print(f"{name}=error:{type(exc).__name__}:{exc}")

    return payloads


def _print_match_block(label: str, payload: Any, needle_parts: Iterable[str]) -> None:
    matches = _walk_matches(payload, needle_parts)
    print(f"{label}_match_count={len(matches)}")
    for path, value in matches[:20]:
        print(f"{label}_match:{path}={value}")


def _report_date(date_str: str, payloads: dict[str, Any]) -> bool:
    print("=" * 80)
    print(f"DATE {date_str}")
    print("=" * 80)

    summary = payloads.get("user_summary") or {}
    training_status = payloads.get("training_status") or {}
    training_readiness = payloads.get("training_readiness")
    morning_training_readiness = payloads.get("morning_training_readiness")

    candidate_fields = _extract_candidate_fields(summary, training_status)
    found_any_candidate = False
    for key, value in candidate_fields.items():
        print(f"{key}={value}")
        if value is not None:
            found_any_candidate = True

    _print_match_block(
        "ftp_related",
        {
            "summary": summary,
            "training_status": training_status,
            "training_readiness": training_readiness,
            "morning_training_readiness": morning_training_readiness,
        },
        ("ftp", "thresholdpower", "functionthreshold"),
    )
    _print_match_block(
        "threshold_related",
        {
            "summary": summary,
            "training_status": training_status,
            "training_readiness": training_readiness,
            "morning_training_readiness": morning_training_readiness,
        },
        ("lthr", "lactatethreshold", "thresholdheartrate"),
    )

    latest_training_status_map = _get_path(
        training_status,
        ("mostRecentTrainingStatus", "latestTrainingStatusData"),
    )
    if isinstance(latest_training_status_map, dict):
        device_ids = list(latest_training_status_map.keys())
        print(f"training_status_device_ids={device_ids}")

    training_load_balance = _get_path(
        training_status,
        ("mostRecentTrainingLoadBalance", "recordedDevices"),
    )
    if isinstance(training_load_balance, list):
        device_names = [item.get("deviceName") for item in training_load_balance if isinstance(item, dict)]
        print(f"recorded_devices={device_names}")

    return found_any_candidate


def _authenticate_client(storage: StorageCoordinator, athlete_id: str) -> tuple[GarminConnectClient, bool]:
    try:
        stored_token = storage.oauth_tokens.get_garmin_tokens(athlete_id)
    except StorageError as exc:
        raise RuntimeError(f"Failed to read stored Garmin token: {exc}") from exc

    if not stored_token:
        raise RuntimeError(f"No stored Garmin token found for athlete_id={athlete_id}")

    client = GarminConnectClient()
    client.authenticate(stored_token)
    return client, True


def main() -> int:
    args = _parse_args()
    settings = _load_local_settings()
    storage_connection_string, storage_mode = _resolve_storage_connection_string(settings)
    dates = _iter_dates(args.date, args.lookback_days)

    print(f"athlete_id={args.athlete_id}")
    print(f"storage_mode={storage_mode}")
    print(f"dates={','.join(dates)}")

    storage = StorageCoordinator(connection_string=storage_connection_string)

    try:
        client, token_present = _authenticate_client(storage, str(args.athlete_id))
        print(f"token_present={token_present}")
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

    found_any_candidate = False

    for date_str in dates:
        payloads = _fetch_endpoint_payloads(client, date_str)
        found_any_candidate = _report_date(date_str, payloads) or found_any_candidate

    if args.refresh_token:
        try:
            refreshed_token = client.dump_tokens()
            storage.oauth_tokens.store_garmin_tokens(str(args.athlete_id), refreshed_token)
            print(f"token_refresh=stored length={len(refreshed_token)}")
        except (GarminConnectError, StorageError) as exc:
            print(f"token_refresh=error:{type(exc).__name__}:{exc}")

    print("=" * 80)
    print(f"found_any_candidate_fields={found_any_candidate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())