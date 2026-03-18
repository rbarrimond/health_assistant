"""Tests for Garmin Connect client authentication behavior."""

from datetime import datetime, timezone
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
