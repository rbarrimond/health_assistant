"""Shared constants and utilities for workout models."""

from functools import wraps

import pandas as pd

# Field description constants
ATHLETE_ID_DESC = "Athlete identifier"
ISO_8601_UTC_DESC = "ISO 8601 UTC timestamp"
LAST_UPDATE_DESC = "ISO 8601 UTC timestamp of last update"
DATETIME64_NS = "datetime64[ns]"

# Analytics computation constants
POWER_ANCHOR_WINDOWS_SEC = [5, 30, 180, 300, 480, 1200, 3600]
POWER_CURVE_SECONDS = [
    5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 420, 600, 900, 1200, 1800, 2400, 3600
]

# Surge and interval detection thresholds
SURGE_THRESHOLD_FACTOR = 1.2
SURGE_MIN_SEC = 3
INTERVAL_THRESHOLD_FACTOR = 0.9
INTERVAL_MIN_SEC = 60
CLIMB_MIN_GRADE = 0.03
CLIMB_MIN_SEC = 60
RECOVERY_HR_WINDOW_SEC = 30
LAG_WINDOW_SEC = 60


def numeric_series(column: str):
    """Decorator to extract numeric series from DataFrame for analytics computation.
    
    Used by CanonicalAnalyticsEngine computed fields to safely extract and validate
    numeric series from the canonical DataFrame.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self):
            # pylint: disable=protected-access
            series = self._numeric_series(self.df, column)
            if series.empty:
                return None
            return func(self, series)

        return property(wrapper)

    return decorator
