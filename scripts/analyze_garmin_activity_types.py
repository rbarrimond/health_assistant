#!/usr/bin/env python3
"""Analyze GarminActivityIndex payloads by activity type.

Read-only analysis over indexed list payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import variance
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Garmin payload shape by type")
    parser.add_argument("--athlete-id", default=os.getenv("ATHLETE_ID") or "rob")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument("--json-out", default="/tmp/garmin_activity_type_matrix_120d.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    athlete_id = str(args.athlete_id)
    lookback_days = max(1, int(args.lookback_days))

    storage = StorageCoordinator(connection_string="UseDevelopmentStorage=true")
    payloads = storage.garmin_activity_index.query_activity_payloads_by_lookback(
        athlete_id=athlete_id,
        lookback_days=lookback_days,
    )

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for payload in payloads:
        type_key = str(((payload.get("activityType") or {}).get("typeKey") or "unknown"))
        by_type[type_key].append(payload)

    key_union_by_type: dict[str, set[str]] = {}
    for type_key, items in by_type.items():
        key_union: set[str] = set()
        for item in items:
            key_union.update(item.keys())
        key_union_by_type[type_key] = key_union

    owners: dict[str, set[str]] = {}
    for type_key, keys in key_union_by_type.items():
        for key in keys:
            owners.setdefault(key, set()).add(type_key)

    unique_keys_by_type: dict[str, list[str]] = defaultdict(list)
    for key, type_owners in owners.items():
        if len(type_owners) == 1:
            unique_keys_by_type[next(iter(type_owners))].append(key)

    all_keys = set().union(*key_union_by_type.values()) if key_union_by_type else set()
    sorted_types = sorted(by_type.keys())

    discriminators = []
    for key in all_keys:
        ratios = []
        for type_key in sorted_types:
            items = by_type[type_key]
            present = sum(1 for item in items if key in item)
            ratios.append(present / len(items) if items else 0.0)
        if min(ratios) == max(ratios):
            continue
        v = variance(ratios) if len(ratios) > 1 else 0.0
        discriminators.append(
            {
                "key": key,
                "variance": v,
                "ratios": {type_key: ratio for type_key, ratio in zip(sorted_types, ratios)},
            }
        )

    discriminators.sort(key=lambda item: item["variance"], reverse=True)

    print(f"payload_count={len(payloads)}")
    print("\n=== Activity Type Counts ===")
    for type_key in sorted_types:
        print(f"{type_key}: {len(by_type[type_key])}")

    print("\n=== Per-Type Key Union Size ===")
    for type_key in sorted_types:
        print(f"{type_key}: {len(key_union_by_type[type_key])}")

    print("\n=== Keys Unique To Single Type ===")
    any_unique = False
    for type_key in sorted_types:
        keys = sorted(unique_keys_by_type.get(type_key, []))
        if keys:
            any_unique = True
            print(f"[{type_key}] {len(keys)}")
            for key in keys:
                print(f"  - {key}")
    if not any_unique:
        print("none")

    print("\n=== Top 20 Discriminative Keys ===")
    print("types_order=" + ",".join(sorted_types))
    for entry in discriminators[:20]:
        ratios = ", ".join(f"{t}:{entry['ratios'][t]:.2f}" for t in sorted_types)
        print(f"{entry['key']} | var={entry['variance']:.4f} | {ratios}")

    out = {
        "payload_count": len(payloads),
        "type_counts": {type_key: len(by_type[type_key]) for type_key in sorted_types},
        "per_type_key_union_size": {
            type_key: len(key_union_by_type[type_key]) for type_key in sorted_types
        },
        "unique_keys_by_type": {
            type_key: sorted(unique_keys_by_type.get(type_key, [])) for type_key in sorted_types
        },
        "top_discriminators": discriminators[:50],
    }

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\njson_report={out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
