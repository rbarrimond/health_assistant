"""Test that all WORKOUT_SCHEMA.md fields are implemented correctly."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from TrainingAnalyticsPlatform.ingestion.fit_parser import FitParser


class TestSchemaFieldImplementation:
    """Test implementation of WORKOUT_SCHEMA.md fields."""

    def test_power_zone_boundaries_computed(self, sample_fit_file, mocker):
        """Test that power zone boundaries are stored in metrics."""
        # Mock the FitFile to return necessary data
        mock_fit = MagicMock()

        # Create session with power data and FTP
        session_msg = MagicMock()
        session_msg.get = MagicMock(side_effect=lambda key: {  # pylint: disable=unnecessary-lambda
            'sport': MagicMock(value=MagicMock(name='cycling')),
            'start_time': MagicMock(value=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            'timestamp': MagicMock(value=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)),
            'total_elapsed_time': MagicMock(value=3600),
            'avg_power': MagicMock(value=250),
        }.get(key))

        # Create records with power data
        records = []
        for power in [200, 220, 250, 280, 300] * 100:  # 500 data points
            record = MagicMock()
            record.get = MagicMock(side_effect=lambda k, p=power: {  # pylint: disable=unnecessary-lambda
                'power': MagicMock(value=p),
            }.get(k))
            records.append(record)

        def get_messages(msg_type):
            if msg_type == 'session':
                return [session_msg]
            elif msg_type == 'record':
                return records
            elif msg_type == 'user_profile':
                # Mock user profile with FTP
                profile = MagicMock()
                profile.get = MagicMock(side_effect=lambda k: {  # pylint: disable=unnecessary-lambda
                    'functional_threshold_power': MagicMock(value=275),
                }.get(k))
                return [profile]
            return []

        mock_fit.get_messages = MagicMock(side_effect=get_messages)

        # Mock fitdecode shim FitFile
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.fit_parser.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.adapter.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )

        # Parse and check for zone boundaries
        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        # Verify all 14 power zone boundary fields exist
        expected_fields = [
            'pwr_z1_low_w', 'pwr_z1_high_w',
            'pwr_z2_low_w', 'pwr_z2_high_w',
            'pwr_z3_low_w', 'pwr_z3_high_w',
            'pwr_z4_low_w', 'pwr_z4_high_w',
            'pwr_z5_low_w', 'pwr_z5_high_w',
            'pwr_z6_low_w', 'pwr_z6_high_w',
            'pwr_z7_low_w', 'pwr_z7_high_w',
        ]

        for field in expected_fields:
            assert field in metrics, f"Missing power zone boundary field: {field}"
            assert isinstance(
                metrics[field], float), f"{field} should be float"
            assert metrics[field] >= 0, f"{field} should be non-negative"

        # Verify zone boundaries are reasonable (based on FTP=275)
        assert metrics['pwr_z1_low_w'] == 0
        assert metrics['pwr_z1_high_w'] == int(275 * 0.55)
        assert metrics['pwr_z2_low_w'] == int(275 * 0.55)
        assert metrics['pwr_z2_high_w'] == int(275 * 0.75)

    def test_training_load_metrics_computed(self, sample_fit_file, mocker):
        """Test TSS and intensity factor calculation."""
        mock_fit = MagicMock()

        session_msg = MagicMock()
        session_msg.get = MagicMock(side_effect=lambda key: {  # pylint: disable=unnecessary-lambda
            'sport': MagicMock(value=MagicMock(name='cycling')),
            'start_time': MagicMock(value=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            'timestamp': MagicMock(value=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)),
            'total_elapsed_time': MagicMock(value=3600),  # 1 hour
            'avg_power': MagicMock(value=250),
            'normalized_power': MagicMock(value=270),  # NP > avg
        }.get(key))

        # Create records with power data for variability
        records = []
        powers = [200, 220, 250, 280, 300, 290, 270, 250, 230, 210] * 50
        for power in powers:
            record = MagicMock()
            record.get = MagicMock(side_effect=lambda k, p=power: {  # pylint: disable=unnecessary-lambda
                'power': MagicMock(value=p),
            }.get(k))
            records.append(record)

        def get_messages(msg_type):
            if msg_type == 'session':
                return [session_msg]
            elif msg_type == 'record':
                return records
            elif msg_type == 'user_profile':
                profile = MagicMock()
                profile.get = MagicMock(side_effect=lambda k: {  # pylint: disable=unnecessary-lambda
                    'functional_threshold_power': MagicMock(value=275),
                }.get(k))
                return [profile]
            return []

        mock_fit.get_messages = MagicMock(side_effect=get_messages)
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.fit_parser.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.adapter.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        # Verify training load fields exist
        assert 'intensity_factor' in metrics
        assert 'tss' in metrics
        assert 'ftp_watts' in metrics

        # Verify calculations are reasonable
        assert 0 < metrics['intensity_factor'] < 2, "IF should be between 0 and 2"
        assert metrics['tss'] > 0, "TSS should be positive"
        assert metrics['ftp_watts'] == 275

    def test_aerobic_efficiency_metrics_computed(
            self, sample_fit_file, mocker):
        """Test EF and decoupling calculations for ≥30min workouts."""
        mock_fit = MagicMock()

        session_msg = MagicMock()
        session_msg.get = MagicMock(side_effect=lambda key: {  # pylint: disable=unnecessary-lambda
            'sport': MagicMock(value=MagicMock(name='cycling')),
            'start_time': MagicMock(value=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            'timestamp': MagicMock(value=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)),
            'total_elapsed_time': MagicMock(value=3600),  # 60 minutes
            'avg_heart_rate': MagicMock(value=150),
            'avg_power': MagicMock(value=250),
        }.get(key))

        # Create records with HR and power (simulate slight HR drift)
        records = []
        # First half: stable HR around 145, power 250
        for _ in range(300):
            record = MagicMock()
            record.get = MagicMock(side_effect=lambda k: {  # pylint: disable=unnecessary-lambda
                'heart_rate': MagicMock(value=145),
                'power': MagicMock(value=250),
            }.get(k))
            records.append(record)

        # Second half: HR drifts to 155, power stays 250
        for _ in range(300):
            record = MagicMock()
            record.get = MagicMock(side_effect=lambda k: {  # pylint: disable=unnecessary-lambda
                'heart_rate': MagicMock(value=155),
                'power': MagicMock(value=250),
            }.get(k))
            records.append(record)

        def get_messages(msg_type):
            if msg_type == 'session':
                return [session_msg]
            elif msg_type == 'record':
                return records
            return []

        mock_fit.get_messages = MagicMock(side_effect=get_messages)
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.fit_parser.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.adapter.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        # Verify aerobic efficiency fields exist
        assert 'ef_first_half' in metrics
        assert 'ef_second_half' in metrics
        assert 'ef_overall' in metrics
        assert 'hr_drift_bpm' in metrics
        assert 'decoupling_pct' in metrics

        # Verify calculations
        # EF first half = 250/145 ≈ 1.724
        # EF second half = 250/155 ≈ 1.613
        # HR drift = 155 - 145 = 10 bpm
        # Decoupling = ((1.613/1.724) - 1) * 100 ≈ -6.4%
        assert metrics['ef_first_half'] > metrics['ef_second_half'], \
            "EF should decrease with HR drift"
        assert metrics['hr_drift_bpm'] > 0, "HR should drift upward"
        assert metrics['decoupling_pct'] < 0, \
            "Negative decoupling indicates efficiency loss"

    def test_resting_hr_extraction(self, sample_fit_file, mocker):
        """Test extraction of resting HR from user profile."""
        mock_fit = MagicMock()

        session_msg = MagicMock()
        session_msg.get = MagicMock(side_effect=lambda key: {  # pylint: disable=unnecessary-lambda
            'sport': MagicMock(value=MagicMock(name='cycling')),
            'start_time': MagicMock(value=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            'timestamp': MagicMock(value=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)),
            'total_elapsed_time': MagicMock(value=3600),
        }.get(key))

        # Mock user profile with resting HR
        profile_msg = MagicMock()
        profile_msg.get = MagicMock(side_effect=lambda key: {  # pylint: disable=unnecessary-lambda
            'resting_heart_rate': MagicMock(value=55),
        }.get(key))

        def get_messages(msg_type):
            if msg_type == 'session':
                return [session_msg]
            elif msg_type == 'user_profile':
                return [profile_msg]
            elif msg_type == 'monitoring':
                return []
            return []

        mock_fit.get_messages = MagicMock(side_effect=get_messages)
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.fit_parser.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.adapter.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        # Verify resting HR is extracted
        assert 'hr_resting_bpm' in metrics
        assert metrics['hr_resting_bpm'] == 55

    def test_short_workout_skips_aerobic_efficiency(
            self, sample_fit_file, mocker):
        """Test that workouts <30min don't compute aerobic efficiency."""
        mock_fit = MagicMock()

        session_msg = MagicMock()
        session_msg.get = MagicMock(side_effect=lambda key: {  # pylint: disable=unnecessary-lambda
            'sport': MagicMock(value=MagicMock(name='cycling')),
            'start_time': MagicMock(value=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            'timestamp': MagicMock(value=datetime(2024, 1, 15, 10, 20, 0, tzinfo=timezone.utc)),
            'total_elapsed_time': MagicMock(value=1200),  # 20 minutes
            'avg_heart_rate': MagicMock(value=150),
            'avg_power': MagicMock(value=250),
        }.get(key))

        def get_messages(msg_type):
            if msg_type == 'session':
                return [session_msg]
            return []

        mock_fit.get_messages = MagicMock(side_effect=get_messages)
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.fit_parser.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )
        mocker.patch(
            'TrainingAnalyticsPlatform.ingestion.adapter.fitdecode_shim.FitFile',
            return_value=mock_fit,
        )

        parser = FitParser(str(sample_fit_file))
        metrics = parser.parse()

        # Verify aerobic efficiency fields are NOT present
        assert 'ef_first_half' not in metrics
        assert 'ef_second_half' not in metrics
        assert 'decoupling_pct' not in metrics
