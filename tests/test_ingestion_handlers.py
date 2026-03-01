# pylint: disable=W0212,C0301,C0303

"""Tests for ingestion handlers and shared base logic."""

import base64
from unittest.mock import Mock, patch

from TrainingAnalyticsPlatform.handlers.fit_payload_handler import FitPayloadIngestionHandler
from TrainingAnalyticsPlatform.handlers.ingestion_base_handler import FitIngestionBaseHandler
from TrainingAnalyticsPlatform.models import CanonicalRecordSet
from TrainingAnalyticsPlatform.platform.exceptions import (
    FitParsingError,
    IngestionIdResolutionError,
    WorkoutIdCalculationError,
)
from TrainingAnalyticsPlatform.storage.storage_infrastructure import (
    CANONICAL_SCHEMA_VERSION,
    IngestionContext,
)


class _TestIngestionHandler(FitIngestionBaseHandler):
    """Concrete handler for testing base behavior."""

    def handle(self, *args, **kwargs):  # type: ignore[override]
        return {"status": "ok"}, 200


def test_ingestion_base_skips_unchanged_records_state() -> None:
    """Test skipping unchanged records."""
    storage = Mock()
    storage.workouts = Mock()
    context = Mock()
    context.should_skip.return_value = True
    context.existing_state = {"workout_id": "workout-1"}
    context.ingestion_key = "ingestion-key"
    storage.workouts.get_ingestion_context.return_value = context

    handler = _TestIngestionHandler(storage)
    skipped, workout_id = handler._skip_if_unchanged(
        "rob",
        {"source_file_name": "file.fit"},
    )

    assert skipped is True
    assert workout_id == "workout-1"
    storage.workouts.record_ingestion_state.assert_called_once_with(
        "rob",
        {"source_file_name": "file.fit"},
        status="skipped",
        workout_id="workout-1",
        ingestion_id=None,
        ingestion_key="ingestion-key",
        existing_state=context.existing_state,
    )


def test_ingestion_base_does_not_skip_when_unchanged() -> None:
    """Test not skipping unchanged records."""
    storage = Mock()
    storage.workouts = Mock()
    context = Mock()
    context.should_skip.return_value = False
    storage.workouts.get_ingestion_context.return_value = context

    handler = _TestIngestionHandler(storage)
    skipped, workout_id = handler._skip_if_unchanged(
        "rob",
        {"source_file_name": "file.fit"},
    )

    assert skipped is False
    assert workout_id is None
    storage.workouts.record_ingestion_state.assert_not_called()


def test_ingestion_base_parse_and_store_records_ingestion_state() -> None:
    """Test parsing and storing records."""
    storage = Mock()
    storage.workouts = Mock()
    storage.workouts.store_canonical_records.return_value = "records.parquet"
    handler = _TestIngestionHandler(storage)
    source_info = {
        "source_file_name": "file.fit",
        "file_sha256": "hash",
        "ingestion_id": "hash",
    }
    # Build structured metadata with semantic zones (schema 2.0.0)
    structured_metadata = {
        "identity": {
            "sport": "Cycling",
            "start_time_utc": "2026-01-01T00:00:00+00:00",
            "sub_sport": None,
            "duration_sec": 3600.0,
            "distance_m": 10000.0,
            "device_name": "Apple Watch Series 5 40mm (GPS)",
            "device_source": "apple_watch",
        },
        "capabilities": {
            "has_power": False,
            "has_hr": True,
            "has_gps": True,
        },
        "session": {},
        "file_metadata": {},
        "activity_metadata": {},
        "enrichment": {},
        "llm_analysis": {},
    }
    laps_payload = {"laps": [{"message_index": 0}]}
    expected_workout_id = "2026-01-01T00:00:00+00:00_Cycling_hash"
    
    # Create empty CanonicalRecordSet for mock
    empty_record_set = CanonicalRecordSet(messages=[], start_dt=None)

    mock_model = Mock()
    mock_model.device_name = "Apple Watch Series 5 40mm (GPS)"
    mock_model.device_manufacturer_code = None
    mock_model.device_product_code = None
    mock_model.validate_semantic_contract.return_value = None
    mock_model.build_canonical_metadata.return_value = structured_metadata
    mock_model.build_canonical_records.return_value = empty_record_set
    mock_model.build_laps_json.return_value = laps_payload
    mock_model.build_metadata_messages.return_value = {"metadata_schema_version": "1.0"}
    mock_model.build_fit_analysis.return_value = {"analysis": "data"}
    mock_model.raw_frames.return_value = '[]'  # JSON string of empty frames list
    mock_model.semantic_workout_id = expected_workout_id

    with patch("TrainingAnalyticsPlatform.handlers.ingestion_base_handler.create_fit_model") as create_model:
        create_model.return_value = mock_model

        metrics, workout_id = handler._parse_and_store(
            "rob",
            source_info,
            file_bytes=b"dummy_fit_bytes",
        )

    # Verify flattened metadata has sport from identity zone
    assert metrics["sport"] == "Cycling"
    assert metrics["start_time_utc"] == "2026-01-01T00:00:00+00:00"
    assert metrics["has_power"] is False
    assert metrics["has_hr"] is True
    # The returned workout_id should come from semantic identity computation.
    assert workout_id == expected_workout_id
    mock_model.validate_semantic_contract.assert_called_once_with()
    
    # Verify store_workout was called with structured metadata (zones)
    assert storage.workouts.store_workout.call_count == 1
    call_args = storage.workouts.store_workout.call_args
    assert call_args[0][0] == "rob"  # athlete_id
    # First arg should be structured_metadata with provenance zone added
    stored_metadata = call_args[0][1]
    assert "identity" in stored_metadata
    assert stored_metadata["identity"]["sport"] == "Cycling"
    assert "provenance" in stored_metadata  # Added by handler
    assert call_args[0][2] == source_info  # source_info (updated with ingestion_id)
    assert call_args[1]["workout_id"] == expected_workout_id
    assert "ingestion_id" in call_args[1]  # Should have ingestion_id
    assert call_args[1]["canonical_schema_version"] == CANONICAL_SCHEMA_VERSION
    assert call_args[1]["canonical_records_blob"] == "records.parquet"
    assert call_args[1]["records_count"] == 0  # Empty record set
    assert call_args[1]["laps_count"] == len(laps_payload["laps"])
    
    # Verify record_ingestion_state was called with correct params
    assert storage.workouts.record_ingestion_state.call_count == 1
    state_call_args = storage.workouts.record_ingestion_state.call_args
    assert state_call_args[0][0] == "rob"  # athlete_id
    # source_info should be updated with ingestion_id
    assert state_call_args[0][1]["source_file_name"] == "file.fit"
    assert state_call_args[0][1]["file_sha256"] == "hash"
    assert "ingestion_id" in state_call_args[0][1]
    assert state_call_args[1]["status"] == "ingested"
    assert state_call_args[1]["workout_id"] == expected_workout_id


def test_fit_payload_handler_missing_file_content() -> None:
    """Test handling missing file content."""
    handler = FitPayloadIngestionHandler(Mock())

    body, status = handler.handle_payload({"athlete_id": "rob"})

    assert status == 400
    assert body["error"] == "No file content"


def test_fit_payload_handler_invalid_base64() -> None:
    """Test handling invalid base64 content."""
    handler = FitPayloadIngestionHandler(Mock())

    body, status = handler.handle_payload({"file_content_b64": "not-base64"})

    assert status == 400
    assert body["error"] == "Invalid base64 content"


def test_fit_payload_handler_skips_unchanged() -> None:
    """Test skipping unchanged payloads."""
    handler = FitPayloadIngestionHandler(Mock())

    with patch.object(handler, "_extract_payload_bytes", return_value=b"data"), \
        patch.object(
            handler,
            "_build_payload_source_info",
            return_value={"source_file_name": "file.fit", "ingestion_id": "hash"},
        ), \
        patch.object(handler, "_skip_if_unchanged", return_value=(True, "workout-3")), \
        patch.object(handler, "_parse_and_store") as parse_and_store:
        body, status = handler.handle_payload({"file_content_b64": "ZGF0YQ=="})

    assert status == 200
    assert body["status"] == "skipped"
    assert body["workout_id"] == "workout-3"
    parse_and_store.assert_not_called()


def test_fit_payload_handler_success_calls_parse_and_store() -> None:
    """Test successful payload handling."""
    handler = FitPayloadIngestionHandler(Mock())
    payload = {
        "file_content_b64": base64.b64encode(b"data").decode("ascii"),
        "source_system": "HealthFit",
    }

    with patch("TrainingAnalyticsPlatform.handlers.fit_payload_handler.compute_bytes_hash", return_value="hash"), \
        patch.object(handler, "_skip_if_unchanged", return_value=(False, None)), \
        patch.object(
            handler,
            "_parse_and_store",
            return_value=({"sport": "Cycling"}, "workout-4"),
        ) as parse_and_store:
        body, status = handler.handle_payload(payload)

    assert status == 200
    assert body["status"] == "success"
    assert body["workout_id"] == "workout-4"

    parse_args = parse_and_store.call_args[0]
    assert parse_args[0] == "rob"
    assert parse_args[1]["file_sha256"] == "hash"


def test_fit_payload_handler_ingestion_id_resolution_error() -> None:
    """Test typed ingestion ID resolution error response mapping."""
    handler = FitPayloadIngestionHandler(Mock())

    with patch.object(handler, "_extract_payload_bytes", return_value=b"data"), \
        patch.object(
            handler,
            "_build_payload_source_info",
            side_effect=IngestionIdResolutionError("missing source identity"),
        ):
        body, status = handler.handle_payload({"file_content_b64": "ZGF0YQ=="})

    assert status == 422
    assert body["status"] == "error"
    assert body["error_code"] == "INGESTION_ID_RESOLUTION_FAILED"
    assert body["error"] == "missing source identity"


def test_fit_payload_handler_workout_id_calculation_error() -> None:
    """Test typed workout ID calculation error response mapping."""
    handler = FitPayloadIngestionHandler(Mock())

    with patch.object(handler, "_extract_payload_bytes", return_value=b"data"), \
        patch.object(
            handler,
            "_build_payload_source_info",
            return_value={"source_file_name": "file.fit", "ingestion_id": "ing-1"},
        ), \
        patch.object(
            handler,
            "ingest_bytes",
            side_effect=WorkoutIdCalculationError("missing semantic identity"),
        ):
        body, status = handler.handle_payload({"file_content_b64": "ZGF0YQ=="})

    assert status == 422
    assert body["status"] == "error"
    assert body["error_code"] == "WORKOUT_ID_CALCULATION_FAILED"
    assert body["error"] == "missing semantic identity"


def test_fit_payload_handler_fit_parsing_error() -> None:
    """Test typed FIT parsing error response mapping."""
    handler = FitPayloadIngestionHandler(Mock())

    with patch.object(handler, "_extract_payload_bytes", return_value=b"data"), \
        patch.object(
            handler,
            "_build_payload_source_info",
            return_value={"source_file_name": "file.fit", "ingestion_id": "ing-1"},
        ), \
        patch.object(
            handler,
            "ingest_bytes",
            side_effect=FitParsingError("invalid fit bytes"),
        ):
        body, status = handler.handle_payload({"file_content_b64": "ZGF0YQ=="})

    assert status == 422
    assert body["status"] == "error"
    assert body["error_code"] == "FIT_PARSING_FAILED"
    assert body["error"] == "invalid fit bytes"


def test_ingestion_context_skipped_unchanged_is_terminal() -> None:
    """Skipped unchanged records should remain terminal and skip reingest."""
    storage = Mock()
    file_info = {
        "source_etag": "etag-1",
    }
    existing_state = {
        "status": "skipped",
        "source_etag": "etag-1",
    }

    context = IngestionContext(
        athlete_id="rob",
        file_info=file_info,
        workout_id=None,
        storage=storage,
        existing_state=existing_state,
        ingestion_key="ingestion-key",
    )

    assert context.is_unchanged() is True
    assert context.should_skip() is True


def test_ingestion_context_preserves_ingested_at_on_skip() -> None:
    """Skipped state should preserve prior ingested_at_utc when present."""
    storage = Mock()
    file_info = {
        "source_etag": "etag-1",
    }
    existing_state = {
        "status": "ingested",
        "source_etag": "etag-1",
        "ingested_at_utc": "2026-02-10T12:00:00+00:00",
    }

    context = IngestionContext(
        athlete_id="rob",
        file_info=file_info,
        workout_id=None,
        storage=storage,
        existing_state=existing_state,
        ingestion_key="ingestion-key",
    )

    entity = context.build_state_entity(status="skipped").to_entity()

    assert entity.get("ingested_at_utc") == "2026-02-10T12:00:00+00:00"


def test_fit_model_parses_once_per_ingestion() -> None:
    """Verify FIT file is parsed exactly once during ingestion."""
    from pathlib import Path
    from unittest.mock import patch
    from TrainingAnalyticsPlatform.ingestion.fit_models import HealthFitModel
    
    # Load a real FIT file for integration test
    test_data = Path(__file__).parent / "data"
    fit_files = list(test_data.glob("*.fit"))
    assert len(fit_files) > 0, "No test FIT files found"
    
    fit_path = fit_files[0]
    with open(fit_path, "rb") as f:
        fit_bytes = f.read()
    
    # Spy on FitReader construction to count parse calls
    with patch("TrainingAnalyticsPlatform.ingestion.fit_models.FitReader") as mock_reader:
        # Let the real FitReader run, just count invocations
        from fitdecode import FitReader as RealFitReader
        mock_reader.side_effect = lambda *args, **kwargs: RealFitReader(*args, **kwargs)
        
        # Create model (should parse once)
        model = HealthFitModel(
            file_bytes=fit_bytes,
            source_metadata={"source_file_name": fit_path.name}
        )
        
        # Access raw_frames (should NOT parse again)
        raw_json = model.raw_frames(as_json=True)
        raw_list = model.raw_frames(as_json=False)
        
        # Verify only one parse happened (in constructor)
        assert mock_reader.call_count == 1, f"Expected 1 parse, got {mock_reader.call_count}"
        
        # Verify output is valid
        assert isinstance(raw_json, str)
        assert isinstance(raw_list, list)
        assert len(raw_list) > 0, "Expected frames from real FIT file"
