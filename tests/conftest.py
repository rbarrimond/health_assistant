"""Pytest configuration and fixtures."""
# pylint: disable=line-too-long

import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import parse_qs, urlparse

import pytest


def _build_fit_message(
    name: str,
    fields: Dict[str, Any],
    developer_fields: Optional[list] = None,
) -> Mock:
    field_objects = []
    field_map: Dict[str, Mock] = {}
    for field_name, value in fields.items():
        field = MagicMock()
        field.name = field_name
        field.value = value
        field.units = getattr(value, "units", None)
        field_objects.append(field)
        field_map[field_name] = field

    msg = MagicMock()
    msg.name = name
    msg.fields = field_objects
    msg.developer_fields = developer_fields or []
    msg.get_value.side_effect = (
        lambda key: field_map.get(key).value if key in field_map else None
    )
    msg.get_raw_value.side_effect = (
        lambda key: field_map.get(key).value if key in field_map else None
    )
    return msg


def _env_enabled(name: str) -> bool:
    value = os.getenv(name, "").lower()
    return value in {"1", "true", "yes"}


def pytest_collection_modifyitems(config, items):  # noqa: ARG001 - pytest hook signature  # pylint: disable=unused-argument
    """Skip certain tests based on environment variables."""
    if not _env_enabled("RUN_INTEGRATION"):
        skip_integration = pytest.mark.skip(
            reason="Set RUN_INTEGRATION=1 to run integration tests"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

    if not _env_enabled("RUN_AZURE_INTEGRATION"):
        skip_azure = pytest.mark.skip(
            reason="Set RUN_AZURE_INTEGRATION=1 to run Azure integration tests"
        )
        for item in items:
            if "azure_integration" in item.keywords:
                item.add_marker(skip_azure)


class _SimpleMocker:
    """Minimal pytest-mock compatible helper for patch()."""

    def __init__(self) -> None:
        self._patches = []

    def patch(self, *args, **kwargs):
        """Start and track a patcher for later cleanup."""
        patcher = patch(*args, **kwargs)
        mocked = patcher.start()
        self._patches.append(patcher)
        return mocked

    def stopall(self) -> None:
        """Stop all active patchers created by this helper."""
        while self._patches:
            self._patches.pop().stop()


@pytest.fixture
def mocker():
    """Provide a minimal mocker fixture when pytest-mock isn't available."""
    simple_mocker = _SimpleMocker()
    yield simple_mocker
    simple_mocker.stopall()


@pytest.fixture
def fit_message_factory():
    """Provide a helper for building fitdecode-like messages in tests."""
    return _build_fit_message


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
def fixture_mock_fit_file_with_data() -> list:
    """Create a mock FIT message list with sample data."""
    # Create enum-like objects with .name attributes
    sport_enum = MagicMock()
    sport_enum.name = 'cycling'
    manufacturer_enum = MagicMock()
    manufacturer_enum.name = 'garmin'

    sub_sport_enum = MagicMock()
    sub_sport_enum.name = 'road'
    session_sport_enum = MagicMock()
    session_sport_enum.name = 'cycling'

    file_id_fields = {
        'type': sport_enum,
        'manufacturer': manufacturer_enum,
    }

    file_id_msg = _build_fit_message("file_id", file_id_fields)

    session_fields = {
        'sub_sport': sub_sport_enum,
        'sport': session_sport_enum,
        'start_time': datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        'timestamp': datetime(2024, 1, 15, 11, 30, 0, tzinfo=timezone.utc),
        'total_elapsed_time': 3600,
        'total_timer_time': 3500,
        'total_distance': 42000,
        'total_ascent': 500,
        'total_descent': 480,
        'avg_speed': 11.67,
        'max_speed': 15.5,
        'avg_heart_rate': 150,
        'max_heart_rate': 185,
        'avg_power': 250,
        'max_power': 1200,
        'avg_cadence': 90,
        'max_cadence': 120,
        'total_calories': 1500,
    }

    session_msg = _build_fit_message("session", session_fields)

    return [file_id_msg, session_msg]


@pytest.fixture(name="mock_fit_file_with_records")
def fixture_mock_fit_file_with_records(mock_fit_file_with_data: list) -> list:
    """Create a mock FIT message list with record messages (heart rate, power, etc.)."""
    # Start with existing messages
    messages = list(mock_fit_file_with_data)

    # Create record messages with heart rate and power data
    heart_rates = [140, 145, 150, 155, 160, 165, 170, 165, 160, 155]
    powers = [200, 220, 250, 280, 300, 290, 270, 250, 230, 210]
    cadences = [85, 88, 90, 92, 95, 93, 90, 88, 85, 82]

    for hr, power, cadence in zip(heart_rates, powers, cadences):
        record_fields = {
            'heart_rate': hr,
            'power': power,
            'cadence': cadence,
        }
        record_msg = _build_fit_message("record", record_fields)
        messages.append(record_msg)

    return messages


@pytest.fixture
def sample_payload() -> Dict[str, Any]:
    """Load example OneDrive payload JSON used by smoke/integration tests."""
    data_path = Path(__file__).resolve().parent / \
        "data" / "test_payload_example.json"
    with data_path.open("r", encoding="utf-8") as f:
        return json.load(f)


class _AgentMemoryRequestHandler(BaseHTTPRequestHandler):  # pylint: disable=invalid-name
    _ERR_MISSING_ATHLETE_ID = "Missing required parameter: athlete_id"
    _ERR_NOT_FOUND = "Not found"

    def log_message(self, format, *args):  # noqa: A003 - match base signature
        # pylint: disable=redefined-builtin
        # Silence request logging during tests.
        return

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        # pylint: disable=invalid-name
        """Handle read-only agent memory endpoints."""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        athlete_id = query.get("athlete_id", [""])[0]

        if path == "/api/agent/context":
            if not athlete_id:
                return self._send_json(
                    {"error": self._ERR_MISSING_ATHLETE_ID},
                    400,
                )
            return self._send_json(
                {
                    "athlete_id": athlete_id,
                    "preferences": {},
                    "active_observations": [],
                    "instruction_addendum": None,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
                200,
            )

        if path == "/api/agent/preferences":
            if not athlete_id:
                return self._send_json(
                    {"error": self._ERR_MISSING_ATHLETE_ID},
                    400,
                )
            return self._send_json({"athlete_id": athlete_id, "preferences": {}}, 200)

        if path == "/api/agent/observations":
            if not athlete_id:
                return self._send_json(
                    {"error": self._ERR_MISSING_ATHLETE_ID},
                    400,
                )
            return self._send_json(
                {"athlete_id": athlete_id, "observations": [], "count": 0},
                200,
            )

        return self._send_json({"error": self._ERR_NOT_FOUND}, 404)

    def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        # pylint: disable=invalid-name
        """Handle write agent memory endpoints."""
        parsed = urlparse(self.path)
        path = parsed.path
        payload = self._read_json()

        if path == "/api/agent/preferences":
            athlete_id = payload.get("athlete_id", "")
            if not athlete_id:
                return self._send_json(
                    {"error": self._ERR_MISSING_ATHLETE_ID},
                    400,
                )
            return self._send_json(
                {
                    "athlete_id": athlete_id,
                    "preferences": payload,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                200,
            )

        if path == "/api/agent/observations":
            athlete_id = payload.get("athlete_id", "")
            if not athlete_id:
                return self._send_json({"error": "Missing required parameters"}, 400)
            obs_id = "test-observation-1"
            return self._send_json(
                {
                    "observation_id": obs_id,
                    "observation": {"observation_id": obs_id, **payload},
                },
                201,
            )

        return self._send_json({"error": self._ERR_NOT_FOUND}, 404)

    def do_PATCH(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        # pylint: disable=invalid-name
        """Handle observation status updates."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/agent/observations/"):
            obs_id = path.rsplit("/", 1)[-1]
            payload = self._read_json()
            status = payload.get("status", "resolved")
            return self._send_json(
                {
                    "observation_id": obs_id,
                    "status": status,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                200,
            )

        return self._send_json({"error": self._ERR_NOT_FOUND}, 404)


class _ThreadedHTTPServer(HTTPServer):
    daemon_threads = True


def _start_test_server() -> Optional[Tuple[HTTPServer, threading.Thread]]:
    """Start a local HTTP server for agent memory tests."""
    try:
        server = _ThreadedHTTPServer(
            ("127.0.0.1", 7071), _AgentMemoryRequestHandler)
    except OSError:
        return None

    thread = threading.Thread(
        target=server.serve_forever, name="agent-memory-test-server")
    thread.daemon = True
    thread.start()
    return server, thread


@pytest.fixture(scope="session", autouse=True)
def agent_memory_test_server():
    """Provide a lightweight HTTP server for integration-style tests."""
    server_info = _start_test_server()
    yield
    if server_info is not None:
        server, thread = server_info
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture(scope="session", name="observation_id")
def fixture_observation_id() -> str:
    """Provide a stable observation id for tests that require one."""
    return "test-observation-1"
