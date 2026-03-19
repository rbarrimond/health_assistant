"""Tests for deferred retry dependency wiring behavior."""

from unittest.mock import MagicMock, PropertyMock, patch

from TrainingAnalyticsPlatform.platform.dependencies import FunctionAppDependencies


def _patch_dep(attr, value):
    return patch.object(FunctionAppDependencies, attr, new=PropertyMock(return_value=value))


class TestDeferredRetryCoordinatorDependency:
    def test_deferred_retry_coordinator_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("DEFERRED_RETRY_ENABLED", "false")
        dependencies = FunctionAppDependencies()

        with patch.object(
            FunctionAppDependencies,
            "deferred_retry_queue",
            new=PropertyMock(side_effect=AssertionError("queue should not be accessed")),
        ):
            with patch.object(
                FunctionAppDependencies,
                "storage",
                new=PropertyMock(side_effect=AssertionError("storage should not be accessed")),
            ):
                coordinator = dependencies.deferred_retry_coordinator

        assert coordinator is None

    def test_deferred_retry_coordinator_initializes_when_enabled(self, monkeypatch):
        monkeypatch.setenv("DEFERRED_RETRY_ENABLED", "true")
        dependencies = FunctionAppDependencies()
        mock_queue = MagicMock()
        mock_storage = MagicMock()
        mock_retry_storage = MagicMock()
        mock_storage.retry_deferrals = mock_retry_storage
        mock_coordinator = MagicMock()

        with _patch_dep("deferred_retry_queue", mock_queue):
            with _patch_dep("storage", mock_storage):
                with patch(
                    "TrainingAnalyticsPlatform.platform.dependencies.DeferredRetryCoordinator.from_env",
                    return_value=mock_coordinator,
                ) as from_env_mock:
                    coordinator = dependencies.deferred_retry_coordinator

        assert coordinator is mock_coordinator
        from_env_mock.assert_called_once_with(
            queue=mock_queue,
            storage=mock_retry_storage,
        )


class TestPreSyncServicesWithDeferredRetryDisabled:
    def test_planning_presync_receives_no_coordinator_when_disabled(self, monkeypatch):
        monkeypatch.setenv("DEFERRED_RETRY_ENABLED", "false")
        dependencies = FunctionAppDependencies()
        sentinel_handler = MagicMock()

        with _patch_dep("onedrive_service", MagicMock()):
            with _patch_dep("garmin_service", MagicMock()):
                with _patch_dep("garmin_physiometrics_service", MagicMock()):
                    with _patch_dep("intervals_service", MagicMock()):
                        with patch.object(
                            FunctionAppDependencies,
                            "deferred_retry_queue",
                            new=PropertyMock(side_effect=AssertionError("queue should not be accessed")),
                        ):
                            with patch(
                                "TrainingAnalyticsPlatform.platform.dependencies.PlanningContextPreSyncHandler.from_env",
                                return_value=sentinel_handler,
                            ) as from_env_mock:
                                handler = dependencies.planning_context_pre_sync_service

        assert handler is sentinel_handler
        assert from_env_mock.call_args.kwargs["deferred_retry_coordinator"] is None


class TestOneDriveAsyncQueueDependency:
    def test_onedrive_async_queue_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ONEDRIVE_ASYNC_QUEUE_ENABLED", "false")
        dependencies = FunctionAppDependencies()

        queue = dependencies.onedrive_async_queue

        assert queue is None

    def test_onedrive_service_receives_queue_when_enabled(self, monkeypatch):
        monkeypatch.setenv("ONEDRIVE_ASYNC_QUEUE_ENABLED", "true")
        dependencies = FunctionAppDependencies()
        mock_storage = MagicMock()
        mock_queue = MagicMock()
        sentinel_handler = MagicMock()

        with _patch_dep("storage", mock_storage):
            with _patch_dep("onedrive_async_queue", mock_queue):
                with patch(
                    "TrainingAnalyticsPlatform.platform.dependencies.OneDriveSyncConfig.from_env",
                    return_value=MagicMock(),
                ):
                    with patch(
                        "TrainingAnalyticsPlatform.platform.dependencies.OneDriveSyncHandler",
                        return_value=sentinel_handler,
                    ) as handler_cls:
                        handler = dependencies.onedrive_service

        assert handler is sentinel_handler
        assert handler_cls.call_args.kwargs["async_queue"] is mock_queue
