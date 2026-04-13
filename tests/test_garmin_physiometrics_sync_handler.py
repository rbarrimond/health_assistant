"""Tests for Garmin physiometrics sync handler."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from TrainingAnalyticsPlatform.handlers.wellness_sync import GarminPhysiometricsSyncHandler
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


def _cycling_ftp_payload(calendar_date: str = "2026-03-03T06:00:00+00:00") -> dict:
    return {
        "calendarDate": calendar_date,
        "functionalThresholdPower": 312,
    }


def _lactate_threshold_payload(calendar_date: str = "2026-03-03") -> dict:
    return {
        "speed_and_heart_rate": {
            "calendarDate": calendar_date,
            "heartRateCycling": 173,
            "heartRate": 165,
        },
        "power": {},
    }


def test_sync_handler_stores_combined_metrics():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days=1)

    assert status == 200
    assert response["count"] >= 1
    assert storage.physiometrics.store_physiometrics.called

    kwargs = storage.physiometrics.store_physiometrics.call_args.kwargs
    assert kwargs["athlete_id"] == "rob"
    assert kwargs["data_source"] == "garmin"
    assert kwargs["physiometrics_data"]["training_load"] == 76
    assert kwargs["physiometrics_data"]["ftp_watts"] == 312
    assert kwargs["physiometrics_data"]["hr_lthr_bpm"] == 173
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
    client.get_cycling_ftp.return_value = None
    client.get_lactate_threshold.return_value = None

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days="not-a-number")

    assert status == 400
    assert "lookback_days" in response["error"]


def test_sync_handler_lookback_zero_targets_today_only():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.upload_external_source_json = Mock(return_value="physiometrics/rob/garmin/daily/blob.json")
    state_table = Mock()
    state_table.query_entities.return_value = [{"blob_name": "physiometrics/rob/garmin/daily/blob.json"}]
    storage.infrastructure.get_table_client = Mock(return_value=state_table)

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-04")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None
    client.get_cycling_ftp.return_value = _cycling_ftp_payload(calendar_date="2026-03-04T06:00:00+00:00")
    client.get_lactate_threshold.return_value = _lactate_threshold_payload(calendar_date="2026-03-04")

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.wellness_sync.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=0)

    assert status == 200
    assert response["records_fetched"] == 1
    client.get_user_summary.assert_called_once_with("2026-03-04")


def test_sync_handler_reports_partial_errors():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    response, status = handler.handle("rob", lookback_days=1)

    assert status == 207
    assert response["count"] == 0
    assert response["errors"] is not None
    assert response["errors"][0]["error_code"] == "INTERNAL_SERVER_ERROR"
    assert response["errors"][0]["recoverable"] is False
    assert response["records_failed"] >= 1


def test_sync_handler_tolerates_readiness_endpoint_failures():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()

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
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.wellness_sync.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=1, force=False)

    assert status == 200
    assert response["records_skipped"] == 1
    assert response["records_fetched"] == 0
    assert response["count"] == 0
    storage.physiometrics.store_physiometrics.assert_not_called()


def test_sync_handler_force_true_reprocesses_stored_dates():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.wellness_sync.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=1, force=True)

    assert status == 200
    assert response["records_skipped"] == 0
    assert response["records_fetched"] == 1
    assert storage.physiometrics.store_physiometrics.call_count == 1


def test_sync_handler_continues_when_prefetch_history_fails():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.wellness_sync.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=1, force=False)

    assert status == 200
    assert response["records_fetched"] == 1
    assert response["records_skipped"] == 0
    assert storage.physiometrics.store_physiometrics.call_count == 1

def test_sync_handler_only_applies_latest_baselines_on_or_after_baseline_date():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
    storage.physiometrics = Mock()
    storage.infrastructure = Mock()
    storage.infrastructure.upload_external_source_json = Mock(return_value="physiometrics/rob/garmin/daily/blob.json")
    state_table = Mock()
    state_table.query_entities.return_value = [{"blob_name": "physiometrics/rob/garmin/daily/blob.json"}]
    storage.infrastructure.get_table_client = Mock(return_value=state_table)

    client = Mock()
    client.get_user_summary.return_value = _summary_payload("2026-03-09")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = _training_readiness_payload()
    client.get_morning_training_readiness.return_value = None
    client.get_cycling_ftp.return_value = _cycling_ftp_payload(calendar_date="2026-03-10T17:48:13.480")
    client.get_lactate_threshold.return_value = _lactate_threshold_payload(calendar_date="2026-03-10")

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    handler._process_single_day("rob", "2026-03-09")

    kwargs = storage.physiometrics.store_physiometrics.call_args.kwargs
    assert kwargs["physiometrics_data"]["ftp_watts"] == 300
    assert kwargs["physiometrics_data"]["hr_lthr_bpm"] == 168


def test_sync_handler_tolerates_dedicated_baseline_endpoint_failures():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.side_effect = GarminConnectError("ftp unavailable")
    client.get_lactate_threshold.side_effect = GarminConnectError("lthr unavailable")

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    _, status = handler.handle("rob", lookback_days=1)

    assert status == 200
    kwargs = storage.physiometrics.store_physiometrics.call_args.kwargs
    assert kwargs["physiometrics_data"]["ftp_watts"] == 300
    assert kwargs["physiometrics_data"]["hr_lthr_bpm"] == 168


# ---------------------------------------------------------------------------
# Token lifecycle tests
# ---------------------------------------------------------------------------

def _make_physiometrics_handler(storage: Mock, client: Mock) -> GarminPhysiometricsSyncHandler:
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()
    client.dump_tokens.return_value = "refreshed-garth-token"

    handler = _make_physiometrics_handler(storage, client)
    _, status = handler.handle("rob", lookback_days=1)

    client.authenticate.assert_called_once_with("stored-garth-token")
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
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()
    client.dump_tokens.return_value = "fresh-garth-token"

    handler = _make_physiometrics_handler(storage, client)
    _, status = handler.handle("rob", lookback_days=1)

    client.authenticate.assert_called_once_with(None)
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
    client.get_user_summary.return_value = _summary_payload("2026-03-03")
    client.get_training_status.return_value = _training_status_payload()
    client.get_training_readiness.return_value = None
    client.get_morning_training_readiness.return_value = None
    client.get_cycling_ftp.return_value = _cycling_ftp_payload()
    client.get_lactate_threshold.return_value = _lactate_threshold_payload()
    client.dump_tokens.return_value = "fresh-garth-token"

    handler = _make_physiometrics_handler(storage, client)
    _, status = handler.handle("rob", lookback_days=1)

    # Handler passes the stored token to authenticate(); the fallback logic
    # (restore → login) is the responsibility of GarminConnectClient.authenticate()
    # and is covered by test_garmin_client.py.
    client.authenticate.assert_called_once_with("expired-token")
    storage.oauth_tokens.store_garmin_tokens.assert_called_with(
        "rob", "fresh-garth-token"
    )
    assert status == 200


def test_handle_returns_429_when_authenticate_raises_rate_limited():
    storage = Mock()
    storage.oauth_tokens.get_garmin_tokens.return_value = None

    client = Mock()
    client.authenticate.side_effect = GarminConnectError("rate limited")

    handler = _make_physiometrics_handler(storage, client)
    response, status = handler.handle("rob", lookback_days=1)

    assert status == 429
    assert response["error_code"] == "GARMIN_RATE_LIMITED"


def test_sync_handler_short_circuits_on_fatal_garmin_error():
    storage = Mock()
    storage.oauth_tokens.get_garmin_rate_limit_blocked_until.return_value = None
    storage.physiometrics = Mock()
    storage.physiometrics.get_physiometrics_history.return_value = []
    storage.infrastructure = Mock()
    storage.infrastructure.get_table_client = Mock(return_value=Mock(query_entities=Mock(return_value=[])))

    client = Mock()
    client.get_user_summary.side_effect = GarminConnectError("not authenticated")
    client.dump_tokens.return_value = "token"

    handler = GarminPhysiometricsSyncHandler(storage=storage, client=client)

    with patch(
        "TrainingAnalyticsPlatform.handlers.wellness_sync.datetime"
    ) as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 3, 4, tzinfo=timezone.utc)
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        response, status = handler.handle("rob", lookback_days=2, force=True)

    assert status == 207
    assert response["records_failed"] == 1
    assert response["records_fetched"] == 0
    assert response["errors"] is not None
    assert response["errors"][0]["error_code"] == "GARMIN_AUTH_ERROR"
    assert response["errors"][0]["recoverable"] is False
    assert client.get_user_summary.call_count == 1
