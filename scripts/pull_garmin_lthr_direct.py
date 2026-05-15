#!/usr/bin/env python3
"""Pull lactate-threshold heart rate directly from python-garminconnect.

This script calls Garmin endpoints directly via the `garminconnect` library,
without going through wellness ingestion handlers.

Usage:
  PYTHONPATH="$PWD" .venv/bin/python scripts/pull_garmin_lthr_direct.py

Examples:
  PYTHONPATH="$PWD" .venv/bin/python scripts/pull_garmin_lthr_direct.py --date 2026-05-14
  PYTHONPATH="$PWD" GARMIN_PROBE_STORAGE_MODE=remote \
    .venv/bin/python scripts/pull_garmin_lthr_direct.py --athlete-id rob --include-raw

Authentication order:
1) Stored Garmin token from OAuth token storage (default)
2) Username/password via GARMIN_EMAIL + GARMIN_PASSWORD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from garminconnect import Garmin

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TrainingAnalyticsPlatform.integrations.garmin_client import GarminConnectClient  # noqa: E402
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
        description="Pull Garmin lactate-threshold heart rate via python-garminconnect"
    )
    parser.add_argument(
        "--athlete-id",
        default=os.getenv("ATHLETE_ID") or os.getenv("DEFAULT_ATHLETE_ID", "rob"),
        help="Athlete id for token lookup (default: ATHLETE_ID/DEFAULT_ATHLETE_ID/rob)",
    )
    parser.add_argument(
        "--date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Date for date-scoped endpoints (YYYY-MM-DD, default: today UTC)",
    )
    parser.add_argument(
        "--skip-stored-token",
        action="store_true",
        help="Skip token restore and force credential-based login",
    )
    parser.add_argument(
        "--refresh-token",
        action="store_true",
        help="Persist refreshed token after successful auth",
    )
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="Include raw endpoint payloads in output JSON",
    )
    return parser.parse_args()


def _extract_first(payload: Any, paths: list[tuple[str, ...]]) -> Any:
    for path in paths:
        value = payload
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if value is not None:
            return value
    return None


def _auth_with_token_or_credentials(
    *,
    athlete_id: str,
    skip_stored_token: bool,
    refresh_token: bool,
) -> tuple[Garmin, str, Optional[StorageCoordinator]]:
    settings = _load_local_settings()
    storage_connection_string, _ = _resolve_storage_connection_string(settings)
    storage: Optional[StorageCoordinator] = None
    if storage_connection_string:
        storage = StorageCoordinator(connection_string=storage_connection_string)

    if not skip_stored_token and storage is not None:
        try:
            stored_token = storage.oauth_tokens.get_garmin_tokens(athlete_id)
        except StorageError:
            stored_token = None

        if stored_token:
            normalized = GarminConnectClient._normalize_stored_token(stored_token)
            client = Garmin()
            client.login(tokenstore=normalized)
            if refresh_token:
                storage.oauth_tokens.store_garmin_tokens(athlete_id, client.garth.dumps())
            return client, "token", storage

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "No stored Garmin token available and GARMIN_EMAIL/GARMIN_PASSWORD are missing"
        )

    client = Garmin(email, password)
    client.login()
    if refresh_token and storage is not None:
        storage.oauth_tokens.store_garmin_tokens(athlete_id, client.garth.dumps())
    return client, "credentials", storage


def _call_optional(client: Garmin, name: str, *args: Any) -> Any:
    func = getattr(client, name, None)
    if not callable(func):
        return None
    try:
        return func(*args)
    except Exception:
        return None


def main() -> int:
    args = _parse_args()

    try:
        client, auth_mode, _ = _auth_with_token_or_credentials(
            athlete_id=str(args.athlete_id),
            skip_stored_token=bool(args.skip_stored_token),
            refresh_token=bool(args.refresh_token),
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "stage": "auth",
                    "message": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    date_str = str(args.date)

    # Direct python-garminconnect endpoint calls
    lactate_threshold = _call_optional(client, "get_lactate_threshold")
    training_status = _call_optional(client, "get_training_status", date_str)
    recovery_metrics = _call_optional(client, "get_recovery_metrics", date_str)
    wellness = _call_optional(client, "get_wellness", date_str)

    lthr_from_lactate_endpoint_generic = _extract_first(
        lactate_threshold,
        [("speed_and_heart_rate", "heartRate")],
    )
    lthr_from_lactate_endpoint_cycling = _extract_first(
        lactate_threshold,
        [("speed_and_heart_rate", "heartRateCycling")],
    )
    lthr_from_training_status = _extract_first(
        training_status,
        [
            ("lactateThresholdHeartRate",),
            ("lactateThreshold", "heartRate"),
            ("recoveryMetrics", "lactateThresholdHeartRate"),
            ("recoveryMetrics", "lthr"),
        ],
    )
    lthr_from_recovery_metrics = _extract_first(
        recovery_metrics,
        [
            ("lactateThresholdHeartRate",),
            ("lactateThreshold",),
            ("lthr",),
            ("recovery", "lactateThresholdHeartRate"),
        ],
    )
    lthr_from_wellness = _extract_first(
        wellness,
        [
            ("lactateThresholdHeartRate",),
            ("lactateThreshold",),
            ("lthr",),
            ("heartRateMetrics", "lactateThresholdHeartRate"),
        ],
    )

    effective_lthr = lthr_from_lactate_endpoint_generic
    if effective_lthr is None:
        effective_lthr = lthr_from_lactate_endpoint_cycling
    if effective_lthr is None:
        effective_lthr = lthr_from_training_status
    if effective_lthr is None:
        effective_lthr = lthr_from_recovery_metrics
    if effective_lthr is None:
        effective_lthr = lthr_from_wellness

    result: dict[str, Any] = {
        "status": "ok",
        "auth_mode": auth_mode,
        "athlete_id": str(args.athlete_id),
        "date": date_str,
        "lthr": {
            "effective_bpm": effective_lthr,
            "from_lactate_threshold_endpoint_generic": lthr_from_lactate_endpoint_generic,
            "from_lactate_threshold_endpoint_cycling": lthr_from_lactate_endpoint_cycling,
            "from_training_status": lthr_from_training_status,
            "from_recovery_metrics": lthr_from_recovery_metrics,
            "from_wellness": lthr_from_wellness,
        },
        "endpoint_presence": {
            "lactate_threshold": lactate_threshold is not None,
            "training_status": training_status is not None,
            "recovery_metrics": recovery_metrics is not None,
            "wellness": wellness is not None,
        },
    }

    if args.include_raw:
        result["raw"] = {
            "lactate_threshold": lactate_threshold,
            "training_status": training_status,
            "recovery_metrics": recovery_metrics,
            "wellness": wellness,
        }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
