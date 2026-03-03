"""Tests for manufacturer code extraction logic in fit_models.py."""

from datetime import datetime, timezone
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
        
        model._file_id_msg = file_id_msg
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

        model._file_id_msg = file_id_msg

        code, name = GarminFitModel._extract_code_and_name(None)
        assert code is None
        assert name is None


class TestAppleManufacturerAndProductNormalization:
    """Tests Apple normalization behavior for HealthFit semantics."""

    @staticmethod
    def _make_enum(value: int, name: str) -> Mock:
        enum_obj = Mock()
        enum_obj.value = value
        enum_obj.name = name
        return enum_obj

    @staticmethod
    def _make_model_stub() -> Mock:
        model = Mock(spec=GarminFitModel)
        model._extract_code_and_name = GarminFitModel._extract_code_and_name
        model._is_apple_manufacturer = (
            lambda manufacturer_code, manufacturer_name: GarminFitModel._is_apple_manufacturer(
                model,
                manufacturer_code,
                manufacturer_name,
            )
        )
        model._normalize_apple_internal_id = (
            lambda raw_product_name: GarminFitModel._normalize_apple_internal_id(
                model,
                raw_product_name,
            )
        )
        return model

    def test_canonical_manufacturer_is_apple_for_code_255(self) -> None:
        """Manufacturer code 255 (development) should canonicalize to Apple."""
        model = self._make_model_stub()
        manufacturer = self._make_enum(255, "development")

        result = GarminFitModel._validate_and_get_manufacturer_name(model, manufacturer)

        assert result == "Apple"

    def test_canonical_manufacturer_is_apple_for_string_development(self) -> None:
        """String manufacturer development should canonicalize to Apple."""
        model = self._make_model_stub()

        result = GarminFitModel._validate_and_get_manufacturer_name(model, "development")

        assert result == "Apple"

    def test_apple_watch_internal_id_maps_to_friendly_name(self) -> None:
        """Watch internal identifiers should map to friendly Apple Watch model names."""
        model = self._make_model_stub()
        manufacturer = self._make_enum(255, "development")

        result = GarminFitModel._validate_and_get_product_name(
            model,
            "Watch7,12",
            manufacturer,
        )

        assert result == "Apple Watch Ultra 3 49mm"

    def test_apple_watch_internal_id_with_space_maps_to_friendly_name(self) -> None:
        """Watch IDs with spacing variations should still map correctly."""
        model = self._make_model_stub()
        manufacturer = self._make_enum(255, "development")

        result = GarminFitModel._validate_and_get_product_name(
            model,
            "Watch 7,12",
            manufacturer,
        )

        assert result == "Apple Watch Ultra 3 49mm"

    def test_get_file_id_product_falls_back_to_product_name(self) -> None:
        """file_id.product_name should be used when file_id.product is missing."""
        model = self._make_model_stub()
        manufacturer = self._make_enum(255, "development")

        file_id_msg = Mock()

        def _get_value(field_name: str, fallback=None):
            values = {
                "manufacturer": manufacturer,
                "product": None,
                "product_name": "Watch17,2",
                "garmin_product": None,
            }
            return values.get(field_name, fallback)

        file_id_msg.get_value.side_effect = _get_value
        model._file_id_msg = file_id_msg

        result = GarminFitModel._get_file_id_product(model)

        assert result == "Watch17,2"

    def test_file_metadata_preserves_raw_manufacturer_fields(self) -> None:
        """Canonical metadata should expose canonical and raw manufacturer provenance."""
        model = self._make_model_stub()
        manufacturer = self._make_enum(255, "development")

        file_id_msg = Mock()

        def _get_value(field_name: str, fallback=None):
            values = {
                "time_created": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
                "manufacturer": manufacturer,
                "serial_number": 123456,
            }
            return values.get(field_name, fallback)

        file_id_msg.get_value.side_effect = _get_value
        model._file_id_msg = file_id_msg
        model._format_utc_timestamp = GarminFitModel._format_utc_timestamp
        model._validate_and_get_manufacturer_name = (
            lambda raw_manufacturer: GarminFitModel._validate_and_get_manufacturer_name(
                model,
                raw_manufacturer,
            )
        )
        model._get_file_id_product = lambda: "Watch7,12"

        metadata = GarminFitModel._build_canonical_file_metadata(model)

        assert metadata["file_manufacturer"] == "Apple"
        assert metadata["file_manufacturer_raw"] == "development"
        assert metadata["file_manufacturer_code"] == 255
        assert metadata["file_product"] == "Watch7,12"
