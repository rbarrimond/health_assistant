"""Unit tests for FitParser module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from FitParser.fit_parser import FitParser, compute_file_hash


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

    def test_init_initializes_empty_state(self, sample_fit_file: Path) -> None:
        """Verify __init__ initializes parser state."""
        parser = FitParser(str(sample_fit_file))
        
        assert parser.fit is None
        assert parser.metrics == {}
        assert parser._file_id_msg is None
        assert parser._session_msg is None
        assert parser._records is None


class TestFitParserCaching:
    """Tests for message caching."""

    def test_cache_messages_stores_file_id(self, sample_fit_file: Path, 
                                           mock_fit_file_with_data: Mock) -> None:
        """Verify _cache_messages stores file_id message."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
        
        parser._cache_messages()
        
        assert parser._file_id_msg is not None
        assert parser._get_file_id_msg() is not None

    def test_cache_messages_stores_session(self, sample_fit_file: Path, 
                                           mock_fit_file_with_data: Mock) -> None:
        """Verify _cache_messages stores session message."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
        
        parser._cache_messages()
        
        assert parser._session_msg is not None
        assert parser._get_session_msg() is not None

    def test_get_records_caches_on_first_call(self, sample_fit_file: Path,
                                              mock_fit_file_with_records: Mock) -> None:
        """Verify _get_records caches results."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_records
        
        records1 = parser._get_records()
        records2 = parser._get_records()
        
        # Should return same object (cached)
        assert records1 is records2


class TestFitParserFieldExtraction:
    """Tests for field extraction methods."""

    def test_get_field_from_msg_returns_value(self, sample_fit_file: Path) -> None:
        """Verify _get_field_from_msg extracts field value."""
        parser = FitParser(str(sample_fit_file))
        
        msg = MagicMock()
        field = MagicMock(value=42)
        msg.get.return_value = field
        
        result = parser._get_field_from_msg(msg, "test_field")
        
        assert result == 42

    def test_get_field_from_msg_handles_none_message(self, sample_fit_file: Path) -> None:
        """Verify _get_field_from_msg handles None message."""
        parser = FitParser(str(sample_fit_file))
        
        result = parser._get_field_from_msg(None, "test_field")
        
        assert result is None

    def test_get_field_from_msg_handles_missing_field(self, sample_fit_file: Path) -> None:
        """Verify _get_field_from_msg handles missing field."""
        parser = FitParser(str(sample_fit_file))
        
        msg = MagicMock()
        msg.get.return_value = None
        
        result = parser._get_field_from_msg(msg, "nonexistent_field")
        
        assert result is None


class TestFitParserSportExtraction:
    """Tests for sport-related field extraction."""

    def test_get_sport_extracts_enum_name(self, sample_fit_file: Path,
                                         mock_fit_file_with_data: Mock) -> None:
        """Verify _get_sport extracts and lowercases sport type."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
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
        parser.fit = mock_fit_file_with_data
        parser._cache_messages()
        
        sub_sport = parser._get_sub_sport()
        
        assert sub_sport == "road"


class TestFitParserTimeExtraction:
    """Tests for time-related field extraction."""

    def test_get_start_time_returns_utc_iso_format(self, sample_fit_file: Path,
                                                   mock_fit_file_with_data: Mock) -> None:
        """Verify _get_start_time returns ISO format UTC timestamp."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
        parser._cache_messages()
        
        start_time = parser._get_start_time()
        
        assert start_time is not None
        assert isinstance(start_time, str)
        assert "2024-01-15" in start_time

    def test_get_duration_returns_int_seconds(self, sample_fit_file: Path,
                                              mock_fit_file_with_data: Mock) -> None:
        """Verify _get_duration returns total elapsed time in seconds."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
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
        parser.fit = mock_fit_file_with_data
        parser._cache_messages()
        
        distance = parser._get_distance()
        
        assert isinstance(distance, float)
        assert distance == 42000.0

    def test_get_elevation_gain_returns_float(self, sample_fit_file: Path,
                                              mock_fit_file_with_data: Mock) -> None:
        """Verify _get_elevation_gain returns gain in meters."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
        parser._cache_messages()
        
        elevation_gain = parser._get_elevation_gain()
        
        assert isinstance(elevation_gain, float)
        assert elevation_gain == 500.0


class TestFitParserSpeedExtraction:
    """Tests for speed-related field extraction."""

    def test_get_avg_speed_returns_float(self, sample_fit_file: Path,
                                         mock_fit_file_with_data: Mock) -> None:
        """Verify _get_avg_speed returns average speed in m/s."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
        parser._cache_messages()
        
        avg_speed = parser._get_avg_speed()
        
        assert isinstance(avg_speed, float)
        assert avg_speed == 11.67

    def test_get_max_speed_returns_float(self, sample_fit_file: Path,
                                         mock_fit_file_with_data: Mock) -> None:
        """Verify _get_max_speed returns maximum speed in m/s."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_data
        parser._cache_messages()
        
        max_speed = parser._get_max_speed()
        
        assert isinstance(max_speed, float)
        assert max_speed == 15.5


class TestFitParserHeartRateExtraction:
    """Tests for heart rate field extraction."""

    def test_get_hr_avg_returns_int(self, sample_fit_file: Path,
                                    mock_fit_file_with_records: Mock) -> None:
        """Verify _get_hr_avg returns average heart rate in bpm."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_records
        
        hr_avg = parser._get_hr_avg()
        
        assert isinstance(hr_avg, float)
        # Average computed from record data
        assert 155 < hr_avg < 157

    def test_get_hr_max_returns_int(self, sample_fit_file: Path,
                                    mock_fit_file_with_records: Mock) -> None:
        """Verify _get_hr_max returns maximum heart rate in bpm."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_records
        
        hr_max = parser._get_hr_max()
        
        assert isinstance(hr_max, float)
        # Max of [140, 145, 150, 155, 160, 165, 170, 165, 160, 155] = 170
        assert hr_max == 170.0


class TestFitParserRecordDataExtraction:
    """Tests for record message data extraction."""

    def test_get_record_data_extracts_all_values(self, sample_fit_file: Path,
                                                 mock_fit_file_with_records: Mock) -> None:
        """Verify _get_record_data extracts array of values from records."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_records
        
        heart_rates = parser._get_record_data("heart_rate")
        
        assert len(heart_rates) == 10
        assert all(isinstance(hr, int) for hr in heart_rates)
        assert heart_rates[0] == 140

    def test_get_record_data_returns_empty_list_no_data(self, sample_fit_file: Path,
                                                        mock_fit_file_with_records: Mock) -> None:
        """Verify _get_record_data returns empty list if field missing."""
        parser = FitParser(str(sample_fit_file))
        parser.fit = mock_fit_file_with_records
        
        missing_field = parser._get_record_data("nonexistent_field")
        
        assert missing_field == []


class TestFitParserZoneComputation:
    """Tests for HR and power zone computation."""

    def test_get_hr_zones_hrmax_basis(self, sample_fit_file: Path) -> None:
        """Verify _get_hr_zones returns correct zones for HRmax method."""
        parser = FitParser(str(sample_fit_file))
        
        zones = parser._get_hr_zones("HRmax", 200)
        
        assert len(zones) == 5
        assert zones["hr_z1"] == (100, 120)
        assert zones["hr_z2"] == (120, 140)
        assert zones["hr_z5"] == (180, 200)

    def test_get_hr_zones_lthr_basis(self, sample_fit_file: Path) -> None:
        """Verify _get_hr_zones returns correct zones for LTHR method."""
        parser = FitParser(str(sample_fit_file))
        
        zones = parser._get_hr_zones("LTHR", 180)
        
        assert len(zones) == 5
        assert zones["hr_z1"][0] == 117  # 180 * 0.65

    def test_get_hr_zones_hrr_basis(self, sample_fit_file: Path) -> None:
        """Verify _get_hr_zones returns correct zones for HRR (Karvonen) method."""
        parser = FitParser(str(sample_fit_file))
        
        zones = parser._get_hr_zones("HRR", 200, hr_rest=60)
        
        assert len(zones) == 5
        # HRR = 200 - 60 = 140
        # Z1: 140 * 0.50 + 60 = 130
        assert zones["hr_z1"][0] == 130

    def test_get_reference_bpm_uses_provided_value(self, sample_fit_file: Path) -> None:
        """Verify _get_reference_bpm returns provided reference_bpm."""
        parser = FitParser(str(sample_fit_file))
        
        ref = parser._get_reference_bpm("HRmax", reference_bpm=190)
        
        assert ref == 190

    def test_get_reference_bpm_derives_from_metrics(self, sample_fit_file: Path) -> None:
        """Verify _get_reference_bpm derives from metrics if not provided."""
        parser = FitParser(str(sample_fit_file))
        parser.metrics = {"hr_max_bpm": 185}
        
        ref = parser._get_reference_bpm("HRmax")
        
        assert ref == 185

    def test_get_reference_bpm_applies_lthr_factor(self, sample_fit_file: Path) -> None:
        """Verify _get_reference_bpm applies 90% factor for LTHR."""
        parser = FitParser(str(sample_fit_file))
        parser.metrics = {"hr_max_bpm": 200}
        
        ref = parser._get_reference_bpm("LTHR")
        
        assert ref == 180.0  # 200 * 0.90

    def test_compute_hr_zones_missing_data(self, sample_fit_file: Path) -> None:
        """Verify _compute_hr_zones handles missing heart rate data."""
        parser = FitParser(str(sample_fit_file))
        parser.metrics = {}
        
        # Should return early without error
        parser._compute_hr_zones()
        
        # No zones should be computed
        assert not any(k.startswith("hr_z") for k in parser.metrics.keys())


class TestFitParserFullParse:
    """Integration tests for full parse workflow."""

    def test_parse_returns_dict(self, sample_fit_file: Path,
                               mock_fit_file_with_records: Mock) -> None:
        """Verify parse() returns a dictionary."""
        parser = FitParser(str(sample_fit_file))
        
        with patch("fitparse.FitFile", return_value=mock_fit_file_with_records):
            result = parser.parse()
        
        assert isinstance(result, dict)

    def test_parse_includes_required_keys(self, sample_fit_file: Path,
                                         mock_fit_file_with_records: Mock) -> None:
        """Verify parse() includes expected metric keys."""
        parser = FitParser(str(sample_fit_file))
        
        with patch("fitparse.FitFile", return_value=mock_fit_file_with_records):
            result = parser.parse()
        
        required_keys = [
            "sport", "sub_sport", "device_name",
            "start_time_utc", "duration_sec", "distance_m",
            "elevation_gain_m", "avg_speed_mps", "max_speed_mps",
            "hr_avg_bpm", "hr_max_bpm"
        ]
        
        for key in required_keys:
            assert key in result

    def test_parse_extracts_sport_correctly(self, sample_fit_file: Path,
                                           mock_fit_file_with_records: Mock) -> None:
        """Verify parse() correctly extracts sport from file."""
        parser = FitParser(str(sample_fit_file))
        
        with patch("fitparse.FitFile", return_value=mock_fit_file_with_records):
            result = parser.parse()
        
        assert result["sport"] == "cycling"
        assert result["sub_sport"] == "road"

    def test_parse_computes_hr_zones_when_data_available(self, sample_fit_file: Path,
                                                          mock_fit_file_with_records: Mock) -> None:
        """Verify parse() computes HR zones when HR data exists."""
        parser = FitParser(str(sample_fit_file))
        parser.metrics = {"hr_max_bpm": 185}
        
        with patch("fitparse.FitFile", return_value=mock_fit_file_with_records):
            result = parser.parse()
        
        # Should have computed HR zones
        assert "hr_zone_basis" in result or result.get("hr_avg_bpm") is None

    def test_parse_handles_missing_fit_file(self, tmp_path: Path) -> None:
        """Verify parse() handles file not found error."""
        parser = FitParser(str(tmp_path / "nonexistent.fit"))
        
        with pytest.raises(Exception):
            parser.parse()


class TestFitParserEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_get_device_name_handles_no_manufacturer(self, sample_fit_file: Path) -> None:
        """Verify _get_device_name handles missing manufacturer field."""
        parser = FitParser(str(sample_fit_file))
        parser._file_id_msg = None
        
        device_name = parser._get_device_name()
        
        assert device_name is None

    def test_zero_values_handled_correctly(self, sample_fit_file: Path) -> None:
        """Verify parser correctly handles zero metric values."""
        parser = FitParser(str(sample_fit_file))
        
        msg = MagicMock()
        field = MagicMock(value=0)
        msg.get.return_value = field
        
        result = parser._get_field_from_msg(msg, "test_field")
        
        # Should return 0, not None
        assert result == 0

    def test_none_record_data_handling(self, sample_fit_file: Path) -> None:
        """Verify _get_record_data filters out None values."""
        parser = FitParser(str(sample_fit_file))
        
        fit_file = MagicMock()
        records = []
        
        # Create records with None and valid values
        for value in [None, 100, None, 150, 200]:
            record = MagicMock()
            record.get.return_value = MagicMock(value=value) if value else None
            records.append(record)
        
        fit_file.get_messages.return_value = records
        parser.fit = fit_file
        
        data = parser._get_record_data("test_field")
        
        # Should only include non-None values
        assert len(data) == 3
        assert data == [100, 150, 200]
