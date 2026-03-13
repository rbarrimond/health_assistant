"""Tests for StorageInfrastructure managed table behavior."""

from unittest.mock import MagicMock

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