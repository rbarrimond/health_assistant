"""Tests for Garmin physiometrics sync handler."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from TrainingAnalyticsPlatform.handlers.garmin_physiometrics_sync_handler import (
    GarminPhysiometricsSyncHandler,
)
from TrainingAnalyticsPlatform.integrations.garmin_client import GarminConnectError


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


def _training_readiness_payload() -> dict:
    return {
        "score": 84,
        "recoveryTimeMinutes": 600,
    }


def test_sync_handler_stores_combined_metrics():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.upload_external_source_json = Mock(return_value="physiometrics/rob/garmin/daily/blob.json")
    state_table = Mock()
    state_table.query_entities.return_value = [{"blob_name": "physiometrics/rob/garmin/daily/blob.json"}]
    storage.infrastructure.get_table_client = Mock(return_value=state_table)

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days=1)

    assert status == 200
    assert response["count"] >= 1
    assert storage.physiometrics.store_physiometrics.called

    kwargs = storage.physiometrics.store_physiometrics.call_args.kwargs
    assert kwargs["athlete_id"] == "rob"
    assert kwargs["data_source"] == "garmin"
    assert kwargs["physiometrics_data"]["training_load"] == 76
    assert kwargs["physiometrics_data"]["cycling_vo2max_ml_kg_min"] == pytest.approx(58.3)
    assert kwargs["physiometrics_data"]["running_vo2max_ml_kg_min"] == pytest.approx(55.1)
    assert kwargs["physiometrics_data"]["readiness_score"] == 84
    assert kwargs["physiometrics_data"]["recovery_time_minutes"] == 600
    assert "ext_json" in kwargs["physiometrics_data"]
    storage.infrastructure.upload_external_source_json.assert_called()


def test_sync_handler_validates_lookback_days_type():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.get_table_client = Mock(return_value=Mock(query_entities=Mock(return_value=[])))
    client = Mock()
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days="not-a-number")

    assert status == 400
    assert "lookback_days" in response["error"]


def test_sync_handler_reports_partial_errors():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.upload_external_source_json = Mock(return_value="physiometrics/rob/garmin/daily/blob.json")
    state_table = Mock()
    state_table.query_entities.return_value = [{"blob_name": "physiometrics/rob/garmin/daily/blob.json"}]
    storage.infrastructure.get_table_client = Mock(return_value=state_table)

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.side_effect = RuntimeError("garmin unavailable")
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days=1)

    assert status == 207
    assert response["count"] == 0
    assert response["errors"] is not None
    assert response["records_failed"] >= 1


def test_sync_handler_tolerates_readiness_endpoint_failures():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.upload_external_source_json = Mock(return_value="physiometrics/rob/garmin/daily/blob.json")
    state_table = Mock()
    state_table.query_entities.return_value = [{"blob_name": "physiometrics/rob/garmin/daily/blob.json"}]
    storage.infrastructure.get_table_client = Mock(return_value=state_table)

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.side_effect = GarminConnectError("readiness unavailable")
    client.get_morning_training_readiness.side_effect = GarminConnectError("morning readiness unavailable")

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days=1)

    assert status == 200
    assert response["count"] >= 1
    kwargs = storage.physiometrics.store_physiometrics.call_args.kwargs
    # Falls back to summary/training-status values when readiness endpoints fail.
    assert kwargs["physiometrics_data"]["readiness_score"] == 80
    assert kwargs["physiometrics_data"]["recovery_time_minutes"] == 720


def test_sync_handler_skips_dates_already_stored_when_not_forced():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.physiometrics.get_physiometrics_history.return_value = [
        {"effective_date": "2026-03-03"},
        {"effective_date": "2026-03-04"},
    ]
    storage.infrastructure = Mock()
    storage.infrastructure.get_table_client = Mock(return_value=Mock(query_entities=Mock(return_value=[])))

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.garmin_physiometrics_sync_handler.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=1, force=False)

    assert status == 200
    assert response["records_skipped"] == 2
    assert response["records_fetched"] == 0
    assert response["count"] == 0
    storage.physiometrics.store_physiometrics.assert_not_called()


def test_sync_handler_force_true_reprocesses_stored_dates():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.physiometrics.get_physiometrics_history.return_value = [
        {"effective_date": "2026-03-03"},
        {"effective_date": "2026-03-04"},
    ]
    storage.infrastructure = Mock()
    storage.infrastructure.upload_external_source_json = Mock(
        return_value="physiometrics/rob/garmin/daily/blob.json"
    )
    state_table = Mock()
    state_table.query_entities.return_value = [{"blob_name": "physiometrics/rob/garmin/daily/blob.json"}]
    storage.infrastructure.get_table_client = Mock(return_value=state_table)

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.garmin_physiometrics_sync_handler.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=1, force=True)

    assert status == 200
    assert response["records_skipped"] == 0
    assert response["records_fetched"] == 2
    assert storage.physiometrics.store_physiometrics.call_count == 2


def test_sync_handler_continues_when_prefetch_history_fails():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.physiometrics.get_physiometrics_history.side_effect = RuntimeError("table read failed")
    storage.infrastructure = Mock()
    storage.infrastructure.upload_external_source_json = Mock(
        return_value="physiometrics/rob/garmin/daily/blob.json"
    )
    state_table = Mock()
    state_table.query_entities.return_value = [{"blob_name": "physiometrics/rob/garmin/daily/blob.json"}]
    storage.infrastructure.get_table_client = Mock(return_value=state_table)

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.garmin_physiometrics_sync_handler.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=1, force=False)

    assert status == 200
    assert response["records_fetched"] == 2
    assert response["records_skipped"] == 0
    assert storage.physiometrics.store_physiometrics.call_count == 2


# ---------------------------------------------------------------------------
# Token lifecycle tests
# ---------------------------------------------------------------------------

def _make_physiometrics_handler(storage: Mock, client: Mock) -> GarminPhysiometricsSyncHandler:
    return GarminPhysiometricsSyncHandler(storage=storage, client=client)


def test_handle_restores_session_from_stored_token_and_skips_login():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.get_table_client = Mock(return_value=Mock(query_entities=Mock(return_value=[])))
    storage.oauth_tokens.get_garmin_tokens.return_value = "stored-garth-token"

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = None
    client.get_morning_training_readiness.return_value = None
    client.dump_tokens.return_value = "refreshed-garth-token"

    handler = _make_physiometrics_handler(storage, client)
    _, status = handler.handle("rob", lookback_days=1)

    client.restore_from_tokens.assert_called_once_with("stored-garth-token")
    client.login.assert_not_called()
    storage.oauth_tokens.store_garmin_tokens.assert_called_with(
        "rob", "refreshed-garth-token"
    )
    assert status == 200


def test_handle_falls_back_to_login_when_no_stored_token():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.get_table_client = Mock(return_value=Mock(query_entities=Mock(return_value=[])))
    storage.oauth_tokens.get_garmin_tokens.return_value = None

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = None
    client.get_morning_training_readiness.return_value = None
    client.dump_tokens.return_value = "fresh-garth-token"

    handler = _make_physiometrics_handler(storage, client)
    _, status = handler.handle("rob", lookback_days=1)

    client.restore_from_tokens.assert_not_called()
    client.login.assert_called_once()
    storage.oauth_tokens.store_garmin_tokens.assert_called_with(
        "rob", "fresh-garth-token"
    )
    assert status == 200


def test_handle_falls_back_to_login_on_stale_token():
    storage = Mock()
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.get_table_client = Mock(return_value=Mock(query_entities=Mock(return_value=[])))
    storage.oauth_tokens.get_garmin_tokens.return_value = "expired-token"

    client = Mock()
    client.restore_from_tokens.side_effect = GarminConnectError("token expired")
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = None
    client.get_morning_training_readiness.return_value = None
    client.dump_tokens.return_value = "fresh-garth-token"

    handler = _make_physiometrics_handler(storage, client)
    _, status = handler.handle("rob", lookback_days=1)

    client.restore_from_tokens.assert_called_once_with("expired-token")
    client.login.assert_called_once()
    storage.oauth_tokens.store_garmin_tokens.assert_called_with(
        "rob", "fresh-garth-token"
    )
    assert status == 200


def test_handle_returns_401_when_login_fails_and_no_stored_token():
    storage = Mock()
    storage.oauth_tokens.get_garmin_tokens.return_value = None

    client = Mock()
    client.login.side_effect = GarminConnectError("rate limited")

    handler = _make_physiometrics_handler(storage, client)
    response, status = handler.handle("rob", lookback_days=1)

    assert status == 401
    assert "Authentication failed" in response["error"]
