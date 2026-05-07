"""Tests for code_mappings lookup and fallback functions."""

from TrainingAnalyticsPlatform.ingestion.code_mappings import (
    get_apple_product_name,
    get_favero_product_name,
    get_garmin_product_name,
    get_manufacturer_code,
    get_manufacturer_name,
)


class TestGetManufacturerName:
    def test_known_code_returns_name(self) -> None:
        assert get_manufacturer_name(1) == "garmin"

    def test_unknown_code_returns_unknown_prefix(self) -> None:
        assert get_manufacturer_name(9999) == "unknown_9999"

    def test_unknown_code_includes_code_value(self) -> None:
        result = get_manufacturer_name(12345)
        assert "12345" in result


class TestGetManufacturerCode:
    def test_known_name_returns_code(self) -> None:
        assert get_manufacturer_code("garmin") == 1

    def test_case_insensitive_name_lookup(self) -> None:
        assert get_manufacturer_code("GARMIN") == 1

    def test_unknown_name_returns_255(self) -> None:
        assert get_manufacturer_code("nonexistent_manufacturer_zz") == 255


class TestGetGarminProductName:
    def test_known_code_returns_name(self) -> None:
        assert get_garmin_product_name(1) == "hrm1"

    def test_unknown_code_returns_garmin_prefix(self) -> None:
        result = get_garmin_product_name(9999)
        assert result == "garmin_9999"

    def test_unknown_code_includes_code_value(self) -> None:
        result = get_garmin_product_name(55555)
        assert "55555" in result


class TestGetFaveroProductName:
    def test_known_code_assioma_uno(self) -> None:
        assert get_favero_product_name(10) == "assioma_uno"

    def test_known_code_assioma_duo(self) -> None:
        assert get_favero_product_name(12) == "assioma_duo"

    def test_unknown_code_returns_favero_prefix(self) -> None:
        assert get_favero_product_name(9999) == "favero_9999"


class TestGetAppleProductName:
    def test_known_code_returns_iphone(self) -> None:
        assert get_apple_product_name(1) == "iPhone"

    def test_unknown_code_returns_apple_prefix(self) -> None:
        assert get_apple_product_name(9999) == "apple_9999"

    def test_unknown_code_includes_code_value(self) -> None:
        result = get_apple_product_name(77777)
        assert "77777" in result
