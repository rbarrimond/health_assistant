"""Tests for Garmin Connect client authentication behavior."""

from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import patch

import pytest

from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
    GarminConnectRateLimitError,
    GarminConnectTooManyRequestsError,
)


def test_login_assigns_client_only_after_successful_authentication():
    email = "user@example.com"
    test_secret = "x" * 12

    class SuccessfulGarmin:
        def __init__(self, email, password):
            self.email = email
            self.password = password
            self.logged_in = False

        def login(self):
            self.logged_in = True

    client = GarminConnectClient(email=email, password=test_secret)

    with patch(
        "TrainingAnalyticsPlatform.integrations.garmin_client.GarminImpl",
        SuccessfulGarmin,
    ):
        client.login()

    assert client.client is not None
    assert bool(getattr(client.client, "logged_in", False)) is True


def test_login_clears_cached_client_after_rate_limit_failure():
    email = "user@example.com"
    test_secret = "x" * 12

    class ThrottledGarmin:
        def __init__(self, email, password):
            self.email = email
            self.password = password

        def login(self):
            raise GarminConnectTooManyRequestsError("Rate limit exceeded")

    client = GarminConnectClient(email=email, password=test_secret)
    client.client = cast(Any, object())

    with patch(
        "TrainingAnalyticsPlatform.integrations.garmin_client.GarminImpl",
        ThrottledGarmin,
    ):
        with pytest.raises(GarminConnectRateLimitError) as exc_info:
            client.login()

    assert str(exc_info.value) == "Garmin Connect rate limited this login attempt"
    assert client.client is None


def test_list_activities_uses_date_range_api():
    class DateRangeGarmin:
        def __init__(self):
            self.calls: list[tuple[str, str]] = []

        def get_activities_by_date(self, startdate: str, enddate: str):
            self.calls.append((startdate, enddate))
            return [{"activityId": "a1"}]

    client = GarminConnectClient(email="user@example.com", password="x" * 12)
    fake = DateRangeGarmin()
    client.client = cast(Any, fake)

    activities = client.list_activities(
        start_date=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    )

    assert activities == [{"activityId": "a1"}]
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == "2026-03-01"


def test_dump_tokens_raises_when_client_not_authenticated():
    client = GarminConnectClient(email="user@example.com", password="x" * 12)
    assert client.client is None
    with pytest.raises(GarminConnectError, match="Not authenticated"):
        client.dump_tokens()


def test_dump_tokens_returns_garth_dumps_result():
    from unittest.mock import MagicMock

    fake_garth = MagicMock()
    fake_garth.dumps.return_value = "base64encodedtoken=="
    fake_client = MagicMock()
    fake_client.garth = fake_garth

    gc = GarminConnectClient(email="user@example.com", password="x" * 12)
    gc.client = fake_client

    result = gc.dump_tokens()

    assert result == "base64encodedtoken=="
    fake_garth.dumps.assert_called_once()


def test_restore_from_tokens_calls_login_with_tokenstore():
    """restore_from_tokens must call login(tokenstore=...) to populate display_name."""
    stored_token = "YWJjZA=="

    class FakeGarmin:
        login_kwargs: dict = {}

        def __init__(self):
            self.display_name = "rob"

        def login(self, *args, **kwargs):
            FakeGarmin.login_kwargs = kwargs

    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    with patch(
        "TrainingAnalyticsPlatform.integrations.garmin_client.GarminImpl",
        FakeGarmin,
    ):
        gc.restore_from_tokens(stored_token)

    assert gc.client is not None
    assert FakeGarmin.login_kwargs == {"tokenstore": stored_token}


def test_restore_from_tokens_raises_and_clears_client_on_failure():
    """If login(tokenstore=...) raises, restore_from_tokens must raise GarminConnectError."""

    class BrokenGarmin:
        def __init__(self):
            # No garth attribute needed; login raises before it would be used.
            pass

        def login(self, *args, **kwargs):
            raise ValueError("invalid token data")

    gc = GarminConnectClient(email="user@example.com", password="x" * 12)
    gc.client = object()  # type: ignore[assignment]  # simulate pre-existing client

    with patch(
        "TrainingAnalyticsPlatform.integrations.garmin_client.GarminImpl",
        BrokenGarmin,
    ):
        with pytest.raises(GarminConnectError, match="Failed to restore"):
            gc.restore_from_tokens("bad-token")

    assert gc.client is None


def test_restore_from_tokens_rejects_malformed_base64_before_library_login():
    class FakeGarmin:
        login_called = False

        def __init__(self):
            pass

        def login(self, *args, **kwargs):
            FakeGarmin.login_called = True

    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    with patch(
        "TrainingAnalyticsPlatform.integrations.garmin_client.GarminImpl",
        FakeGarmin,
    ):
        with pytest.raises(GarminConnectError, match="invalid base64"):
            gc.restore_from_tokens("a" * 2709)

    assert FakeGarmin.login_called is False
    assert gc.client is None


def test_restore_from_tokens_normalizes_whitespace_and_padding():
    valid_token_without_padding = "YWJjZA"
    input_token = f"  {valid_token_without_padding}\n"

    class FakeGarmin:
        login_kwargs: dict = {}

        def __init__(self):
            pass

        def login(self, *args, **kwargs):
            FakeGarmin.login_kwargs = kwargs

    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    with patch(
        "TrainingAnalyticsPlatform.integrations.garmin_client.GarminImpl",
        FakeGarmin,
    ):
        gc.restore_from_tokens(input_token)

    assert FakeGarmin.login_kwargs == {"tokenstore": "YWJjZA=="}


# ---------------------------------------------------------------------------
# authenticate()
# ---------------------------------------------------------------------------

def test_authenticate_restores_session_when_token_provided():
    """authenticate() should call restore_from_tokens and return without login."""
    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    restore_calls: list[str] = []
    login_calls: list[None] = []

    def fake_restore(token: str) -> None:
        restore_calls.append(token)

    def fake_login() -> None:
        login_calls.append(None)

    gc.restore_from_tokens = fake_restore  # type: ignore[method-assign]
    gc.login = fake_login  # type: ignore[method-assign]

    gc.authenticate("stored-token==")

    assert restore_calls == ["stored-token=="]
    assert login_calls == []


def test_authenticate_falls_back_to_login_when_token_restore_fails():
    """authenticate() should fall through to login() when restore raises."""
    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    login_calls: list[None] = []

    def fake_restore(token: str) -> None:
        raise GarminConnectError("token expired")

    def fake_login() -> None:
        login_calls.append(None)

    gc.restore_from_tokens = fake_restore  # type: ignore[method-assign]
    gc.login = fake_login  # type: ignore[method-assign]

    gc.authenticate("stale-token==")

    assert login_calls == [None]


def test_authenticate_calls_login_directly_when_no_token():
    """authenticate(None) should skip restore entirely and call login()."""
    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    restore_calls: list[str] = []
    login_calls: list[None] = []

    def fake_restore(token: str) -> None:
        restore_calls.append(token)

    def fake_login() -> None:
        login_calls.append(None)

    gc.restore_from_tokens = fake_restore  # type: ignore[method-assign]
    gc.login = fake_login  # type: ignore[method-assign]

    gc.authenticate(None)

    assert restore_calls == []
    assert login_calls == [None]


def test_authenticate_propagates_login_error():
    """If login() raises, authenticate() must propagate the GarminConnectError."""
    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    def fake_login() -> None:
        raise GarminConnectError("Garmin Connect rate limited this login attempt")

    gc.login = fake_login  # type: ignore[method-assign]

    with pytest.raises(GarminConnectError, match="rate limited"):
        gc.authenticate(None)


def test_authenticate_does_not_fallback_to_login_when_token_restore_rate_limited():
    """authenticate() should not hammer login when token restore is rate limited."""
    gc = GarminConnectClient(email="user@example.com", password="x" * 12)

    login_calls: list[None] = []

    def fake_restore(token: str) -> None:
        raise GarminConnectRateLimitError("Garmin Connect rate limited this token restore attempt")

    def fake_login() -> None:
        login_calls.append(None)

    gc.restore_from_tokens = fake_restore  # type: ignore[method-assign]
    gc.login = fake_login  # type: ignore[method-assign]

    with pytest.raises(GarminConnectRateLimitError, match="rate limited"):
        gc.authenticate("stale-token==")

    assert login_calls == []


def test_login_respects_cooldown_after_rate_limit():
    """A second immediate login attempt should fail fast during cooldown."""
    email = "user@example.com"
    test_secret = "x" * 12

    class ThrottledGarmin:
        def __init__(self, email, password):
            self.email = email
            self.password = password

        def login(self):
            raise GarminConnectTooManyRequestsError("Rate limit exceeded")

    client = GarminConnectClient(email=email, password=test_secret)

    with patch(
        "TrainingAnalyticsPlatform.integrations.garmin_client.GarminImpl",
        ThrottledGarmin,
    ):
        with pytest.raises(GarminConnectRateLimitError, match="rate limited"):
            client.login()

        with pytest.raises(GarminConnectRateLimitError, match="temporarily rate limited"):
            client.login()
