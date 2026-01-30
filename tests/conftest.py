"""Pytest configuration and fixtures."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, patch

import json
import pytest


class _SimpleMocker:
    """Minimal pytest-mock compatible helper for patch()."""

    def __init__(self) -> None:
        self._patches = []

    def patch(self, *args, **kwargs):
        patcher = patch(*args, **kwargs)
        mocked = patcher.start()
        self._patches.append(patcher)
        return mocked

    def stopall(self) -> None:
        while self._patches:
            self._patches.pop().stop()


@pytest.fixture
def mocker():
    """Provide a minimal mocker fixture when pytest-mock isn't available."""
    simple_mocker = _SimpleMocker()
    yield simple_mocker
    simple_mocker.stopall()


@pytest.fixture
def sample_fit_file(tmp_path: Path) -> Path:
    """Create a temporary FIT file for testing."""
    fit_file = tmp_path / "sample.fit"
    # Create a minimal binary FIT file structure
    # FIT file starts with 14-byte header
    header = bytes([14, 16, 32, 32])  # Size, protocol, profile, type
    header += b'\x00' * 10  # Padding
    fit_file.write_bytes(header + b'minimal_fit_data')
    return fit_file


@pytest.fixture
def mock_fit_message() -> Mock:
    """Create a mock FIT message."""
    msg = MagicMock()

    # Create mock field objects with .value attributes
    def create_field(value):
        field = MagicMock()
        field.value = value
        return field

    def _msg_get(_key):
        return create_field(None)

    msg.get = MagicMock(side_effect=_msg_get)
    return msg


@pytest.fixture(name="mock_fit_file_with_data")
def fixture_mock_fit_file_with_data() -> Mock:
    """Create a mock FitFile with sample data."""
    fit_file = MagicMock()

    # Create file_id message
    file_id_msg = MagicMock()

    # Create enum-like objects with .name attributes
    sport_enum = MagicMock()
    sport_enum.name = 'cycling'
    manufacturer_enum = MagicMock()
    manufacturer_enum.name = 'garmin'

    _file_id_mapping = {
        'type': MagicMock(value=sport_enum),
        'manufacturer': MagicMock(value=manufacturer_enum),
    }

    def _file_id_get(key):
        return _file_id_mapping.get(key)

    file_id_msg.get = MagicMock(side_effect=_file_id_get)

    # Create session message
    session_msg = MagicMock()

    # Create enum objects for sub_sport and sport
    sub_sport_enum = MagicMock()
    sub_sport_enum.name = 'road'
    session_sport_enum = MagicMock()
    session_sport_enum.name = 'cycling'

    _session_mapping = {
        'sub_sport': MagicMock(value=sub_sport_enum),
        'sport': MagicMock(value=session_sport_enum),
        'start_time': MagicMock(value=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)),
        'timestamp': MagicMock(value=datetime(2024, 1, 15, 11, 30, 0, tzinfo=timezone.utc)),
        'total_elapsed_time': MagicMock(value=3600),  # 1 hour
        'total_timer_time': MagicMock(value=3500),    # Active time
        'total_distance': MagicMock(value=42000),     # 42 km
        'total_ascent': MagicMock(value=500),         # 500 m
        'total_descent': MagicMock(value=480),        # 480 m
        'avg_speed': MagicMock(value=11.67),          # m/s
        'max_speed': MagicMock(value=15.5),           # m/s
        'avg_heart_rate': MagicMock(value=150),       # bpm
        'max_heart_rate': MagicMock(value=185),       # bpm
        'avg_power': MagicMock(value=250),            # watts
        'max_power': MagicMock(value=1200),           # watts
        'avg_cadence': MagicMock(value=90),           # rpm
        'max_cadence': MagicMock(value=120),          # rpm
        'total_calories': MagicMock(value=1500),      # kcal
    }

    def _session_get(key):
        return _session_mapping.get(key)

    session_msg.get = MagicMock(side_effect=_session_get)

    # Setup get_messages to return appropriate message lists
    def get_messages(msg_type):
        if msg_type == 'file_id':
            return [file_id_msg]
        elif msg_type == 'session':
            return [session_msg]
        elif msg_type == 'record':
            return []
        return []

    fit_file.get_messages = MagicMock(side_effect=get_messages)
    return fit_file


@pytest.fixture(name="mock_fit_file_with_records")
def fixture_mock_fit_file_with_records(mock_fit_file_with_data: Mock) -> Mock:
    """Create a mock FitFile with record messages (heart rate, power, etc.)."""
    fit_file = mock_fit_file_with_data

    # Create record messages with heart rate and power data
    records = []
    heart_rates = [140, 145, 150, 155, 160, 165, 170, 165, 160, 155]
    powers = [200, 220, 250, 280, 300, 290, 270, 250, 230, 210]
    cadences = [85, 88, 90, 92, 95, 93, 90, 88, 85, 82]

    for hr, power, cadence in zip(heart_rates, powers, cadences):
        record = MagicMock()

        def _record_get(key, h=hr, p=power, c=cadence):
            mapping = {
                'heart_rate': MagicMock(value=h),
                'power': MagicMock(value=p),
                'cadence': MagicMock(value=c),
            }
            return mapping.get(key)

        record.get = MagicMock(side_effect=_record_get)
        records.append(record)

    # Override get_messages for records
    original_get_messages = fit_file.get_messages

    def get_messages_with_records(msg_type):
        if msg_type == 'record':
            return records
        return original_get_messages(msg_type)

    fit_file.get_messages = MagicMock(side_effect=get_messages_with_records)
    return fit_file


@pytest.fixture
def sample_payload() -> Dict[str, Any]:
    """Load example OneDrive payload JSON used by smoke/integration tests."""
    data_path = Path(__file__).resolve().parent / "data" / "test_payload_example.json"
    with data_path.open("r", encoding="utf-8") as f:
        return json.load(f)
