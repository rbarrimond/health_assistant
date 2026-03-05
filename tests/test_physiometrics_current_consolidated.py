"""Test physiometrics/current endpoint consolidation behavior across sources."""

import pytest
from unittest.mock import MagicMock
from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer


class TestCurrentPhysiometricsConsolidation:
    """Verify GET /api/physiometrics/current consolidates Intervals, Garmin, Withings."""

    @pytest.fixture
    def layer(self):
        """Create semantic layer with mocked storage."""
        layer = SemanticLayer(MagicMock())
        return layer

    def test_consolidate_latest_per_source(self, layer):
        """Consolidate latest Intervals, Garmin, and Withings rows with precedence."""
        # Mock the infrastructure table client to return multi-source rows
        mock_table = MagicMock()
        mock_table.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-01",
                "effective_date": "2026-03-01",
                "data_source": "withings",
                "updated_at_utc": "2026-03-01T08:00:00+00:00",
                "weight_kg": 73.2,
                "body_fat_pct": 14.8,
                "muscle_mass_kg": 38.5,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "intervals",
                "updated_at_utc": "2026-03-02T08:15:00+00:00",
                "hrv_ln_rmssd": 3.95,
                "heart_rate_resting_bpm": 48,
                "sleep_duration_sec": 28000,
                "fatigue": 6,
                "activity_steps": 11500,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-02T08:20:00+00:00",
                "power_ftp_watts": 320,
                "cycling_vo2max_ml_kg_min": 62.5,
                "running_vo2max_ml_kg_min": 58.1,
                "training_load": 310.0,
                "training_stress_score": 310.0,
                "training_stress_balance": 0.88,
            },
        ]
        layer.storage.infrastructure.get_table_client = MagicMock(return_value=mock_table)

        result = layer.get_current_physiometrics("rob")

        # Verify consolidation applied precedence correctly
        assert result["athlete_id"] == "rob"
        assert result["weight_kg"] == pytest.approx(73.2)  # Withings
        assert result["body_fat_pct"] == pytest.approx(14.8)  # Withings
        assert result["muscle_mass_kg"] == pytest.approx(38.5)  # Withings
        assert result["heart_rate"]["resting_hr_bpm"] == 48  # Intervals
        assert result["fatigue"] == 6  # Intervals
        assert result["steps"] == 11500  # Intervals
        assert result["power"]["ftp_watts"] == 320  # Garmin
        assert result["cycling_vo2max_ml_kg_min"] == pytest.approx(62.5)  # Garmin
        assert result["running_vo2max_ml_kg_min"] == pytest.approx(58.1)  # Garmin
        assert result["training_load"] == pytest.approx(310.0)  # Garmin
        
        # Verify metadata includes all contributing sources
        assert sorted(result["data_sources"]) == ["garmin", "intervals", "withings"]
        
        # Verify source dates tracked
        assert result["source_effective_dates"]["withings"] == "2026-03-01"
        assert result["source_effective_dates"]["intervals"] == "2026-03-02"
        assert result["source_effective_dates"]["garmin"] == "2026-03-02"

    def test_returns_latest_when_no_data_found(self, layer):
        """Return error when no physiometrics rows exist."""
        mock_table = MagicMock()
        mock_table.query_entities.return_value = []
        layer.storage.infrastructure.get_table_client = MagicMock(return_value=mock_table)

        result = layer.get_current_physiometrics("rob")

        assert result["athlete_id"] == "rob"
        assert "error" in result
        assert result["error"] == "No physiometrics data found"

    def test_metric_precedence_intervals_over_garmin_for_wellness(self, layer):
        """Intervals takes precedence over Garmin for HRV and sleep metrics."""
        mock_table = MagicMock()
        mock_table.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "intervals",
                "updated_at_utc": "2026-03-02T08:15:00+00:00",
                "hrv_ln_rmssd": 3.95,
                "sleep_duration_sec": 28000,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-02T08:20:00+00:00",
                "hrv_ln_rmssd": 3.5,  # Lower than Intervals
                "sleep_duration_sec": 27000,  # Different, but Intervals wins
                "training_load": 310.0,
            },
        ]
        layer.storage.infrastructure.get_table_client = MagicMock(return_value=mock_table)

        result = layer.get_current_physiometrics("rob")

        # Intervals values should win
        assert result["hrv_ln_rmssd"] == pytest.approx(3.95)
        assert result["sleep_duration_sec"] == 28000

    def test_metric_precedence_garmin_over_intervals_for_ftp(self, layer):
        """Garmin takes precedence over Intervals for FTP and training metrics."""
        mock_table = MagicMock()
        mock_table.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "intervals",
                "updated_at_utc": "2026-03-02T08:15:00+00:00",
                "ftp_watts": 310,
                "training_load": 290.0,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-02T08:20:00+00:00",
                "power_ftp_watts": 320,
                "training_load": 310.0,
            },
        ]
        layer.storage.infrastructure.get_table_client = MagicMock(return_value=mock_table)

        result = layer.get_current_physiometrics("rob")

        # Garmin values should win
        assert result["power"]["ftp_watts"] == 320
        assert result["training_load"] == pytest.approx(310.0)

    def test_uses_timestamp_to_break_ties(self, layer):
        """When effective_date is same, use updated_at_utc to pick latest."""
        mock_table = MagicMock()
        mock_table.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-02T08:15:00+00:00",  # Earlier
                "power_ftp_watts": 300,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-02T08:20:00+00:00",  # Later
                "power_ftp_watts": 320,
            },
        ]
        layer.storage.infrastructure.get_table_client = MagicMock(return_value=mock_table)

        result = layer.get_current_physiometrics("rob")

        # Later timestamp should win
        assert result["power"]["ftp_watts"] == 320

    def test_storage_alias_fields_resolved(self, layer):
        """Resolve canonical metric names from storage alias fields."""
        mock_table = MagicMock()
        mock_table.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02",
                "effective_date": "2026-03-02",
                "data_source": "garmin",
                "updated_at_utc": "2026-03-02T08:20:00+00:00",
                "power_ftp_watts": 320,  # Alias for ftp_watts
                "heart_rate_lthr_bpm": 172,  # Alias for hr_lthr_bpm
                "heart_rate_hr_max_bpm": 190,  # Alias for hr_max_bpm
            },
        ]
        layer.storage.infrastructure.get_table_client = MagicMock(return_value=mock_table)

        result = layer.get_current_physiometrics("rob")

        # Canonical names should be resolved from aliases
        assert result["power"]["ftp_watts"] == 320
        assert result["heart_rate"]["lthr_bpm"] == 172
        assert result["heart_rate"]["hr_max_bpm"] == 190
