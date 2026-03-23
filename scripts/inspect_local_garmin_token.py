#!/usr/bin/env python3
"""Inspect local Garmin token restore behavior.

Usage:
    PYTHONPATH="$PWD" .venv/bin/python scripts/inspect_local_garmin_token.py

Optional environment variables:
  ATHLETE_ID: Override athlete id (defaults to DEFAULT_ATHLETE_ID or "rob")
  GARMIN_PROBE_LIST: Set to "0" to skip list_activities call
    GARMIN_PROBE_SHOW_SECRETS: Set to "1" to print full token values
    GARMIN_PROBE_STORAGE_MODE: "runtime" (default) or "remote"
    GARMIN_PROBE_REFRESH_TOKEN: Set to "1" to persist refreshed Garmin token
"""

from __future__ import annotations

import json
import os
import sys
from base64 import b64decode
from pathlib import Path
from typing import Any, Optional

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


def _load_local_settings() -> dict[str, Any]:
    settings_path = REPO_ROOT / "local.settings.json"
    if not settings_path.exists():
        return {}

    try:
        data = json.loads(settings_path.read_text())
    except Exception:
        return {}

    for key, value in data.get("Values", {}).items():
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


def _mask_secret(value: str, *, keep_prefix: int = 8, keep_suffix: int = 6) -> str:
    if len(value) <= keep_prefix + keep_suffix:
        return "<redacted>"
    return f"{value[:keep_prefix]}...{value[-keep_suffix:]}"


def _redact_decoded_payload(payload: Any, *, show_secrets: bool) -> Any:
    if show_secrets:
        return payload

    secret_keys = {
        "oauth_token",
        "oauth_token_secret",
        "access_token",
        "refresh_token",
        "token",
        "secret",
        "jwt",
    }

    if isinstance(payload, dict):
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            key_lower = key.lower()
            if isinstance(value, str) and any(secret_key in key_lower for secret_key in secret_keys):
                redacted[key] = _mask_secret(value)
            else:
                redacted[key] = _redact_decoded_payload(value, show_secrets=show_secrets)
        return redacted

    if isinstance(payload, list):
        return [_redact_decoded_payload(item, show_secrets=show_secrets) for item in payload]

    return payload


def _decode_stored_token(garth_token: str) -> Any:
    normalized = GarminConnectClient._normalize_stored_token(garth_token)
    decoded = b64decode(normalized)
    decoded_text = decoded.decode("utf-8")
    return json.loads(decoded_text)


def main() -> int:
    settings = _load_local_settings()

    athlete_id = os.getenv("ATHLETE_ID") or os.getenv("DEFAULT_ATHLETE_ID", "rob")
    should_list = os.getenv("GARMIN_PROBE_LIST", "1") != "0"
    show_secrets = os.getenv("GARMIN_PROBE_SHOW_SECRETS", "0") == "1"
    should_refresh_token = os.getenv("GARMIN_PROBE_REFRESH_TOKEN", "0") == "1"
    storage_connection_string, storage_mode = _resolve_storage_connection_string(settings)

    print(f"athlete_id={athlete_id}")
    print(f"storage_mode={storage_mode}")
    print(f"refresh_token_mode={should_refresh_token}")

    storage = StorageCoordinator(connection_string=storage_connection_string)

    try:
        stored_token = storage.oauth_tokens.get_garmin_tokens(athlete_id)
    except StorageError as exc:
        print(f"token_read=error:{type(exc).__name__}:{exc}")
        stored_token = None

    print(f"token_present={bool(stored_token)}")
    if stored_token:
        print(f"token_length={len(stored_token)}")
        try:
            decoded_payload = _decode_stored_token(stored_token)
            safe_payload = _redact_decoded_payload(decoded_payload, show_secrets=show_secrets)
            print("decoded_token_json=")
            print(json.dumps(safe_payload, indent=2, sort_keys=True))
        except Exception as exc:
            print(f"decoded_token_json=error:{type(exc).__name__}:{exc}")

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

    is_authenticated = client.client is not None

    if not should_list:
        print("list_activities=skipped:disabled")
    elif not is_authenticated:
        print("list_activities=skipped:not_authenticated")
    else:
        try:
            activities = client.list_activities()
            print(f"list_activities=success count={len(activities)}")
        except Exception as exc:
            print(f"list_activities=error:{type(exc).__name__}:{exc}")

    if should_refresh_token and is_authenticated:
        try:
            refreshed_token = client.dump_tokens()
            storage.oauth_tokens.store_garmin_tokens(athlete_id, refreshed_token)
            print("token_refresh=stored")
            print(f"token_refresh_length={len(refreshed_token)}")
        except (GarminConnectError, StorageError) as exc:
            print(f"token_refresh=error:{type(exc).__name__}:{exc}")
    elif should_refresh_token:
        print("token_refresh=skipped:not_authenticated")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
