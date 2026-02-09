# pylint: disable=W0212

"""Tests for ingestion handlers and shared base logic."""

import base64
from unittest.mock import Mock, patch

from FitParser.handlers.fit_payload_handler import FitPayloadIngestionHandler
from FitParser.handlers.ingestion_base_handler import FitIngestionBaseHandler


class _TestIngestionHandler(FitIngestionBaseHandler):
    """Concrete handler for testing base behavior."""

    def handle(self, *args, **kwargs):  # type: ignore[override]
        return {"status": "ok"}, 200


def test_ingestion_base_skips_unchanged_records_state() -> None:
    """Test skipping unchanged records."""
    storage = Mock()
    context = Mock()
    context.should_skip.return_value = True
    context.existing_state = {"workout_id": "workout-1"}
    context.ingestion_key = "ingestion-key"
    storage.get_ingestion_context.return_value = context

    handler = _TestIngestionHandler(storage)
    skipped, workout_id = handler._skip_if_unchanged(
        "rob",
        {"source_file_name": "file.fit"},
    )

    assert skipped is True
    assert workout_id == "workout-1"
    storage.record_ingestion_state.assert_called_once_with(
        "rob",
        {"source_file_name": "file.fit"},
        status="skipped",
        workout_id="workout-1",
        ingestion_key="ingestion-key",
        existing_state=context.existing_state,
    )


def test_ingestion_base_does_not_skip_when_unchanged() -> None:
    """Test not skipping unchanged records."""
    storage = Mock()
    context = Mock()
    context.should_skip.return_value = False
    storage.get_ingestion_context.return_value = context

    handler = _TestIngestionHandler(storage)
    skipped, workout_id = handler._skip_if_unchanged(
        "rob",
        {"source_file_name": "file.fit"},
    )

    assert skipped is False
    assert workout_id is None
    storage.record_ingestion_state.assert_not_called()


def test_ingestion_base_parse_and_store_records_ingestion_state() -> None:
    """Test parsing and storing records."""
    storage = Mock()
    storage.store_workout.return_value = "workout-2"
    handler = _TestIngestionHandler(storage)

    with patch("FitParser.handlers.ingestion_base_handler.FitParser") as parser_cls:
        parser = parser_cls.return_value
        parser.parse.return_value = {"sport": "Cycling"}

        metrics, workout_id = handler._parse_and_store(
            "rob",
            {"source_file_name": "file.fit"},
            file_path="/tmp/file.fit",
        )

    assert metrics["sport"] == "Cycling"
    assert workout_id == "workout-2"
    storage.store_workout.assert_called_once_with(
        "rob",
        {"sport": "Cycling"},
        {"source_file_name": "file.fit"},
    )
    storage.record_ingestion_state.assert_called_once_with(
        "rob",
        {"source_file_name": "file.fit"},
        status="ingested",
        workout_id="workout-2",
    )


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
            return_value={"source_file_name": "file.fit"},
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

    with patch("FitParser.handlers.fit_payload_handler.compute_bytes_hash", return_value="hash"), \
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
