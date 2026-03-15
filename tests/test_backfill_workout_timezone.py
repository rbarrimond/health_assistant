"""Unit tests for workout timezone backfill script."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import backfill_workout_timezone as module  # pylint: disable=wrong-import-position


def _sample_entity() -> dict:
    return {
        "PartitionKey": "rob|2026-01",
        "RowKey": "w-1",
        "athlete_id": "rob",
        "workout_id": "w-1",
        "start_time_utc": "2026-01-15T12:00:00+00:00",
        "local_tz_offset": "UTC-05:00",
        "timezone": "UTC-05:00",
    }


def _sample_metadata() -> dict:
    return {
        "identity": {"start_time_utc": "2026-01-15T12:00:00+00:00"},
        "activity_metadata": {"local_tz_offset": "UTC-05:00"},
    }


def test_resolve_expected_timezone_keeps_existing_timezone() -> None:
    resolved = module._resolve_expected_timezone(
        current_timezone="America/New_York",
        local_tz_offset="UTC-05:00",
        start_time_utc="2026-01-15T12:00:00+00:00",
        athlete_timezone="America/New_York",
        is_zwift_workout=False,
    )

    assert resolved == "America/New_York"


def test_resolve_expected_timezone_falls_back_to_offset_without_athlete_hint() -> None:
    resolved = module._resolve_expected_timezone(
        current_timezone=None,
        local_tz_offset="UTC+09:00",
        start_time_utc="2026-01-15T12:00:00+00:00",
        athlete_timezone=None,
        is_zwift_workout=False,
    )

    assert resolved == "UTC+09:00"


def test_resolve_expected_timezone_falls_back_to_offset_without_timestamp() -> None:
    resolved = module._resolve_expected_timezone(
        current_timezone=None,
        local_tz_offset="UTC-05:00",
        start_time_utc=None,
        athlete_timezone="America/New_York",
        is_zwift_workout=False,
    )

    assert resolved == "UTC-05:00"


def test_resolve_expected_timezone_zwift_prefers_athlete_home_timezone() -> None:
    resolved = module._resolve_expected_timezone(
        current_timezone=None,
        local_tz_offset="UTC+00:00",
        start_time_utc="2026-01-15T12:00:00+00:00",
        athlete_timezone="America/New_York",
        is_zwift_workout=True,
    )

    assert resolved == "America/New_York"


def test_compute_update_state_detects_zwift_and_uses_home_timezone() -> None:
    entity = {
        "timezone": "UTC+00:00",
        "local_tz_offset": "UTC+00:00",
        "sub_sport": "virtual_activity",
        "device_manufacturer": "zwift",
    }
    metadata = {
        "identity": {
            "start_time_utc": "2026-01-15T12:00:00+00:00",
            "sub_sport": "virtual_activity",
        },
        "enrichment": {"workout_name": "Zwift - Recovery Ride"},
        "activity_metadata": {"local_tz_offset": "UTC+00:00"},
    }

    expected, row_needs_update, metadata_needs_update, _ = module._compute_update_state(
        entity=entity,
        metadata=metadata,
        athlete_timezone="America/New_York",
    )

    assert expected == "America/New_York"
    assert row_needs_update is True
    assert metadata_needs_update is True


def test_compute_update_state_non_zwift_utc_does_not_use_home_timezone() -> None:
    entity = {
        "timezone": "UTC+00:00",
        "local_tz_offset": "UTC+00:00",
        "sub_sport": "indoor_cycling",
        "device_manufacturer": "garmin",
    }
    metadata = {
        "identity": {
            "start_time_utc": "2026-01-15T12:00:00+00:00",
            "sub_sport": "indoor_cycling",
            "device_manufacturer": "garmin",
        },
        "enrichment": {"workout_name": "Easy Trainer Ride"},
        "activity_metadata": {"local_tz_offset": "UTC+00:00"},
    }

    expected, row_needs_update, metadata_needs_update, _ = module._compute_update_state(
        entity=entity,
        metadata=metadata,
        athlete_timezone="America/New_York",
    )

    assert expected != "America/New_York"
    assert row_needs_update is True
    assert metadata_needs_update is True


def test_backfill_single_entity_dry_run_reports_updates(monkeypatch) -> None:
    metadata = _sample_metadata()
    entity = _sample_entity()

    monkeypatch.setattr(
        module,
        "_load_metadata_with_fallback",
        lambda **kwargs: (metadata, "w-1/metadata.json"),
    )

    storage = SimpleNamespace(infrastructure=MagicMock())
    workouts_table = MagicMock()

    status, row_updated, metadata_updated = module._backfill_single_entity(
        entity=entity,
        storage=storage,
        workouts_table=workouts_table,
        apply=False,
        athlete_timezone="America/New_York",
    )

    assert status == "updated"
    assert row_updated is True
    assert metadata_updated is True
    workouts_table.upsert_entity.assert_not_called()
    storage.infrastructure.upload_json_blob.assert_not_called()


def test_backfill_single_entity_apply_updates_row_and_blob(monkeypatch) -> None:
    metadata = _sample_metadata()
    entity = _sample_entity()

    monkeypatch.setattr(
        module,
        "_load_metadata_with_fallback",
        lambda **kwargs: (metadata, "w-1/metadata.json"),
    )

    storage = SimpleNamespace(infrastructure=MagicMock())
    workouts_table = MagicMock()

    status, row_updated, metadata_updated = module._backfill_single_entity(
        entity=entity,
        storage=storage,
        workouts_table=workouts_table,
        apply=True,
        athlete_timezone="America/New_York",
    )

    assert status == "updated"
    assert row_updated is True
    assert metadata_updated is True
    workouts_table.upsert_entity.assert_called_once()
    storage.infrastructure.upload_json_blob.assert_called_once()
    assert metadata["activity_metadata"]["timezone"] == "America/New_York"
