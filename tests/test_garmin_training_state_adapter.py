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
    assert snapshot.resting_hr_bpm == 51
    assert snapshot.readiness_score == 82

    assert snapshot.training_load == 87
    assert snapshot.training_effect_aerobic == pytest.approx(3.2)
    assert snapshot.training_effect_anaerobic == pytest.approx(1.4)
    assert snapshot.training_stress_score == pytest.approx(92.5)
    assert snapshot.training_stress_balance == pytest.approx(-14.2)
    assert snapshot.atp_probability == pytest.approx(71.0)
    assert snapshot.recovery_time_minutes == 820
    assert snapshot.lactate_threshold_hr_bpm == 171
    assert snapshot.hr_lthr_bpm == 171


def test_lthr_falls_back_to_estimate_when_training_status_missing_lthr():
    adapter = GarminTrainingStateAdapter()

    snapshot = adapter.adapt(_raw_payload(include_lthr=False), athlete_id="rob")

    assert snapshot.lactate_threshold_hr_bpm is None
    assert snapshot.hr_lthr_bpm == int(196 * 0.85)


def test_rejects_training_effect_out_of_range():
    adapter = GarminTrainingStateAdapter()
    raw = _raw_payload()
    raw["training_status"]["trainingEffect"]["aerobic"] = 6.2

    with pytest.raises(AdapterError):
        adapter.adapt(raw, athlete_id="rob")
