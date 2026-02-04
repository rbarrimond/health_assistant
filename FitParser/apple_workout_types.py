"""Apple Watch workout type definitions and extraction logic."""

from typing import Optional

# Comprehensive list of Apple Watch workout types
APPLE_WORKOUT_TYPES = {
    # Strength & Functional
    "Functional Strength Training",
    "Traditional Strength Training",
    "Core Training",
    # Cycling
    "Indoor Cycle",
    "Outdoor Cycle",
    "Stationary Bike",
    # Running & Walking
    "Outdoor Run",
    "Indoor Run",
    "Trail Run",
    "Outdoor Walk",
    "Indoor Walk",
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
    ("training", "strength_training"): "Traditional Strength Training",
    ("training", "functional_training"): "Functional Strength Training",
    ("training", "core"): "Core Training",
    ("training", None): "Traditional Strength Training",  # Default for training
    ("cycling", "indoor_cycling"): "Indoor Cycle",
    ("cycling", "stationary_bike"): "Stationary Bike",
    ("cycling", None): "Outdoor Cycle",
    ("running", "indoor_running"): "Indoor Run",
    ("running", "trail_run"): "Trail Run",
    ("running", None): "Outdoor Run",
    ("walking", "indoor_walk"): "Indoor Walk",
    ("walking", None): "Outdoor Walk",
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


def extract_apple_workout_type(
    workout_name: Optional[str],
    sport: Optional[str],
    sub_sport: Optional[str],
) -> Optional[str]:
    """
    Extract Apple Watch workout type from workout name or infer from FIT sport/sub_sport.

    This function attempts to identify the Apple Watch workout type through:
    1. Pattern matching in the workout_name (e.g., "Functional Strength Training - Upper")
       Handles both spaces and hyphens (e.g., "Functional-Strength-Training")
    2. Fallback mapping from FIT sport/sub_sport tuples
    3. Returns None if no match found

    Args:
        workout_name: User-provided workout name from FIT session_name field
        sport: FIT sport enum value (e.g., 'training', 'cycling')
        sub_sport: FIT sub_sport enum value (e.g., 'strength_training', 'indoor_cycling')

    Returns:
        Apple workout type string (e.g., 'Functional Strength Training') or None
    """
    # Strategy 1: Try to extract from workout_name
    if workout_name:
        # Normalize: replace hyphens with spaces for pattern matching
        # (HealthFit filenames use hyphens, but Apple types use spaces)
        workout_name_normalized = workout_name.replace("-", " ").lower()
        
        # Special case: "Indoor Cycling" should map to "Indoor Cycle"
        if "indoor cycling" in workout_name_normalized:
            return "Indoor Cycle"
        
        # Special case: "Outdoor Cycling" should map to "Outdoor Cycle"
        if "outdoor cycling" in workout_name_normalized:
            return "Outdoor Cycle"
        
        # Special case: "Outdoor Walking" should map to "Outdoor Walk"
        if "outdoor walking" in workout_name_normalized:
            return "Outdoor Walk"
        
        # Special case: "Indoor Walking" should map to "Indoor Walk"
        if "indoor walking" in workout_name_normalized:
            return "Indoor Walk"
        
        for apple_type in APPLE_WORKOUT_TYPES:
            # Skip "Other" in pattern matching - only use as explicit last resort
            if apple_type == "Other":
                continue
            if apple_type.lower() in workout_name_normalized:
                return apple_type

    # Strategy 2: Fallback to FIT sport/sub_sport mapping
    if sport:
        sport_lower = sport.lower() if sport else None
        sub_sport_lower = sub_sport.lower() if sub_sport else None

        # Exact match (sport, sub_sport)
        key = (sport_lower, sub_sport_lower)
        if key in FIT_TO_APPLE_WORKOUT_TYPE:
            return FIT_TO_APPLE_WORKOUT_TYPE[key]

        # Fallback to (sport, None) if sub_sport not in mapping
        key_no_subsport = (sport_lower, None)
        if key_no_subsport in FIT_TO_APPLE_WORKOUT_TYPE:
            return FIT_TO_APPLE_WORKOUT_TYPE[key_no_subsport]

    return None
