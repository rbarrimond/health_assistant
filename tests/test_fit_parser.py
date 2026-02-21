"""Unit tests for FitParser module."""

# Allow protected member access in tests to validate internal caching behavior.
# pylint: disable=protected-access, line-too-long

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from TrainingAnalyticsPlatform.ingestion.fit_parser import FitParser, compute_file_hash


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


class TestFitParserInitialization:
    """Tests for FitParser initialization."""

    def test_init_sets_file_path(self, sample_fit_file: Path) -> None:
        """Verify __init__ stores file path."""
        parser = FitParser(str(sample_fit_file))

        assert parser.file_path == str(sample_fit_file)


class TestFitParserCaching:
    """Tests for message caching."""

    def test_cache_messages_stores_file_id(self, sample_fit_file: Path,
                                           mock_fit_file_with_data: Mock) -> None:
        """Verify _cache_messages stores file_id message."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data

        parser._cache_messages()

        assert parser._file_id_msg is not None
        assert parser.file_id_msg is not None

    def test_cache_messages_stores_session(self, sample_fit_file: Path,
                                           mock_fit_file_with_data: Mock) -> None:
        """Verify _cache_messages stores session message."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data

        parser._cache_messages()

        assert parser._session_msg is not None
        assert parser.session_msg is not None


class TestFitParserIndoorDetection:
    """Tests for indoor workout detection from activity name."""

    def test_get_is_indoor_detects_zwift(self, sample_fit_file: Path,
                                         fit_message_factory: Mock) -> None:
        """Verify _get_is_indoor returns True for Zwift activities."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = "Zwift - Crit City"
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is True

    def test_get_is_indoor_detects_peloton(self, sample_fit_file: Path) -> None:
        """Verify _get_is_indoor returns True for Peloton activities."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = "Peloton Ride"
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is True

    def test_get_is_indoor_detects_indoor_keyword(self, sample_fit_file: Path) -> None:
        """Verify _get_is_indoor returns True for 'indoor' keyword."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = "Indoor Cycling Workout"
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is True

    def test_get_is_indoor_detects_trainer(self, sample_fit_file: Path) -> None:
        """Verify _get_is_indoor returns True for trainer keyword."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = "Smart Trainer Ride"
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is True

    def test_get_is_indoor_detects_stationary(self, sample_fit_file: Path) -> None:
        """Verify _get_is_indoor returns True for stationary keyword."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = "Stationary Bike Session"
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is True

    def test_get_is_indoor_returns_false_for_outdoor(self, sample_fit_file: Path) -> None:
        """Verify _get_is_indoor returns False for outdoor activities."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = "Road Cycle Commute"
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is False

    def test_get_is_indoor_returns_none_without_activity_name(self, sample_fit_file: Path) -> None:
        """Verify _get_is_indoor returns None when activity name unavailable."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = None
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is None

    def test_get_is_indoor_case_insensitive(self, sample_fit_file: Path) -> None:
        """Verify _get_is_indoor keyword matching is case-insensitive."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = []
        parser.source_activity_name = "ZWIFT SESSION"
        parser._cache_messages()

        is_indoor = parser._get_is_indoor()

        assert is_indoor is True


class TestFitParserEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_get_device_name_handles_no_manufacturer(self, sample_fit_file: Path) -> None:
        """Verify _get_device_name handles missing manufacturer field."""
        parser = FitParser(str(sample_fit_file))
        parser._file_id_msg = None

        device_name = parser._get_device_name()

        assert device_name is None

class TestFitMessageLoading:
    """Tests for FitParser loading FIT messages directly."""

    def test_load_fit_sources_sets_messages(self) -> None:
        """Verify _load_fit_sources loads messages and sets self.messages."""
        class DummyFitDataMessage:
            """Dummy FitDataMessage for testing."""
            def __init__(self) -> None:
                self.name = "session"
                self.fields = []
                self.developer_fields = []

        parser = FitParser(file_bytes=b"fit")
        frame = DummyFitDataMessage()
        reader = MagicMock()
        reader.__enter__.return_value = [frame]
        reader.__exit__.return_value = False

        with patch(
            "TrainingAnalyticsPlatform.ingestion.fit_parser.fitdecode.FitReader",
            return_value=reader,
        ) as loader, patch(
            "TrainingAnalyticsPlatform.ingestion.fit_parser.fitdecode.FitDataMessage",
            DummyFitDataMessage,
        ):
            parser._load_fit_sources()

        loader.assert_called_once()
        assert parser.messages == [frame]


class TestFitAnalysis:
    """Tests for extract_fit_analysis payload."""

    def test_extract_fit_analysis_contains_structured_sections(self, sample_fit_file: Path,
                                                               fit_message_factory: Mock) -> None:
        """Verify extract_fit_analysis returns payload with expected sections."""
        parser = FitParser(str(sample_fit_file))
        dev_field = MagicMock()
        dev_field.name = "pedal_smoothness"
        dev_field.value = 23.5
        dev_field.units = "%"
        parser.messages = [
            fit_message_factory(
                "session",
                {
                    "sub_sport": "virtual_activity",
                },
            ),
            fit_message_factory(
                "record",
                {
                    "position_lat": 1,
                    "position_long": 2,
                },
                developer_fields=[dev_field],
            ),
        ]

        payload = parser.extract_fit_analysis()

        assert payload["analysis_version"] == "v1.0.0"
        assert "message_inventory" in payload
        assert "classification_evidence" in payload
        assert "developer_fields_summary" in payload
        assert payload["developer_fields_summary"]["field_count"] >= 1
