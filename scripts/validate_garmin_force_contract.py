#!/usr/bin/env python3
"""Validate Garmin force=true contract against a running Function App.

Usage:
    PYTHONPATH="$PWD" .venv/bin/python scripts/validate_garmin_force_contract.py \
      --base-url "https://<app>.azurewebsites.net" \
      --function-key "<function_key>" \
      --athlete-id rob \
      --lookback-days 7

The script exits non-zero when any item in the sync result has status
`skipped_duplicate` while `force=true`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TrainingAnalyticsPlatform.platform.force_contract_validation import (
    find_force_contract_violations,
)


def _load_local_settings() -> None:
    settings_path = REPO_ROOT / "local.settings.json"
    if not settings_path.exists():
        return

    try:
        payload = json.loads(settings_path.read_text())
    except Exception:
        return

    values = payload.get("Values")
    if not isinstance(values, dict):
        return

    for key, value in values.items():
        if isinstance(value, str) and key not in os.environ:
            os.environ[key] = value


def _normalize_base_url(raw: str) -> str:
    return raw.rstrip("/")


def _resolve_base_url(cli_value: str | None) -> str:
    if cli_value:
        return _normalize_base_url(cli_value)

    env_value = os.getenv("HEALTH_ASSISTANT_BASE_URL") or os.getenv("FUNCTION_BASE_URL")
    if env_value:
        return _normalize_base_url(env_value)

    raise ValueError(
        "Missing Function App base URL. Provide --base-url or set HEALTH_ASSISTANT_BASE_URL."
    )


def _resolve_function_key(cli_value: str | None) -> str | None:
    if cli_value:
        return cli_value

    for key_name in ("HEALTH_ASSISTANT_FUNCTION_KEY", "FUNCTION_KEY", "AZURE_FUNCTION_KEY"):
        value = os.getenv(key_name)
        if value:
            return value

    return None


def _post_sync_request(
    *,
    session: requests.Session,
    base_url: str,
    function_key: str | None,
    athlete_id: str,
    lookback_days: int,
    timeout_sec: int,
) -> dict[str, Any]:
    sync_url = f"{base_url}/api/garmin/sync"
    params: dict[str, Any] = {}
    if function_key:
        params["code"] = function_key

    response = session.post(
        sync_url,
        params=params,
        json={
            "athlete_id": athlete_id,
            "lookback_days": lookback_days,
            "force": True,
            "async": False,
        },
        timeout=timeout_sec,
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Sync response payload is not a JSON object")

    return payload


def _poll_async_status_once(
    *,
    session: requests.Session,
    base_url: str,
    function_key: str | None,
    athlete_id: str,
    lookback_days: int,
    timeout_sec: int,
    poll_interval_sec: float,
    max_wait_sec: int,
) -> dict[str, Any]:
    sync_url = f"{base_url}/api/garmin/sync"
    params: dict[str, Any] = {}
    if function_key:
        params["code"] = function_key

    queue_response = session.post(
        sync_url,
        params=params,
        json={
            "athlete_id": athlete_id,
            "lookback_days": lookback_days,
            "force": True,
            "async": True,
        },
        timeout=timeout_sec,
    )
    queue_response.raise_for_status()

    queue_payload = queue_response.json()
    if not isinstance(queue_payload, dict):
        raise ValueError("Async queue response payload is not a JSON object")

    operation_id = queue_payload.get("operation_id")
    if not operation_id:
        raise ValueError("Async queue response did not include operation_id")

    status_url = f"{base_url}/api/async/operations/status"
    deadline = time.monotonic() + max_wait_sec
    while True:
        status_response = session.get(
            status_url,
            params={
                "athlete_id": athlete_id,
                "operation_id": operation_id,
                **({"code": function_key} if function_key else {}),
            },
            timeout=timeout_sec,
        )
        status_response.raise_for_status()
        status_payload = status_response.json()
        if not isinstance(status_payload, dict):
            raise ValueError("Async operation status payload is not a JSON object")

        status_value = str(status_payload.get("status", "")).strip().lower()
        if status_value in {"succeeded", "failed"}:
            return {
                "operation_id": operation_id,
                "status": status_value,
                "context": status_payload.get("context"),
                "result": status_payload.get("result"),
                "error": status_payload.get("error"),
            }

        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for async operation {operation_id} to finish"
            )

        time.sleep(poll_interval_sec)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Garmin force=true contract")
    parser.add_argument("--base-url", help="Function App base URL")
    parser.add_argument("--function-key", help="Function key (optional if auth disabled)")
    parser.add_argument("--athlete-id", default=os.getenv("DEFAULT_ATHLETE_ID", "rob"))
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--timeout-sec", type=int, default=60)
    parser.add_argument("--verify-async", action="store_true")
    parser.add_argument("--max-wait-sec", type=int, default=240)
    parser.add_argument("--poll-interval-sec", type=float, default=2.0)
    return parser


def main() -> int:
    _load_local_settings()
    args = _build_parser().parse_args()

    try:
        base_url = _resolve_base_url(args.base_url)
    except ValueError as exc:
        print(f"config_error={exc}")
        return 2

    function_key = _resolve_function_key(args.function_key)

    with requests.Session() as session:
        try:
            sync_payload = _post_sync_request(
                session=session,
                base_url=base_url,
                function_key=function_key,
                athlete_id=args.athlete_id,
                lookback_days=args.lookback_days,
                timeout_sec=args.timeout_sec,
            )
        except Exception as exc:
            print(f"sync_request_error={type(exc).__name__}:{exc}")
            return 3

        items = sync_payload.get("items")
        violations = find_force_contract_violations(items)

        print(f"sync_status={sync_payload.get('status')}")
        print(f"sync_found={sync_payload.get('found')}")
        print(f"sync_ingested={sync_payload.get('ingested')}")
        print(f"sync_skipped={sync_payload.get('skipped')}")
        print(f"force_contract_violations={len(violations)}")

        if violations:
            print("violations_json=")
            print(json.dumps(violations, indent=2, sort_keys=True))
            return 1

        if not args.verify_async:
            print("validation=pass")
            return 0

        try:
            async_summary = _poll_async_status_once(
                session=session,
                base_url=base_url,
                function_key=function_key,
                athlete_id=args.athlete_id,
                lookback_days=args.lookback_days,
                timeout_sec=args.timeout_sec,
                poll_interval_sec=args.poll_interval_sec,
                max_wait_sec=args.max_wait_sec,
            )
        except Exception as exc:
            print(f"async_validation_error={type(exc).__name__}:{exc}")
            return 4

        async_context = async_summary.get("context") if isinstance(async_summary, dict) else None
        force_flag = None
        if isinstance(async_context, dict):
            force_flag = async_context.get("force")

        print(f"async_operation_id={async_summary.get('operation_id')}")
        print(f"async_status={async_summary.get('status')}")
        print(f"async_force_context={force_flag}")

        if async_summary.get("status") != "succeeded":
            print("validation=fail_async_status")
            if async_summary.get("error") is not None:
                print(f"async_error={async_summary.get('error')}")
            return 1

        if force_flag is not True:
            print("validation=fail_async_force_context")
            return 1

        print("validation=pass")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
