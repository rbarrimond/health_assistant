"""Unit tests for fit_parser utility functions.

Note: FitParser class was removed in v13.0.0. Handlers now call create_fit_model()
directly. Model-specific tests (indoor detection, device extraction, etc.) are in
test_fit_models.py with the concrete model tests.
"""

# Allow protected member access in tests to validate internal caching behavior.
# pylint: disable=protected-access, line-too-long

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from TrainingAnalyticsPlatform.handlers.ingestion_hashing import compute_file_hash
from TrainingAnalyticsPlatform.ingestion.apple_workout_types import INDOOR_CYCLE
from TrainingAnalyticsPlatform.ingestion.fit_models import HealthFitModel, PayloadFitModel


class _EnumLike:
    def __init__(self, name: str) -> None:
        self.name = name


class _MessageStub:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get_value(self, field_name: str, fallback: object = None) -> object:
        """Simulate FitMessage get_value method for testing."""
        return self._values.get(field_name, fallback)


class TestComputeFileHash:
    """Tests for compute_file_hash function."""

    def test_compute_file_hash_returns_64_char_string(self, tmp_path: Path) -> None:
        """Verify hash is 64 characters (SHA256 hex digest)."""
        test_file = tmp_path / "test.fit"
        test_file.write_bytes(b"test content")

        hash_value = compute_file_hash(str(test_file))

        assert isinstance(hash_value, str)
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_compute_file_hash_consistency(self, tmp_path: Path) -> None:
        """Verify same file produces same hash."""
        test_file = tmp_path / "test.fit"
        content = b"identical content"
        test_file.write_bytes(content)

        hash1 = compute_file_hash(str(test_file))
        hash2 = compute_file_hash(str(test_file))

        assert hash1 == hash2

    def test_compute_file_hash_different_content(self, tmp_path: Path) -> None:
        """Verify different files produce different hashes."""
        file1 = tmp_path / "file1.fit"
        file2 = tmp_path / "file2.fit"
        file1.write_bytes(b"content1")
        file2.write_bytes(b"content2")

        hash1 = compute_file_hash(str(file1))
        hash2 = compute_file_hash(str(file2))

        assert hash1 != hash2


class TestSemanticWorkoutIdFallbacks:
    """Regression tests for semantic workout ID input derivation."""

    def test_semantic_workout_id_uses_session_sport_when_file_id_missing(self) -> None:
        """Verify that when file_id message is missing, session sport and start time are used for workout ID."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})
        model._messages_loaded = True
        model._session_msg = cast(
            Any,
            _MessageStub(
            {
                "sport": _EnumLike("cycling"),
                "start_time": datetime(2026, 2, 23, 6, 30, 0, tzinfo=timezone.utc),
            }
            ),
        )
        model._file_id_msg = None

        expected_start = "2026-02-23T06:30:00+00:00"
        expected = hashlib.sha1(f"{expected_start}#cycling".encode()).hexdigest()

        assert model.sport == "cycling"
        assert model.semantic_workout_id == expected

    def test_semantic_workout_id_uses_session_timestamp_when_start_time_missing(self) -> None:
        """Verify that when start_time is missing, session timestamp is used for workout ID."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})
        model._messages_loaded = True
        model._session_msg = cast(
            Any,
            _MessageStub(
            {
                "sport": "running",
                "timestamp": datetime(2026, 2, 23, 7, 45, 0, tzinfo=timezone.utc),
            }
            ),
        )
        model._file_id_msg = None

        expected_start = "2026-02-23T07:45:00+00:00"
        expected = hashlib.sha1(f"{expected_start}#running".encode()).hexdigest()

        assert model.start_time_utc_precise == expected_start
        assert model.semantic_workout_id == expected

    def test_healthfit_semantic_workout_id_falls_back_to_filename_activity_type(self) -> None:
        """Verify that HealthFit model falls back to filename activity type for workout ID."""
        model = HealthFitModel(
            file_bytes=b"fit",
            source_metadata={
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )
        model._messages_loaded = True
        model._session_msg = None
        model._file_id_msg = None

        expected_start = "2026-02-17T20:24:35+00:00"
        expected = hashlib.sha1(f"{expected_start}#indoor_cycling".encode()).hexdigest()

        assert model.sport == "indoor_cycling"
        assert model.start_time_utc_precise == expected_start
        assert model.semantic_workout_id == expected


class TestHealthFitWorkoutTypeParsing:
    """Integration checks for HealthFit-derived workout typing."""

    def test_healthfit_filename_regex_parses_spaced_activity_type(self) -> None:
        """Verify regex captures spaced Apple activity token correctly."""
        model = HealthFitModel(
            file_bytes=b"fit",
            source_metadata={
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )

        assert model.filename_activity_type == "Indoor Cycling"

    def test_healthfit_filename_regex_treats_hyphen_as_field_delimiter(self) -> None:
        """Verify hyphen splits activity/source fields and is not assumed inside activity token."""
        model = HealthFitModel(
            file_bytes=b"fit",
            source_metadata={
                "source_file_name": "2026-02-17-202435-Indoor-Cycling-RunGap.fit",
            },
        )

        assert model.filename_activity_type == "Indoor"

    def test_healthfit_apple_workout_type_resolves_from_filename_activity_type(self) -> None:
        """Verify that HealthFit model derives Apple workout type from filename activity type when messages are missing."""
        model = HealthFitModel(
            file_bytes=b"fit",
            source_metadata={
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )
        model._messages_loaded = True
        model._session_msg = None
        model._file_id_msg = None

        assert model.workout_name == "Indoor Cycling"
        assert model.apple_workout_type == INDOOR_CYCLE

    def test_healthfit_apple_workout_type_prefers_filename_over_fit_signals(self) -> None:
        """Verify that HealthFit model prefers filename-derived activity type for Apple workout type resolution over FIT session messages."""
        model = HealthFitModel(
            file_bytes=b"fit",
            source_metadata={
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )
        model._messages_loaded = True
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "running",
                    "sub_sport": "indoor_running",
                }
            ),
        )
        model._file_id_msg = None

        assert model.apple_workout_type == INDOOR_CYCLE

    def test_healthfit_apple_workout_type_does_not_infer_without_filename_token(self) -> None:
        """Verify that HealthFit model does not infer Apple workout type when filename activity type token is missing, even if FIT session messages are present."""
        model = HealthFitModel(
            file_bytes=b"fit",
            source_metadata={},
        )
        model._messages_loaded = True
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "running",
                    "sub_sport": "indoor_running",
                }
            ),
        )
        model._file_id_msg = None

        assert model.apple_workout_type is None


class TestConstructedWorkoutNameFallbacks:
    """Tests for constructed fallback naming semantics."""

    def test_constructed_workout_name_uses_daypart_and_apple_type_when_available(self) -> None:
        """Verify that constructed workout name uses daypart and Apple workout type when filename tokens are present."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})
        model._messages_loaded = True
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "cycling",
                    "sub_sport": "indoor_cycling",
                    "start_time": datetime(2026, 2, 23, 6, 30, 0, tzinfo=timezone.utc),
                }
            ),
        )
        model._file_id_msg = None

        assert model.workout_name == "Morning Indoor Cycle"

    def test_constructed_workout_name_falls_back_to_fit_fields_and_datetime(self) -> None:
        """Verify that constructed workout name falls back to FIT fields and datetime when filename tokens are missing."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})
        model._messages_loaded = True
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "kayaking",
                    "start_time": datetime(2026, 2, 23, 14, 30, 0, tzinfo=timezone.utc),
                }
            ),
        )
        model._file_id_msg = None

        assert model.workout_name == "kayaking-2026-02-23 14:30"
