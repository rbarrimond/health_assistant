"""Deprecated compatibility shim for Intervals sync.

Canonical runtime ownership lives in
TrainingAnalyticsPlatform.handlers.wellness_sync.IntervalsSyncHandler.
This module is retained temporarily to avoid breaking existing imports.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from TrainingAnalyticsPlatform.integrations.intervals_client import IntervalsicuClient
from TrainingAnalyticsPlatform.handlers.wellness_sync import (
	IntervalsSyncHandler as WellnessIntervalsSyncHandler,
)


class IntervalsSyncHandler(WellnessIntervalsSyncHandler):
	"""Compatibility shim preserving legacy module patch points."""

	def __init__(
		self,
		storage: Any,
		client: Optional[IntervalsicuClient] = None,
	) -> None:
		# Keep legacy constructor behavior for tests that patch this module symbol.
		super().__init__(storage=storage, client=client or IntervalsicuClient())

	@staticmethod
	def _resolve_sync_window(lookback_days: int) -> tuple[datetime.date, datetime.date]:
		"""Resolve date window using this module's datetime for compatibility patches."""
		today = datetime.now(timezone.utc).date()
		if lookback_days == 0:
			return today, today

		end_date = today - timedelta(days=1)
		start_date = end_date - timedelta(days=lookback_days - 1)
		return start_date, end_date

__all__ = ["IntervalsSyncHandler"]
