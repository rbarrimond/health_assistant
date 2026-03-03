"""Backfill missing Apple device_model in Workouts and metadata.json.

Usage:
  python scripts/backfill_device_model.py                 # dry run
  python scripts/backfill_device_model.py --apply         # apply changes
  python scripts/backfill_device_model.py --athlete-id rob --apply
"""

import argparse
import logging
import os
import re
import sys
from typing import Any, Dict, Optional

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.data.tables import UpdateMode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.ingestion.code_mappings import get_apple_watch_model
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

WATCH_ID_PATTERN = re.compile(r"^Watch\s*\d+,\d+$", re.IGNORECASE)


def _is_missing(value: Optional[str]) -> bool:
    return value is None or not str(value).strip()


def _normalize_watch_identifier(value: str) -> str:
    return re.sub(r"^Watch\s+", "Watch", value.strip(), flags=re.IGNORECASE)


def _resolve_apple_model_from_metadata(metadata: Dict[str, Any]) -> Optional[str]:
    identity = metadata.get("identity") if isinstance(metadata, dict) else None
    if isinstance(identity, dict):
        identity_model = identity.get("device_model")
        if isinstance(identity_model, str) and identity_model.strip():
            return identity_model.strip()

    file_metadata = metadata.get("file_metadata") if isinstance(metadata, dict) else None
    if not isinstance(file_metadata, dict):
        return None

    file_product = file_metadata.get("file_product")
    if not isinstance(file_product, str) or not file_product.strip():
        return None

    product = file_product.strip()
    if WATCH_ID_PATTERN.match(product):
        normalized = _normalize_watch_identifier(product)
        mapped = get_apple_watch_model(normalized)
        return mapped.strip() if mapped and mapped.strip() else normalized

    return product


def _should_process_entity(entity: Dict[str, Any], athlete_id: Optional[str]) -> bool:
    if athlete_id and entity.get("athlete_id") != athlete_id:
        return False

    manufacturer = entity.get("device_manufacturer")
    if not isinstance(manufacturer, str) or manufacturer.strip().lower() != "apple":
        return False

    return _is_missing(entity.get("device_model"))


def _metadata_blob_candidates(entity: Dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    workout_id = entity.get("workout_id")
    if isinstance(workout_id, str) and workout_id:
        candidates.append(f"{workout_id}/metadata.json")

    canonical_records_blob = entity.get("canonical_records_blob")
    if isinstance(canonical_records_blob, str) and canonical_records_blob:
        prefix = canonical_records_blob.rsplit("/", 1)[0]
        if prefix:
            candidates.append(f"{prefix}/metadata.json")

    # preserve order and deduplicate
    return list(dict.fromkeys(candidates))


def _load_metadata_with_fallback(
    *,
    entity: Dict[str, Any],
    storage: StorageCoordinator,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    for blob_name in _metadata_blob_candidates(entity):
        try:
            metadata = storage.infrastructure.load_json_blob(blob_name)
            if isinstance(metadata, dict):
                return metadata, blob_name
        except (ResourceNotFoundError, HttpResponseError, ValueError):
            continue
    return None, None


def _backfill_single_entity(
    *,
    entity: Dict[str, Any],
    storage: StorageCoordinator,
    workouts_table: Any,
    apply: bool,
) -> tuple[str, bool]:
    workout_id = entity.get("workout_id")
    if not isinstance(workout_id, str) or not workout_id:
        return "no_metadata", False

    metadata, metadata_blob_name = _load_metadata_with_fallback(
        entity=entity,
        storage=storage,
    )
    if metadata is None or metadata_blob_name is None:
        logger.warning(
            "Skipping %s: unable to load metadata.json from candidate paths %s",
            workout_id,
            _metadata_blob_candidates(entity),
        )
        return "no_metadata", False

    resolved_model = _resolve_apple_model_from_metadata(metadata)
    if _is_missing(resolved_model):
        logger.warning("Skipping %s: could not derive device_model from metadata", workout_id)
        return "no_model", False

    resolved_model = str(resolved_model).strip()
    metadata_updated = False

    identity = metadata.get("identity") if isinstance(metadata, dict) else None
    if isinstance(identity, dict) and _is_missing(identity.get("device_model")):
        identity["device_model"] = resolved_model
        metadata_updated = True

    if apply:
        row_update = {
            "PartitionKey": entity["PartitionKey"],
            "RowKey": entity["RowKey"],
            "device_model": resolved_model,
        }
        workouts_table.upsert_entity(row_update, mode=UpdateMode.MERGE)
        if metadata_updated:
            storage.infrastructure.upload_json_blob(metadata_blob_name, metadata)

    logger.info(
            "%s workout_id=%s device_model=%s metadata_updated=%s metadata_blob=%s",
        "APPLY" if apply else "DRY-RUN",
        workout_id,
        resolved_model,
        metadata_updated,
            metadata_blob_name,
    )
    return "updated", metadata_updated


def backfill_device_model(
    *,
    apply: bool,
    athlete_id: Optional[str],
    limit: Optional[int],
    connection_string: Optional[str],
) -> None:
    """Backfill missing Apple device models from metadata blobs."""
    storage = StorageCoordinator(connection_string=connection_string)
    workouts_table = storage.infrastructure.get_table_client("Workouts")

    scanned = 0
    candidates = 0
    updated_workouts = 0
    updated_metadata = 0
    skipped_no_model = 0
    skipped_no_metadata = 0

    entities = workouts_table.query_entities(query_filter="PartitionKey ne ''")

    for entity in entities:
        scanned += 1

        if not _should_process_entity(entity, athlete_id):
            continue

        candidates += 1
        if limit is not None and updated_workouts >= limit:
            break

        status, metadata_was_updated = _backfill_single_entity(
            entity=entity,
            storage=storage,
            workouts_table=workouts_table,
            apply=apply,
        )

        if status == "updated":
            updated_workouts += 1
            if metadata_was_updated:
                updated_metadata += 1
        elif status == "no_model":
            skipped_no_model += 1
        else:
            skipped_no_metadata += 1

    logger.info(
        "Backfill complete apply=%s scanned=%d candidates=%d updated_workouts=%d "
        "updated_metadata=%d skipped_no_model=%d skipped_no_metadata=%d",
        apply,
        scanned,
        candidates,
        updated_workouts,
        updated_metadata,
        skipped_no_model,
        skipped_no_metadata,
    )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Backfill missing Apple device_model in Workouts and metadata.json",
    )
    parser.add_argument("--apply", action="store_true", help="Persist changes (default is dry-run)")
    parser.add_argument("--athlete-id", type=str, default=None, help="Optional athlete_id filter")
    parser.add_argument("--limit", type=int, default=None, help="Optional max records to update")
    parser.add_argument(
        "--connection-string",
        type=str,
        default=None,
        help="Optional Azure Storage connection string override",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
        logging.WARNING
    )
    backfill_device_model(
        apply=args.apply,
        athlete_id=args.athlete_id,
        limit=args.limit,
        connection_string=args.connection_string,
    )


if __name__ == "__main__":
    main()
