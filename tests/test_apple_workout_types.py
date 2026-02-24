"""Unit tests for Apple workout type resolution."""

from TrainingAnalyticsPlatform.ingestion.apple_workout_types import (
    AppleWorkoutTypeResolver,
    FUNCTIONAL_STRENGTH,
    INDOOR_CYCLE,
    OUTDOOR_WALK,
    TRADITIONAL_STRENGTH,
    resolve_apple_workout_type_from_name,
)


def test_resolve_uses_fit_subsport_mapping() -> None:
    """Sport/sub_sport mapping should resolve to specific Apple type."""
    resolver = AppleWorkoutTypeResolver(
        sport="training",
        sub_sport="strength_training",
    )

    assert resolver.resolve() == TRADITIONAL_STRENGTH


def test_resolve_maps_virtual_activity_cycling_to_indoor_cycle() -> None:
    """Virtual activity with cycling sport should map to Apple Indoor Cycle."""
    resolver = AppleWorkoutTypeResolver(
        sport="cycling",
        sub_sport="virtual_activity",
    )

    assert resolver.resolve() == INDOOR_CYCLE


def test_resolve_maps_virtual_activity_running_to_indoor_run() -> None:
    """Virtual activity with running sport should map to Apple Indoor Run."""
    resolver = AppleWorkoutTypeResolver(
        sport="running",
        sub_sport="virtual_activity",
    )

    assert resolver.resolve() == "Indoor Run"


def test_resolve_maps_virtual_activity_walking_to_indoor_walk() -> None:
    """Virtual activity with walking sport should map to Apple Indoor Walk."""
    resolver = AppleWorkoutTypeResolver(
        sport="walking",
        sub_sport="virtual_activity",
    )

    assert resolver.resolve() == "Indoor Walk"


def test_resolve_falls_back_to_sport_default_mapping() -> None:
    """Sport-only mapping should be used when sub_sport is missing."""
    resolver = AppleWorkoutTypeResolver(
        sport="training",
        sub_sport=None,
    )

    assert resolver.resolve() == TRADITIONAL_STRENGTH


def test_resolve_handles_unmapped_sport_with_other() -> None:
    """Unknown sport/sub_sport should map to catch-all 'Other'."""
    resolver = AppleWorkoutTypeResolver(
        sport="kayaking",
        sub_sport=None,
    )

    assert resolver.resolve() == "Other"


def test_resolve_apple_workout_type_from_name_handles_special_cases() -> None:
    """HealthFit/source-name helper should resolve special-case labels."""
    assert resolve_apple_workout_type_from_name("Indoor Cycling") == INDOOR_CYCLE


def test_resolve_apple_workout_type_from_name_matches_known_type() -> None:
    """HealthFit/source-name helper should match known Apple workout labels."""
    assert resolve_apple_workout_type_from_name("Outdoor Walk 2025-01-01") == OUTDOOR_WALK


def test_resolve_apple_workout_type_from_name_functional_strength() -> None:
    """HealthFit/source-name helper should detect functional strength labels."""
    assert (
        resolve_apple_workout_type_from_name("Morning Functional Strength Training")
        == FUNCTIONAL_STRENGTH
    )
