"""Tests for Garmin activity payload normalization contract."""

from TrainingAnalyticsPlatform.integrations.garmin_activity_contract import (
    GarminActivityContract,
)


def test_contract_normalizes_core_common_and_type_specific_fields_for_walking() -> None:
    contract = GarminActivityContract(
        {
            "activity_id": "w-1",
            "activity_name": "Morning Walk",
            "activityTypeDTO": {"typeKey": "walking"},
            "startTimeGmt": "2026-02-20T10:00:00+00:00",
            "startTimeGmtLocal": "2026-02-20T06:00:00",
            "durationInSeconds": 1800,
            "distanceMeters": 2500,
            "averageHR": 118,
            "maximumHR": 139,
            "calories": 220,
            "steps": 3124,
            "averageRunCadence": 79.2,
        }
    )

    assert contract.activity_id == "w-1"
    assert contract.activity_type_key == "walking"
    assert contract.start_time_utc == "2026-02-20T10:00:00+00:00"
    assert contract.duration_sec == 1800.0

    metadata = contract.to_source_metadata_fields()
    assert metadata["source_activity_name"] == "Morning Walk"
    assert metadata["source_activity_type"] == "walking"
    assert metadata["source_start_time_utc"] == "2026-02-20T10:00:00+00:00"
    assert metadata["source_duration_sec"] == 1800
    assert metadata["source_distance_meters"] == 2500
    assert metadata["source_average_hr_bpm"] == 118
    assert metadata["source_max_hr_bpm"] == 139
    assert metadata["source_calories"] == 220
    assert metadata["source_steps"] == 3124
    assert metadata["source_average_run_cadence"] == 79.2


def test_contract_adds_cycling_power_fields_when_present() -> None:
    contract = GarminActivityContract(
        {
            "activityId": 123,
            "activityName": "Ride",
            "activityType": {"typeKey": "virtual_ride"},
            "startTimeGMT": "2026-02-20T10:00:00+00:00",
            "duration": 3600,
            "distance": 32000,
            "averagePower": 208,
            "normPower": 224,
        }
    )

    metadata = contract.to_source_metadata_fields()
    assert contract.activity_id == "123"
    assert metadata["source_activity_type"] == "virtual_ride"
    assert metadata["source_average_power_watts"] == 208
    assert metadata["source_normalized_power_watts"] == 224
