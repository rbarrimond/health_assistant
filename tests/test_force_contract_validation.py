from TrainingAnalyticsPlatform.platform.force_contract_validation import (
    find_force_contract_violations,
)


def test_find_force_contract_violations_returns_empty_for_none_items():
    assert find_force_contract_violations(None) == []


def test_find_force_contract_violations_returns_empty_when_no_blocked_statuses():
    items = [
        {"activity_id": "1", "status": "success"},
        {"activity_id": "2", "status": "skipped_seen_id"},
        {"activity_id": "3", "status": "skipped"},
    ]

    assert find_force_contract_violations(items) == []


def test_find_force_contract_violations_detects_skipped_duplicate_status():
    items = [
        {
            "activity_id": "1",
            "activity_name": "Morning Ride",
            "status": "skipped_duplicate",
            "workout_id": "workout-1",
        },
        {
            "activity_id": "2",
            "activity_name": "Evening Run",
            "status": "success",
            "workout_id": "workout-2",
        },
    ]

    violations = find_force_contract_violations(items)

    assert violations == [
        {
            "activity_id": "1",
            "activity_name": "Morning Ride",
            "status": "skipped_duplicate",
            "workout_id": "workout-1",
        }
    ]
