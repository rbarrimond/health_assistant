"""Unit tests for Apple workout type resolution."""

from FitParser.apple_workout_types import (
    AppleWorkoutTypeResolver,
    FUNCTIONAL_STRENGTH,
    INDOOR_CYCLE,
    OUTDOOR_WALK,
    TRADITIONAL_STRENGTH,
)


def test_resolve_prefers_session_name() -> None:
    """Session name should have highest priority."""
    resolver = AppleWorkoutTypeResolver(
        session_name="Functional Strength Training",
        source_file_name="Outdoor Walk 2025-01-01.fit",
        sport="training",
        sub_sport="strength_training",
    )

    assert resolver.resolve() == FUNCTIONAL_STRENGTH


def test_resolve_falls_back_to_source_filename() -> None:
    """Source filename should be used when session name is missing."""
    resolver = AppleWorkoutTypeResolver(
        session_name=None,
        source_file_name="Outdoor Walk 2025-01-01.fit",
        sport="training",
        sub_sport="strength_training",
    )

    assert resolver.resolve() == OUTDOOR_WALK


def test_resolve_falls_back_to_fit_sport_mapping() -> None:
    """Sport/sub_sport mapping should be used as a final fallback."""
    resolver = AppleWorkoutTypeResolver(
        session_name=None,
        source_file_name=None,
        sport="training",
        sub_sport="strength_training",
    )

    assert resolver.resolve() == TRADITIONAL_STRENGTH


def test_resolve_handles_special_cases() -> None:
    """Special case strings should map correctly."""
    resolver = AppleWorkoutTypeResolver(
        session_name="Indoor Cycling",
        source_file_name=None,
        sport="cycling",
        sub_sport="indoor_cycling",
    )

    assert resolver.resolve() == INDOOR_CYCLE
