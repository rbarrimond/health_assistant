"""Tests for device source classification utilities."""

import pytest

from TrainingAnalyticsPlatform.ingestion.device_classifier import FitDevice


class TestFitDeviceClassifier:
    """Test device source classification logic."""

    def test_is_healthkit_synced_with_iphone(self):
        """iPhone device_name indicates HealthKit synced."""
        assert FitDevice.is_healthkit_synced(device_name="iPhone") is True
        assert FitDevice.is_healthkit_synced(device_name="iPhone 13") is True
        assert FitDevice.is_healthkit_synced(device_name="development iPhone") is True

    def test_is_healthkit_synced_with_apple_watch(self):
        """Apple Watch device_name indicates true source."""
        assert FitDevice.is_healthkit_synced(device_name="Apple Watch Series 5 40mm (GPS)") is False
        assert FitDevice.is_healthkit_synced(device_name="development Watch") is False
        assert FitDevice.is_healthkit_synced(device_name="Apple Watch") is False

    def test_is_healthkit_synced_with_none(self):
        """None device_name conservatively assumes true source."""
        assert FitDevice.is_healthkit_synced(device_name=None) is False

    def test_is_apple_watch_source(self):
        """is_apple_watch_source is inverse of is_healthkit_synced."""
        assert FitDevice.is_apple_watch_source(device_name="Apple Watch Series 5 40mm (GPS)") is True
        assert FitDevice.is_apple_watch_source(device_name="iPhone") is False
        assert FitDevice.is_apple_watch_source(device_name=None) is True

    def test_device_source_type_apple_watch(self):
        """Apple Watch device_name returns 'apple_watch'."""
        assert FitDevice.device_source_type(device_name="Apple Watch Series 5 40mm (GPS)") == "apple_watch"
        assert FitDevice.device_source_type(device_name="development Watch") == "apple_watch"

    def test_device_source_type_healthkit_synced(self):
        """iPhone device_name returns 'healthkit_synced'."""
        assert FitDevice.device_source_type(device_name="iPhone") == "healthkit_synced"
        assert FitDevice.device_source_type(device_name="iPhone 13") == "healthkit_synced"

    def test_device_source_type_unknown(self):
        """Missing or unrecognized device_name returns 'unknown'."""
        assert FitDevice.device_source_type(device_name=None) == "unknown"
        assert FitDevice.device_source_type(device_name="Garmin Edge 520") == "unknown"
        assert FitDevice.device_source_type(device_name="development fenix7") == "unknown"

    def test_device_source_type_case_insensitive(self):
        """Classification is case-insensitive."""
        assert FitDevice.device_source_type(device_name="iphone") == "healthkit_synced"
        assert FitDevice.device_source_type(device_name="IPHONE") == "healthkit_synced"
        assert FitDevice.device_source_type(device_name="apple watch") == "apple_watch"
        assert FitDevice.device_source_type(device_name="WATCH") == "apple_watch"
