#!/usr/bin/env python3
"""Backfill Garmin list-derived enrichment into canonical metadata.json blobs.

This script updates metadata.json for existing Garmin workouts by joining:
- Workouts table rows (for ingestion_id/workout linkage)
- GarminActivityIndex rows (for raw list activity payloads)

For each matching workout, it extracts normalized Garmin source fields from the
activity-list payload and writes additive enrichment fields into
`metadata.json -> enrichment`.

Storage targets:
- runtime (default): Values.AzureWebJobsStorage (local Azurite/runtime connection)
- remote: ConnectionStrings.AzureWebJobsStorageRemote

Usage:
  PYTHONPATH="$PWD" .venv/bin/python scripts/backfill_garmin_metadata_enrichment.py
  PYTHONPATH="$PWD" .venv/bin/python scripts/backfill_garmin_metadata_enrichment.py --apply
  PYTHONPATH="$PWD" GARMIN_PROBE_STORAGE_MODE=remote \
    .venv/bin/python scripts/backfill_garmin_metadata_enrichment.py --athlete-id rob --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TrainingAnalyticsPlatform.integrations.garmin_activity_contract import GarminActivityContract  # noqa: E402
from TrainingAnalyticsPlatform.integrations.garmin_client import GarminConnectClient, GarminConnectError  # noqa: E402
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator  # noqa: E402

logger = logging.getLogger(__name__)

_ENRICHMENT_MAPPING: tuple[tuple[str, str], ...] = (
    ("source_activity_training_load", "garmin_activity_training_load"),
    ("source_aerobic_training_effect", "garmin_aerobic_training_effect"),
    ("source_anaerobic_training_effect", "garmin_anaerobic_training_effect"),
    ("source_training_effect_label", "garmin_training_effect_label"),
    (
        "source_aerobic_training_effect_message",
        "garmin_aerobic_training_effect_message",
    ),
    (
        "source_anaerobic_training_effect_message",
        "garmin_anaerobic_training_effect_message",
    ),
    ("source_vo2max_value", "garmin_vo2max_value"),
    ("source_avg_biking_cadence_rpm", "garmin_avg_biking_cadence_rpm"),
    ("source_max_biking_cadence_rpm", "garmin_max_biking_cadence_rpm"),
    ("source_avg_left_balance_pct", "garmin_avg_left_balance_pct"),
    ("source_avg_running_cadence_spm", "garmin_avg_running_cadence_spm"),
    ("source_max_running_cadence_spm", "garmin_max_running_cadence_spm"),
    ("source_avg_respiration_rate_brpm", "garmin_avg_respiration_rate_brpm"),
    ("source_max_respiration_rate_brpm", "garmin_max_respiration_rate_brpm"),
    ("source_min_respiration_rate_brpm", "garmin_min_respiration_rate_brpm"),
    ("source_max_temperature_c", "garmin_max_temperature_c"),
    ("source_min_temperature_c", "garmin_min_temperature_c"),
)


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


def _resolve_storage_connection_string(
    settings: dict[str, Any],
    *,
    requested_mode: Optional[str],
) -> tuple[Optional[str], str]:
    storage_mode = (
        (requested_mode or os.getenv("GARMIN_PROBE_STORAGE_MODE") or "runtime")
        .strip()
        .lower()
    )

    if storage_mode == "remote":
        connection_strings = settings.get("ConnectionStrings")
        if not isinstance(connection_strings, dict):
            raise ValueError(
                "remote mode requires local.settings.json ConnectionStrings"
            )
        remote_connection = connection_strings.get("AzureWebJobsStorageRemote")
        if not isinstance(remote_connection, str) or not remote_connection.strip():
            raise ValueError(
                "remote mode requires ConnectionStrings.AzureWebJobsStorageRemote"
            )
        return remote_connection, "remote"

    values = settings.get("Values")
    if isinstance(values, dict):
        runtime_connection = values.get("AzureWebJobsStorage")
        if isinstance(runtime_connection, str) and runtime_connection.strip():
            return runtime_connection, "runtime"

    return os.getenv("AzureWebJobsStorage"), "runtime"


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate if candidate else None


def _load_index_payload(
    *,
    storage: StorageCoordinator,
    athlete_id: str,
    activity_id: str,
) -> Optional[Dict[str, Any]]:
    table_client = storage.infrastructure.get_table_client("GarminActivityIndex")
    query_filter = "PartitionKey eq @pk and activity_id eq @activity_id"
    parameters = {"pk": athlete_id, "activity_id": activity_id}

    entities = list(
        table_client.query_entities(
            query_filter=query_filter,
            parameters=parameters,
            select=["raw_activity_payload_json"],
            top=1,
        )
    )
    if not entities:
        return None

    raw_payload = entities[0].get("raw_activity_payload_json")
    if not raw_payload:
        return None

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        logger.warning(
            "Skipping activity due to invalid index payload JSON",
            extra={"athlete_id": athlete_id, "activity_id": activity_id},
        )
        return None

    return payload if isinstance(payload, dict) else None


def _load_source_item_id_from_state(
    *,
    storage: StorageCoordinator,
    athlete_id: str,
    ingestion_id: str,
) -> Optional[str]:
    ingestion_state_table = storage.infrastructure.get_table_client("IngestionState")
    try:
        state_entity = ingestion_state_table.get_entity(
            partition_key=athlete_id,
            row_key=ingestion_id,
        )
    except (ResourceNotFoundError, HttpResponseError):
        return None

    return _string_or_none(state_entity.get("source_item_id"))


def _build_garmin_api_payload_map(
    *,
    storage: StorageCoordinator,
    athlete_id: str,
    lookback_days: int,
) -> Dict[str, Dict[str, Any]]:
    stored_token = storage.oauth_tokens.get_garmin_tokens(athlete_id)
    if not stored_token:
        logger.warning(
            "Garmin API fallback enabled but no stored token found",
            extra={"athlete_id": athlete_id},
        )
        return {}

    client = GarminConnectClient()
    try:
        client.authenticate(stored_token)
    except GarminConnectError as exc:
        logger.warning(
            "Garmin API fallback authentication failed: %s",
            exc,
            extra={"athlete_id": athlete_id},
        )
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))
    try:
        activities = client.list_activities(start_date=cutoff)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Garmin API fallback list_activities failed: %s",
            exc,
            extra={"athlete_id": athlete_id},
        )
        return {}

    payload_map: Dict[str, Dict[str, Any]] = {}
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        activity_id = _string_or_none(activity.get("activityId"))
        if not activity_id:
            continue
        payload_map[activity_id] = activity

    logger.info(
        "Garmin API fallback cache built athlete_id=%s lookback_days=%d activities=%d",
        athlete_id,
        lookback_days,
        len(payload_map),
    )
    return payload_map


def _resolve_activity_id_for_index(
    *,
    storage: StorageCoordinator,
    athlete_id: str,
    ingestion_id: str,
) -> tuple[Optional[str], bool]:
    """Resolve Garmin activity id used for index lookup.

    Primary key is ingestion_id (current Garmin contract).
    Fallback is IngestionState.source_item_id for historical rows where
    ingestion_id keying may differ from activity id.
    """
    if _load_index_payload(
        storage=storage,
        athlete_id=athlete_id,
        activity_id=ingestion_id,
    ) is not None:
        return ingestion_id, False

    ingestion_state_table = storage.infrastructure.get_table_client("IngestionState")
    try:
        state_entity = ingestion_state_table.get_entity(
            partition_key=athlete_id,
            row_key=ingestion_id,
        )
    except (ResourceNotFoundError, HttpResponseError):
        return None, False

    source_item_id = _string_or_none(state_entity.get("source_item_id"))
    if not source_item_id:
        return None, False

    if _load_index_payload(
        storage=storage,
        athlete_id=athlete_id,
        activity_id=source_item_id,
    ) is not None:
        return source_item_id, True

    return None, False


def _metadata_blob_candidates(entity: Dict[str, Any], ingestion_id: str) -> list[str]:
    candidates: list[str] = [f"{ingestion_id}/metadata.json"]

    workout_id = _string_or_none(entity.get("workout_id"))
    if workout_id:
        candidates.append(f"{workout_id}/metadata.json")

    canonical_records_blob = _string_or_none(entity.get("canonical_records_blob"))
    if canonical_records_blob and "/" in canonical_records_blob:
        prefix = canonical_records_blob.rsplit("/", 1)[0]
        if prefix:
            candidates.append(f"{prefix}/metadata.json")

    deduped: list[str] = []
    for name in candidates:
        if name not in deduped:
            deduped.append(name)
    return deduped


def _load_metadata_with_fallback(
    *,
    storage: StorageCoordinator,
    ingestion_id: str,
    entity: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    for blob_name in _metadata_blob_candidates(entity, ingestion_id):
        try:
            metadata = storage.infrastructure.load_json_blob(blob_name)
        except (ResourceNotFoundError, HttpResponseError, ValueError):
            continue
        if isinstance(metadata, dict):
            return metadata, blob_name
    return None, None


def _compute_enrichment_updates(activity_payload: Dict[str, Any]) -> Dict[str, Any]:
    contract = GarminActivityContract(activity_payload)
    source_metadata = contract.to_source_metadata_fields()

    updates: Dict[str, Any] = {}
    for source_key, enrichment_key in _ENRICHMENT_MAPPING:
        value = source_metadata.get(source_key)
        if value is not None:
            updates[enrichment_key] = value

    if updates:
        updates["garmin_enrichment_source"] = "activity_list"
        updates["garmin_enrichment_scope"] = "activity"

    return updates


def _merge_enrichment(metadata: Dict[str, Any], updates: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    enrichment_raw = metadata.get("enrichment")
    enrichment: Dict[str, Any] = dict(enrichment_raw) if isinstance(enrichment_raw, dict) else {}

    changed = False
    for key, value in updates.items():
        if enrichment.get(key) != value:
            enrichment[key] = value
            changed = True

    if changed:
        metadata["enrichment"] = enrichment

    return metadata, changed


@dataclass
class BackfillCounters:
    scanned: int = 0
    candidates: int = 0
    updated: int = 0
    skipped_missing_ingestion: int = 0
    skipped_missing_athlete: int = 0
    skipped_missing_index_payload: int = 0
    skipped_missing_metadata: int = 0
    skipped_no_enrichment_signal: int = 0
    skipped_unchanged: int = 0
    matched_via_source_item_id: int = 0
    updated_via_metadata_path_fallback: int = 0
    matched_via_garmin_api: int = 0
    index_seeded_from_garmin_api: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Garmin list-derived enrichment fields into metadata.json",
    )
    parser.add_argument("--apply", action="store_true", help="Persist changes (default dry-run)")
    parser.add_argument("--athlete-id", default=None, help="Optional athlete_id filter")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of metadata blobs to update",
    )
    parser.add_argument(
        "--connection-string",
        default=None,
        help="Optional explicit connection string override",
    )
    parser.add_argument(
        "--storage-mode",
        choices=("runtime", "remote"),
        default=None,
        help="Storage mode override (otherwise GARMIN_PROBE_STORAGE_MODE or runtime)",
    )
    parser.add_argument(
        "--garmin-api-fallback",
        action="store_true",
        help="Fallback to Garmin API list_activities for rows missing index payload",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=365,
        help="Garmin API fallback lookback window in days (default: 365)",
    )
    parser.add_argument(
        "--seed-index-from-api",
        action="store_true",
        help="When Garmin API fallback resolves missing payloads, upsert them into GarminActivityIndex",
    )
    return parser.parse_args()


def backfill_metadata_enrichment(
    *,
    apply: bool,
    athlete_id: Optional[str],
    limit: Optional[int],
    connection_string: Optional[str],
    storage_mode: Optional[str],
    garmin_api_fallback: bool,
    lookback_days: int,
    seed_index_from_api: bool,
) -> None:
    settings = _load_local_settings()
    resolved_connection = connection_string
    resolved_mode = "explicit" if connection_string else "runtime"

    if not resolved_connection:
        resolved_connection, resolved_mode = _resolve_storage_connection_string(
            settings,
            requested_mode=storage_mode,
        )

    storage = StorageCoordinator(connection_string=resolved_connection)
    workouts_table = storage.infrastructure.get_table_client("Workouts")

    query_filter = "PartitionKey ne ''"
    if athlete_id:
        query_filter = "athlete_id eq @athlete_id"
        entities = workouts_table.query_entities(
            query_filter=query_filter,
            parameters={"athlete_id": athlete_id},
        )
    else:
        entities = workouts_table.query_entities(query_filter=query_filter)

    counters = BackfillCounters()
    garmin_api_payload_map: Dict[str, Dict[str, Any]] = {}
    if garmin_api_fallback:
        if athlete_id:
            garmin_api_payload_map = _build_garmin_api_payload_map(
                storage=storage,
                athlete_id=athlete_id,
                lookback_days=lookback_days,
            )
        else:
            logger.warning(
                "Garmin API fallback requires --athlete-id for token scoping; disabling fallback for this run"
            )

    logger.info(
        "Starting Garmin metadata enrichment backfill apply=%s storage_mode=%s athlete_id=%s limit=%s",
        apply,
        resolved_mode,
        athlete_id,
        limit,
    )

    for entity in entities:
        counters.scanned += 1

        entity_athlete_id = _string_or_none(entity.get("athlete_id"))
        if not entity_athlete_id:
            counters.skipped_missing_athlete += 1
            continue

        ingestion_id = _string_or_none(entity.get("ingestion_id"))
        if not ingestion_id:
            counters.skipped_missing_ingestion += 1
            continue

        counters.candidates += 1

        resolved_activity_id, used_source_item_fallback = _resolve_activity_id_for_index(
            storage=storage,
            athlete_id=entity_athlete_id,
            ingestion_id=ingestion_id,
        )
        source_item_id = _load_source_item_id_from_state(
            storage=storage,
            athlete_id=entity_athlete_id,
            ingestion_id=ingestion_id,
        )
        if used_source_item_fallback:
            counters.matched_via_source_item_id += 1

        payload = None
        if resolved_activity_id:
            payload = _load_index_payload(
                storage=storage,
                athlete_id=entity_athlete_id,
                activity_id=resolved_activity_id,
            )
        if payload is None and garmin_api_payload_map:
            for candidate_activity_id in (
                resolved_activity_id,
                source_item_id,
                ingestion_id,
            ):
                if not candidate_activity_id:
                    continue
                payload = garmin_api_payload_map.get(candidate_activity_id)
                if payload is not None:
                    counters.matched_via_garmin_api += 1
                    resolved_activity_id = candidate_activity_id
                    if seed_index_from_api and apply:
                        try:
                            storage.garmin_activity_index.upsert_activity_payload(
                                athlete_id=entity_athlete_id,
                                activity_payload=payload,
                            )
                            counters.index_seeded_from_garmin_api += 1
                        except Exception as exc:  # pylint: disable=broad-exception-caught
                            logger.warning(
                                "Failed seeding GarminActivityIndex from API fallback: %s",
                                exc,
                                extra={
                                    "athlete_id": entity_athlete_id,
                                    "ingestion_id": ingestion_id,
                                    "activity_id": candidate_activity_id,
                                },
                            )
                    break
        if payload is None:
            counters.skipped_missing_index_payload += 1
            continue

        updates = _compute_enrichment_updates(payload)
        if not updates:
            counters.skipped_no_enrichment_signal += 1
            continue

        metadata, metadata_blob_name = _load_metadata_with_fallback(
            storage=storage,
            ingestion_id=ingestion_id,
            entity=entity,
        )
        if metadata is None or metadata_blob_name is None:
            counters.skipped_missing_metadata += 1
            continue

        merged_metadata, changed = _merge_enrichment(metadata, updates)
        if not changed:
            counters.skipped_unchanged += 1
            continue

        if apply:
            storage.infrastructure.upload_json_blob(metadata_blob_name, merged_metadata)

        counters.updated += 1
        if metadata_blob_name != f"{ingestion_id}/metadata.json":
            counters.updated_via_metadata_path_fallback += 1
        logger.info(
            "%s athlete_id=%s ingestion_id=%s activity_id=%s metadata_blob=%s updated_fields=%s",
            "APPLY" if apply else "DRY-RUN",
            entity_athlete_id,
            ingestion_id,
            resolved_activity_id,
            metadata_blob_name,
            sorted(updates.keys()),
        )

        if limit is not None and counters.updated >= limit:
            logger.info("Reached update limit=%d", limit)
            break

    logger.info(
        "Backfill complete apply=%s scanned=%d candidates=%d updated=%d "
        "skipped_missing_ingestion=%d skipped_missing_athlete=%d "
        "skipped_missing_index_payload=%d skipped_missing_metadata=%d "
        "skipped_no_enrichment_signal=%d skipped_unchanged=%d "
        "matched_via_source_item_id=%d matched_via_garmin_api=%d "
        "index_seeded_from_garmin_api=%d updated_via_metadata_path_fallback=%d",
        apply,
        counters.scanned,
        counters.candidates,
        counters.updated,
        counters.skipped_missing_ingestion,
        counters.skipped_missing_athlete,
        counters.skipped_missing_index_payload,
        counters.skipped_missing_metadata,
        counters.skipped_no_enrichment_signal,
        counters.skipped_unchanged,
        counters.matched_via_source_item_id,
        counters.matched_via_garmin_api,
        counters.index_seeded_from_garmin_api,
        counters.updated_via_metadata_path_fallback,
    )


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
        logging.WARNING
    )

    try:
        backfill_metadata_enrichment(
            apply=args.apply,
            athlete_id=args.athlete_id,
            limit=args.limit,
            connection_string=args.connection_string,
            storage_mode=args.storage_mode,
            garmin_api_fallback=args.garmin_api_fallback,
            lookback_days=args.lookback_days,
            seed_index_from_api=args.seed_index_from_api,
        )
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
