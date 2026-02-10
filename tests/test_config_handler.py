"""Tests for ConfigHandler."""

# pylint: disable=line-too-long

import json
from unittest.mock import Mock

import pytest

from FitParser.handlers import ConfigHandler


class TestConfigHandler:
    """Test suite for ConfigHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return ConfigHandler()

    @pytest.fixture
    def sample_config_data(self):
        """Sample configuration data."""
        return {
            "heart_rate": {
                "basis": "percentage",
                "lthr_bpm": 165,
                "hr_max_bpm": 190,
                "resting_hr_bpm": 50
            },
            "power": {
                "ftp_watts": 280
            }
        }

    def test_reload_config_success(self, handler, sample_config_data, mocker):
        """Test successful config reload."""
        # Arrange
        mock_load = mocker.patch('FitParser.handlers.config_handler.Config.load_physiometrics')
        mock_load.return_value = sample_config_data

        mock_hr_config = Mock()
        mock_hr_config.basis = "percentage"
        mock_hr_config.lthr_bpm = 165
        mock_hr_config.hr_max_bpm = 190
        mock_hr_config.resting_hr_bpm = 50

        mock_pwr_config = Mock()
        mock_pwr_config.ftp_watts = 280

        mocker.patch('FitParser.handlers.config_handler.Config.hr_config', return_value=mock_hr_config)
        mocker.patch('FitParser.handlers.config_handler.Config.power_config', return_value=mock_pwr_config)

        # Act
        result, status = handler.reload_config()

        # Assert
        assert status == 200
        assert result["status"] == "success"
        assert "message" in result
        assert "heart_rate" in result
        assert result["heart_rate"]["lthr_bpm"] == 165
        assert result["power"]["ftp_watts"] == 280
        mock_load.assert_called_once_with(force_reload=True)

    def test_reload_config_file_not_found(self, handler, mocker):
        """Test reload when config file doesn't exist."""
        # Arrange
        mock_load = mocker.patch('FitParser.handlers.config_handler.Config.load_physiometrics')
        mock_load.return_value = None

        # Act
        result, status = handler.reload_config()

        # Assert
        assert status == 404
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_reload_config_json_decode_error(self, handler, mocker):
        """Test reload handles JSON parsing errors."""
        # Arrange
        mock_load = mocker.patch('FitParser.handlers.config_handler.Config.load_physiometrics')
        mock_load.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)

        # Act
        result, status = handler.reload_config()

        # Assert
        assert status == 500
        assert "error" in result
        assert "JSON" in result["error"]

    def test_reload_config_io_error(self, handler, mocker):
        """Test reload handles I/O errors."""
        # Arrange
        mock_load = mocker.patch('FitParser.handlers.config_handler.Config.load_physiometrics')
        mock_load.side_effect = IOError("Disk error")

        # Act
        result, status = handler.reload_config()

        # Assert
        assert status == 500
        assert "error" in result

    def test_update_config_success(self, handler, sample_config_data, mocker):
        """Test successful config update."""
        # Arrange
        mock_save = mocker.patch('FitParser.handlers.config_handler.Config.save_physiometrics')
        mock_save.return_value = "2026-02-01T12:00:00+00:00"

        mock_hr_config = Mock()
        mock_hr_config.basis = "percentage"
        mock_hr_config.lthr_bpm = 166  # Updated value
        mock_hr_config.hr_max_bpm = 190
        mock_hr_config.resting_hr_bpm = 50

        mock_pwr_config = Mock()
        mock_pwr_config.ftp_watts = 285  # Updated value

        mocker.patch('FitParser.handlers.config_handler.Config.hr_config', return_value=mock_hr_config)
        mocker.patch('FitParser.handlers.config_handler.Config.power_config', return_value=mock_pwr_config)

        # Act
        result, status = handler.update_config(sample_config_data)

        # Assert
        assert status == 200
        assert result["status"] == "success"
        assert "updated_at_utc" in result
        assert result["updated_at_utc"] == "2026-02-01T12:00:00+00:00"
        assert result["heart_rate"]["lthr_bpm"] == 166
        assert result["power"]["ftp_watts"] == 285
        mock_save.assert_called_once_with(sample_config_data)

    def test_update_config_invalid_type(self, handler, mocker):
        """Test update with non-dict config data."""
        # Arrange
        mock_save = mocker.patch('FitParser.handlers.config_handler.Config.save_physiometrics')

        # Act
        result, status = handler.update_config("not_a_dict")

        # Assert
        assert status == 400
        assert "error" in result
        assert "JSON object" in result["error"]
        mock_save.assert_not_called()

    def test_update_config_validation_error(self, handler, sample_config_data, mocker):
        """Test update handles validation errors."""
        # Arrange
        mock_save = mocker.patch('FitParser.handlers.config_handler.Config.save_physiometrics')
        mock_save.side_effect = ValueError("Invalid HR value")

        # Act
        result, status = handler.update_config(sample_config_data)

        # Assert
        assert status == 500
        assert "error" in result
        assert "Failed to update" in result["error"]

    def test_update_config_io_error(self, handler, sample_config_data, mocker):
        """Test update handles I/O errors."""
        # Arrange
        mock_save = mocker.patch('FitParser.handlers.config_handler.Config.save_physiometrics')
        mock_save.side_effect = IOError("Disk full")

        # Act
        result, status = handler.update_config(sample_config_data)

        # Assert
        assert status == 500
        assert "error" in result

    def test_get_history_success(self, handler, mocker):
        """Test successful history retrieval."""
        # Arrange
        mock_history_data = [
            {
                "RowKey": "2026-02-01T12:00:00+00:00",
                "heart_rate_basis": "percentage",
                "heart_rate_lthr_bpm": 165,
                "heart_rate_hr_max_bpm": 190,
                "heart_rate_resting_bpm": 50,
                "power_ftp_watts": 280
            },
            {
                "RowKey": "2026-01-15T10:00:00+00:00",
                "heart_rate_basis": "percentage",
                "heart_rate_lthr_bpm": 164,
                "heart_rate_hr_max_bpm": 190,
                "heart_rate_resting_bpm": 50,
                "power_ftp_watts": 275
            }
        ]
        mock_get_history = mocker.patch('FitParser.handlers.config_handler.Config.get_physiometrics_history')
        mock_get_history.return_value = mock_history_data

        # Act
        result, status = handler.get_history(limit=10)

        # Assert
        assert status == 200
        assert result["status"] == "success"
        assert result["count"] == 2
        assert len(result["history"]) == 2
        assert result["history"][0]["updated_at_utc"] == "2026-02-01T12:00:00+00:00"
        assert result["history"][0]["heart_rate"]["lthr_bpm"] == 165
        assert result["history"][1]["power"]["ftp_watts"] == 275
        mock_get_history.assert_called_once_with(limit=10)

    def test_get_history_caps_limit_at_50(self, handler, mocker):
        """Test history caps limit parameter at 50."""
        # Arrange
        mock_get_history = mocker.patch('FitParser.handlers.config_handler.Config.get_physiometrics_history')
        mock_get_history.return_value = []

        # Act
        _, status = handler.get_history(limit=100)

        # Assert
        assert status == 200
        # Verify limit was capped at 50
        mock_get_history.assert_called_once_with(limit=50)

    def test_get_history_default_limit(self, handler, mocker):
        """Test history uses default limit of 10."""
        # Arrange
        mock_get_history = mocker.patch('FitParser.handlers.config_handler.Config.get_physiometrics_history')
        mock_get_history.return_value = []

        # Act
        _, status = handler.get_history()

        # Assert
        assert status == 200
        mock_get_history.assert_called_once_with(limit=10)

    def test_get_history_exception_handling(self, handler, mocker):
        """Test history handles exceptions."""
        # Arrange
        mock_get_history = mocker.patch('FitParser.handlers.config_handler.Config.get_physiometrics_history')
        mock_get_history.side_effect = ValueError("Invalid limit")

        # Act - handler catches ValueError and returns 500
        result, status = handler.get_history()

        # Assert
        assert status == 500
        assert "error" in result
        assert "Failed to retrieve configuration history" in result["error"]

    def test_get_history_empty_result(self, handler, mocker):
        """Test history with no entries."""
        # Arrange
        mock_get_history = mocker.patch('FitParser.handlers.config_handler.Config.get_physiometrics_history')
        mock_get_history.return_value = []

        # Act
        result, status = handler.get_history()

        # Assert
        assert status == 200
        assert result["count"] == 0
        assert len(result["history"]) == 0
