"""Test that all WORKOUT_SCHEMA.md fields are implemented correctly."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.ingestion.fit_parser import FitParser


def _fit_field(value):
    field = MagicMock()
    field.value = value
    return field


def _fit_message(name, fields):
    return {
        "name": name,
        "frame": MagicMock(developer_fields=[]),
        "fields": {key: _fit_field(value) for key, value in fields.items()},
    }


def _enum(name):
    enum = MagicMock()
    enum.name = name
    return enum


class TestSchemaFieldImplementation:
    """Test implementation of WORKOUT_SCHEMA.md fields."""

    def test_power_zone_boundaries_computed(self, sample_fit_file, mocker):
        """Test that power zone boundaries are stored in metrics."""
        session_msg = _fit_message(
            "session",
            {
                "sport": _enum("cycling"),
                "start_time": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "timestamp": datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
                "total_elapsed_time": 3600,
                "avg_power": 250,
            },
        )
        profile_msg = _fit_message("user_profile", {"functional_threshold_power": 275})
        records = [
            _fit_message("record", {"power": power})
            for power in [200, 220, 250, 280, 300] * 100
        ]
        messages = [session_msg, profile_msg] + records

        mocker.patch(
            "TrainingAnalyticsPlatform.ingestion.fit_parser.load_fit_messages",
            return_value=(messages, "test_file"),
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        expected_fields = [
            "pwr_z1_low_w", "pwr_z1_high_w",
            "pwr_z2_low_w", "pwr_z2_high_w",
            "pwr_z3_low_w", "pwr_z3_high_w",
            "pwr_z4_low_w", "pwr_z4_high_w",
            "pwr_z5_low_w", "pwr_z5_high_w",
            "pwr_z6_low_w", "pwr_z6_high_w",
            "pwr_z7_low_w", "pwr_z7_high_w",
        ]

        for field in expected_fields:
            assert field in metrics, f"Missing power zone boundary field: {field}"
            assert isinstance(metrics[field], float), f"{field} should be float"
            assert metrics[field] >= 0, f"{field} should be non-negative"

        assert metrics["pwr_z1_low_w"] == 0
        assert metrics["pwr_z1_high_w"] == int(275 * 0.55)
        assert metrics["pwr_z2_low_w"] == int(275 * 0.55)
        assert metrics["pwr_z2_high_w"] == int(275 * 0.75)

    def test_training_load_metrics_computed(self, sample_fit_file, mocker):
        """Test TSS and intensity factor calculation."""
        session_msg = _fit_message(
            "session",
            {
                "sport": _enum("cycling"),
                "start_time": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "timestamp": datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
                "total_elapsed_time": 3600,
                "avg_power": 250,
                "normalized_power": 270,
            },
        )
        profile_msg = _fit_message("user_profile", {"functional_threshold_power": 275})
        records = [
            _fit_message("record", {"power": power})
            for power in [200, 220, 250, 280, 300, 290, 270, 250, 230, 210] * 50
        ]
        messages = [session_msg, profile_msg] + records

        mocker.patch(
            "TrainingAnalyticsPlatform.ingestion.fit_parser.load_fit_messages",
            return_value=(messages, "test_file"),
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        assert "intensity_factor" in metrics
        assert "tss" in metrics
        assert "ftp_watts" in metrics
        assert 0 < metrics["intensity_factor"] < 2
        assert metrics["tss"] > 0
        assert metrics["ftp_watts"] == 275

    def test_aerobic_efficiency_metrics_computed(self, sample_fit_file, mocker):
        """Test EF and decoupling calculations for >=30min workouts."""
        session_msg = _fit_message(
            "session",
            {
                "sport": _enum("cycling"),
                "start_time": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "timestamp": datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
                "total_elapsed_time": 3600,
                "avg_heart_rate": 150,
                "avg_power": 250,
            },
        )
        records = [
            _fit_message("record", {"heart_rate": 145, "power": 250})
            for _ in range(300)
        ] + [
            _fit_message("record", {"heart_rate": 155, "power": 250})
            for _ in range(300)
        ]
        messages = [session_msg] + records

        mocker.patch(
            "TrainingAnalyticsPlatform.ingestion.fit_parser.load_fit_messages",
            return_value=(messages, "test_file"),
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        assert "ef_first_half" in metrics
        assert "ef_second_half" in metrics
        assert "ef_overall" in metrics
        assert "hr_drift_bpm" in metrics
        assert "decoupling_pct" in metrics
        assert metrics["ef_first_half"] > metrics["ef_second_half"]
        assert metrics["hr_drift_bpm"] > 0
        assert metrics["decoupling_pct"] < 0

    def test_resting_hr_extraction(self, sample_fit_file, mocker):
        """Test extraction of resting HR from user profile."""
        session_msg = _fit_message(
            "session",
            {
                "sport": _enum("cycling"),
                "start_time": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "timestamp": datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
                "total_elapsed_time": 3600,
            },
        )
        profile_msg = _fit_message("user_profile", {"resting_heart_rate": 55})
        messages = [session_msg, profile_msg]

        mocker.patch(
            "TrainingAnalyticsPlatform.ingestion.fit_parser.load_fit_messages",
            return_value=(messages, "test_file"),
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        assert "hr_resting_bpm" in metrics
        assert metrics["hr_resting_bpm"] == 55

    def test_short_workout_skips_aerobic_efficiency(self, sample_fit_file, mocker):
        """Test that workouts <30min don't compute aerobic efficiency."""
        session_msg = _fit_message(
            "session",
            {
                "sport": _enum("cycling"),
                "start_time": datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                "timestamp": datetime(2024, 1, 15, 10, 20, 0, tzinfo=timezone.utc),
                "total_elapsed_time": 1200,
                "avg_heart_rate": 150,
                "avg_power": 250,
            },
        )
        messages = [session_msg]

        mocker.patch(
            "TrainingAnalyticsPlatform.ingestion.fit_parser.load_fit_messages",
            return_value=(messages, "test_file"),
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        assert "ef_first_half" not in metrics
        assert "ef_second_half" not in metrics
        assert "decoupling_pct" not in metrics
