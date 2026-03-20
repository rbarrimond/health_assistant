"""Unit tests for source handler registry contract."""

from TrainingAnalyticsPlatform.handlers.source_handler_registry import SourceHandlerRegistry


def test_source_handler_registry_resolves_registered_handler():
    handler = object()
    registry = SourceHandlerRegistry(handlers={"onedrive": handler})

    assert registry.resolve("onedrive") is handler


def test_source_handler_registry_returns_none_for_unknown_source():
    registry = SourceHandlerRegistry(handlers={"garmin": object()})

    assert registry.resolve("unknown") is None
