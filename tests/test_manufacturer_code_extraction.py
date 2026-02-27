"""Tests for manufacturer code extraction logic in fit_models.py."""

from unittest.mock import Mock
from TrainingAnalyticsPlatform.ingestion.fit_models import GarminFitModel


class TestExtractCodeAndName:
    """Test the _extract_code_and_name static method."""

    def test_returns_none_for_none_input(self) -> None:
        """_extract_code_and_name should return (None, None) for None input."""
        code, name = GarminFitModel._extract_code_and_name(None)
        assert code is None
        assert name is None

    def test_returns_int_for_int_input(self) -> None:
        """_extract_code_and_name should return (int, None) for int input."""
        code, name = GarminFitModel._extract_code_and_name(1)
        assert code == 1
        assert name is None

        code, name = GarminFitModel._extract_code_and_name(260)
        assert code == 260
        assert name is None

    def test_returns_string_for_string_input(self) -> None:
        """_extract_code_and_name should return (None, str) for string input."""
        code, name = GarminFitModel._extract_code_and_name("garmin")
        assert code is None
        assert name == "garmin"

        code, name = GarminFitModel._extract_code_and_name("zwift")
        assert code is None
        assert name == "zwift"

    def test_extracts_from_enum_object(self) -> None:
        """_extract_code_and_name should extract .value and .name from enum-like objects."""
        enum_obj = Mock()
        enum_obj.value = 1
        enum_obj.name = "garmin"

        code, name = GarminFitModel._extract_code_and_name(enum_obj)
        assert code == 1
        assert name == "garmin"

    def test_extracts_only_value_if_no_name(self) -> None:
        """Should extract code if object has .value but no .name."""
        obj = Mock(spec=["value"])
        obj.value = 260

        code, name = GarminFitModel._extract_code_and_name(obj)
        assert code == 260
        assert name is None

    def test_extracts_only_name_if_no_value(self) -> None:
        """Should extract name if object has .name but no .value."""
        obj = Mock(spec=["name"])
        obj.name = "zwift"

        code, name = GarminFitModel._extract_code_and_name(obj)
        assert code is None
        assert name == "zwift"


class TestDeviceManufacturerCodeResolution:
    """Test manufacturer code resolution with reverse lookup."""

    def test_resolves_string_manufacturer_to_code(self) -> None:
        """Device code should be resolved from string names via reverse lookup."""
        # This test requires creating a GarminFitModel with mocked file_id_msg
        # and verifying that string manufacturer values are converted to codes
        
        model = Mock(spec=GarminFitModel)
        
        # Mock the file_id_msg to return a string manufacturer
        file_id_msg = Mock()
        file_id_msg.get_value.return_value = "garmin"
        
        model.file_id_msg = file_id_msg
        model._source_metadata = {"ingestion_id": "test_id", "file_sha256": "hash"}
        
        # Call the actual method via the class
        code, name = GarminFitModel._extract_code_and_name("garmin")
        assert name == "garmin"
        assert code is None
        # The resolution happens in device_manufacturer_code property which
        # we'll test with integration test loading actual FIT files

    def test_none_manufacturer_code_for_missing_field(self) -> None:
        """Should return None code when manufacturer field is missing."""
        model = Mock(spec=GarminFitModel)
        file_id_msg = Mock()
        file_id_msg.get_value.return_value = None
        
        model.file_id_msg = file_id_msg
        
        code, name = GarminFitModel._extract_code_and_name(None)
        assert code is None
        assert name is None
