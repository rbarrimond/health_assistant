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
        workout_name="Functional Strength Training",
        sport="training",
        sub_sport="strength_training",
    )

    assert resolver.resolve() == FUNCTIONAL_STRENGTH


def test_resolve_uses_workout_name() -> None:
    """Workout name should be used when available."""
    resolver = AppleWorkoutTypeResolver(
        workout_name="Outdoor Walk 2025-01-01",
        sport="training",
        sub_sport="strength_training",
    )

    assert resolver.resolve() == OUTDOOR_WALK


def test_resolve_falls_back_to_fit_sport_mapping() -> None:
    """Sport/sub_sport mapping should be used as a final fallback."""
    resolver = AppleWorkoutTypeResolver(
        workout_name=None,
        sport="training",
        sub_sport="strength_training",
    )

    assert resolver.resolve() == TRADITIONAL_STRENGTH


def test_resolve_handles_special_cases() -> None:
    """Special case strings should map correctly."""
    resolver = AppleWorkoutTypeResolver(
        workout_name="Indoor Cycling",
        sport="cycling",
        sub_sport="indoor_cycling",
    )

    assert resolver.resolve() == INDOOR_CYCLE
