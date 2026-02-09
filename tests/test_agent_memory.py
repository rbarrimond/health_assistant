"""Test script for Agent Memory System.

Run this to verify the agent memory endpoints are working correctly.
"""

import json
import os
import requests
import pytest

# Configuration
BASE_URL = os.getenv("FUNCTION_APP_URL", "http://localhost:7071/api")
FUNCTION_KEY = os.getenv("FUNCTION_APP_KEY", "")
ATHLETE_ID = "rob"
REQUEST_TIMEOUT = 30  # seconds

# Skip integration tests unless FUNCTION_APP_URL is explicitly set.
if not os.getenv("FUNCTION_APP_URL"):
    pytest.skip("Set FUNCTION_APP_URL to run integration tests", allow_module_level=True)


def test_get_context():
    """Test GET /api/agent/context"""
    print("\n[TEST] GET /api/agent/context")
    url = f"{BASE_URL}/agent/context"
    params = {"athlete_id": ATHLETE_ID}

    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    return response.status_code == 200


def test_get_preferences():
    """Test GET /api/agent/preferences"""
    print("\n[TEST] GET /api/agent/preferences")
    url = f"{BASE_URL}/agent/preferences"
    params = {"athlete_id": ATHLETE_ID}

    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    return response.status_code == 200


def test_update_preferences():
    """Test POST /api/agent/preferences"""
    print("\n[TEST] POST /api/agent/preferences")
    url = f"{BASE_URL}/agent/preferences"

    if FUNCTION_KEY:
        url += f"?code={FUNCTION_KEY}"

    payload = {
        "athlete_id": ATHLETE_ID,
        "current_goal": "Build aerobic base for spring races",
        "training_phase": "base-building",
        "preferred_sports": ["cycling", "running"],
        "ftp_test_frequency_weeks": 6,
        "last_ftp_test_date": "2026-01-15",
        "notes": "Focus on Z2 quality and consistency"
    }

    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    return response.status_code == 200


def test_add_observation():
    """Test POST /api/agent/observations"""
    print("\n[TEST] POST /api/agent/observations")
    url = f"{BASE_URL}/agent/observations"

    if FUNCTION_KEY:
        url += f"?code={FUNCTION_KEY}"

    payload = {
        "athlete_id": ATHLETE_ID,
        "category": "pattern",
        "summary": "Consistent low decoupling in Z2 sessions",
        "details": (
            "Last 6 Z2 sessions show <5% decoupling, "
            "indicating good aerobic development"
        ),
        "workout_ids": ["test-workout-1", "test-workout-2"],
        "priority": "normal",
        "expires_days": 30
    }

    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    print(f"Status: {response.status_code}")

    if response.status_code == 201:
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        return data.get("observation_id")
    else:
        print(f"Error: {response.text}")
        return None


def test_list_observations():
    """Test GET /api/agent/observations"""
    print("\n[TEST] GET /api/agent/observations")
    url = f"{BASE_URL}/agent/observations"
    params = {
        "athlete_id": ATHLETE_ID,
        "status": "active",
        "limit": 20
    }

    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    return response.status_code == 200


def test_update_observation_status(observation_id: str):
    """Test PATCH /api/agent/observations/{observation_id}"""
    print(f"\n[TEST] PATCH /api/agent/observations/{observation_id}")
    url = f"{BASE_URL}/agent/observations/{observation_id}"

    if FUNCTION_KEY:
        url += f"?code={FUNCTION_KEY}"

    payload = {
        "athlete_id": ATHLETE_ID,
        "status": "resolved"
    }

    response = requests.patch(url, json=payload, timeout=REQUEST_TIMEOUT)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

    return response.status_code == 200


def run_all_tests():
    """Run all agent memory tests"""
    print("=" * 60)
    print("AGENT MEMORY SYSTEM - TEST SUITE")
    print("=" * 60)
    print(f"Base URL: {BASE_URL}")
    print(f"Athlete ID: {ATHLETE_ID}")
    print(
        f"Function Key: {'Set' if FUNCTION_KEY else 'Not set (some tests will fail)'}")

    results = {
        "get_context": False,
        "get_preferences": False,
        "update_preferences": False,
        "add_observation": False,
        "list_observations": False,
        "update_observation": False
    }

    # Read-only tests (no auth required)
    results["get_context"] = test_get_context()
    results["get_preferences"] = test_get_preferences()

    # Write tests (require function key)
    if FUNCTION_KEY:
        results["update_preferences"] = test_update_preferences()
        observation_id = test_add_observation()
        results["add_observation"] = observation_id is not None
        results["list_observations"] = test_list_observations()

        if observation_id:
            results["update_observation"] = test_update_observation_status(
                observation_id)
    else:
        print("\n[SKIP] Write operations (set FUNCTION_APP_KEY environment variable)")

    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL/SKIP"
        print(f"{status:12} {test_name}")

    total = len([r for r in results.values() if r])
    print(f"\nPassed: {total}/{len(results)}")

    return all(results.values())


if __name__ == "__main__":
    try:
        success = run_all_tests()
        exit(0 if success else 1)
    except requests.exceptions.ConnectionError:
        print("\n[ERROR] Could not connect to function app. Is it running?")
        print(f"Expected URL: {BASE_URL}")
        exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"\n[ERROR] Test failed: {e}")
        exit(1)
