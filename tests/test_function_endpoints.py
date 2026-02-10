"""Unit tests for Azure Function endpoints."""

# Allow imports inside test functions to avoid circular dependencies.
# pylint: disable=import-outside-toplevel

import json
from unittest.mock import MagicMock, patch, PropertyMock

import azure.functions as func
from FitParser.dependencies import FunctionAppDependencies

# Import endpoints (these are module-level functions in function_app.py)
# We'll test them by importing the app module


class TestHealthCheckEndpoint:
    """Tests for GET /health endpoint."""

    def test_health_check_returns_200(self) -> None:
        """Verify health check returns 200 OK."""
        from function_app import health_check

        mock_storage = MagicMock()
        mock_storage.service_client.list_tables.return_value = []
        with patch.object(FunctionAppDependencies, "storage", new=PropertyMock(return_value=mock_storage)):

            req = MagicMock(spec=func.HttpRequest)
            response = health_check(req)

            assert response.status_code == 200
            body = json.loads(response.get_body())
            assert body["status"] == "healthy"

    def test_health_check_returns_json(self) -> None:
        """Verify health check returns JSON."""
        from function_app import health_check

        mock_storage = MagicMock()
        mock_storage.service_client.list_tables.return_value = []
        with patch.object(FunctionAppDependencies, "storage", new=PropertyMock(return_value=mock_storage)):

            req = MagicMock(spec=func.HttpRequest)
            response = health_check(req)

            assert response.mimetype == "application/json"
            body = json.loads(response.get_body())
            assert isinstance(body, dict)


class TestReloadConfigEndpoint:
    """Tests for POST /config/reload endpoint."""

    def test_reload_config_success(self) -> None:
        """Verify config reload returns 200 with config details."""
        from FitParser.config import Config
        from function_app import reload_config

        config_data = {
            "heart_rate": {"basis": "HRmax", "hr_max_bpm": 195},
            "power": {"ftp_watts": 285}
        }

        with patch.object(Config, "load_physiometrics", return_value=config_data):
            with patch.object(Config, "physiometrics_file"):
                req = MagicMock(spec=func.HttpRequest)
                response = reload_config(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        assert body["heart_rate"]["basis"] == "HRmax"
        assert body["power"]["ftp_watts"] == 285

    def test_reload_config_file_not_found(self) -> None:
        """Verify 404 when physiometrics.json not found."""
        from FitParser.config import Config
        from function_app import reload_config

        with patch.object(Config, "load_physiometrics", return_value=None):
            with patch.object(Config, "physiometrics_file"):
                req = MagicMock(spec=func.HttpRequest)
                response = reload_config(req)

        assert response.status_code == 404
        body = json.loads(response.get_body())
        assert "error" in body

    def test_reload_config_json_error(self) -> None:
        """Verify 500 on JSON parse error."""
        from FitParser.config import Config
        from function_app import reload_config

        with patch.object(
            Config,
            "load_physiometrics",
            side_effect=json.JSONDecodeError("msg", "doc", 0)
        ):
            req = MagicMock(spec=func.HttpRequest)
            response = reload_config(req)

        assert response.status_code == 500


class TestUpdateConfigEndpoint:
    """Tests for POST /config/update endpoint."""

    def test_update_config_success(self) -> None:
        """Verify config update stores and returns 200."""
        from FitParser.config import Config
        from function_app import update_config

        payload = {
            "heart_rate": {
                "basis": "LTHR",
                "lthr_bpm": 170,
                "hr_max_bpm": 190,
                "resting_hr_bpm": 48
            },
            "power": {"ftp_watts": 300}
        }

        with patch.object(Config, "save_physiometrics", return_value="2026-01-18T10:30:00+00:00"):
            with patch.object(Config, "hr_config") as mock_hr:
                with patch.object(Config, "power_config") as mock_pwr:
                    mock_hr.return_value = MagicMock(
                        basis="LTHR", lthr_bpm=170, hr_max_bpm=190, resting_hr_bpm=48
                    )
                    mock_pwr.return_value = MagicMock(ftp_watts=300)

                    req = MagicMock(spec=func.HttpRequest)
                    req.get_json.return_value = payload
                    response = update_config(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        assert body["updated_at_utc"] == "2026-01-18T10:30:00+00:00"

    def test_update_config_invalid_json(self) -> None:
        """Verify 400 on invalid JSON."""
        from function_app import update_config

        req = MagicMock(spec=func.HttpRequest)
        req.get_json.side_effect = ValueError("Invalid JSON")
        response = update_config(req)

        assert response.status_code == 400
        body = json.loads(response.get_body())
        assert "error" in body

    def test_update_config_not_dict(self) -> None:
        """Verify 400 when payload is not a dict."""
        from function_app import update_config

        req = MagicMock(spec=func.HttpRequest)
        req.get_json.return_value = ["not", "a", "dict"]
        response = update_config(req)

        assert response.status_code == 400

    def test_update_config_storage_error(self) -> None:
        """Verify 500 when storage save fails."""
        from FitParser.config import Config
        from function_app import update_config

        payload = {"heart_rate": {}, "power": {}}

        with patch.object(
            Config,
            "save_physiometrics",
            side_effect=ValueError("Storage error")
        ):
            req = MagicMock(spec=func.HttpRequest)
            req.get_json.return_value = payload
            response = update_config(req)

        assert response.status_code == 500


class TestConfigHistoryEndpoint:
    """Tests for GET /config/history endpoint."""

    def test_config_history_success(self) -> None:
        """Verify config history returns list of changes."""
        from FitParser.config import Config
        from function_app import config_history

        mock_entries = [
            {
                "RowKey": "2026-01-18T10:30:00+00:00",
                "heart_rate_basis": "HRmax",
                "heart_rate_hr_max_bpm": 195,
                "power_ftp_watts": 285,
            },
            {
                "RowKey": "2026-01-18T09:30:00+00:00",
                "heart_rate_basis": "LTHR",
                "heart_rate_lthr_bpm": 170,
                "power_ftp_watts": 250,
            },
        ]

        with patch.object(Config, "get_physiometrics_history", return_value=mock_entries):
            req = MagicMock(spec=func.HttpRequest)
            req.params = {}
            response = config_history(req)

        assert response.status_code == 200
        body = json.loads(response.get_body())
        assert body["status"] == "success"
        assert body["count"] == 2
        assert len(body["history"]) == 2

    def test_config_history_with_limit(self) -> None:
        """Verify limit parameter is respected."""
        from FitParser.config import Config
        from function_app import config_history

        mock_entries = [{"RowKey": "2026-01-18T10:30:00+00:00"}]

        with patch.object(
            Config, "get_physiometrics_history", return_value=mock_entries
        ) as mock_history:
            req = MagicMock(spec=func.HttpRequest)
            req.params = {"limit": "5"}
            config_history(req)

        mock_history.assert_called_once_with(limit=5)

    def test_config_history_limit_capped(self) -> None:
        """Verify limit is capped at 50."""
        from FitParser.config import Config
        from function_app import config_history

        with patch.object(Config, "get_physiometrics_history", return_value=[]) as mock_history:
            req = MagicMock(spec=func.HttpRequest)
            req.params = {"limit": "999"}
            config_history(req)

        mock_history.assert_called_once_with(limit=50)

    def test_config_history_invalid_limit(self) -> None:
        """Verify invalid limit returns 400."""
        from function_app import config_history

        req = MagicMock(spec=func.HttpRequest)
        req.params = {"limit": "invalid"}
        response = config_history(req)

        assert response.status_code == 400
        body = json.loads(response.get_body())
        assert body["error"] == "Invalid limit parameter"

    def test_config_history_error(self) -> None:
        """Verify 500 on retrieval error."""
        from FitParser.config import Config
        from function_app import config_history

        with patch.object(
            Config,
            "get_physiometrics_history",
            side_effect=ValueError("History error")
        ):
            req = MagicMock(spec=func.HttpRequest)
            req.params = {}
            response = config_history(req)

        assert response.status_code == 500
