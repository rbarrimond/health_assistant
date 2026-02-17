"""Tests for PhysiometricsHandler."""

# pylint: disable=line-too-long

from unittest.mock import Mock

import pytest

from TrainingAnalyticsPlatform.handlers import PhysiometricsHandler


class TestPhysiometricsHandler:
    """Test suite for PhysiometricsHandler."""

    @pytest.fixture
    def mock_semantic_layer(self):
        """Create mock SemanticLayer."""
        return Mock()

    @pytest.fixture
    def handler(self, mock_semantic_layer):
        """Create handler instance with mocked dependencies."""
        return PhysiometricsHandler(mock_semantic_layer)

    def test_get_current_success(self, handler, mock_semantic_layer):
        """Test successful retrieval of current physiometrics."""
        # Arrange
        expected_data = {
            "athlete_id": "athlete1",
            "weight_kg": 70.5,
            "lthr_bpm": 165,
            "ftp_watts": 280
        }
        mock_semantic_layer.get_current_physiometrics.return_value = expected_data

        # Act
        result, status = handler.get_current("athlete1")

        # Assert
        assert status == 200
        assert result == expected_data
        mock_semantic_layer.get_current_physiometrics.assert_called_once_with("athlete1")

    def test_get_current_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test get_current with missing athlete_id."""
        # Act
        result, status = handler.get_current(None)

        # Assert
        assert status == 400
        assert "error" in result
        assert "athlete_id" in result["error"].lower()
        mock_semantic_layer.get_current_physiometrics.assert_not_called()

    def test_get_current_empty_athlete_id(self, handler, mock_semantic_layer):
        """Test get_current with empty athlete_id."""
        # Act
        result, status = handler.get_current("")

        # Assert
        assert status == 400
        assert "error" in result
        mock_semantic_layer.get_current_physiometrics.assert_not_called()

    def test_get_current_exception_handling(self, handler, mock_semantic_layer):
        """Test get_current handles exceptions properly."""
        # Arrange
        mock_semantic_layer.get_current_physiometrics.side_effect = Exception("DB error")

        # Act
        result, status = handler.get_current("athlete1")

        # Assert
        assert status == 500
        assert "error" in result
        assert "Failed to retrieve physiometrics" in result["error"]

    def test_get_history_success(self, handler, mock_semantic_layer):
        """Test successful retrieval of physiometrics history."""
        # Arrange
        expected_data = {
            "athlete_id": "athlete1",
            "days": 30,
            "data": [
                {"date": "2026-01-01", "weight_kg": 70.5},
                {"date": "2026-01-02", "weight_kg": 70.3}
            ]
        }
        mock_semantic_layer.get_physiometrics_trends.return_value = expected_data

        # Act
        result, status = handler.get_history("athlete1", 30, None)

        # Assert
        assert status == 200
        assert result == expected_data
        mock_semantic_layer.get_physiometrics_trends.assert_called_once_with(
            athlete_id="athlete1",
            days=30,
            metrics=None
        )

    def test_get_history_with_specific_metrics(self, handler, mock_semantic_layer):
        """Test get_history with specific metrics filter."""
        # Arrange
        metrics = ["weight_kg", "lthr_bpm"]
        expected_data = {"athlete_id": "athlete1", "metrics": metrics}
        mock_semantic_layer.get_physiometrics_trends.return_value = expected_data

        # Act
        _, status = handler.get_history("athlete1", 90, metrics)

        # Assert
        assert status == 200
        mock_semantic_layer.get_physiometrics_trends.assert_called_once_with(
            athlete_id="athlete1",
            days=90,
            metrics=metrics
        )

    def test_get_history_caps_days_at_365(self, handler, mock_semantic_layer):
        """Test get_history caps days parameter at 365."""
        # Arrange
        mock_semantic_layer.get_physiometrics_trends.return_value = {"data": []}

        # Act
        _, status = handler.get_history("athlete1", 500, None)

        # Assert
        assert status == 200
        # Verify it was capped at 365
        mock_semantic_layer.get_physiometrics_trends.assert_called_once_with(
            athlete_id="athlete1",
            days=365,
            metrics=None
        )

    def test_get_history_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test get_history with missing athlete_id."""
        # Act
        result, status = handler.get_history(None, 30, None)

        # Assert
        assert status == 400
        assert "error" in result
        mock_semantic_layer.get_physiometrics_trends.assert_not_called()

    def test_update_metric_success(self, handler, mock_semantic_layer):
        """Test successful single metric update."""
        # Arrange
        expected_result = {
            "status": "success",
            "metric": "weight_kg",
            "value": 71.0
        }
        mock_semantic_layer.update_physiometric_value.return_value = expected_result

        # Act
        result, status = handler.update_metric(
            athlete_id="athlete1",
            metric="weight_kg",
            value=71.0,
            effective_date="2026-02-01",
            source="manual"
        )

        # Assert
        assert status == 200
        assert result == expected_result
        mock_semantic_layer.update_physiometric_value.assert_called_once_with(
            athlete_id="athlete1",
            metric="weight_kg",
            value=71.0,
            effective_date="2026-02-01",
            source="manual"
        )

    def test_update_metric_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test update_metric with missing athlete_id."""
        # Act
        result, status = handler.update_metric(
            athlete_id=None,
            metric="weight_kg",
            value=71.0
        )

        # Assert
        assert status == 400
        assert "error" in result
        mock_semantic_layer.update_physiometric_value.assert_not_called()

    def test_update_metric_missing_metric_name(self, handler, mock_semantic_layer):
        """Test update_metric with missing metric name - exception occurs."""
        # Arrange
        mock_semantic_layer.update_physiometric_value.side_effect = TypeError("missing required argument")

        # Act
        result, status = handler.update_metric(
            athlete_id="athlete1",
            metric=None,
            value=71.0
        )

        # Assert
        assert status == 500
        assert "error" in result

    def test_update_metrics_bulk_success(self, handler, mock_semantic_layer):
        """Test successful bulk metrics update."""
        # Arrange
        metrics = {
            "weight_kg": 71.0,
            "lthr_bpm": 166,
            "ftp_watts": 285
        }
        mock_semantic_layer.update_physiometric_value.return_value = {"status": "success"}

        # Act
        result, status = handler.update_metrics(
            athlete_id="athlete1",
            metrics=metrics,
            effective_date="2026-02-01",
            source="chatgpt"
        )

        # Assert
        assert status == 200
        assert result["status"] == "success"
        assert "updates" in result
        assert len(result["updates"]) == 3
        assert mock_semantic_layer.update_physiometric_value.call_count == 3

    def test_update_metrics_missing_athlete_id(self, handler, mock_semantic_layer):
        """Test update_metrics with missing athlete_id."""
        # Act
        result, status = handler.update_metrics(
            athlete_id=None,
            metrics={"weight_kg": 71.0}
        )

        # Assert
        assert status == 400
        assert "error" in result
        mock_semantic_layer.update_physiometric_value.assert_not_called()

    def test_update_metrics_empty_metrics_dict(self, handler, mock_semantic_layer):
        """Test update_metrics with empty metrics dict - succeeds with 0 updates."""
        # Act
        result, status = handler.update_metrics(
            athlete_id="athlete1",
            metrics={}
        )

        # Assert
        assert status == 200
        assert result["status"] == "success"
        assert len(result["updates"]) == 0
        mock_semantic_layer.update_physiometric_value.assert_not_called()

    def test_update_metrics_invalid_metrics_type(self, handler, mock_semantic_layer):
        """Test update_metrics with non-dict metrics - causes exception."""
        # Act
        result, status = handler.update_metrics(
            athlete_id="athlete1",
            metrics="not_a_dict"
        )

        # Assert
        assert status == 500
        assert "error" in result
        assert "Failed to update physiometrics" in result["error"]
        mock_semantic_layer.update_physiometric_value.assert_not_called()

    def test_update_metrics_exception_stops_iteration(self, handler, mock_semantic_layer):
        """Test bulk update stops on first exception."""
        # Arrange
        metrics = {"weight_kg": 71.0, "lthr_bpm": 166, "ftp_watts": 285}

        # First call succeeds, second fails
        call_count = [0]
        def side_effect(_, metric, ___, **____):  # pylint: disable=unused-argument
            call_count[0] += 1
            if call_count[0] == 2:  # Second call fails
                raise ValueError("Invalid HR value")
            return {"status": "success", "metric": metric}

        mock_semantic_layer.update_physiometric_value.side_effect = side_effect

        # Act
        result, status = handler.update_metrics(
            athlete_id="athlete1",
            metrics=metrics
        )

        # Assert
        assert status == 500  # Returns 500 on exception
        assert "error" in result
