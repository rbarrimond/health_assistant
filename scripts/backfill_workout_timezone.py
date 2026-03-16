"""Backfill workout timezone fields in Workouts and metadata.json.

Usage:
  python scripts/backfill_workout_timezone.py                  # dry run
  python scripts/backfill_workout_timezone.py --apply          # apply changes
  python scripts/backfill_workout_timezone.py --athlete-id rob --apply
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.data.tables import UpdateMode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer
from TrainingAnalyticsPlatform.ingestion.timezone_utils import (
    is_zwift_cloud_workout,
    resolve_canonical_timezone,
)
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)


def _is_present(value: Optional[str]) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_utc_offset_string(value: Optional[str]) -> bool:
    if not _is_present(value):
        return False

    normalized = str(value).strip().upper()
    return normalized == "UTC" or normalized.startswith(("UTC+", "UTC-"))


def _to_lower(value: Any) -> Optional[str]:
    """Normalize enum-like values to lowercase strings."""
    if value is None:
        return None

    name = getattr(value, "name", None)
    if name is not None:
        return str(name).lower()
    return str(value).lower()


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

    return list(dict.fromkeys(candidates))


def _load_metadata_with_fallback(
    *,
    entity: Dict[str, Any],
    storage: StorageCoordinator,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    for blob_name in _metadata_blob_candidates(entity):
        try:
            metadata = storage.infrastructure.load_json_blob(blob_name)
            if isinstance(metadata, dict):
                return metadata, blob_name
        except (ResourceNotFoundError, HttpResponseError, ValueError):
            continue
    return None, None


def _parse_iso8601_utc(raw_timestamp: Optional[str]) -> Optional[datetime]:
    if not _is_present(raw_timestamp):
        return None

    candidate = str(raw_timestamp).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    return parsed


def _resolve_expected_timezone(
    *,
    current_timezone: Optional[str],
    local_tz_offset: Optional[str],
    start_time_utc: Optional[str],
    athlete_timezone: Optional[str],
    is_zwift_workout: bool,
) -> Optional[str]:
    explicit_timezone = (
        str(current_timezone).strip()
        if _is_present(current_timezone) and not _is_utc_offset_string(current_timezone)
        else None
    )
    offset_from_current_timezone = None
    if _is_present(current_timezone) and _is_utc_offset_string(current_timezone):
        offset_from_current_timezone = str(current_timezone).strip()

    session_offset = (
        str(local_tz_offset).strip()
        if _is_present(local_tz_offset)
        else offset_from_current_timezone
    )

    _, timezone_value = resolve_canonical_timezone(
        explicit_timezone=explicit_timezone,
        fallback_offsets=(session_offset,) if session_offset else (),
        start_time_utc=_parse_iso8601_utc(start_time_utc),
        athlete_timezone=(
            str(athlete_timezone).strip() if _is_present(athlete_timezone) else None
        ),
        is_zwift_workout=is_zwift_workout,
    )
    return timezone_value


def _resolve_athlete_timezone(semantic_layer: SemanticLayer, athlete_id: Optional[str]) -> Optional[str]:
    if not _is_present(athlete_id):
        return None

    try:
        return semantic_layer._resolve_athlete_home_timezone(str(athlete_id))  # pylint: disable=protected-access
    except (HttpResponseError, ValueError, TypeError, AttributeError):
        return None


def _should_process_entity(entity: Dict[str, Any], athlete_id: Optional[str]) -> bool:
    if athlete_id and entity.get("athlete_id") != athlete_id:
        return False

    workout_id = entity.get("workout_id")
    if not _is_present(workout_id):
        return False

    return True


def _extract_start_time_utc(metadata: Dict[str, Any], entity: Dict[str, Any]) -> Optional[str]:
    """Extract authoritative UTC start timestamp from metadata/entity."""
    identity_raw = metadata.get("identity")
    identity = identity_raw if isinstance(identity_raw, dict) else {}
    start_time = identity.get("start_time_utc") or entity.get("start_time_utc")
    return str(start_time).strip() if _is_present(start_time) else None


def _is_zwift_workout(
    *,
    metadata: Dict[str, Any],
    entity: Dict[str, Any],
) -> bool:
    """Detect Zwift workouts that should use athlete home timezone.

    Aligns historical backfill behavior with ingestion-time Zwift handling:
    indoor/virtual UTC workouts from Zwift should map to athlete home timezone.
    """
    identity_raw = metadata.get("identity")
    identity: Dict[str, Any] = identity_raw if isinstance(identity_raw, dict) else {}
    file_metadata_raw = metadata.get("file_metadata")
    file_metadata: Dict[str, Any] = (
        file_metadata_raw if isinstance(file_metadata_raw, dict) else {}
    )

    device_manufacturer = (
        _to_lower(identity.get("device_manufacturer"))
        or _to_lower(entity.get("device_manufacturer"))
        or _to_lower(file_metadata.get("file_manufacturer"))
    )
    return is_zwift_cloud_workout(device_manufacturer=device_manufacturer)


def _compute_update_state(
    *,
    entity: Dict[str, Any],
    metadata: Dict[str, Any],
    athlete_timezone: Optional[str],
) -> Tuple[Optional[str], bool, bool, Dict[str, Any]]:
    """Compute expected timezone and required update flags."""
    activity_raw = metadata.get("activity_metadata")
    activity_metadata: Dict[str, Any]
    if isinstance(activity_raw, dict):
        activity_metadata = activity_raw
    else:
        activity_metadata = {}
        metadata["activity_metadata"] = activity_metadata

    current_timezone_raw = activity_metadata.get("timezone") or entity.get("timezone")
    local_offset_raw = activity_metadata.get("local_tz_offset") or entity.get("local_tz_offset")
    local_tz_offset = str(local_offset_raw).strip() if _is_present(local_offset_raw) else None
    is_zwift_workout = _is_zwift_workout(
        metadata=metadata,
        entity=entity,
    )
    start_time_utc = _extract_start_time_utc(metadata, entity)

    expected_timezone = _resolve_expected_timezone(
        current_timezone=str(current_timezone_raw).strip() if _is_present(current_timezone_raw) else None,
        local_tz_offset=local_tz_offset,
        start_time_utc=start_time_utc,
        athlete_timezone=athlete_timezone,
        is_zwift_workout=is_zwift_workout,
    )

    if not _is_present(expected_timezone):
        return None, False, False, activity_metadata

    expected = str(expected_timezone).strip()
    metadata_needs_update = activity_metadata.get("timezone") != expected
    row_needs_update = entity.get("timezone") != expected
    return expected, row_needs_update, metadata_needs_update, activity_metadata


def _apply_single_entity_updates(
    *,
    entity: Dict[str, Any],
    workouts_table: Any,
    storage: Any,
    metadata_blob_name: str,
    metadata: Dict[str, Any],
    expected_timezone: str,
    row_needs_update: bool,
    metadata_needs_update: bool,
) -> None:
    """Persist row/blob updates for one workout when apply mode is enabled."""
    if row_needs_update:
        row_update = {
            "PartitionKey": entity["PartitionKey"],
            "RowKey": entity["RowKey"],
            "timezone": expected_timezone,
        }
        workouts_table.upsert_entity(row_update, mode=UpdateMode.MERGE)

    if metadata_needs_update:
        storage.infrastructure.upload_json_blob(metadata_blob_name, metadata)


@dataclass
class BackfillCounters:
    """Counter bucket for timezone backfill execution."""

    scanned: int = 0
    candidates: int = 0
    updated: int = 0
    updated_rows: int = 0
    updated_metadata: int = 0
    skipped_no_metadata: int = 0
    skipped_no_signal: int = 0
    skipped_unchanged: int = 0


def _record_backfill_result(
    *,
    counters: BackfillCounters,
    status: str,
    row_was_updated: bool,
    metadata_was_updated: bool,
) -> None:
    """Apply one entity processing result to aggregate counters."""
    if status == "updated":
        counters.updated += 1
        if row_was_updated:
            counters.updated_rows += 1
        if metadata_was_updated:
            counters.updated_metadata += 1
    elif status == "no_metadata":
        counters.skipped_no_metadata += 1
    elif status == "no_signal":
        counters.skipped_no_signal += 1
    elif status == "unchanged":
        counters.skipped_unchanged += 1


def _backfill_single_entity(
    *,
    entity: Dict[str, Any],
    storage: Any,
    workouts_table: Any,
    apply: bool,
    athlete_timezone: Optional[str],
) -> Tuple[str, bool, bool]:
    workout_id = str(entity.get("workout_id"))
    metadata, metadata_blob_name = _load_metadata_with_fallback(entity=entity, storage=storage)
    if metadata is None or metadata_blob_name is None:
        logger.warning(
            "Skipping %s: unable to load metadata.json from candidate paths %s",
            workout_id,
            _metadata_blob_candidates(entity),
        )
        return "no_metadata", False, False

    expected_timezone, row_needs_update, metadata_needs_update, activity_metadata = _compute_update_state(
        entity=entity,
        metadata=metadata,
        athlete_timezone=athlete_timezone,
    )

    if not _is_present(expected_timezone):
        logger.info("Skipping %s: no timezone/offset signal available", workout_id)
        return "no_signal", False, False

    expected_timezone = str(expected_timezone).strip()

    if not metadata_needs_update and not row_needs_update:
        logger.debug("Skipping %s: timezone already up to date (%s)", workout_id, expected_timezone)
        return "unchanged", False, False

    if metadata_needs_update:
        activity_metadata["timezone"] = expected_timezone

    if apply:
        _apply_single_entity_updates(
            entity=entity,
            workouts_table=workouts_table,
            storage=storage,
            metadata_blob_name=metadata_blob_name,
            metadata=metadata,
            expected_timezone=expected_timezone,
            row_needs_update=row_needs_update,
            metadata_needs_update=metadata_needs_update,
        )

    logger.info(
        "%s workout_id=%s timezone=%s row_updated=%s metadata_updated=%s metadata_blob=%s",
        "APPLY" if apply else "DRY-RUN",
        workout_id,
        expected_timezone,
        row_needs_update,
        metadata_needs_update,
        metadata_blob_name,
    )
    return "updated", row_needs_update, metadata_needs_update


def backfill_workout_timezone(
    *,
    apply: bool,
    athlete_id: Optional[str],
    limit: Optional[int],
    connection_string: Optional[str],
) -> None:
    """Backfill workout timezone in Workouts rows and metadata blobs."""
    storage = StorageCoordinator(connection_string=connection_string)
    semantic_layer = SemanticLayer(storage)
    workouts_table = storage.infrastructure.get_table_client("Workouts")

    counters = BackfillCounters()

    athlete_timezone_cache: Dict[str, Optional[str]] = {}

    entities = workouts_table.query_entities(query_filter="PartitionKey ne ''")

    for entity in entities:
        counters.scanned += 1
        if not _should_process_entity(entity, athlete_id):
            continue

        counters.candidates += 1
        if limit is not None and counters.updated >= limit:
            break

        entity_athlete_id = entity.get("athlete_id")
        athlete_key = str(entity_athlete_id) if _is_present(entity_athlete_id) else ""
        if athlete_key not in athlete_timezone_cache:
            athlete_timezone_cache[athlete_key] = _resolve_athlete_timezone(
                semantic_layer,
                athlete_key if athlete_key else None,
            )

        status, row_was_updated, metadata_was_updated = _backfill_single_entity(
            entity=entity,
            storage=storage,
            workouts_table=workouts_table,
            apply=apply,
            athlete_timezone=athlete_timezone_cache.get(athlete_key),
        )
        _record_backfill_result(
            counters=counters,
            status=status,
            row_was_updated=row_was_updated,
            metadata_was_updated=metadata_was_updated,
        )

    logger.info(
        "Backfill complete apply=%s scanned=%d candidates=%d updated=%d "
        "updated_rows=%d updated_metadata=%d skipped_no_metadata=%d "
        "skipped_no_signal=%d skipped_unchanged=%d",
        apply,
        counters.scanned,
        counters.candidates,
        counters.updated,
        counters.updated_rows,
        counters.updated_metadata,
        counters.skipped_no_metadata,
        counters.skipped_no_signal,
        counters.skipped_unchanged,
    )


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Backfill workout timezone in Workouts and metadata.json",
    )
    parser.add_argument("--apply", action="store_true", help="Persist changes (default is dry-run)")
    parser.add_argument("--athlete-id", type=str, default=None, help="Optional athlete_id filter")
    parser.add_argument("--limit", type=int, default=None, help="Optional max updates")
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

    backfill_workout_timezone(
        apply=args.apply,
        athlete_id=args.athlete_id,
        limit=args.limit,
        connection_string=args.connection_string,
    )


if __name__ == "__main__":
    main()
