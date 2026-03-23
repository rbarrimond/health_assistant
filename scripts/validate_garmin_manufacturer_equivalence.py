#!/usr/bin/env python3
"""Validate Garmin list manufacturer codes against ingested FIT manufacturer codes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TrainingAnalyticsPlatform.integrations.garmin_activity_contract import GarminActivityContract  # noqa: E402
from TrainingAnalyticsPlatform.ingestion.code_mappings import normalize_manufacturer_to_code  # noqa: E402
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Garmin activity-list manufacturer values to ingested FIT manufacturer codes"
    )
    parser.add_argument("--athlete-id", default=os.getenv("ATHLETE_ID") or "rob")
    parser.add_argument("--lookback-days", type=int, default=120)
    parser.add_argument(
        "--connection-string",
        default=os.getenv("AZURE_STORAGE_CONNECTION_STRING") or "UseDevelopmentStorage=true",
    )
    parser.add_argument("--json-out", default="/tmp/garmin_manufacturer_equivalence.json")
    parser.add_argument("--sample-limit", type=int, default=25)
    return parser.parse_args()


def extract_fit_manufacturer(metadata: dict[str, Any]) -> tuple[int | None, str | None]:
    file_metadata = metadata.get("file_metadata")
    if isinstance(file_metadata, dict):
        code = file_metadata.get("file_manufacturer_code")
        raw_name = file_metadata.get("file_manufacturer_raw") or file_metadata.get("file_manufacturer")
        return code if isinstance(code, int) else normalize_manufacturer_to_code(code), raw_name if isinstance(raw_name, str) else None

    code = metadata.get("file_manufacturer_code")
    raw_name = metadata.get("file_manufacturer_raw") or metadata.get("file_manufacturer")
    return code if isinstance(code, int) else normalize_manufacturer_to_code(code), raw_name if isinstance(raw_name, str) else None


def extract_workout_table_manufacturer(
    storage: StorageCoordinator,
    athlete_id: str,
    workout_id: str,
) -> tuple[int | None, str | None]:
    table_client = storage.infrastructure.get_table_client("Workouts")
    entities = list(
        table_client.query_entities(
            query_filter=f"athlete_id eq '{athlete_id}' and workout_id eq '{workout_id}'"
        )
    )
    if not entities:
        return None, None

    raw_name = entities[0].get("device_manufacturer")
    return normalize_manufacturer_to_code(raw_name), raw_name if isinstance(raw_name, str) else None


def main() -> int:
    args = parse_args()
    storage = StorageCoordinator(connection_string=str(args.connection_string))
    payloads = storage.garmin_activity_index.query_activity_payloads_by_lookback(
        athlete_id=str(args.athlete_id),
        lookback_days=max(1, int(args.lookback_days)),
    )

    matched = 0
    mismatched = 0
    missing_ingestion_state = 0
    missing_cached_code = 0
    missing_fit_code = 0
    skipped_not_ingested = 0
    samples: list[dict[str, Any]] = []

    for payload in payloads:
        contract = GarminActivityContract(payload)
        activity_id = contract.activity_id
        if not activity_id:
            continue

        source_metadata = contract.to_source_metadata_fields()
        cached_raw = source_metadata.get("source_manufacturer")
        cached_code = source_metadata.get("source_manufacturer_code")
        if cached_code is None:
            cached_code = normalize_manufacturer_to_code(cached_raw)

        if cached_code is None:
            missing_cached_code += 1
            if len(samples) < args.sample_limit:
                samples.append(
                    {
                        "activity_id": activity_id,
                        "status": "missing_cached_code",
                        "cached_manufacturer": cached_raw,
                    }
                )
            continue

        ingestion_state = storage.workouts.get_ingestion_state(str(args.athlete_id), activity_id)
        if not ingestion_state:
            missing_ingestion_state += 1
            continue
        if ingestion_state.get("status") != "ingested":
            skipped_not_ingested += 1
            continue

        ingestion_id = ingestion_state.get("ingestion_id")
        if not isinstance(ingestion_id, str) or not ingestion_id:
            missing_fit_code += 1
            continue

        metadata = storage.workouts.load_metadata_json(ingestion_id)
        fit_code, fit_raw = extract_fit_manufacturer(metadata)
        if fit_code is None:
            workout_id = ingestion_state.get("workout_id")
            if isinstance(workout_id, str) and workout_id:
                fit_code, fit_raw = extract_workout_table_manufacturer(
                    storage,
                    str(args.athlete_id),
                    workout_id,
                )
        if fit_code is None:
            missing_fit_code += 1
            if len(samples) < args.sample_limit:
                samples.append(
                    {
                        "activity_id": activity_id,
                        "status": "missing_fit_code",
                        "cached_manufacturer": cached_raw,
                        "cached_code": cached_code,
                    }
                )
            continue

        if cached_code == fit_code:
            matched += 1
            continue

        mismatched += 1
        if len(samples) < args.sample_limit:
            samples.append(
                {
                    "activity_id": activity_id,
                    "status": "mismatch",
                    "cached_manufacturer": cached_raw,
                    "cached_code": cached_code,
                    "fit_manufacturer_raw": fit_raw,
                    "fit_code": fit_code,
                    "activity_name": source_metadata.get("source_activity_name"),
                    "device_id": source_metadata.get("source_device_id"),
                }
            )

    compared = matched + mismatched
    report = {
        "athlete_id": str(args.athlete_id),
        "lookback_days": max(1, int(args.lookback_days)),
        "payload_count": len(payloads),
        "compared": compared,
        "matched": matched,
        "mismatched": mismatched,
        "match_rate": (matched / compared) if compared else None,
        "missing_ingestion_state": missing_ingestion_state,
        "skipped_not_ingested": skipped_not_ingested,
        "missing_cached_code": missing_cached_code,
        "missing_fit_code": missing_fit_code,
        "samples": samples,
    }

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"payload_count={report['payload_count']}")
    print(f"compared={compared}")
    print(f"matched={matched}")
    print(f"mismatched={mismatched}")
    print(f"missing_ingestion_state={missing_ingestion_state}")
    print(f"skipped_not_ingested={skipped_not_ingested}")
    print(f"missing_cached_code={missing_cached_code}")
    print(f"missing_fit_code={missing_fit_code}")
    if report["match_rate"] is not None:
        print(f"match_rate={report['match_rate']:.4f}")
    print(f"json_report={out_path}")

    return 0 if mismatched == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
