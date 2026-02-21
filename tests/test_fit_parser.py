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


class TestFitParserSportExtraction:
    """Tests for sport-related field extraction."""

    def test_get_sport_extracts_enum_name(self, sample_fit_file: Path,
                                         mock_fit_file_with_data: Mock) -> None:
        """Verify _get_sport extracts and lowercases sport type."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        sport = parser._get_sport()

        assert sport == "cycling"

    def test_get_sport_returns_none_without_file_id(self, sample_fit_file: Path) -> None:
        """Verify _get_sport returns None if no file_id message."""
        parser = FitParser(str(sample_fit_file))
        parser._file_id_msg = None

        sport = parser._get_sport()

        assert sport is None

    def test_get_sub_sport_extracts_enum_name(self, sample_fit_file: Path,
                                              mock_fit_file_with_data: Mock) -> None:
        """Verify _get_sub_sport extracts and lowercases sub-sport type."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        sub_sport = parser._get_sub_sport()

        assert sub_sport == "road"

    def test_get_sport_handles_string_values(self, sample_fit_file: Path,
                                              fit_message_factory: Mock) -> None:
        """Verify _get_sport handles both enum and string values from fitparse."""
        parser = FitParser(str(sample_fit_file))

        # Create message list with file_id message containing sport
        messages = [fit_message_factory("file_id", {"type": "cycling"})]
        parser.messages = messages
        parser._cache_messages()

        sport = parser._get_sport()

        assert sport == "cycling"

    def test_get_sub_sport_handles_string_values(self, sample_fit_file: Path,
                                                 fit_message_factory: Mock) -> None:
        """Verify _get_sub_sport handles both enum and string values."""
        parser = FitParser(str(sample_fit_file))

        # Create message list with session message containing sub_sport
        messages = [fit_message_factory("session", {"sub_sport": "indoor_cycling"})]
        parser.messages = messages
        parser._cache_messages()

        sub_sport = parser._get_sub_sport()

        assert sub_sport == "indoor_cycling"


class TestFitParserTimeExtraction:
    """Tests for time-related field extraction."""

    def test_get_start_time_returns_utc_iso_format(self, sample_fit_file: Path,
                                                   mock_fit_file_with_data: Mock) -> None:
        """Verify _get_start_time returns ISO format UTC timestamp."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        start_time = parser._get_start_time()

        assert start_time is not None
        assert isinstance(start_time, str)
        assert "2024-01-15" in start_time

    def test_get_duration_returns_int_seconds(self, sample_fit_file: Path,
                                              mock_fit_file_with_data: Mock) -> None:
        """Verify _get_duration returns total elapsed time in seconds."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        duration = parser._get_duration()

        assert isinstance(duration, int)
        assert duration == 3600

    def test_get_duration_returns_none_without_session(self, sample_fit_file: Path) -> None:
        """Verify _get_duration returns None without session message."""
        parser = FitParser(str(sample_fit_file))
        parser._session_msg = None

        duration = parser._get_duration()

        assert duration is None


class TestFitParserDistanceExtraction:
    """Tests for distance-related field extraction."""

    def test_get_distance_returns_float(self, sample_fit_file: Path,
                                        mock_fit_file_with_data: Mock) -> None:
        """Verify _get_distance returns total distance in meters."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        distance = parser._get_distance()

        assert isinstance(distance, float)
        assert distance == pytest.approx(42000.0, rel=0.01)

    def test_get_elevation_gain_returns_float(self, sample_fit_file: Path,
                                              mock_fit_file_with_data: Mock) -> None:
        """Verify _get_elevation_gain returns gain in meters."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        elevation_gain = parser._get_elevation_gain()

        assert isinstance(elevation_gain, float)
        assert elevation_gain == pytest.approx(500.0, rel=0.01)


class TestFitParserSpeedExtraction:
    """Tests for speed-related field extraction."""

    def test_get_avg_speed_returns_float(self, sample_fit_file: Path,
                                         mock_fit_file_with_data: Mock) -> None:
        """Verify _get_avg_speed returns average speed in m/s."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        avg_speed = parser._get_avg_speed()

        assert isinstance(avg_speed, float)
        assert avg_speed == pytest.approx(11.67, rel=0.01)

    def test_get_max_speed_returns_float(self, sample_fit_file: Path,
                                         mock_fit_file_with_data: Mock) -> None:
        """Verify _get_max_speed returns maximum speed in m/s."""
        parser = FitParser(str(sample_fit_file))
        parser.messages = mock_fit_file_with_data
        parser._cache_messages()

        max_speed = parser._get_max_speed()

        assert isinstance(max_speed, float)
        assert max_speed == pytest.approx(15.5, rel=0.01)


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
                    "indoor": None,
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
