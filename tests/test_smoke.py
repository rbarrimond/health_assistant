"""Smoke checks for imports and minimal happy paths.

These are intentionally shallow: do modules import and do core call paths work?
"""

import base64
import importlib
from pathlib import Path
from typing import Any, cast

import pytest

from FitParser.fit_parser import compute_file_hash
from function_app import parse_onedrive_payload


def test_fit_parser_imports() -> None:
    """FitParser.fit_parser should import and expose compute_file_hash."""
    mod = importlib.import_module("FitParser.fit_parser")
    assert hasattr(mod, "compute_file_hash")


def test_table_storage_imports() -> None:
    """FitParser.table_storage should import and expose WorkoutTableStorage."""
    mod = importlib.import_module("FitParser.table_storage")
    assert hasattr(mod, "WorkoutTableStorage")


def test_function_app_importable() -> None:
    """function_app should import when azure.functions is available."""
    pytest.importorskip("azure.functions")
    mod = importlib.import_module("function_app")
    assert hasattr(mod, "parse_onedrive_payload")


def test_compute_file_hash(tmp_path: Path) -> None:
    """compute_file_hash should return a 64-char hex digest for a file."""
    test_file = tmp_path / "sample.fit"
    test_file.write_bytes(b"test file content")

    file_hash = compute_file_hash(str(test_file))
    assert isinstance(file_hash, str)
    assert len(file_hash) == 64


def test_payload_structure() -> None:
    """Sample payload dict should include required fields."""
    example_payload = {
        "athlete_id": "rob",
        "source_item_id": "test_item_id",
        "source_file_name": "2026-01-07-test.fit",
        "source_file_path": "/Apps/HealthFit/2026-01-07-test.fit",
        "source_drive_id": "drive_id",
        "file_content_b64": base64.b64encode(b"test content").decode(),
        "file_size_bytes": 100,
    }

    required_fields = {"athlete_id", "source_file_name", "file_content_b64"}
    assert required_fields.issubset(example_payload.keys())


def test_parse_onedrive_payload_happy_path() -> None:
    """parse_onedrive_payload should accept a minimal valid request."""
    pytest.importorskip("azure.functions")

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

    parsed = parse_onedrive_payload(cast(Any, DummyReq()))
    assert parsed["athlete_id"] == "rob"
    assert parsed["source_file_name"] == "file.fit"
    assert isinstance(parsed["file_content_b64"], str)
