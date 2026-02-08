"""Backfill IngestionState with ingestion metadata from Workouts."""

import argparse
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from azure.core.exceptions import HttpResponseError

from FitParser.table_storage import INGEST_VERSION, WorkoutTableStorage

UTC_SUFFIX = "+00:00"

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace(UTC_SUFFIX, "Z")


def _build_ingestion_key(entity: Dict) -> Optional[str]:
    return entity.get("source_item_id") or entity.get("file_sha256") or entity.get("workout_id")


def _merge_ingestion_state(
    existing: Optional[Dict],
    workout_entity: Dict,
    ingestion_key: str,
    athlete_id: str,
) -> Dict:
    ingested_at = workout_entity.get("ingested_at_utc") or _utc_now()
    ingest_version = workout_entity.get("ingest_version") or INGEST_VERSION

    if existing:
        merged = dict(existing)
        merged.setdefault("PartitionKey", athlete_id)
        merged.setdefault("RowKey", ingestion_key)
        merged.setdefault("status", "ingested")
        merged.setdefault("first_seen_at_utc", ingested_at)
        merged.setdefault("last_attempt_at_utc", ingested_at)
        merged.setdefault("retry_count", 0)
        merged.setdefault("workout_id", workout_entity.get("workout_id"))
        merged.setdefault("source_file_name", workout_entity.get("source_file_name"))
        merged.setdefault("source_drive_id", workout_entity.get("source_drive_id"))
        merged.setdefault("source_etag", workout_entity.get("source_etag"))
        merged.setdefault("source_ctag", workout_entity.get("source_ctag"))
        merged.setdefault("source_quickxor_hash", workout_entity.get("source_quickxor_hash"))
        merged.setdefault("source_modified_at_utc", workout_entity.get("source_modified_at_utc"))
        merged.setdefault("file_sha256", workout_entity.get("file_sha256"))
        merged.setdefault("ingest_version", ingest_version)
        merged.setdefault("ingested_at_utc", ingested_at)
        return merged

    return {
        "PartitionKey": athlete_id,
        "RowKey": ingestion_key,
        "status": "ingested",
        "first_seen_at_utc": ingested_at,
        "last_attempt_at_utc": ingested_at,
        "retry_count": 0,
        "workout_id": workout_entity.get("workout_id"),
        "source_file_name": workout_entity.get("source_file_name"),
        "source_drive_id": workout_entity.get("source_drive_id"),
        "source_etag": workout_entity.get("source_etag"),
        "source_ctag": workout_entity.get("source_ctag"),
        "source_quickxor_hash": workout_entity.get("source_quickxor_hash"),
        "source_modified_at_utc": workout_entity.get("source_modified_at_utc"),
        "file_sha256": workout_entity.get("file_sha256"),
        "ingest_version": ingest_version,
        "ingested_at_utc": ingested_at,
    }


def backfill_ingestion_state(apply: bool) -> None:
    """Backfill IngestionState from Workouts table."""
    storage = WorkoutTableStorage()
    workouts_table = storage._get_table_client("Workouts")  # pylint: disable=protected-access
    ingestion_table = storage._get_table_client("IngestionState")  # pylint: disable=protected-access

    updated = 0
    skipped = 0

    try:
        entities = workouts_table.query_entities(query_filter="PartitionKey ne ''")
        for entity in entities:
            athlete_id = entity.get("athlete_id")
            workout_id = entity.get("workout_id")
            ingestion_key = _build_ingestion_key(entity)

            if not athlete_id or not workout_id or not ingestion_key:
                skipped += 1
                continue

            existing = storage.get_ingestion_state(athlete_id, ingestion_key)
            merged = _merge_ingestion_state(existing, entity, ingestion_key, athlete_id)

            if apply:
                ingestion_table.upsert_entity(merged)
            updated += 1

        logger.info("Backfill complete. updated=%d skipped=%d apply=%s", updated, skipped, apply)
    except HttpResponseError as exc:
        logger.error("Backfill failed: %s", exc)
        raise


def main() -> None:
    """Main entry point for backfill script."""
    parser = argparse.ArgumentParser(description="Backfill IngestionState from Workouts.")
    parser.add_argument("--apply", action="store_true", help="Apply changes to storage")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    backfill_ingestion_state(args.apply)


if __name__ == "__main__":
    main()
