"""Tests for device filtration policies in ingestion handlers."""

from unittest.mock import Mock

import pytest

from TrainingAnalyticsPlatform.handlers.fit_payload_handler import FitPayloadIngestionHandler
from TrainingAnalyticsPlatform.handlers.garmin_sync_handler import GarminSyncIngestionHandler
from TrainingAnalyticsPlatform.handlers.onedrive_sync_handler import OneDriveSyncIngestionHandler
from TrainingAnalyticsPlatform.platform.exceptions import DeviceFilteredError


def _build_model(
    *,
    device_name: str | None,
    manufacturer_code: int | None,
    product_code: int | None = None,
    device_model: str | None = None,
) -> Mock:
    model = Mock()
    model.device_name = device_name
    model.device_manufacturer_code = manufacturer_code
    model.device_product_code = product_code
    model.device_model = device_model
    return model


def _build_source_info() -> dict:
    return {
        "source_file_name": "file.fit",
        "file_sha256": "hash",
        "ingestion_id": "hash",
    }


def test_payload_handler_does_not_filter() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = FitPayloadIngestionHandler(storage)
    model = _build_model(
        device_name="iPhone", manufacturer_code=255, device_model="iPhone17,1"
    )
    source_info = _build_source_info()

    handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_not_called()


def test_onedrive_handler_filters_healthkit_synced() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = OneDriveSyncIngestionHandler(storage, Mock())
    model = _build_model(
        device_name="iPhone", manufacturer_code=255, device_model="iPhone17,1"
    )
    source_info = _build_source_info()

    with pytest.raises(DeviceFilteredError):
        handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_called_once()
    _, kwargs = storage.workouts.record_ingestion_state.call_args
    assert kwargs["status"] == "filtered"
    assert "not_apple_watch_device" in kwargs["error"]


def test_onedrive_handler_rejects_garmin_device() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = OneDriveSyncIngestionHandler(storage, Mock())
    model = _build_model(device_name="Garmin Forerunner 955", manufacturer_code=1)
    source_info = _build_source_info()

    with pytest.raises(DeviceFilteredError):
        handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_called_once()
    _, kwargs = storage.workouts.record_ingestion_state.call_args
    assert kwargs["status"] == "filtered"
    assert "not_apple_watch_device" in kwargs["error"]


def test_onedrive_handler_rejects_unknown_device() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = OneDriveSyncIngestionHandler(storage, Mock())
    model = _build_model(device_name="Wahoo", manufacturer_code=32)
    source_info = _build_source_info()

    with pytest.raises(DeviceFilteredError):
        handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_called_once()
    _, kwargs = storage.workouts.record_ingestion_state.call_args
    assert kwargs["status"] == "filtered"
    assert "not_apple_watch_device" in kwargs["error"]


def test_onedrive_handler_allows_watch_device_name() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = OneDriveSyncIngestionHandler(storage, Mock())
    model = _build_model(device_name="Apple Watch Ultra", manufacturer_code=255)
    source_info = _build_source_info()

    handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_not_called()


def test_onedrive_handler_allows_watch_device_model() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = OneDriveSyncIngestionHandler(storage, Mock())
    model = _build_model(
        device_name="RunGap", manufacturer_code=255, device_model="Watch7,12"
    )
    source_info = _build_source_info()

    handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_not_called()


def test_garmin_handler_filters_non_allowlisted_manufacturer() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = GarminSyncIngestionHandler(storage, Mock())
    model = _build_model(device_name="Wahoo", manufacturer_code=32)
    source_info = _build_source_info()

    with pytest.raises(DeviceFilteredError):
        handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_called_once()
    _, kwargs = storage.workouts.record_ingestion_state.call_args
    assert kwargs["status"] == "filtered"
    assert "manufacturer_not_allowed" in kwargs["error"]


def test_garmin_handler_allows_garmin() -> None:
    storage = Mock()
    storage.workouts = Mock()
    handler = GarminSyncIngestionHandler(storage, Mock())
    model = _build_model(device_name="Garmin Forerunner 955", manufacturer_code=1)
    source_info = _build_source_info()

    handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_not_called()


def test_garmin_handler_allows_zwift() -> None:
    """Zwift workouts synced via Garmin API should be allowed."""
    storage = Mock()
    storage.workouts = Mock()
    handler = GarminSyncIngestionHandler(storage, Mock())
    model = _build_model(device_name="Zwift", manufacturer_code=260)
    source_info = _build_source_info()

    handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_not_called()


def test_garmin_handler_rejects_none_manufacturer() -> None:
    """Garmin API sync should reject workouts with None manufacturer_code."""
    storage = Mock()
    storage.workouts = Mock()
    handler = GarminSyncIngestionHandler(storage, Mock())
    model = _build_model(device_name="Unknown", manufacturer_code=None)
    source_info = _build_source_info()

    with pytest.raises(DeviceFilteredError):
        handler._apply_device_source_filtration("rob", model, source_info)

    storage.workouts.record_ingestion_state.assert_called_once()
    _, kwargs = storage.workouts.record_ingestion_state.call_args
    assert kwargs["status"] == "filtered"
    assert "manufacturer_not_allowed" in kwargs["error"]
