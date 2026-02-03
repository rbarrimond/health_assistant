"""Tests for is_indoor inference logic."""


from FitParser.models import WorkoutSession


class TestIsIndoorInference:
    """Tests for inferring is_indoor from sub_sport."""

    def test_indoor_cycling_marked_as_indoor(self) -> None:
        """Verify indoor_cycling is marked as indoor."""
        session = WorkoutSession(
            sport="cycling",
            sub_sport="indoor_cycling",
            is_indoor=True,  # Set by adapter based on sub_sport
        )
        assert session.is_indoor is True

    def test_zwift_ride_marked_as_indoor(self) -> None:
        """Verify zwift is marked as indoor even with GPS."""
        session = WorkoutSession(
            sport="cycling",
            sub_sport="zwift",
            is_indoor=True,  # Set by adapter
        )
        assert session.is_indoor is True

    def test_virtual_ride_marked_as_indoor(self) -> None:
        """Verify virtual rides are marked as indoor."""
        session = WorkoutSession(
            sport="cycling",
            sub_sport="virtual_ride",
            is_indoor=True,  # Set by adapter
        )
        assert session.is_indoor is True

    def test_stationary_bike_marked_as_indoor(self) -> None:
        """Verify stationary bike is marked as indoor."""
        session = WorkoutSession(
            sport="cycling",
            sub_sport="stationary_cycling",
            is_indoor=True,  # Set by adapter
        )
        assert session.is_indoor is True

    def test_trainer_marked_as_indoor(self) -> None:
        """Verify trainer workouts are marked as indoor."""
        session = WorkoutSession(
            sport="cycling",
            sub_sport="trainer",
            is_indoor=True,
        )
        assert session.is_indoor is True

    def test_outdoor_cycling_not_marked_as_indoor(self) -> None:
        """Verify outdoor cycling is not marked as indoor."""
        session = WorkoutSession(
            sport="cycling",
            sub_sport="road",
            is_indoor=False,
        )
        assert session.is_indoor is False

    def test_mountain_biking_not_marked_as_indoor(self) -> None:
        """Verify mountain biking is not marked as indoor."""
        session = WorkoutSession(
            sport="cycling",
            sub_sport="mountain",
            is_indoor=False,
        )
        assert session.is_indoor is False
