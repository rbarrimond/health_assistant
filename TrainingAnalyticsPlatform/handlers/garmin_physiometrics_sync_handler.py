"""Compatibility shim for Garmin physiometrics sync handler.

Canonical ownership has moved to:
    TrainingAnalyticsPlatform.handlers.wellness_sync.GarminPhysiometricsSyncHandler

This module is preserved only to:
- Maintain backward-compatible import paths
- Preserve legacy module symbols used by tests and import sites
- Preserve test mock patch targets for datetime
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.handlers.wellness_sync import (
    GarminPhysiometricsSyncHandler as WellnessGarminPhysiometricsSyncHandler,
)

__all__ = ["GarminPhysiometricsSyncHandler"]


class GarminPhysiometricsSyncHandler(WellnessGarminPhysiometricsSyncHandler):
    """Backward-compatible re-export; canonical ownership lives in wellness_sync."""

    @staticmethod
    def _resolve_sync_window(lookback_days: int) -> tuple[date, date]:
        """Use module-local datetime to honour test mock patches."""
        today = datetime.now(timezone.utc).date()
        if lookback_days == 0:
            return today, today

        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=lookback_days - 1)
        return start_date, end_date

