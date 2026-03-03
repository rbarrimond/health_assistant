"""Unit tests for fit_parser utility functions.

Note: FitParser class was removed in v13.0.0. Handlers now call create_fit_model()
directly. Model-specific tests (indoor detection, device extraction, etc.) are in
test_fit_models.py with the concrete model tests.
"""

# Allow protected member access in tests to validate internal caching behavior.
# pylint: disable=protected-access, line-too-long

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
import pytest

from TrainingAnalyticsPlatform.handlers.ingestion_hashing import compute_file_hash
from TrainingAnalyticsPlatform.ingestion.apple_workout_types import INDOOR_CYCLE, INDOOR_RUN, FUNCTIONAL_STRENGTH
from TrainingAnalyticsPlatform.ingestion.fit_models import BaseFitModel, HealthFitModel, PayloadFitModel
from TrainingAnalyticsPlatform.platform.exceptions import FitParsingError


class _EnumLike:
    def __init__(self, name: str) -> None:
        self.name = name


class _MessageStub:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get_value(self, field_name: str, fallback: object = None) -> object:
        """Simulate FitMessage get_value method for testing."""
        return self._values.get(field_name, fallback)


@pytest.fixture(autouse=True)
def _stub_fit_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub FIT parsing so tests can focus on semantic behavior."""
    monkeypatch.setattr(
        BaseFitModel,
        "_parse_fit_messages",
        lambda self, file_bytes: ([], [], {}),
    )


def _build_activity_fit_messages(
    *,
    include_file_id: bool = True,
    include_session: bool = True,
    include_record: bool = True,
    file_type: str = "activity",
    sport: str = "cycling",
) -> dict[str, list[Any]]:
    messages: dict[str, list[Any]] = {}
    if include_file_id:
        messages["file_id"] = [cast(Any, _MessageStub({"type": file_type}))]
    if include_session:
        messages["session"] = [
            cast(
                Any,
                _MessageStub(
                    {
                        "sport": sport,
                        "timestamp": datetime(2026, 2, 23, 7, 45, 0, tzinfo=timezone.utc),
                        "total_elapsed_time": 900,
                        "total_timer_time": 890,
                    }
                ),
            )
        ]
    if include_record:
        messages["record"] = [
            cast(
                Any,
                _MessageStub(
                    {
                        "timestamp": datetime(2026, 2, 23, 7, 31, 0, tzinfo=timezone.utc),
                    }
                ),
            )
        ]
    return messages


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
        """Verify that when file_id is missing, session UTC timestamp math and session sport drive workout ID."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._session_msg = cast(
            Any,
            _MessageStub(
            {
                "sport": _EnumLike("cycling"),
                "timestamp": datetime(2026, 2, 23, 7, 45, 0, tzinfo=timezone.utc),
                "total_elapsed_time": 4500,
            }
            ),
        )
        model._file_id_msg = None

        expected_start = "2026-02-23T06:30:00+00:00"
        expected = hashlib.sha1(f"{expected_start}#cycling".encode()).hexdigest()

        assert model.sport == "cycling"
        assert model.semantic_workout_id == expected

    def test_semantic_workout_id_uses_session_timestamp_when_start_time_missing(self) -> None:
        """Verify session-derived start uses timestamp minus elapsed duration."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._session_msg = cast(
            Any,
            _MessageStub(
            {
                "sport": "running",
                "timestamp": datetime(2026, 2, 23, 7, 45, 0, tzinfo=timezone.utc),
                "total_elapsed_time": 900,
            }
            ),
        )
        model._file_id_msg = None

        expected_start = "2026-02-23T07:30:00+00:00"
        expected = hashlib.sha1(f"{expected_start}#running".encode()).hexdigest()

        assert model.start_time_utc == expected_start
        assert model.semantic_workout_id == expected

    def test_healthfit_semantic_workout_id_requires_fit_start_time(self) -> None:
        """Verify semantic sport must come from FIT signals, not filename tokens."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )
        model._session_msg = None
        model._file_id_msg = None

        with pytest.raises(FitParsingError, match="Missing required FIT sport"):
            _ = model.sport


class TestFitSemanticContractValidation:
    """Tests for BaseFitModel semantic validation contract."""

    def test_validate_requires_exactly_one_file_id(self) -> None:
        """Verify validation fails when file_id message is missing."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._data_messages_by_type = _build_activity_fit_messages(include_file_id=False)

        with pytest.raises(FitParsingError, match="exactly one file_id"):
            model.validate_semantic_contract()

    def test_validate_requires_activity_file_type(self) -> None:
        """Verify validation fails when file_type is not activity."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._data_messages_by_type = _build_activity_fit_messages(file_type="workout")

        with pytest.raises(FitParsingError, match="file_id.type must be activity"):
            model.validate_semantic_contract()

    def test_validate_requires_session_and_record(self) -> None:
        """Verify validation fails when session or record messages are missing."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._data_messages_by_type = _build_activity_fit_messages(include_session=False)

        with pytest.raises(FitParsingError, match="missing required session"):
            model.validate_semantic_contract()

        model._data_messages_by_type = _build_activity_fit_messages(include_record=False)
        with pytest.raises(FitParsingError, match="missing required record"):
            model.validate_semantic_contract()

    def test_validate_enforces_monotonic_record_timestamps(self) -> None:
        """Verify validation fails when record timestamps are not monotonically increasing."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._data_messages_by_type = _build_activity_fit_messages()
        model._data_messages_by_type["record"] = [
            cast(
                Any,
                _MessageStub({"timestamp": datetime(2026, 2, 23, 7, 31, 0, tzinfo=timezone.utc)}),
            ),
            cast(
                Any,
                _MessageStub({"timestamp": datetime(2026, 2, 23, 7, 30, 0, tzinfo=timezone.utc)}),
            ),
        ]

        with pytest.raises(FitParsingError, match="non-decreasing"):
            model.validate_semantic_contract()


class TestHealthFitTimezoneInference:
    """Regression tests for HealthFit timezone fallback behavior."""

    def test_healthfit_filename_timezone_uses_fit_message_start_time(self) -> None:
        """Verify filename timezone inference compares local filename time against FIT-message UTC time."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "timestamp": datetime(2026, 2, 17, 20, 24, 35, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )

        assert model.inferred_timezone_filename == "UTC+00:00"
        assert model.local_tz_offset == "UTC+00:00"
        assert model.timezone == "UTC+00:00"


class TestSessionTimeMathSemantics:
    """Regression tests for session UTC and local offset semantics."""

    def test_session_uses_utc_math_for_start_and_local_math_for_offset(self) -> None:
        """Ensure start_time_utc and local_tz_offset are derived from the correct session fields."""
        model = HealthFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "timestamp": datetime(2026, 2, 24, 15, 0, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 3600,
                    "start_time": datetime(2026, 2, 24, 10, 0, 0),
                }
            ),
        )

        assert model.start_time_utc == "2026-02-24T14:00:00+00:00"
        assert model.local_tz_offset == "UTC-04:00"


class TestHealthFitWorkoutTypeParsing:
    """Integration checks for HealthFit-derived workout typing."""

    def test_healthfit_filename_regex_parses_spaced_activity_type(self) -> None:
        """Verify regex captures spaced Apple activity token correctly."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )

        # "Indoor Cycling" normalizes to canonical "Indoor Cycle"
        assert model.filename_apple_workout_type == "Indoor Cycle"

    def test_healthfit_filename_regex_parses_canonical_activity_with_device_no_spaces(self) -> None:
        """Verify regex captures canonical format: spaced activity type, simple device name (no spaces)."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )

        # "Indoor Cycling" normalizes to canonical "Indoor Cycle"
        assert model.filename_apple_workout_type == "Indoor Cycle"
        assert model.filename_source_device == "RunGap"

    def test_healthfit_filename_regex_preserves_full_source_device_name(self) -> None:
        """Verify source-device token is preserved exactly, including apostrophes and suffixes."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-Robert's Apple Watch Ultra 3.fit",
            },
        )

        # "Indoor Cycling" normalizes to canonical "Indoor Cycle"
        assert model.filename_apple_workout_type == "Indoor Cycle"
        assert model.filename_source_device == "Robert's Apple Watch Ultra 3"

    def test_healthfit_filename_regex_preserves_hyphenated_source_device_name(self) -> None:
        """Verify hyphenated source-device token is preserved in full (canonical format with spaced activity)."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-03-02-093346-Functional Strength Training-Robert's-Apple-Watch-7.fit",
            },
        )

        assert model.filename_apple_workout_type == "Functional Strength Training"
        assert model.filename_source_device == "Robert's-Apple-Watch-7"

    def test_healthfit_apple_workout_type_resolves_from_filename(self) -> None:
        """Verify that HealthFit model derives Apple workout type from filename when messages are missing."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "cycling",
                    "sub_sport": "indoor_cycling",
                    "timestamp": datetime(2026, 2, 17, 6, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        assert model.workout_name is not None
        assert model.workout_name.endswith("Indoor Cycle")
        assert model.apple_workout_type == INDOOR_CYCLE

    def test_healthfit_accepts_hyphenated_activity_tokens(self) -> None:
        """Verify hyphenated activity tokens (OneDrive corruption) are now accepted and parsed."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor-Cycling-RunGap.fit",
            },
        )

        # Hyphenated tokens should now be accepted via normalized lookup
        assert model.filename_components is not None
        assert model.filename_apple_workout_type == "Indoor Cycle"
        assert model.filename_source_device == "RunGap"

    def test_healthfit_apple_workout_type_prefers_filename_over_fit_signals(self) -> None:
        """Verify HealthFit prefers filename-derived Apple workout type over FIT session messages."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-RunGap.fit",
            },
        )
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

    def test_healthfit_apple_workout_type_falls_back_to_fit_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Verify HealthFit falls back to FIT inference when filename token is missing, logging a warning."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={},  # type: ignore[call-arg]
        )
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

        with caplog.at_level(logging.WARNING):
            assert model.apple_workout_type == INDOOR_RUN

        assert any(
            "falling back to FIT apple workout type resolution" in record.message
            for record in caplog.records
        )

    def test_healthfit_canonical_metadata_emits_provenance_source_device_name(self) -> None:
        """Verify canonical metadata preserves filename source-device token in provenance."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2026-02-17-202435-Indoor Cycling-Robert's Apple Watch Ultra 3.fit",
            },
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "cycling",
                    "sub_sport": "indoor_cycling",
                    "timestamp": datetime(2026, 2, 17, 6, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        metadata = model.build_canonical_metadata()

        assert metadata["identity"]["device_name"] == "Robert's Apple Watch Ultra 3"
        assert metadata["provenance"]["source_device_name"] == "Robert's Apple Watch Ultra 3"


class TestHealthFitDeviceNameExtraction:
    """Tests for device name extraction from corrupted OneDrive filenames."""

    def test_extract_device_name_from_corrupted_functional_strength_training_filename(self) -> None:
        """Extract device name when activity type is hyphenated by OneDrive."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2025-12-14-183750-Functional-Strength-Training-Robert's-Apple-Watch-7.fit",
            },
        )
        # Mock the FIT sport/sub_sport so apple_workout_type resolves correctly
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "training",
                    "sub_sport": "functional_training",
                    "timestamp": datetime(2025, 12, 14, 9, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        # FIT-derived apple_workout_type should be "Functional Strength Training"
        assert model.apple_workout_type == FUNCTIONAL_STRENGTH
        # Extracted and denormalized device name (model number stays hyphenated)
        assert model.device_name == "Robert's Apple Watch-7"

    def test_extract_device_name_from_corrupted_indoor_cycling_filename(self) -> None:
        """Extract device name for simple activity type."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2025-12-14-183750-Indoor-Cycle-RunGap.fit",
            },
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "cycling",
                    "sub_sport": "indoor_cycling",
                    "timestamp": datetime(2025, 12, 14, 9, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        assert model.apple_workout_type == INDOOR_CYCLE
        assert model.device_name == "RunGap"

    def test_extract_device_name_from_corrupted_other_activity_filename(self) -> None:
        """Extract device name for 'Other' activity type."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2025-12-14-183750-Other-Robert's-Apple-Watch-Ultra-3.fit",
            },
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "unknown",
                    "sub_sport": None,
                    "timestamp": datetime(2025, 12, 14, 9, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        assert model.apple_workout_type == "Other"
        # Device name has "Apple Watch Ultra" denormalized, but model number stays hyphenated
        assert model.device_name == "Robert's Apple Watch Ultra-3"

    def test_extract_device_name_with_gzip_suffix(self) -> None:
        """Verify device name extraction handles .fit.gz suffixes."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2025-12-14-183750-Functional-Strength-Training-Robert's-Apple-Watch-7.fit.gz",
            },
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "training",
                    "sub_sport": "functional_training",
                    "timestamp": datetime(2025, 12, 14, 9, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        assert model.device_name == "Robert's Apple Watch-7"

    def test_extract_device_name_from_other_single_word_activity_type(self) -> None:
        """Extract device name for 'Other' single-word activity via normalized lookup."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                # "Other" is single word, device has hyphens (OneDrive corruption)
                "source_file_name": "2025-12-14-183750-Other-Robert's-Apple-Watch-7.fit",
            },
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "unknown_sport",
                    "sub_sport": None,
                    "timestamp": datetime(2025, 12, 14, 9, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        # Should successfully parse "Other" and extract device name
        assert model.filename_components is not None
        assert model.filename_apple_workout_type == "Other"
        assert model.filename_source_device == "Robert's-Apple-Watch-7"
        # Device name denormalized
        assert model.device_name == "Robert's Apple Watch-7"

    def test_extract_device_name_returns_none_when_no_source_filename(self) -> None:
        """Device name returns None when source_file_name is missing."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={},  # type: ignore[call-arg]
        )
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "training",
                    "sub_sport": "functional_training",
                    "timestamp": datetime(2025, 12, 14, 9, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        assert model.device_name is None

    def test_filename_components_returns_none_for_unrecognized_activity_type(self) -> None:
        """Filename parsing fails gracefully for unrecognized activity types."""
        model = HealthFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={  # type: ignore[call-arg]
                "source_file_name": "2025-12-14-183750-UnknownActivityType-Running-Watch.fit",
            },
        )
        
        # "UnknownActivityType" won't be found in normalized lookup table
        assert model.filename_components is None
        assert model.filename_apple_workout_type is None
        assert model.filename_source_device is None
        assert model.device_name is None

    def test_denormalize_device_name_apple_watch(self) -> None:
        """Test denormalization of Apple Watch pattern."""
        # Only "Apple-Watch" pattern is denormalized; other hyphens remained
        result = HealthFitModel._denormalize_device_name("Robert's-Apple-Watch-7")
        assert result == "Robert's Apple Watch-7"

    def test_denormalize_device_name_apple_watch_ultra(self) -> None:
        """Test denormalization of Apple Watch Ultra pattern."""
        result = HealthFitModel._denormalize_device_name("Robert's-Apple-Watch-Ultra-3")
        assert result == "Robert's Apple Watch Ultra-3"

    def test_denormalize_device_name_preserves_ambiguous_hyphens(self) -> None:
        """Test that ambiguous hyphens are preserved."""
        result = HealthFitModel._denormalize_device_name("Some-Unknown-Device-Name")
        assert result == "Some-Unknown-Device-Name"

    def test_denormalize_device_name_mixed_patterns(self) -> None:
        """Test denormalization with multiple known patterns."""
        result = HealthFitModel._denormalize_device_name("Robert's-Apple-Watch-Ultra-3-backup")
        assert result == "Robert's Apple Watch Ultra-3-backup"


class TestConstructedWorkoutNameFallbacks:
    """Tests for constructed fallback naming semantics."""

    def test_constructed_workout_name_uses_daypart_and_apple_type_when_available(self) -> None:
        """Verify that constructed workout name uses daypart and Apple workout type when filename tokens are present."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "cycling",
                    "sub_sport": "indoor_cycling",
                    "timestamp": datetime(2026, 2, 23, 6, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        assert model.workout_name == "Morning Indoor Cycle"

    def test_constructed_workout_name_falls_back_to_fit_fields_and_datetime(self) -> None:
        """Verify that constructed workout name falls back to FIT fields and datetime when filename tokens are missing."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]
        model._session_msg = cast(
            Any,
            _MessageStub(
                {
                    "sport": "kayaking",
                    "timestamp": datetime(2026, 2, 23, 14, 30, 0, tzinfo=timezone.utc),
                    "total_elapsed_time": 0,
                }
            ),
        )
        model._file_id_msg = None

        assert model.workout_name == "kayaking-2026-02-23 14:30"


class TestPayloadModelSourceNormalization:
    """Tests for payload source normalization semantics."""

    def test_payload_model_source_is_http_without_metadata(self) -> None:
        """Verify payload uploads always normalize source system to HTTP."""
        model = PayloadFitModel(file_bytes=b"fit", source_metadata={})  # type: ignore[call-arg]

        assert model.normalized_source_system == "HTTP"

    def test_payload_model_source_is_http_even_with_source_metadata_override(self) -> None:
        """Verify payload source normalization ignores caller-provided source_system."""
        model = PayloadFitModel(
            file_bytes=b"fit",  # type: ignore[call-arg]
            source_metadata={"source_system": "HealthFit"},  # type: ignore[call-arg]
        )

        assert model.normalized_source_system == "HTTP"
