"""Unit tests for timezone resolution helper functions in fit_models.

Note: Full integration tests for BaseFitModel.timezone property are covered  
by tests with real FIT files (test_fit_parser.py). These tests focus on
the helper methods that support timezone resolution.
"""

from unittest.mock import patch

import pytest

from TrainingAnalyticsPlatform.ingestion.fit_models import PayloadFitModel


@pytest.fixture(autouse=True)
def _stub_fit_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub FIT parsing so tests can focus on timezone behavior."""
    monkeypatch.setattr(
        PayloadFitModel,
        "_parse_fit_messages",
        lambda self, file_bytes: ([], [], {}),
    )


@pytest.fixture
def payload_model() -> PayloadFitModel:
    """Create a minimal PayloadFitModel instance for testing."""
    file_bytes = b"fake_fit_data"
    source_metadata = {
        "source_system": "HTTP",
        "ingestion_id": "test_123",
    }
    return PayloadFitModel(file_bytes=file_bytes, source_metadata=source_metadata)


class TestAthleteTimezoneHelper:
    """Tests for _get_athlete_timezone() helper method."""

    def test_get_athlete_timezone_returns_config_value(self, payload_model: PayloadFitModel) -> None:
        """Should load athlete timezone from Config."""
        with patch("TrainingAnalyticsPlatform.platform.config.Config.get_athlete_timezone", return_value="America/Chicago"):
            tz = payload_model._get_athlete_timezone()
            assert tz == "America/Chicago"

    def test_get_athlete_timezone_handles_import_error(self, payload_model: PayloadFitModel) -> None:
        """Should return None gracefully when Config import fails."""
        with patch("TrainingAnalyticsPlatform.platform.config.Config.get_athlete_timezone", side_effect=ImportError("Cannot import")):
            tz = payload_model._get_athlete_timezone()
            assert tz is None

    def test_get_athlete_timezone_handles_attribute_error(self, payload_model: PayloadFitModel) -> None:
        """Should return None gracefully when Config has no get_athlete_timezone method."""
        with patch("TrainingAnalyticsPlatform.platform.config.Config.get_athlete_timezone", side_effect=AttributeError("No such attribute")):
            tz = payload_model._get_athlete_timezone()
            assert tz is None

    def test_get_athlete_timezone_returns_none_when_not_configured(self, payload_model: PayloadFitModel) -> None:
        """Should return None when athlete timezone not configured."""
        with patch("TrainingAnalyticsPlatform.platform.config.Config.get_athlete_timezone", return_value=None):
            tz = payload_model._get_athlete_timezone()
            assert tz is None

