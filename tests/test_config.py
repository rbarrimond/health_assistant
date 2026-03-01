"""Unit tests for Config and physiometrics management."""

# Allow protected member access in tests for internal state verification.
# pylint: disable=protected-access

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from TrainingAnalyticsPlatform.platform.config import Config, HeartRateConfig, PowerConfig


class TestHeartRateConfigDataclass:
    """Tests for HeartRateConfig dataclass."""

    def test_heart_rate_config_creation(self) -> None:
        """Verify HeartRateConfig instantiation."""
        hr_cfg = HeartRateConfig(
            basis="HRmax",
            lthr_bpm=175,
            hr_max_bpm=195,
            resting_hr_bpm=52,
            zones={"z1": {"label": "Recovery"}}
        )

        assert hr_cfg.basis == "HRmax"
        assert hr_cfg.lthr_bpm == 175
        assert hr_cfg.hr_max_bpm == 195
        assert hr_cfg.resting_hr_bpm == 52
        assert "z1" in hr_cfg.zones

    def test_heart_rate_config_frozen(self) -> None:
        """Verify HeartRateConfig is immutable."""
        hr_cfg = HeartRateConfig(
            basis="HRmax",
            lthr_bpm=None,
            hr_max_bpm=None,
            resting_hr_bpm=60,
            zones={}
        )

        with pytest.raises(AttributeError):
            hr_cfg.basis = "LTHR"  # type: ignore


class TestPowerConfigDataclass:
    """Tests for PowerConfig dataclass."""

    def test_power_config_creation(self) -> None:
        """Verify PowerConfig instantiation."""
        pwr_cfg = PowerConfig(
            ftp_watts=285,
            zones={"z1": {"label": "Recovery"}}
        )

        assert pwr_cfg.ftp_watts == 285
        assert "z1" in pwr_cfg.zones

    def test_power_config_frozen(self) -> None:
        """Verify PowerConfig is immutable."""
        pwr_cfg = PowerConfig(
            ftp_watts=250,
            zones={}
        )

        with pytest.raises(AttributeError):
            pwr_cfg.ftp_watts = 300  # type: ignore


class TestConfigPhysiometricsFile:
    """Tests for physiometrics file discovery."""

    def test_physiometrics_file_default_location(self) -> None:
        """Verify default location is config/physiometrics.json."""
        path = Config.physiometrics_file()
        assert "config" in str(path)
        assert "physiometrics.json" in str(path)

    def test_physiometrics_file_expanduser(self) -> None:
        """Verify ~ expansion in path."""
        rel_path = "~/custom_config.json"
        with patch.dict(os.environ, {"PHYSIOMETRICS_PATH": rel_path}):
            # Update class var to reflect env change
            Config.PHYSIOMETRICS_PATH = rel_path
            path = Config.physiometrics_file()
            assert "~" not in str(path)
            # Reset
            Config.PHYSIOMETRICS_PATH = None


class TestConfigLoadPhysiometrics:
    """Tests for loading physiometrics from filesystem."""

    def test_load_physiometrics_from_file(self, tmp_path: Path) -> None:
        """Verify loading JSON from filesystem."""
        config_data = {
            "heart_rate": {"basis": "HRmax", "hr_max_bpm": 195},
            "power": {"ftp_watts": 285}
        }
        config_file = tmp_path / "physio.json"
        config_file.write_text(json.dumps(config_data))

        with patch.object(Config, "physiometrics_file", return_value=config_file):
            Config._physiometrics_cache = None  # Reset cache
            result = Config.load_physiometrics()

        assert result == config_data
        assert Config._physiometrics_cache == config_data

    def test_load_physiometrics_caches_result(self, tmp_path: Path) -> None:
        """Verify caching of loaded config."""
        config_data = {"heart_rate": {"basis": "HRmax"}, "power": {}}
        config_file = tmp_path / "physio.json"
        config_file.write_text(json.dumps(config_data))

        with patch.object(Config, "physiometrics_file", return_value=config_file):
            Config._physiometrics_cache = None
            result1 = Config.load_physiometrics()
            result2 = Config.load_physiometrics()

        assert result1 is result2  # Same object (cached)

    def test_load_physiometrics_force_reload(self, tmp_path: Path) -> None:
        """Verify force_reload bypasses cache."""
        config_file = tmp_path / "physio.json"
        config_file.write_text(json.dumps({"heart_rate": {"basis": "HRmax"}}))

        with patch.object(Config, "physiometrics_file", return_value=config_file):
            Config._physiometrics_cache = {"cached": "data"}
            result = Config.load_physiometrics(force_reload=True)

        assert result == {"heart_rate": {"basis": "HRmax"}}

    def test_load_physiometrics_file_not_found(self) -> None:
        """Verify returns None if file doesn't exist."""
        nonexistent = Path("/nonexistent/path/physio.json")

        with patch.object(Config, "physiometrics_file", return_value=nonexistent):
            Config._physiometrics_cache = None
            result = Config.load_physiometrics()

        assert result is None


class TestConfigHrConfig:
    """Tests for HR configuration loading."""

    def test_hr_config_defaults(self) -> None:
        """Verify HR config uses defaults when no config present."""
        with patch.dict(os.environ, {
            "HR_ZONE_BASIS": "",
            "HR_ZONE_REFERENCE_BPM": "",
            "HR_RESTING_BPM": ""
        }):
            with patch.object(Config, "load_physiometrics", return_value=None):
                Config._physiometrics_cache = None
                hr_cfg = Config.hr_config()

        assert hr_cfg.basis == "HRmax"
        assert hr_cfg.resting_hr_bpm == 60

    def test_hr_config_env_override_basis(self) -> None:
        """Verify environment variable overrides basis."""
        with patch.dict(os.environ, {"HR_ZONE_BASIS": "LTHR"}):
            with patch.object(Config, "load_physiometrics", return_value=None):
                Config._physiometrics_cache = None
                hr_cfg = Config.hr_config()

        assert hr_cfg.basis == "LTHR"

    def test_hr_config_env_override_resting_hr(self) -> None:
        """Verify environment variable overrides resting HR."""
        with patch.dict(os.environ, {"HR_RESTING_BPM": "50"}):
            with patch.object(Config, "load_physiometrics", return_value=None):
                Config._physiometrics_cache = None
                hr_cfg = Config.hr_config()

        assert hr_cfg.resting_hr_bpm == 50

    def test_hr_config_from_physiometrics_file(self) -> None:
        """Verify loading from physiometrics.json."""
        config_data = {
            "heart_rate": {
                "basis": "HRR",
                "lthr_bpm": 170,
                "hr_max_bpm": 190,
                "resting_hr_bpm": 48,
                "zones": {}
            }
        }

        with patch.object(Config, "load_physiometrics", return_value=config_data):
            Config._physiometrics_cache = None
            hr_cfg = Config.hr_config()

        assert hr_cfg.basis == "HRR"
        assert hr_cfg.lthr_bpm == 170
        assert hr_cfg.hr_max_bpm == 190
        assert hr_cfg.resting_hr_bpm == 48

    def test_hr_config_zones_default(self) -> None:
        """Verify default HR zones when not configured."""
        with patch.object(Config, "load_physiometrics", return_value=None):
            Config._physiometrics_cache = None
            hr_cfg = Config.hr_config()

        assert len(hr_cfg.zones) > 0
        assert all(f"z{i}" in hr_cfg.zones for i in range(1, 6))


class TestConfigPowerConfig:
    """Tests for power configuration loading."""

    def test_power_config_defaults(self) -> None:
        """Verify power config defaults to 250W FTP."""
        with patch.dict(os.environ, {"DEFAULT_FTP": ""}):
            with patch.object(Config, "load_physiometrics", return_value=None):
                Config._physiometrics_cache = None
                pwr_cfg = Config.power_config()

        assert pwr_cfg.ftp_watts == 250

    def test_power_config_env_override(self) -> None:
        """Verify environment variable overrides FTP."""
        with patch.dict(os.environ, {"DEFAULT_FTP": "320"}):
            with patch.object(Config, "load_physiometrics", return_value=None):
                Config._physiometrics_cache = None
                pwr_cfg = Config.power_config()

        assert pwr_cfg.ftp_watts == 320

    def test_power_config_from_physiometrics_file(self) -> None:
        """Verify loading from physiometrics.json."""
        config_data = {
            "power": {
                "ftp_watts": 305,
                "zones": {}
            }
        }

        with patch.object(Config, "load_physiometrics", return_value=config_data):
            Config._physiometrics_cache = None
            pwr_cfg = Config.power_config()

        assert pwr_cfg.ftp_watts == 305

    def test_power_config_zones_default(self) -> None:
        """Verify default power zones when not configured."""
        with patch.object(Config, "load_physiometrics", return_value=None):
            Config._physiometrics_cache = None
            pwr_cfg = Config.power_config()

        assert len(pwr_cfg.zones) > 0
        assert all(f"z{i}" in pwr_cfg.zones for i in range(1, 8))


class TestConfigSavePhysiometrics:
    """Tests for saving physiometrics to Azure Table."""

    def test_save_physiometrics_requires_table_storage(self) -> None:
        """Verify ValueError raised when table storage unavailable."""
        with patch.object(Config, "_get_table_storage", return_value=None):
            physiometrics = {
                "heart_rate": {"basis": "HRmax"},
                "power": {"ftp_watts": 250}
            }

            with pytest.raises(ValueError, match="Table storage not available"):
                Config.save_physiometrics(physiometrics)

    def test_save_physiometrics_clears_cache(self) -> None:
        """Verify cache is cleared after save."""
        mock_storage = MagicMock()
        mock_storage.store_physiometrics.return_value = "2026-01-18T10:30:00+00:00"

        with patch.object(Config, "_get_table_storage", return_value=mock_storage):
            Config._physiometrics_cache = {"cached": "data"}
            physiometrics = {"heart_rate": {}, "power": {}}

            Config.save_physiometrics(physiometrics)

            assert Config._physiometrics_cache is None

    def test_save_physiometrics_returns_timestamp(self) -> None:
        """Verify timestamp is returned on success."""
        mock_storage = MagicMock()
        expected_timestamp = "2026-01-18T10:30:00+00:00"
        mock_storage.store_physiometrics.return_value = expected_timestamp

        with patch.object(Config, "_get_table_storage", return_value=mock_storage):
            with patch.dict(os.environ, {"DEFAULT_ATHLETE_ID": "rob"}):
                physiometrics = {"heart_rate": {}, "power": {}}
                result = Config.save_physiometrics(physiometrics)

            assert result == expected_timestamp


class TestConfigHistory:
    """Tests for config history retrieval."""

    def test_get_physiometrics_history_empty_when_no_storage(self) -> None:
        """Verify empty list returned when storage unavailable."""
        with patch.object(Config, "_get_table_storage", return_value=None):
            history = Config.get_physiometrics_history(limit=5)

        assert history == []

    def test_get_physiometrics_history_delegates_to_storage(self) -> None:
        """Verify history is retrieved from storage."""
        mock_storage = MagicMock()
        mock_entries = [
            {"RowKey": "2026-01-18T10:30:00+00:00", "heart_rate_basis": "HRmax"},
            {"RowKey": "2026-01-18T09:30:00+00:00", "heart_rate_basis": "LTHR"},
        ]
        mock_storage.list_physiometrics_history.return_value = mock_entries

        with patch.object(Config, "_get_table_storage", return_value=mock_storage):
            with patch.dict(os.environ, {"DEFAULT_ATHLETE_ID": "rob"}):
                history = Config.get_physiometrics_history(limit=10)

        assert len(history) == 2
        mock_storage.list_physiometrics_history.assert_called_once()


class TestConfigAthleteTimezone:
    """Tests for get_athlete_timezone() method."""

    def test_athlete_timezone_from_env_var(self) -> None:
        """Verify get_athlete_timezone loads from ATHLETE_TIMEZONE env var."""
        # Patch the class variable directly
        original_value = Config.ATHLETE_TIMEZONE
        try:
            Config.ATHLETE_TIMEZONE = "America/New_York"
            Config._physiometrics_cache = None
            tz = Config.get_athlete_timezone()
            assert tz == "America/New_York"
        finally:
            Config.ATHLETE_TIMEZONE = original_value

    def test_athlete_timezone_from_physiometrics_file(self, tmp_path: Path) -> None:
        """Verify get_athlete_timezone loads from physiometrics.json."""
        config_data = {
            "athlete_timezone": "America/Chicago",
            "heart_rate": {"basis": "HRmax", "hr_max_bpm": 190}
        }
        config_file = tmp_path / "physiometrics.json"
        config_file.write_text(json.dumps(config_data))

        original_value = Config.ATHLETE_TIMEZONE
        try:
            Config.ATHLETE_TIMEZONE = None  # Ensure env var not set
            Config._physiometrics_cache = None
            with patch.object(Config, "physiometrics_file", return_value=config_file):
                tz = Config.get_athlete_timezone()
                assert tz == "America/Chicago"
        finally:
            Config.ATHLETE_TIMEZONE = original_value

    def test_athlete_timezone_invalid_zone_returns_none(self) -> None:
        """Verify invalid IANA timezone returns None with warning."""
        original_value = Config.ATHLETE_TIMEZONE
        try:
            Config.ATHLETE_TIMEZONE = "Invalid/Timezone"
            Config._physiometrics_cache = None
            tz = Config.get_athlete_timezone()
            assert tz is None
        finally:
            Config.ATHLETE_TIMEZONE = original_value

    def test_athlete_timezone_not_configured_returns_none(self) -> None:
        """Verify None returned when get_athlete_timezone not configured."""
        original_value = Config.ATHLETE_TIMEZONE
        try:
            Config.ATHLETE_TIMEZONE = None
            Config._physiometrics_cache = None
            with patch.object(Config, "load_physiometrics", return_value={}):
                tz = Config.get_athlete_timezone()
                assert tz is None
        finally:
            Config.ATHLETE_TIMEZONE = original_value
