"""Tests for StorageInfrastructure managed table behavior."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from TrainingAnalyticsPlatform.storage.storage_infrastructure import (
    MANAGED_TABLE_NAMES,
    StorageInfrastructure,
)


def test_ensure_tables_exist_covers_all_managed_tables() -> None:
    """Bootstrap should create every managed application-owned table."""
    infrastructure = StorageInfrastructure.__new__(StorageInfrastructure)
    infrastructure.service_client = MagicMock()

    infrastructure._ensure_tables_exist()

    created_tables = [
        call.args[0]
        for call in infrastructure.service_client.create_table_if_not_exists.call_args_list
    ]
    assert created_tables == list(MANAGED_TABLE_NAMES)


def test_get_table_client_recreates_missing_managed_table_before_access() -> None:
    """Managed tables should be recreated lazily before table client access."""
    infrastructure = StorageInfrastructure.__new__(StorageInfrastructure)
    infrastructure.service_client = MagicMock()
    expected_client = MagicMock()
    infrastructure.service_client.get_table_client.return_value = expected_client

    table_client = infrastructure.get_table_client("WeeklyRollups")

    infrastructure.service_client.create_table_if_not_exists.assert_called_once_with("WeeklyRollups")
    infrastructure.service_client.get_table_client.assert_called_once_with("WeeklyRollups")
    assert table_client is expected_client


def test_garmin_activity_index_table_is_managed() -> None:
    """Garmin activity index table should be part of managed table bootstrap set."""
    assert "GarminActivityIndex" in MANAGED_TABLE_NAMES


def test_get_table_client_skips_recreate_for_unmanaged_table() -> None:
    """Unknown table names should not be implicitly created by the infrastructure."""
    infrastructure = StorageInfrastructure.__new__(StorageInfrastructure)
    infrastructure.service_client = MagicMock()
    expected_client = MagicMock()
    infrastructure.service_client.get_table_client.return_value = expected_client

    table_client = infrastructure.get_table_client("AdHocTable")

    infrastructure.service_client.create_table_if_not_exists.assert_not_called()
    infrastructure.service_client.get_table_client.assert_called_once_with("AdHocTable")
    assert table_client is expected_client


def test_upload_parquet_blob_persists_1hz_canonical_records() -> None:
    """Canonical parquet writes should accept already-valid 1 Hz record streams."""
    infrastructure = StorageInfrastructure.__new__(StorageInfrastructure)
    infrastructure._blob_service_client = MagicMock()
    blob_client = MagicMock()
    infrastructure._blob_service_client.get_blob_client.return_value = blob_client

    record_set = SimpleNamespace(
        to_dataframe=pd.DataFrame(
            {
                "elapsed_sec": [0, 1, 2],
                "power_watts": [100.0, 110.0, 120.0],
            }
        )
    )

    blob_name = infrastructure.upload_parquet_blob("workout-1", record_set)

    assert blob_name == "workout-1/canonical.parquet"
    infrastructure._blob_service_client.get_blob_client.assert_called_once_with(
        container="workouts",
        blob="workout-1/canonical.parquet",
    )
    blob_client.upload_blob.assert_called_once()


def test_upload_parquet_blob_persists_non_1hz_canonical_records() -> None:
    """Canonical parquet writes should persist source-derived records even when not 1 Hz."""
    infrastructure = StorageInfrastructure.__new__(StorageInfrastructure)
    infrastructure._blob_service_client = MagicMock()
    blob_client = MagicMock()
    infrastructure._blob_service_client.get_blob_client.return_value = blob_client

    record_set = SimpleNamespace(
        to_dataframe=pd.DataFrame(
            {
                "elapsed_sec": [0, 2, 4],
                "heart_rate_bpm": [120.0, 125.0, 130.0],
            }
        )
    )

    blob_name = infrastructure.upload_parquet_blob("workout-2", record_set)

    assert blob_name == "workout-2/canonical.parquet"
    infrastructure._blob_service_client.get_blob_client.assert_called_once_with(
        container="workouts",
        blob="workout-2/canonical.parquet",
    )
    blob_client.upload_blob.assert_called_once()