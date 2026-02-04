"""Apple Watch workout type definitions and extraction logic."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Apple Watch workout type constants (for reuse in mappings)
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
}


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


def _match_fit_sport(sport: str, sub_sport: Optional[str]) -> Optional[str]:
    """Match FIT sport/sub_sport to Apple Watch workout type."""
    sport_lower = sport.lower()
    sub_sport_lower = sub_sport.lower() if sub_sport else None

    # Exact match (sport, sub_sport)
    key = (sport_lower, sub_sport_lower)
    if key in FIT_TO_APPLE_WORKOUT_TYPE:
        return FIT_TO_APPLE_WORKOUT_TYPE[key]

    # Fallback to (sport, None)
    key_no_subsport = (sport_lower, None)
    if key_no_subsport in FIT_TO_APPLE_WORKOUT_TYPE:
        return FIT_TO_APPLE_WORKOUT_TYPE[key_no_subsport]

    return None


def extract_apple_workout_type(
    workout_name: Optional[str],
    sport: Optional[str],
    sub_sport: Optional[str],
) -> Optional[str]:
    """
    Extract Apple Watch workout type from workout name or infer from FIT.

    Args:
        workout_name: User-provided workout name from FIT session_name field
        sport: FIT sport enum value (e.g., 'training', 'cycling')
        sub_sport: FIT sub_sport enum value
                   (e.g., 'strength_training', 'indoor_cycling')

    Returns:
        Apple workout type string or None
    """
    # Strategy 1: Try to extract from workout_name
    if workout_name:
        normalized = workout_name.replace("-", " ").lower()
        logger.debug(
            "Extracting apple_workout_type from workout_name: input=%s, normalized=%s",
            workout_name, normalized
        )

        # Check special cases first
        result = _check_special_cases(normalized)
        logger.debug("_check_special_cases returned: %s", result)
        if result:
            return result

        # Try pattern matching
        result = _match_workout_name(normalized)
        logger.debug("_match_workout_name returned: %s", result)
        if result:
            return result

    # Strategy 2: Fallback to FIT sport/sub_sport mapping
    if sport:
        result = _match_fit_sport(sport, sub_sport)
        logger.debug(
            "Fallback to FIT sport mapping: sport=%s, sub_sport=%s, result=%s",
            sport, sub_sport, result
        )
        return result

    logger.debug("No apple_workout_type could be determined")
    return None
