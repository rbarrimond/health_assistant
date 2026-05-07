"""Unit tests for platform dependency helper behavior."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from TrainingAnalyticsPlatform.platform.dependencies import FunctionAppDependencies


class TestFunctionAppDependenciesFlags:
    def test_deferred_retry_enabled_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEFERRED_RETRY_ENABLED", "yes")
        assert FunctionAppDependencies._is_deferred_retry_enabled() is True

        monkeypatch.setenv("DEFERRED_RETRY_ENABLED", "false")
        assert FunctionAppDependencies._is_deferred_retry_enabled() is False

    def test_onedrive_async_queue_enabled_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONEDRIVE_ASYNC_QUEUE_ENABLED", "on")
        assert FunctionAppDependencies._is_onedrive_async_queue_enabled() is True

        monkeypatch.setenv("ONEDRIVE_ASYNC_QUEUE_ENABLED", "0")
        assert FunctionAppDependencies._is_onedrive_async_queue_enabled() is False

    def test_garmin_async_queue_enabled_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GARMIN_ASYNC_QUEUE_ENABLED", "true")
        assert FunctionAppDependencies._is_garmin_async_queue_enabled() is True

        monkeypatch.delenv("GARMIN_ASYNC_QUEUE_ENABLED", raising=False)
        assert FunctionAppDependencies._is_garmin_async_queue_enabled() is False

    def test_resolve_async_ingestion_queue_name_default_and_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEDRIVE_ASYNC_QUEUE_NAME", raising=False)
        assert FunctionAppDependencies._resolve_async_ingestion_queue_name() == "async-ingestion"

        monkeypatch.setenv("ONEDRIVE_ASYNC_QUEUE_NAME", "my-queue")
        assert FunctionAppDependencies._resolve_async_ingestion_queue_name() == "my-queue"


class TestFunctionAppDependenciesWarmup:
    def test_warmup_bootstraps_non_none_queues(self) -> None:
        deps = FunctionAppDependencies()
        queue_a = MagicMock()
        queue_b = MagicMock()

        with patch.object(
            FunctionAppDependencies,
            "storage",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch.object(
            FunctionAppDependencies,
            "workout_service",
            new_callable=PropertyMock,
            return_value=MagicMock(),
        ), patch.object(
            FunctionAppDependencies,
            "onedrive_async_queue",
            new_callable=PropertyMock,
            return_value=queue_a,
        ), patch.object(
            FunctionAppDependencies,
            "garmin_async_queue",
            new_callable=PropertyMock,
            return_value=None,
        ), patch.object(
            FunctionAppDependencies,
            "deferred_retry_queue",
            new_callable=PropertyMock,
            return_value=queue_b,
        ):
            deps.warmup()

        queue_a.bootstrap.assert_called_once()
        queue_b.bootstrap.assert_called_once()

    def test_warmup_tolerates_storage_initialization_error(self) -> None:
        deps = FunctionAppDependencies()

        with patch.object(
            FunctionAppDependencies,
            "storage",
            new_callable=PropertyMock,
            side_effect=ValueError("bad config"),
        ), patch.object(
            FunctionAppDependencies,
            "onedrive_async_queue",
            new_callable=PropertyMock,
            return_value=None,
        ), patch.object(
            FunctionAppDependencies,
            "garmin_async_queue",
            new_callable=PropertyMock,
            return_value=None,
        ), patch.object(
            FunctionAppDependencies,
            "deferred_retry_queue",
            new_callable=PropertyMock,
            return_value=None,
        ):
            deps.warmup()
