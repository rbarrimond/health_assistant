"""Tests for Garmin Connect client authentication behavior."""

from typing import Any, cast
from unittest.mock import patch

import pytest

from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
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
        with pytest.raises(GarminConnectError) as exc_info:
            client.login()

    assert str(exc_info.value) == "Garmin Connect rate limited this login attempt"
    assert client.client is None
