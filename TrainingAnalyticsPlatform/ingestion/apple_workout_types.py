"""Apple Watch workout type definitions and extraction logic."""

import logging
from typing import Optional

from TrainingAnalyticsPlatform.platform.exceptions import WorkoutTypeResolutionError
logger = logging.getLogger(__name__)


class AppleWorkoutTypeResolver:
    """
    Resolves Apple Watch workout type from FIT sport/sub_sport signals.
    """

    def __init__(
        self,
        sport: Optional[str] = None,
        sub_sport: Optional[str] = None,
    ):
        """
        Initialize resolver with FIT sport inputs.

        Args:
            sport: FIT sport enum value
            sub_sport: FIT sub_sport enum value
        """
        self.sport = sport
        self.sub_sport = sub_sport

        logger.debug(
            "AppleWorkoutTypeResolver initialized: sport=%r, sub_sport=%r",
            sport,
            sub_sport,
        )

    def resolve(self) -> Optional[str]:
        """
        Resolve Apple Watch workout type from FIT sport/sub_sport.

        Returns:
            Apple Watch workout type string or None
        """
        try:
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


def _match_workout_name(normalized_name: str) -> Optional[str]:
    """Match workout name against known Apple Watch types."""
    for apple_type in APPLE_WORKOUT_TYPES:
        if apple_type == "Other":
            continue
        if apple_type.lower() in normalized_name:
            return apple_type
    return None


def resolve_apple_workout_type_from_name(name: Optional[str]) -> Optional[str]:
    """Resolve Apple workout type from a source-specific name token.

    This is intentionally separate from `AppleWorkoutTypeResolver`, which maps
    only FIT sport/sub_sport signals.
    """
    if not name:
        return None

    normalized = name.replace("-", " ").lower()
    result = _check_special_cases(normalized)
    if result:
        return result
    return _match_workout_name(normalized)


# Apple Watch workout type constants (for reuse in methods)
TRADITIONAL_STRENGTH = "Traditional Strength Training"
FUNCTIONAL_STRENGTH = "Functional Strength Training"
INDOOR_CYCLE = "Indoor Cycle"
OUTDOOR_CYCLE = "Outdoor Cycle"
OUTDOOR_WALK = "Outdoor Walk"
INDOOR_WALK = "Indoor Walk"
INDOOR_RUN = "Indoor Run"
OUTDOOR_RUN = "Outdoor Run"
TRAIL_RUN = "Trail Run"

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
    OUTDOOR_RUN,
    INDOOR_RUN,
    TRAIL_RUN,
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
    ("cycling", "virtual_activity"): INDOOR_CYCLE,
    ("cycling", "stationary_bike"): "Stationary Bike",
    ("cycling", None): OUTDOOR_CYCLE,
    ("running", "virtual_activity"): INDOOR_RUN,
    ("running", "indoor_running"): INDOOR_RUN,
    ("running", "trail_run"): "Trail Run",
    ("running", None): "Outdoor Run",
    ("walking", "virtual_activity"): INDOOR_WALK,
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


def _build_normalized_to_canonical() -> dict[str, str]:
    """Build normalized (hyphenated-lowercase) to canonical activity type mapping.
    
    Normalizes all Apple Watch workout types by converting to lowercase and
    replacing spaces with hyphens. This enables flexible filename matching for
    both space-separated and hyphen-separated formats, as well as both FIT-style
    (Cycling/Walking/Running) and Apple Watch canonical (Cycle/Walk/Run) spellings.
    
    HealthFit filenames may use either form depending on the source:
    - OneDrive filenames often use FIT-aligned names: "Indoor Cycling", "Outdoor Walking"
    - Canonical Apple Watch types: "Indoor Cycle", "Outdoor Walk"
    
    Returns:
        Dict mapping normalized form (e.g., "functional-strength-training")
        to canonical form (e.g., "Functional Strength Training")
    """
    mapping = {}
    
    # Add canonical types
    for apple_type in APPLE_WORKOUT_TYPES:
        normalized = apple_type.lower().replace(" ", "-")
        mapping[normalized] = apple_type
    
    # Add HealthFit filename aliases to handle both Apple Watch and FIT-style spellings
    # HealthFit can use either Cycling/Walking/Running (aligned with FIT) or Cycle/Walk/Run (Apple canonical)
    common_aliases = {
        # Cycling variants
        "indoor-cycling": INDOOR_CYCLE,
        "outdoor-cycling": OUTDOOR_CYCLE,
        "indoor-cycle": INDOOR_CYCLE,
        "outdoor-cycle": OUTDOOR_CYCLE,
        # Walking variants
        "indoor-walking": INDOOR_WALK,
        "outdoor-walking": OUTDOOR_WALK,
        "indoor-walk": INDOOR_WALK,
        "outdoor-walk": OUTDOOR_WALK,
        # Running variants
        "indoor-running": INDOOR_RUN,
        "outdoor-running": OUTDOOR_RUN,
        "indoor-run": INDOOR_RUN,
        "outdoor-run": OUTDOOR_RUN,
        "trail-running": TRAIL_RUN,
        "trail-run": TRAIL_RUN,
    }
    mapping.update(common_aliases)
    
    return mapping


# Mapping from normalized activity token (hyphenated-lowercase) to canonical Apple Watch type
# Used by HealthFit filename parsing to handle both space-separated and hyphen-separated formats
NORMALIZED_ACTIVITY_TO_CANONICAL = _build_normalized_to_canonical()
