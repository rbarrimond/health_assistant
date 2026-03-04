"""Intervals.icu API client for physiometrics data."""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from TrainingAnalyticsPlatform.platform.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

# Intervals.icu API endpoints
INTERVALS_API_BASE_URL = "https://intervals.icu/api/v1"


class IntervalsicuClient:
    """Client for Intervals.icu API integration."""

    def __init__(self, api_key: Optional[str] = None, athlete_id: Optional[str] = None):
        """
        Initialize Intervals.icu client with API credentials.

        Args:
            api_key: API key for authentication (reads from INTERVALS_API_KEY env if not provided)
            athlete_id: Athlete ID (reads from INTERVALS_ATHLETE_ID env if not provided)

        Raises:
            ExternalServiceError: If API key is not configured
        """
        self.api_key = api_key or os.getenv("INTERVALS_API_KEY")
        if not self.api_key:
            raise ExternalServiceError(
                "Intervals.icu API key not configured. Set INTERVALS_API_KEY environment variable."
            )

        self.athlete_id = athlete_id or os.getenv("INTERVALS_ATHLETE_ID")
        self.base_url = INTERVALS_API_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def get_athlete_measurements(
        self,
        athlete_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any] | List[Dict[str, Any]]:
        """
        Fetch measurements for an athlete over a date range.

        Args:
            athlete_id: Intervals.icu athlete ID or email
            start_date: Start date in YYYY-MM-DD format (default: 30 days ago)
            end_date: End date in YYYY-MM-DD format (default: today)

        Returns:
            Dict or list of dicts with measurements data

        Raises:
            ExternalServiceError: If API call fails
        """
        if not start_date:
            start_date = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        if not end_date:
            end_date = datetime.now(timezone.utc).date().isoformat()

        try:
            url = f"{self.base_url}/athlete/{athlete_id}/measurements"
            logger.info(
                "Fetching measurements for athlete %s from %s to %s",
                athlete_id, start_date, end_date
            )

            params = {
                "start_date": start_date,
                "end_date": end_date,
            }

            response = self._make_request("GET", url, params=params)
            return response
        except ExternalServiceError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error fetching measurements from Intervals.icu: %s", exc)
            raise ExternalServiceError(
                f"Failed to fetch measurements from Intervals.icu: {exc}"
            ) from exc

    def get_athlete_hrv(
        self,
        athlete_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch HRV (heart rate variability) data for an athlete.

        Args:
            athlete_id: Intervals.icu athlete ID or email
            start_date: Start date in YYYY-MM-DD format (default: 30 days ago)
            end_date: End date in YYYY-MM-DD format (default: today)

        Returns:
            Dict with HRV data

        Raises:
            ExternalServiceError: If API call fails
        """
        if not start_date:
            start_date = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        if not end_date:
            end_date = datetime.now(timezone.utc).date().isoformat()

        try:
            url = f"{self.base_url}/athlete/{athlete_id}/hrv"
            logger.info(
                "Fetching HRV for athlete %s from %s to %s",
                athlete_id, start_date, end_date
            )

            params = {
                "start_date": start_date,
                "end_date": end_date,
            }

            response = self._make_request("GET", url, params=params)
            return response
        except ExternalServiceError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error fetching HRV from Intervals.icu: %s", exc)
            raise ExternalServiceError(
                f"Failed to fetch HRV from Intervals.icu: {exc}"
            ) from exc

    def get_athlete_readiness(
        self,
        athlete_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch readiness scores for an athlete.

        Args:
            athlete_id: Intervals.icu athlete ID or email
            start_date: Start date in YYYY-MM-DD format (default: 30 days ago)
            end_date: End date in YYYY-MM-DD format (default: today)

        Returns:
            Dict with readiness scores

        Raises:
            ExternalServiceError: If API call fails
        """
        if not start_date:
            start_date = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        if not end_date:
            end_date = datetime.now(timezone.utc).date().isoformat()

        try:
            url = f"{self.base_url}/athlete/{athlete_id}/readiness"
            logger.info(
                "Fetching readiness for athlete %s from %s to %s",
                athlete_id, start_date, end_date
            )

            params = {
                "start_date": start_date,
                "end_date": end_date,
            }

            response = self._make_request("GET", url, params=params)
            return response
        except ExternalServiceError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Error fetching readiness from Intervals.icu: %s", exc)
            raise ExternalServiceError(
                f"Failed to fetch readiness from Intervals.icu: {exc}"
            ) from exc

    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make an authenticated HTTP request to Intervals.icu API.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full API URL
            params: Query parameters
            data: Request body
            timeout: Request timeout in seconds

        Returns:
            Parsed JSON response

        Raises:
            ExternalServiceError: If request fails

        """
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                timeout=timeout,
            )

            # Handle HTTP errors
            if response.status_code == 401:
                logger.error("Unauthorized: Invalid Intervals.icu API key")
                raise ExternalServiceError("Intervals.icu API authentication failed (401)")
            elif response.status_code == 404:
                logger.warning("Athlete not found in Intervals.icu: %s", url)
                raise ExternalServiceError(f"Athlete not found in Intervals.icu: {url}")
            elif response.status_code == 429:
                logger.warning("Rate limited by Intervals.icu API")
                raise ExternalServiceError("Rate limited by Intervals.icu API (429)")
            elif response.status_code >= 400:
                logger.error(
                    "API error %d: %s",
                    response.status_code,
                    response.text
                )
                raise ExternalServiceError(
                    f"Intervals.icu API error {response.status_code}: {response.text}"
                )

            response.raise_for_status()
            return response.json()

        except requests.Timeout as exc:
            logger.error("Timeout calling Intervals.icu API: %s", exc)
            raise ExternalServiceError("Intervals.icu API request timeout") from exc
        except requests.ConnectionError as exc:
            logger.error("Connection error calling Intervals.icu API: %s", exc)
            raise ExternalServiceError("Intervals.icu API connection error") from exc
        except ValueError as exc:
            logger.error("Invalid JSON response from Intervals.icu API: %s", exc)
            raise ExternalServiceError("Invalid JSON response from Intervals.icu API") from exc
