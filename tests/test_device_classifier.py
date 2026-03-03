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
        """is_apple_watch_source requires explicit watch indicators."""
        assert FitDevice.is_apple_watch_source(device_name="Apple Watch Series 5 40mm (GPS)") is True
        assert FitDevice.is_apple_watch_source(device_name="iPhone") is False
        assert FitDevice.is_apple_watch_source(device_name=None) is False

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
    def test_is_healthkit_synced_with_iphone_model_identifier(self):
        """iPhone model identifier in device_model indicates HealthKit synced."""
        # Common iPhone model identifiers
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="iPhone17,1") is True
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="iPhone14,2") is True
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="iPhone13,4") is True
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="iPhone12,1") is True
        
        # Case insensitive
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="iphone17,1") is True
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="IPHONE14,2") is True

    def test_is_healthkit_synced_with_watch_model_identifier(self):
        """Watch model identifier in device_model indicates Apple Watch source."""
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="Watch7,12") is False
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="Watch8,1") is False
        assert FitDevice.is_healthkit_synced(device_name=None, device_model="watch7,12") is False

    def test_is_healthkit_synced_device_model_overrides_missing_device_name(self):
        """device_model iPhone identifier catches synced workouts even when device_name is non-iPhone."""
        # Scenario: RunGap syncs workout, filename device="RunGap", FIT device_model="iPhone17,1"
        assert FitDevice.is_healthkit_synced(device_name="RunGap", device_model="iPhone17,1") is True
        assert FitDevice.is_healthkit_synced(device_name="Zwift", device_model="iPhone14,2") is True
        assert FitDevice.is_healthkit_synced(device_name="Intervals.icu", device_model="iPhone13,4") is True

    def test_device_source_type_with_iphone_model_identifier(self):
        """iPhone model identifier in device_model returns 'healthkit_synced'."""
        assert FitDevice.device_source_type(device_name=None, device_model="iPhone17,1") == "healthkit_synced"
        assert FitDevice.device_source_type(device_name=None, device_model="iPhone14,2") == "healthkit_synced"
        
        # Works even with non-iPhone device_name
        assert FitDevice.device_source_type(device_name="RunGap", device_model="iPhone17,1") == "healthkit_synced"

    def test_device_source_type_with_watch_model_identifier(self):
        """Watch model identifier in device_model returns 'apple_watch'."""
        assert FitDevice.device_source_type(device_name=None, device_model="Watch7,12") == "apple_watch"
        assert FitDevice.device_source_type(device_name=None, device_model="Watch8,1") == "apple_watch"
        assert FitDevice.device_source_type(device_name="Apple Watch", device_model="Watch7,12") == "apple_watch"