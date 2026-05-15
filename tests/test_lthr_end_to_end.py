"""End-to-end test for LTHR data flow through the ingestion pipeline."""

import json
from unittest.mock import MagicMock, patch

import pytest

from TrainingAnalyticsPlatform.handlers.wellness_sync import GarminPhysiometricsSyncHandler
from TrainingAnalyticsPlatform.ingestion.wellness_adapters import GarminTrainingStateAdapter


@pytest.fixture
def sample_lthr_payload():
    """Sample Garmin lactate threshold payload."""
    return {
        "speed_and_heart_rate": {
            "calendarDate": "2026-03-14",
            "heartRate": 168,
            "heartRateCycling": 170,
        },
        "power": {},
    }


@pytest.fixture
def sample_recovery_metrics():
    """Sample Garmin recovery metrics payload (alternative LTHR source)."""
    return {
        "lactateThresholdHeartRate": 165,
        "recovery": {
            "lactateThresholdHeartRate": 166,
        },
    }


@pytest.fixture
def sample_wellness_payload():
    """Sample Garmin wellness payload (tertiary LTHR source)."""
    return {
        "heartRateMetrics": {
            "lactateThresholdHeartRate": 164,
        },
        "lthr": 167,
    }


@pytest.fixture
def complete_garmin_payload(sample_lthr_payload, sample_recovery_metrics, sample_wellness_payload):
    """Complete Garmin physiometrics payload with all endpoints."""
    return {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {
                "maxHeartRate": 196,
                "restingHeartRate": 51,
                "functionThreshold": 300,
                "vo2MaxCycling": {"value": 59.2},
                "vo2MaxRunning": {"value": 56.8},
                "readiness": {"score": 82},
            },
        },
        "training_status": {
            "trainingLoad": {"load": 87},
            "trainingEffect": {"aerobic": 3.2, "anaerobic": 1.4},
            "trainingStressScore": 92.5,
            "trainingStressBalance": -14.2,
            "atpProbability": 71.0,
            "recoveryTimeMinutes": 820,
            "lactateThresholdHeartRate": 171,
        },
        "training_readiness": None,
        "morning_training_readiness": None,
        "cycling_ftp": {
            "calendarDate": "2026-03-14T06:00:00+00:00",
            "functionalThresholdPower": 312,
        },
        "lactate_threshold": sample_lthr_payload,
        "recovery_metrics": sample_recovery_metrics,
        "wellness": sample_wellness_payload,
        "hrv": {},
    }


def test_lthr_extraction_from_primary_endpoint(sample_lthr_payload):
    """Test LTHR extraction from primary lactate_threshold endpoint."""
    adapter = GarminTrainingStateAdapter()
    payload = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {
                "maxHeartRate": 196,
            },
        },
        "training_status": {},
        "lactate_threshold": sample_lthr_payload,
        "cycling_ftp": {},
        "recovery_metrics": {},
        "wellness": {},
        "hrv": {},
    }
    
    snapshot = adapter.adapt(payload, athlete_id="rob")
    
    assert snapshot.hr_lthr_bpm == 168
    assert snapshot.athlete_id == "rob"


def test_lthr_extraction_fallback_to_recovery_metrics(sample_recovery_metrics):
    """Test LTHR extraction falls back to recovery_metrics endpoint."""
    adapter = GarminTrainingStateAdapter()
    payload = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {
                "maxHeartRate": 196,
            },
        },
        "training_status": {},
        "lactate_threshold": {},  # Empty primary endpoint
        "cycling_ftp": {},
        "recovery_metrics": sample_recovery_metrics,
        "wellness": {},
        "hrv": {},
    }
    
    snapshot = adapter.adapt(payload, athlete_id="rob")
    
    assert snapshot.hr_lthr_bpm == 165


def test_lthr_extraction_fallback_to_wellness(sample_wellness_payload):
    """Test LTHR extraction falls back to wellness endpoint."""
    adapter = GarminTrainingStateAdapter()
    payload = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {
                "maxHeartRate": 196,
            },
        },
        "training_status": {},
        "lactate_threshold": {},
        "cycling_ftp": {},
        "recovery_metrics": {},
        "wellness": sample_wellness_payload,
        "hrv": {},
    }
    
    snapshot = adapter.adapt(payload, athlete_id="rob")
    
    assert snapshot.hr_lthr_bpm == 167


def test_lthr_extraction_fallback_to_training_status():
    """Test LTHR extraction falls back to training_status field."""
    adapter = GarminTrainingStateAdapter()
    payload = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {
                "maxHeartRate": 196,
            },
        },
        "training_status": {
            "lactateThresholdHeartRate": 171,
        },
        "lactate_threshold": {},
        "cycling_ftp": {},
        "recovery_metrics": {},
        "wellness": {},
        "hrv": {},
    }
    
    snapshot = adapter.adapt(payload, athlete_id="rob")
    
    assert snapshot.hr_lthr_bpm == 171


def test_lthr_fallback_to_estimation_when_all_endpoints_empty():
    """Test LTHR falls back to 0.85 * max_hr when all sources fail."""
    adapter = GarminTrainingStateAdapter()
    payload = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {
                "maxHeartRate": 200,  # 0.85 * 200 = 170 pylint: disable=comment-outside-code-block
            },
        },
        "training_status": {},
        "lactate_threshold": {},
        "cycling_ftp": {},
        "recovery_metrics": {},
        "wellness": {},
        "hrv": {},
    }
    
    snapshot = adapter.adapt(payload, athlete_id="rob")
    
    assert snapshot.hr_lthr_bpm == 170


def test_lthr_prefers_primary_endpoint_over_fallbacks(complete_garmin_payload):
    """Test LTHR prefers primary endpoint when multiple sources have values."""
    adapter = GarminTrainingStateAdapter()
    
    snapshot = adapter.adapt(complete_garmin_payload, athlete_id="rob")
    
    # Should use primary endpoint value (168) not fallback values
    assert snapshot.hr_lthr_bpm == 168


def test_lthr_validation_range():
    """Test LTHR validation for out-of-range values."""
    adapter = GarminTrainingStateAdapter()
    
    # Test out-of-range high
    payload_high = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {"maxHeartRate": 196},
        },
        "training_status": {},
        "lactate_threshold": {
            "speed_and_heart_rate": {
                "heartRate": 250,  # Out of range
            },
        },
        "cycling_ftp": {},
        "recovery_metrics": {},
        "wellness": {},
        "hrv": {},
    }
    
    with pytest.raises(Exception):  # Should raise AdapterError
        adapter.adapt(payload_high, athlete_id="rob")
    
    # Test out-of-range low
    payload_low = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {"maxHeartRate": 196},
        },
        "training_status": {},
        "lactate_threshold": {
            "speed_and_heart_rate": {
                "heartRate": 50,  # Out of range
            },
        },
        "cycling_ftp": {},
        "recovery_metrics": {},
        "wellness": {},
        "hrv": {},
    }
    
    with pytest.raises(Exception):
        adapter.adapt(payload_low, athlete_id="rob")


def test_snapshot_maps_lthr_to_storage_dict():
    """Test that LTHR is properly mapped to storage dict for persistence."""
    adapter = GarminTrainingStateAdapter()
    payload = {
        "summary": {
            "calendarDate": "2026-03-14",
            "stats": {
                "maxHeartRate": 196,
                "restingHeartRate": 51,
            },
        },
        "training_status": {},
        "lactate_threshold": {
            "speed_and_heart_rate": {
                "heartRate": 168,
            },
        },
        "cycling_ftp": {},
        "recovery_metrics": {},
        "wellness": {},
        "hrv": {},
    }
    snapshot = adapter.adapt(payload, athlete_id="rob")
    
    storage_dict = snapshot.to_storage_dict()
    
    assert storage_dict["hr_lthr_bpm"] == 168
    assert storage_dict["hr_max_bpm"] == 196
    assert storage_dict["resting_hr_bpm"] is None
