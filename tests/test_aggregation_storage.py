"""Tests for weekly aggregation storage writes."""

from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.aggregation_storage import AggregationStorage


@pytest.fixture
def aggregation_storage():
    """Create AggregationStorage with mocked infrastructure."""
    infrastructure = MagicMock()
    return AggregationStorage(infrastructure), infrastructure


def test_update_weekly_rollup_uses_pipe_partition_key(aggregation_storage):
    """Weekly rollups should use pipe-delimited partition keys for Azure Table compatibility."""
    storage, infrastructure = aggregation_storage
    table_client = MagicMock()
    infrastructure.get_table_client.return_value = table_client

    storage.update_weekly_rollup(
        athlete_id="rob",
        year="2026",
        week="10",
        rollup_data={
            "week_start_utc": "2026-03-02T05:00:00+00:00",
            "week_end_utc": "2026-03-09T03:59:59+00:00",
            "workouts_count": 2,
            "total_duration_min": 150.0,
            "total_hr_z2_min": 100.0,
            "total_pwr_z2_min": 90.0,
            "total_low_aerobic_min": 70.0,
            "total_intensity_min": 17.0,
        },
    )

    table_client.upsert_entity.assert_called_once()
    entity = table_client.upsert_entity.call_args.args[0]
    assert entity["PartitionKey"] == "rob|2026"
    assert entity["RowKey"] == "2026-10"


def test_update_weekly_rollup_filters_unsupported_and_non_finite_values(aggregation_storage):
    """Unsupported nested values and non-finite numbers are dropped before upsert."""
    storage, infrastructure = aggregation_storage
    table_client = MagicMock()
    infrastructure.get_table_client.return_value = table_client

    storage.update_weekly_rollup(
        athlete_id="rob",
        year="2026",
        week="10",
        rollup_data={
            "week_start_utc": "2026-03-02T05:00:00+00:00",
            "week_end_utc": "2026-03-09T03:59:59+00:00",
            "workouts_count": 2,
            "avg_decoupling_pct": float("nan"),
            "invalid_nested": {"a": 1},
            "invalid_list": [1, 2, 3],
        },
    )

    entity = table_client.upsert_entity.call_args.args[0]
    assert "avg_decoupling_pct" not in entity
    assert "invalid_nested" not in entity
    assert "invalid_list" not in entity


def test_update_weekly_rollup_handles_http_response_error(aggregation_storage):
    """Storage errors should be translated into StorageError with preserved cause."""
    storage, infrastructure = aggregation_storage
    table_client = MagicMock()
    table_client.upsert_entity.side_effect = HttpResponseError("boom")
    infrastructure.get_table_client.return_value = table_client

    with pytest.raises(StorageError, match="Failed to update weekly rollup") as exc_info:
        storage.update_weekly_rollup(
            athlete_id="rob",
            year="2026",
            week="10",
            rollup_data={"workouts_count": 2},
        )

    assert isinstance(exc_info.value.__cause__, HttpResponseError)
