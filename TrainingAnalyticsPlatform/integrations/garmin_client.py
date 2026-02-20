"""Garmin Connect client using garminconnect library for authentication and FIT download."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast

from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError

logger = logging.getLogger(__name__)


class GarminConnectError(RuntimeError):
    """Raised when Garmin Connect API calls fail."""


class GarminConnectClient:
    """Client for Garmin Connect integration using garminconnect library."""

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None) -> None:
        """Initialize Garmin Connect client with optional credentials.
        
        Args:
            email: Garmin account email (from env if not provided)
            password: Garmin account password (from env if not provided)
        """
        self.email = email or os.getenv("GARMIN_EMAIL")
        self.password = password or os.getenv("GARMIN_PASSWORD")
        self.client: Optional[Garmin] = None

    def login(self) -> None:
        """Authenticate with Garmin Connect using credentials.
        
        Raises:
            GarminConnectError: If authentication fails
        """
        if not self.email or not self.password:
            raise GarminConnectError(
                "Missing credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD environment variables."
            )

        try:
            self.client = Garmin(self.email, self.password)
            self.client.login()
            logger.info("Successfully authenticated with Garmin Connect")
        except GarminConnectAuthenticationError as exc:
            logger.error("Garmin authentication failed: %s", exc)
            raise GarminConnectError("Authentication failed - check credentials") from exc
        except GarminConnectConnectionError as exc:
            logger.error("Garmin connection failed: %s", exc)
            raise GarminConnectError("Connection to Garmin Connect failed") from exc
        except Exception as exc:
            logger.error("Unexpected error during Garmin login: %s", exc)
            raise GarminConnectError("Failed to authenticate with Garmin Connect") from exc

    def list_activities(
        self,
        start_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """List recent activities from Garmin Connect.

        Args:
            start_date: Only return activities after this date (default: 30 days ago)
            limit: Maximum number of activities to return

        Returns:
            List of activity dicts from Garmin API

        Raises:
            GarminConnectError: If API call fails
        """
        if not self.client:
            raise GarminConnectError("Not authenticated. Call login() first.")

        try:
            # Default lookback: 30 days
            if start_date is None:
                start_date = datetime.now() - timedelta(days=30)

            # garminconnect uses start index (0-based) and limit
            activities = cast(List[Dict[str, Any]],
                              self.client.get_activities(start=0, limit=limit))

            # Filter by date if needed (activities are returned newest first)
            if start_date:
                return [
                    activity
                    for activity in activities
                    if self._is_activity_after_date(activity, start_date)
                ]

            return activities
        except Exception as exc:
            logger.error("Failed to list Garmin activities: %s", exc)
            raise GarminConnectError("Failed to fetch activity list") from exc

    def _is_activity_after_date(
        self, activity: Dict[str, Any], start_date: datetime
    ) -> bool:
        """Check if activity date is after the start date.

        Args:
            activity: Activity dict from Garmin API
            start_date: Reference date for comparison

        Returns:
            True if activity date >= start_date, False otherwise
        """
        activity_date_str = activity.get("startTimeGMT") or activity.get(
            "startTimeLocal"
        )
        if not activity_date_str:
            return False

        try:
            activity_date = datetime.fromisoformat(
                activity_date_str.replace("Z", "+00:00")
            )
            return activity_date >= start_date
        except ValueError:
            return False

    def download_activity_fit(self, activity_id: str) -> bytes:
        """Download FIT file for a specific activity.
        
        Args:
            activity_id: Garmin activity ID
            
        Returns:
            Raw FIT file bytes
            
        Raises:
            GarminConnectError: If download fails
        """
        if not self.client:
            raise GarminConnectError("Not authenticated. Call login() first.")

        try:
            # Use ORIGINAL format to get the FIT file
            fit_data = self.client.download_activity(
                activity_id,
                dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
            )

            if not fit_data:
                raise GarminConnectError(
                    f"No FIT data returned for activity {activity_id}"
                )

            logger.info(
                "Downloaded FIT file for activity %s (%d bytes)",
                activity_id,
                len(fit_data),
            )
            return fit_data
        except Exception as exc:
            logger.error(
                "Failed to download FIT file for activity %s: %s",
                activity_id,
                exc,
            )
            raise GarminConnectError(
                f"Failed to download FIT file for activity {activity_id}"
            ) from exc
