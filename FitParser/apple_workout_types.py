"""Apple Watch workout type definitions and extraction logic."""

import logging
from typing import Optional

from .exceptions import WorkoutTypeResolutionError
logger = logging.getLogger(__name__)


class AppleWorkoutTypeResolver:
    """
    Resolves Apple Watch workout type from various FIT file inputs.

    This class takes all available inputs and applies a clear resolution
    strategy to determine the Apple Watch workout type.
    """

    def __init__(
        self,
        session_name: Optional[str] = None,
        source_file_name: Optional[str] = None,
        sport: Optional[str] = None,
        sub_sport: Optional[str] = None,
    ):
        """
        Initialize resolver with all available inputs.

        Args:
            session_name: FIT session_name field (most accurate)
            source_file_name: Original filename (e.g., from OneDrive)
            sport: FIT sport enum value
            sub_sport: FIT sub_sport enum value
        """
        self.session_name = session_name
        self.source_file_name = source_file_name
        self.sport = sport
        self.sub_sport = sub_sport

        logger.debug(
            "AppleWorkoutTypeResolver initialized: session_name=%r, "
            "source_file_name=%r, sport=%r, sub_sport=%r",
            session_name, source_file_name, sport, sub_sport
        )

    def resolve(self) -> Optional[str]:
        """
        Resolve Apple Watch workout type with clear priority.

        Resolution strategy:
        1. Extract from session_name (FIT field, most reliable)
        2. Extract from source_file_name (filename fallback)
        3. Map from FIT sport/sub_sport (final fallback)

        Returns:
            Apple Watch workout type string or None
        """
        try:
            # Strategy 1: Try session_name first
            if self.session_name:
                result = self._extract_from_name(self.session_name)
                if result:
                    logger.debug("Resolved from session_name: %r -> %r",
                                 self.session_name, result)
                    return result
                logger.debug("No match in session_name: %r", self.session_name)

            # Strategy 2: Fallback to source filename
            if self.source_file_name:
                result = self._extract_from_name(self.source_file_name)
                if result:
                    logger.debug("Resolved from source_file_name: %r -> %r",
                                 self.source_file_name, result)
                    return result
                logger.debug("No match in source_file_name: %r",
                             self.source_file_name)

            # Strategy 3: Final fallback to FIT sport mapping
            if self.sport:
                result = self._match_fit_sport(self.sport, self.sub_sport)
                if result:
                    logger.debug("Resolved from FIT sport: (%r, %r) -> %r",
                                 self.sport, self.sub_sport, result)
                    return result
                logger.debug("No mapping for FIT sport: (%r, %r)",
                             self.sport, self.sub_sport)

            logger.debug("Could not resolve Apple workout type")
            return None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise WorkoutTypeResolutionError("Apple workout type resolution failed") from exc

    @staticmethod
    def _check_special_cases(normalized_name: str) -> Optional[str]:
        """Check for special case workout name mappings."""
        if "indoor cycling" in normalized_name:
            return INDOOR_CYCLE
        if "outdoor cycling" in normalized_name:
            return OUTDOOR_CYCLE
        if "outdoor walking" in normalized_name:
            return OUTDOOR_WALK
        if "indoor walking" in normalized_name:
            return INDOOR_WALK
        return None

    @staticmethod
    def _match_workout_name(normalized_name: str) -> Optional[str]:
        """Match workout name against known Apple Watch types."""
        for apple_type in APPLE_WORKOUT_TYPES:
            if apple_type == "Other":
                continue
            if apple_type.lower() in normalized_name:
                return apple_type
        return None

    @classmethod
    def _extract_from_name(cls, name: str) -> Optional[str]:
        """
        Extract Apple Watch workout type from a name string.

        This handles both session_name and source_file_name inputs.

        Args:
            name: Name string to extract from (session or filename)

        Returns:
            Apple Watch workout type or None
        """
        normalized = name.replace("-", " ").lower()

        # Check special cases first
        result = cls._check_special_cases(normalized)
        if result:
            return result

        # Try pattern matching
        return cls._match_workout_name(normalized)

    @staticmethod
    def _match_fit_sport(sport: str, sub_sport: Optional[str]) -> Optional[str]:
        """Match FIT sport/sub_sport to Apple Watch workout type."""
        sport_lower = sport.lower() if sport else None
        sub_sport_lower = sub_sport.lower() if sub_sport else None

        # Exact match (sport, sub_sport)
        key = (sport_lower, sub_sport_lower)
        if key in FIT_TO_APPLE_WORKOUT_TYPE:
            return FIT_TO_APPLE_WORKOUT_TYPE[key]

        # Fallback to (sport, None)
        key_no_subsport = (sport_lower, None)
        if key_no_subsport in FIT_TO_APPLE_WORKOUT_TYPE:
            return FIT_TO_APPLE_WORKOUT_TYPE[key_no_subsport]

        # Final fallback to catch-all
        return FIT_TO_APPLE_WORKOUT_TYPE.get(("generic", "generic"), "Other")


# Apple Watch workout type constants (for reuse in methods)
TRADITIONAL_STRENGTH = "Traditional Strength Training"
FUNCTIONAL_STRENGTH = "Functional Strength Training"
INDOOR_CYCLE = "Indoor Cycle"
OUTDOOR_CYCLE = "Outdoor Cycle"
OUTDOOR_WALK = "Outdoor Walk"
INDOOR_WALK = "Indoor Walk"

# Comprehensive list of Apple Watch workout types
APPLE_WORKOUT_TYPES = {
    # Strength & Functional
    FUNCTIONAL_STRENGTH,
    TRADITIONAL_STRENGTH,
    "Core Training",
    # Cycling
    INDOOR_CYCLE,
    OUTDOOR_CYCLE,
    "Stationary Bike",
    # Running & Walking
    "Outdoor Run",
    "Indoor Run",
    "Trail Run",
    OUTDOOR_WALK,
    INDOOR_WALK,
    "Hiking",
    "Racewalking",
    # Sports
    "Tennis",
    "Basketball",
    "Soccer",
    "Football",
    "Baseball",
    "Volleyball",
    "Martial Arts",
    "Boxing",
    # Mind & Body
    "Yoga",
    "Pilates",
    "Flexibility",
    "Tai Chi",
    "Barre",
    # HIIT & Cross-training
    "HIIT",
    "CrossFit",
    "Rowing",
    "Swimming",
    "Open Water Swimming",
    # Recovery
    "Cooldown",
    "Stretching",
    "Meditation",
    # Catchall & Other
    "Other",  # For unclassified activities (e.g., snow shoveling)
    # Other activities
    "Dance",
    "Elliptical",
    "Stair Climbing",
    "Kickboxing",
    "Disc Golf",
    "Gymnastics",
    "Handball",
    "Lacrosse",
    "Pickleball",
    "Skiing",
    "Snowboarding",
    "Skateboarding",
    "Surfing",
    "Wheelchair Walk",
    "Wheelchair Run",
}

# Mapping from FIT (sport, sub_sport) tuples to likely Apple workout types
# Use when extraction from workout_name fails
FIT_TO_APPLE_WORKOUT_TYPE = {
    ("training", "strength_training"): TRADITIONAL_STRENGTH,
    ("training", "functional_training"): FUNCTIONAL_STRENGTH,
    ("training", "core"): "Core Training",
    ("training", None): TRADITIONAL_STRENGTH,  # Default for training
    ("cycling", "indoor_cycling"): INDOOR_CYCLE,
    ("cycling", "stationary_bike"): "Stationary Bike",
    ("cycling", None): OUTDOOR_CYCLE,
    ("running", "indoor_running"): "Indoor Run",
    ("running", "trail_run"): "Trail Run",
    ("running", None): "Outdoor Run",
    ("walking", "indoor_walk"): INDOOR_WALK,
    ("walking", None): OUTDOOR_WALK,
    ("walking", "hiking"): "Hiking",
    ("yoga", None): "Yoga",
    ("pilates", None): "Pilates",
    ("flexibility", None): "Flexibility",
    ("swimming", "pool_swimming"): "Swimming",
    ("swimming", "open_water_swimming"): "Open Water Swimming",
    ("swimming", None): "Swimming",
    ("rowing", None): "Rowing",
    ("elliptical", None): "Elliptical",
    ("generic", "generic"): "Other",  # Catch-all for unmapped sports
}
