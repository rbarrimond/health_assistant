"""Tests for Garmin physiometrics sync handler."""

from unittest.mock import Mock

import pytest

from TrainingAnalyticsPlatform.handlers.garmin_physiometrics_sync_handler import (
    GarminPhysiometricsSyncHandler,
)


def _summary_payload(date_str: str) -> dict:
    return {
        "calendarDate": date_str,
        "stats": {
            "functionThreshold": 300,
            "vo2MaxCycling": {"value": 58.3},
            "vo2MaxRunning": {"value": 55.1},
            "maxHeartRate": 194,
            "restingHeartRate": 50,
            "readiness": {"score": 80},
        },
    }


def _training_status_payload() -> dict:
    return {
        "trainingLoad": {"load": 76},
        "trainingEffect": {"aerobic": 2.9, "anaerobic": 1.2},
        "trainingStressScore": 86,
        "trainingStressBalance": -10,
        "atpProbability": 69,
        "recoveryTimeMinutes": 720,
        "lactateThresholdHeartRate": 168,
    }


def test_sync_handler_stores_combined_metrics():
    storage = Mock()
    storage.physiometrics = Mock()

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days=1)

    assert status == 200
    assert response["count"] >= 1
    assert storage.physiometrics.store_physiometrics.called

    kwargs = storage.physiometrics.store_physiometrics.call_args.kwargs
    assert kwargs["athlete_id"] == "rob"
    assert kwargs["data_source"] == "garmin"
    assert kwargs["physiometrics_data"]["training_load"] == 76
    assert kwargs["physiometrics_data"]["running_vo2max_ml_kg_min"] == pytest.approx(55.1)


def test_sync_handler_validates_lookback_days_type():
    storage = Mock()
    storage.physiometrics = Mock()
    client = Mock()

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days="not-a-number")

    assert status == 400
    assert "lookback_days" in response["error"]


def test_sync_handler_reports_partial_errors():
    storage = Mock()
    storage.physiometrics = Mock()

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.side_effect = RuntimeError("garmin unavailable")

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days=1)

    assert status == 200
    assert response["count"] == 0
    assert response["errors"] is not None
