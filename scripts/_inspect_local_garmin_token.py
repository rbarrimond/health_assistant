#!/usr/bin/env python3
"""Inspect local Garmin token restore behavior.

Usage:
  PYTHONPATH="$PWD" .venv/bin/python scripts/_inspect_local_garmin_token.py

Optional environment variables:
  ATHLETE_ID: Override athlete id (defaults to DEFAULT_ATHLETE_ID or "rob")
  GARMIN_PROBE_LIST: Set to "0" to skip list_activities call
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.platform.exceptions import GarminConnectRateLimitError
from TrainingAnalyticsPlatform.storage.oauth_token_storage import StorageError
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator


def _load_local_settings() -> None:
    settings_path = Path("local.settings.json")
    if not settings_path.exists():
        return

    try:
        data = json.loads(settings_path.read_text())
    except Exception:
        return

    for key, value in data.get("Values", {}).items():
        if isinstance(value, str) and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    _load_local_settings()

    athlete_id = os.getenv("ATHLETE_ID") or os.getenv("DEFAULT_ATHLETE_ID", "rob")
    should_list = os.getenv("GARMIN_PROBE_LIST", "1") != "0"

    print(f"athlete_id={athlete_id}")

    storage = StorageCoordinator(connection_string=os.getenv("AzureWebJobsStorage"))

    try:
        stored_token = storage.oauth_tokens.get_garmin_tokens(athlete_id)
    except StorageError as exc:
        print(f"token_read=error:{type(exc).__name__}:{exc}")
        stored_token = None

    print(f"token_present={bool(stored_token)}")
    if stored_token:
        print(f"token_length={len(stored_token)}")

    client = GarminConnectClient()
    original_restore = client.restore_from_tokens
    original_login = client.login
    state = {
        "restore_attempted": False,
        "restore_succeeded": False,
        "login_called": False,
    }

    def restore_wrapper(garth_token: str) -> None:
        state["restore_attempted"] = True
        original_restore(garth_token)
        state["restore_succeeded"] = True

    def login_wrapper() -> None:
        state["login_called"] = True
        original_login()

    client.restore_from_tokens = restore_wrapper
    client.login = login_wrapper

    try:
        client.authenticate(stored_token)
        print("authenticate=success")
    except GarminConnectRateLimitError as exc:
        print(f"authenticate=rate_limited:{exc}")
    except GarminConnectError as exc:
        print(f"authenticate=error:{exc}")
    except Exception as exc:
        print(f"authenticate=unexpected:{type(exc).__name__}:{exc}")

    print(f"restore_attempted={state['restore_attempted']}")
    print(f"restore_succeeded={state['restore_succeeded']}")
    print(f"login_called={state['login_called']}")

    if not should_list:
        print("list_activities=skipped:disabled")
        return 0

    if client.client is None:
        print("list_activities=skipped:not_authenticated")
        return 0

    try:
        activities = client.list_activities()
        print(f"list_activities=success count={len(activities)}")
    except Exception as exc:
        print(f"list_activities=error:{type(exc).__name__}:{exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
