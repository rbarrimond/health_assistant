#!/usr/bin/env python
"""Pytest-friendly sanity checks for local Azure Function development."""

import base64
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    # Ensure project modules are importable when pytest runs from repo root
    sys.path.insert(0, str(PROJECT_ROOT))

from FitParser.fit_parser import compute_file_hash  # noqa: E402


@pytest.fixture(scope="module")
def project_root() -> Path:
    return PROJECT_ROOT


def test_fit_parser_module_exists(project_root: Path) -> None:
    parser_path = project_root / "FitParser" / "fit_parser.py"
    assert parser_path.exists(), "fit_parser.py is missing"


def test_compute_file_hash(tmp_path: Path) -> None:
    test_file = tmp_path / "sample.fit"
    test_file.write_bytes(b"test file content")

    file_hash = compute_file_hash(str(test_file))
    assert isinstance(file_hash, str)
    assert len(file_hash) == 64


def test_table_storage_module_exists(project_root: Path) -> None:
    storage_path = project_root / "FitParser" / "table_storage.py"
    assert storage_path.exists(), "table_storage.py is missing"


def test_function_handler_exists(project_root: Path) -> None:
    handler_path = project_root / "function_app" / "function_handler.py"
    assert handler_path.exists(), "function_handler.py is missing"


def test_payload_structure() -> None:
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
