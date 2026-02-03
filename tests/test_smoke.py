"""Smoke checks for imports and minimal happy paths.

These are intentionally shallow: do modules import and do core call paths work?
"""

import base64
from pathlib import Path
from typing import Any, cast

import pytest

from FitParser.fit_parser import compute_file_hash
from function_app import parse_ingest_payload


def test_core_modules_importable() -> None:
    """Core FitParser and function_app modules should import successfully."""
    # If this test runs, the imports at module level succeeded
    from FitParser.fit_parser import compute_file_hash as _  # noqa: F401
    from FitParser.table_storage import WorkoutTableStorage as _  # noqa: F401
    from function_app import parse_ingest_payload as _  # noqa: F401
    # All imports succeeded - test passes


def test_compute_file_hash(tmp_path: Path) -> None:
    """compute_file_hash should return a 64-char hex digest for a file."""
    test_file = tmp_path / "sample.fit"
    test_file.write_bytes(b"test file content")

    file_hash = compute_file_hash(str(test_file))
    assert isinstance(file_hash, str)
    assert len(file_hash) == 64
    # Verify it's valid hex
    int(file_hash, 16)


def test_parse_ingest_payload_valid() -> None:
    """parse_ingest_payload should parse valid minimal request."""
    body = {
        "athlete_id": "rob",
        "source_file_name": "file.fit",
        "file_content_b64": base64.b64encode(b"data").decode(),
    }

    class DummyReq:
        """Minimal HttpRequest-like object for testing."""
        def get_json(self):
            """Return the request body payload for parsing."""
            return body

    parsed = parse_ingest_payload(cast(Any, DummyReq()))
    assert parsed["athlete_id"] == "rob"
    assert parsed["source_file_name"] == "file.fit"
    assert isinstance(parsed["file_content_b64"], str)


def test_parse_ingest_payload_missing_athlete_id() -> None:
    """parse_ingest_payload should raise ValueError if athlete_id missing."""
    body = {
        "source_file_name": "file.fit",
        "file_content_b64": base64.b64encode(b"data").decode(),
    }

    class DummyReq:
        def get_json(self):
            return body

    with pytest.raises(ValueError, match="Missing required field: athlete_id"):
        parse_ingest_payload(cast(Any, DummyReq()))


def test_parse_ingest_payload_missing_file_content() -> None:
    """parse_ingest_payload should raise ValueError if file_content_b64 missing."""
    body = {
        "athlete_id": "rob",
        "source_file_name": "file.fit",
    }

    class DummyReq:
        def get_json(self):
            return body

    with pytest.raises(ValueError, match="Missing required field: file_content_b64"):
        parse_ingest_payload(cast(Any, DummyReq()))


def test_parse_ingest_payload_invalid_json() -> None:
    """parse_ingest_payload should raise ValueError on invalid JSON."""
    class DummyReq:
        def get_json(self):
            raise ValueError("Invalid JSON")

    with pytest.raises(ValueError, match="Invalid payload"):
        parse_ingest_payload(cast(Any, DummyReq()))
