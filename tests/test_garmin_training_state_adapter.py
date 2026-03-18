"""Tests for Garmin training state adapter mapping and validation."""

import pytest

from TrainingAnalyticsPlatform.ingestion.wellness_adapters import (
    AdapterError,
    GarminTrainingStateAdapter,
)


def _raw_payload(include_lthr: bool = True) -> dict:
    training_status = {
        "trainingLoad": {"load": 87},
        "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        "trainingStressScore": 92.5,
        "trainingStressBalance": -14.2,
        "atpProbability": 71.0,
        "recoveryTimeMinutes": 820,
    }
    if include_lthr:
        training_status["lactateThresholdHeartRate"] = 171

    return {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {
                "functionThreshold": 300,
                "vo2MaxCycling": {"value": 59.2},
                "vo2MaxRunning": {"value": 56.8},
                "maxHeartRate": 196,
                "restingHeartRate": 51,
                "readiness": {"score": 82},
            },
        },
        "training_status": training_status,
    }


def test_maps_summary_and_training_status_fields():
    adapter = GarminTrainingStateAdapter()

    snapshot = adapter.adapt(_raw_payload(), athlete_id="rob")

    assert snapshot.effective_date == "2026-03-03"
    assert snapshot.ftp_watts == 300
    assert snapshot.cycling_vo2max_ml_kg_min == pytest.approx(59.2)
    assert snapshot.running_vo2max_ml_kg_min == pytest.approx(56.8)
    assert snapshot.hr_max_bpm == 196
    # Intervals is the exclusive source for resting HR in v3.0.0.
    assert snapshot.resting_hr_bpm is None
    assert snapshot.readiness_score == 82

    assert snapshot.training_load == 87
    assert snapshot.training_effect_aerobic == pytest.approx(3.2)
    assert snapshot.training_effect_anaerobic == pytest.approx(1.4)
    assert snapshot.training_stress_score == pytest.approx(92.5)
    assert snapshot.training_stress_balance == pytest.approx(-14.2)
    assert snapshot.atp_probability == pytest.approx(71.0)
    assert snapshot.recovery_time_minutes == 820
    assert snapshot.hr_lthr_bpm == 171


def test_lthr_falls_back_to_estimate_when_training_status_missing_lthr():
    adapter = GarminTrainingStateAdapter()

    snapshot = adapter.adapt(_raw_payload(include_lthr=False), athlete_id="rob")

    assert snapshot.hr_lthr_bpm == int(196 * 0.85)


def test_rejects_training_effect_out_of_range():
    adapter = GarminTrainingStateAdapter()
    raw = _raw_payload()
    raw["training_status"]["trainingEffect"]["aerobic"] = 6.2

    with pytest.raises(AdapterError):
        adapter.adapt(raw, athlete_id="rob")


def test_maps_running_vo2max_from_modern_training_status_context():
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {
                "functionThreshold": 300,
                "maxHeartRate": 196,
                "readiness": {"score": 82},
            },
        },
        "training_status": {
            "mostRecentVO2Max": {
                "running": {"vo2MaxPreciseValue": 57.4},
                "cycling": {"vo2MaxPreciseValue": 60.1},
            },
            "trainingLoad": {"load": 87},
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        },
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.cycling_vo2max_ml_kg_min == pytest.approx(60.1)
    assert snapshot.running_vo2max_ml_kg_min == pytest.approx(57.4)


def test_extracts_training_status_label_and_load_focus():
    """Test extraction of new Garmin training status + load focus fields (v4.2.0)."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {
                "functionThreshold": 300,
                "maxHeartRate": 196,
                "readiness": {"score": 82},
            },
        },
        "training_status": {
            "trainingLoad": {"load": 87},
            "mostRecentTrainingLoadBalance": {
                "loadFocusWeek": {
                    "lowAerobic": 35.2,
                    "highAerobic": 48.1,
                    "anaerobic": 16.7,
                },
            },
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "2026-03-03": {
                        "trainingStatusLabel": "PRODUCTIVE",
                    },
                },
            },
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        },
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.training_status_label == "PRODUCTIVE"
    assert snapshot.load_focus_low_aerobic_pct == pytest.approx(35.2)
    assert snapshot.load_focus_high_aerobic_pct == pytest.approx(48.1)
    assert snapshot.load_focus_anaerobic_pct == pytest.approx(16.7)


def test_training_status_fields_are_none_safe():
    """Test that missing training status + load focus fields default to None."""
    adapter = GarminTrainingStateAdapter()
    raw = _raw_payload()
    # Do not add mostRecentTrainingLoadBalance or latestTrainingStatusData

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.training_status_label is None
    assert snapshot.load_focus_low_aerobic_pct is None
    assert snapshot.load_focus_high_aerobic_pct is None
    assert snapshot.load_focus_anaerobic_pct is None


def test_partial_load_focus_data():
    """Test that partial load focus data is handled gracefully."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {"functionThreshold": 300, "maxHeartRate": 196, "readiness": {"score": 82}},
        },
        "training_status": {
            "trainingLoad": {"load": 87},
            "mostRecentTrainingLoadBalance": {
                "loadFocusWeek": {
                    "lowAerobic": 40.0,
                    # Missing highAerobic and anaerobic
                },
            },
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        },
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.load_focus_low_aerobic_pct == pytest.approx(40.0)
    assert snapshot.load_focus_high_aerobic_pct is None
    assert snapshot.load_focus_anaerobic_pct is None


def test_extracts_load_focus_from_metrics_training_load_balance_map():
    """Map load-focus metrics from real Garmin device-map payload shape."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {"functionThreshold": 300, "maxHeartRate": 196, "readiness": {"score": 82}},
        },
        "training_status": {
            "trainingLoad": {"load": 87},
            "mostRecentTrainingLoadBalance": {
                "metricsTrainingLoadBalanceDTOMap": {
                    "3491049563": {
                        "monthlyLoadAerobicLow": 292.90237,
                        "monthlyLoadAerobicHigh": 833.71606,
                        "monthlyLoadAnaerobic": 80.648224,
                    }
                }
            },
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        },
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    total = 292.90237 + 833.71606 + 80.648224
    assert snapshot.load_focus_low_aerobic_pct == pytest.approx((292.90237 / total) * 100)
    assert snapshot.load_focus_high_aerobic_pct == pytest.approx((833.71606 / total) * 100)
    assert snapshot.load_focus_anaerobic_pct == pytest.approx((80.648224 / total) * 100)


def test_extracts_training_status_from_feedback_phrase():
    """Map training status label from Garmin feedback-phrase key."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {"functionThreshold": 300, "maxHeartRate": 196, "readiness": {"score": 82}},
        },
        "training_status": {
            "trainingLoad": {"load": 87},
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "3491049563": {
                        "trainingStatusFeedbackPhrase": "MAINTAINING_2",
                    }
                }
            },
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        },
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.training_status_label == "MAINTAINING_2"


def test_modern_path_has_priority_over_legacy_load_focus_paths():
    """Prefer modern metrics map values when both modern and legacy keys exist."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {"functionThreshold": 300, "maxHeartRate": 196, "readiness": {"score": 82}},
        },
        "training_status": {
            "trainingLoad": {"load": 87},
            "mostRecentTrainingLoadBalance": {
                "metricsTrainingLoadBalanceDTOMap": {
                    "3491049563": {
                        "monthlyLoadAerobicLow": 101.0,
                        "monthlyLoadAerobicHigh": 202.0,
                        "monthlyLoadAnaerobic": 303.0,
                    }
                },
                "loadFocusWeek": {
                    "lowAerobic": 1.0,
                    "highAerobic": 2.0,
                    "anaerobic": 3.0,
                },
            },
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        },
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    total = 101.0 + 202.0 + 303.0
    assert snapshot.load_focus_low_aerobic_pct == pytest.approx((101.0 / total) * 100)
    assert snapshot.load_focus_high_aerobic_pct == pytest.approx((202.0 / total) * 100)
    assert snapshot.load_focus_anaerobic_pct == pytest.approx((303.0 / total) * 100)


def test_extracts_readiness_and_recovery_from_training_readiness_payloads():
    """morning_training_readiness wins over list training_readiness; recovery hours normalised."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {
            "calendarDate": "2026-03-03",
            "stats": {
                "functionThreshold": 300,
                "maxHeartRate": 196,
                "readiness": {"score": 12},
            },
        },
        "training_status": {
            "trainingLoad": {"load": 87},
            "recoveryTimeMinutes": 30,
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
        },
        # Real Garmin API shape: list of per-context entries
        "training_readiness": [
            {"inputContext": "TRAINING_LOAD", "score": 65, "recoveryTimeMinutes": 480},
            {"inputContext": "AFTER_WAKEUP_RESET", "score": 73, "recoveryTimeMinutes": 720},
        ],
        "morning_training_readiness": {
            "score": 79,
            "recoveryTimeHours": 18,
        },
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.readiness_score == 79
    assert snapshot.recovery_time_minutes == 1080


def test_extracts_readiness_from_training_readiness_list_prefers_after_wakeup():
    """When morning_training_readiness is absent, prefer AFTER_WAKEUP_RESET from list."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {"calendarDate": "2026-03-03", "stats": {}},
        "training_status": {"trainingLoad": {"load": 87}},
        "training_readiness": [
            {"inputContext": "TRAINING_LOAD", "score": 55, "recoveryTimeMinutes": 300},
            {"inputContext": "AFTER_WAKEUP_RESET", "score": 82, "recoveryTimeMinutes": 600},
        ],
        "morning_training_readiness": None,
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.readiness_score == 82
    assert snapshot.recovery_time_minutes == 600


def test_extracts_readiness_from_training_readiness_list_falls_back_to_first():
    """When no AFTER_WAKEUP_RESET entry exists, fall back to the first list entry."""
    adapter = GarminTrainingStateAdapter()
    raw = {
        "summary": {"calendarDate": "2026-03-03", "stats": {}},
        "training_status": {"trainingLoad": {"load": 87}},
        "training_readiness": [
            {"inputContext": "TRAINING_LOAD", "score": 71, "recoveryTimeMinutes": 540},
        ],
        "morning_training_readiness": None,
    }

    snapshot = adapter.adapt(raw, athlete_id="rob")

    assert snapshot.readiness_score == 71
    assert snapshot.recovery_time_minutes == 540
