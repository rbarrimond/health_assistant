#!/usr/bin/env python3
"""Inspect GarminActivityIndex payload shape and key frequencies.

Usage:
  PYTHONPATH="$PWD" .venv/bin/python scripts/inspect_garmin_activity_index_shape.py

Example:
  PYTHONPATH="$PWD" ATHLETE_ID=rob GARMIN_PROBE_STORAGE_MODE=runtime \
    .venv/bin/python scripts/inspect_garmin_activity_index_shape.py --lookback-days 120 --json-out /tmp/garmin_shape.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    parser = argparse.ArgumentParser(description="Inspect GarminActivityIndex payload shape")
    parser.add_argument(
        "--athlete-id",
        default=os.getenv("ATHLETE_ID") or os.getenv("DEFAULT_ATHLETE_ID", "rob"),
        help="Athlete id partition key (default: ATHLETE_ID/DEFAULT_ATHLETE_ID/rob)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=120,
        help="Lookback days for index query window (default: 120)",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write machine-readable JSON report",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=3,
        help="Max sample values stored per key path (default: 3)",
    )
    return parser.parse_args()


def _type_label(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return type(value).__name__


def _sample_repr(value: Any) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= 120:
        return text
    return text[:117] + "..."


def _walk_paths(value: Any, base_path: str, output: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{base_path}.{key}" if base_path else str(key)
            output[key_path] = child
            _walk_paths(child, key_path, output)
        return

    if isinstance(value, list):
        list_path = f"{base_path}[]" if base_path else "[]"
        output[list_path] = value
        for child in value:
            _walk_paths(child, list_path, output)


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

    print(f"athlete_id={athlete_id}")
    print(f"storage_mode={storage_mode}")
    print(f"lookback_days={lookback_days}")

    storage = StorageCoordinator(connection_string=storage_connection_string)

    try:
        payloads = storage.garmin_activity_index.query_activity_payloads_by_lookback(
            athlete_id=athlete_id,
            lookback_days=lookback_days,
        )
    except (StorageError, ValueError) as exc:
        print(f"query=error:{type(exc).__name__}:{exc}")
        return 3

    total = len(payloads)
    print(f"payload_count={total}")
    if total == 0:
        print("No payloads found in lookback window.")
        return 0

    path_presence = Counter()
    path_types: dict[str, Counter] = {}
    path_samples: dict[str, list[str]] = {}

    for payload in payloads:
        flat_paths: dict[str, Any] = {}
        _walk_paths(payload, "", flat_paths)

        for path, value in flat_paths.items():
            path_presence[path] += 1

            label = _type_label(value)
            if path not in path_types:
                path_types[path] = Counter()
            path_types[path][label] += 1

            if path not in path_samples:
                path_samples[path] = []
            if len(path_samples[path]) < args.sample_limit:
                sample = _sample_repr(value)
                if sample not in path_samples[path]:
                    path_samples[path].append(sample)

    sorted_paths = sorted(path_presence.keys())

    required_paths = ["activityId", "startTimeGMT"]
    runtime_paths = [
        "activityName",
        "startTimeLocal",
        "duration",
        "distance",
        "activityType",
        "activityType.typeKey",
    ]
    optional_upstream_paths = ["calories", "avgHR"]

    def _presence_line(path: str) -> str:
        count = path_presence.get(path, 0)
        pct = (count / total) * 100
        return f"{path}: {count}/{total} ({pct:.1f}%)"

    print("\n=== Required Contract Keys ===")
    for path in required_paths:
        print(_presence_line(path))

    print("\n=== Runtime-Consumed Keys ===")
    for path in runtime_paths:
        print(_presence_line(path))

    print("\n=== Optional Upstream-Observed Keys ===")
    for path in optional_upstream_paths:
        print(_presence_line(path))

    print("\n=== Full Key Union ===")
    for path in sorted_paths:
        count = path_presence[path]
        pct = (count / total) * 100
        type_counts = dict(path_types[path])
        print(f"- {path}: {count}/{total} ({pct:.1f}%) types={type_counts}")

    report = {
        "athlete_id": athlete_id,
        "storage_mode": storage_mode,
        "lookback_days": lookback_days,
        "payload_count": total,
        "required_paths": {
            path: {
                "count": path_presence.get(path, 0),
                "pct": round((path_presence.get(path, 0) / total) * 100, 2),
            }
            for path in required_paths
        },
        "runtime_paths": {
            path: {
                "count": path_presence.get(path, 0),
                "pct": round((path_presence.get(path, 0) / total) * 100, 2),
            }
            for path in runtime_paths
        },
        "optional_upstream_paths": {
            path: {
                "count": path_presence.get(path, 0),
                "pct": round((path_presence.get(path, 0) / total) * 100, 2),
            }
            for path in optional_upstream_paths
        },
        "key_union": [
            {
                "path": path,
                "count": path_presence[path],
                "pct": round((path_presence[path] / total) * 100, 2),
                "types": dict(path_types[path]),
                "samples": path_samples.get(path, []),
            }
            for path in sorted_paths
        ],
    }

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\njson_report={out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
