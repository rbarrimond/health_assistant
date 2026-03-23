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


def test_contract_reports_missing_required_core_fields() -> None:
    contract = GarminActivityContract(
        {
            "activityId": 456,
            "startTimeGMT": "2026-02-20T10:00:00+00:00",
        }
    )

    missing = contract.missing_required_core_fields()
    assert "activity_type_key" in missing
    assert "duration_sec" in missing
    assert "distance_meters" in missing


def test_contract_reports_unknown_activity_type() -> None:
    contract = GarminActivityContract(
        {
            "activityId": 789,
            "activityType": {"typeKey": "paddle_boarding"},
            "startTimeGMT": "2026-02-20T10:00:00+00:00",
            "duration": 2400,
            "distance": 6000,
        }
    )

    assert contract.has_unknown_activity_type() is True


def test_contract_reports_unknown_interesting_fields() -> None:
    contract = GarminActivityContract(
        {
            "activityId": 1001,
            "activityType": {"typeKey": "walking"},
            "startTimeGMT": "2026-02-20T10:00:00+00:00",
            "duration": 1800,
            "distance": 2500,
            "newPowerMetric": 321,
            "mysteryCadenceSignal": 88,
            "irrelevantField": "value",
        }
    )

    unknown = contract.unknown_interesting_fields(limit=5)
    assert "newPowerMetric" in unknown
    assert "mysteryCadenceSignal" in unknown
    assert "irrelevantField" not in unknown


def test_contract_extracts_training_cycling_and_environmental_enrichment_fields() -> None:
    contract = GarminActivityContract(
        {
            "activityId": 2002,
            "activityType": {"typeKey": "cycling"},
            "startTimeGMT": "2026-03-22T10:00:00+00:00",
            "duration": 3600,
            "distance": 42000,
            "activityTrainingLoad": 252.5,
            "aerobicTrainingEffect": 5.0,
            "anaerobicTrainingEffect": 2.1,
            "trainingEffectLabel": "VO2MAX",
            "aerobicTrainingEffectMessage": "OVERREACHING_17",
            "anaerobicTrainingEffectMessage": "MAINTAINING_ANAEROBIC_BASE_1",
            "vO2MaxValue": 42.0,
            "averageBikingCadenceInRevPerMinute": 86.0,
            "maxBikingCadenceInRevPerMinute": 99.0,
            "avgLeftBalance": 46.07,
            "averageRunningCadenceInStepsPerMinute": 66.0,
            "maxRunningCadenceInStepsPerMinute": 82.0,
            "avgRespirationRate": 32.22,
            "maxRespirationRate": 39.58,
            "minRespirationRate": 21.26,
            "maxTemperature": 23.0,
            "minTemperature": 21.0,
        }
    )

    metadata = contract.to_source_metadata_fields()

    assert metadata["source_activity_training_load"] == 252.5
    assert metadata["source_aerobic_training_effect"] == 5.0
    assert metadata["source_anaerobic_training_effect"] == 2.1
    assert metadata["source_training_effect_label"] == "VO2MAX"
    assert metadata["source_aerobic_training_effect_message"] == "OVERREACHING_17"
    assert metadata["source_anaerobic_training_effect_message"] == "MAINTAINING_ANAEROBIC_BASE_1"
    assert metadata["source_vo2max_value"] == 42.0
    assert metadata["source_avg_biking_cadence_rpm"] == 86.0
    assert metadata["source_max_biking_cadence_rpm"] == 99.0
    assert metadata["source_avg_left_balance_pct"] == 46.07
    assert metadata["source_avg_running_cadence_spm"] == 66.0
    assert metadata["source_max_running_cadence_spm"] == 82.0
    assert metadata["source_avg_respiration_rate_brpm"] == 32.22
    assert metadata["source_max_respiration_rate_brpm"] == 39.58
    assert metadata["source_min_respiration_rate_brpm"] == 21.26
    assert metadata["source_max_temperature_c"] == 23.0
    assert metadata["source_min_temperature_c"] == 21.0


def test_contract_does_not_report_new_enrichment_keys_as_unknown_drift() -> None:
    contract = GarminActivityContract(
        {
            "activityId": 2003,
            "activityType": {"typeKey": "cycling"},
            "startTimeGMT": "2026-03-22T10:00:00+00:00",
            "duration": 1200,
            "distance": 10000,
            "activityTrainingLoad": 100.0,
            "avgRespirationRate": 20.1,
            "maxTemperature": 26.0,
        }
    )

    unknown = contract.unknown_interesting_fields(limit=10)
    assert "activityTrainingLoad" not in unknown
    assert "avgRespirationRate" not in unknown
    assert "maxTemperature" not in unknown
