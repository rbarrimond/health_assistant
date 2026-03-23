"""Tests for Garmin cached manufacturer normalization and validation."""

from unittest.mock import Mock

from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import GarminSyncIngestionHandler
from TrainingAnalyticsPlatform.ingestion.code_mappings import normalize_manufacturer_to_code
from TrainingAnalyticsPlatform.integrations.garmin_activity_contract import GarminActivityContract


def test_normalize_manufacturer_to_code_handles_uppercase_names() -> None:
    assert normalize_manufacturer_to_code("ZWIFT") == 260
    assert normalize_manufacturer_to_code("garmin") == 1


def test_contract_emits_cached_manufacturer_fields() -> None:
    contract = GarminActivityContract(
        {
            "activityId": 123,
            "activityName": "Ride",
            "activityType": {"typeKey": "virtual_ride"},
            "startTimeGMT": "2026-02-20T10:00:00+00:00",
            "duration": 3600,
            "distance": 32000,
            "manufacturer": "ZWIFT",
            "deviceId": 987654,
        }
    )

    metadata = contract.to_source_metadata_fields()
    assert metadata["source_manufacturer"] == "ZWIFT"
    assert metadata["source_manufacturer_code"] == 260
    assert metadata["source_device_id"] == 987654


def test_garmin_handler_warns_on_cached_fit_manufacturer_mismatch(caplog) -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = GarminSyncIngestionHandler(storage, Mock())

    model = Mock()
    model.device_name = "Garmin Forerunner 955"
    model.device_model = "Forerunner 955"
    model.device_manufacturer_code = 1
    model.device_product_code = 123

    source_info = {
        "source_system": "Garmin",
        "source_item_id": "abc123",
        "source_activity_name": "Mismatch Ride",
        "source_file_name": "abc123.fit",
        "ingestion_id": "abc123",
        "source_manufacturer": "ZWIFT",
        "source_manufacturer_code": 260,
        "source_device_id": 987654,
    }

    with caplog.at_level("WARNING"):
        handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_not_called()
    assert source_info["device_manufacturer_code"] == 1
    assert any(record.message == "Garmin manufacturer equivalence mismatch" for record in caplog.records)
