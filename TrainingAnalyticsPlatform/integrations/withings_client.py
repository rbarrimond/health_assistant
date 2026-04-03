"""Withings API client for OAuth and measurement data."""
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

from TrainingAnalyticsPlatform.platform.exceptions import (
    AuthError,
    ExternalServiceError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# Withings API endpoints
WITHINGS_AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_NOTIFY_URL = "https://wbsapi.withings.net/notify"
WITHINGS_MEASURE_URL = "https://wbsapi.withings.net/measure"

# Measurement type identifiers
TYPE_WEIGHT = 1
TYPE_FAT_RATIO = 6
TYPE_FAT_MASS = 8
TYPE_MUSCLE_MASS = 76
TYPE_BONE_MASS = 88
TYPE_VISCERAL_FAT = 123
TYPE_METABOLIC_AGE = 155


class WithingsClient:
    """Client for Withings API integration."""

    @staticmethod
    def _build_measure_params(
        start_date: Optional[int],
        end_date: Optional[int],
        lastupdate: Optional[int],
        offset: Optional[int],
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "action": "getmeas",
            # Body composition metrics only
            "meastypes": "1,5,6,8,76,77,88,91,123,155",
            "category": 1,
        }

        if lastupdate is not None:
            params["lastupdate"] = lastupdate
        else:
            params["startdate"] = start_date
            params["enddate"] = end_date

        if offset is not None:
            params["offset"] = offset

        return params

    @staticmethod
    def _next_offset(body: Dict[str, Any]) -> Optional[int]:
        if not bool(body.get("more", 0)):
            return None
        next_offset = body.get("offset")
        if next_offset is None:
            return None
        return int(next_offset)

    @staticmethod
    def _parse_measurements_from_groups(measure_groups: List[Dict], parser: Any) -> List[Dict]:
        parsed_measurements: List[Dict] = []
        for group in measure_groups:
            parsed = parser(group)
            if parsed:
                parsed_measurements.append(parsed)
        return parsed_measurements

    def _fetch_measure_page(
        self,
        access_token: str,
        start_date: Optional[int],
        end_date: Optional[int],
        lastupdate: Optional[int],
        offset: Optional[int],
    ) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        params = self._build_measure_params(
            start_date=start_date,
            end_date=end_date,
            lastupdate=lastupdate,
            offset=offset,
        )

        response = requests.post(
            WITHINGS_MEASURE_URL,
            data=params,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        if result.get("status") != 0:
            raise ExternalServiceError(
                f"Withings API error: {result.get('error')}"
            )

        return result.get("body", {})

    def __init__(self):
        """Initialize Withings client with credentials from environment."""
        self.client_id = os.getenv("WITHINGS_CLIENT_ID")
        self.client_secret = os.getenv("WITHINGS_CLIENT_SECRET")
        self.redirect_uri = os.getenv("WITHINGS_REDIRECT_URI")

        if not all([self.client_id, self.client_secret, self.redirect_uri]):
            logger.warning(
                "Withings credentials not fully configured. "
                "Set WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET, and WITHINGS_REDIRECT_URI."
            )

    def get_authorization_url(self, athlete_id: str) -> Tuple[str, str]:
        """
        Generate OAuth authorization URL for user to authorize access.

        Args:
            athlete_id: Athlete identifier (used in state parameter)

        Returns:
            Tuple of (authorization_url, state_token)
        """
        # Generate secure state token
        state = secrets.token_urlsafe(32)

        # Encode athlete_id in state (format: {token}:{athlete_id})
        state_with_athlete = f"{state}:{athlete_id}"

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "user.metrics,user.info",
            "state": state_with_athlete,
        }

        auth_url = f"{WITHINGS_AUTH_URL}?{urlencode(params)}"
        logger.info("Generated Withings authorization URL for athlete %s", athlete_id)

        return auth_url, state_with_athlete

    def exchange_auth_code(self, code: str, state: str) -> Dict:
        """
        Exchange authorization code for access/refresh tokens.

        Args:
            code: Authorization code from callback
            state: State parameter to validate

        Returns:
            Dict with:
                - userid: Withings user ID
                - access_token: OAuth access token
                - refresh_token: OAuth refresh token
                - expires_in: Token lifetime in seconds
                - scope: Granted scopes
                - athlete_id: Extracted from state

        Raises:
            ValidationError: If callback state is invalid
            AuthError: If Withings rejects the token exchange
            ExternalServiceError: If the Withings request fails unexpectedly
        """
        # Extract athlete_id from state
        if ":" not in state:
            raise ValidationError("Invalid state parameter format")

        _, athlete_id = state.rsplit(":", 1)

        # Exchange code for tokens
        data = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }

        try:
            response = requests.post(WITHINGS_TOKEN_URL, data=data, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("status") != 0:
                raise AuthError(f"Withings API error: {result.get('error')}")

            body = result.get("body", {})
            logger.info(
                "Successfully exchanged auth code for tokens (athlete: %s, userid: %s)",
                athlete_id, body.get("userid")
            )

            return {
                "userid": body.get("userid"),
                "access_token": body.get("access_token"),
                "refresh_token": body.get("refresh_token"),
                "expires_in": body.get("expires_in"),
                "scope": body.get("scope"),
                "athlete_id": athlete_id,
            }

        except requests.RequestException as exc:
            logger.error("Failed to exchange auth code", exc_info=True)
            raise ExternalServiceError("Token exchange failed") from exc
        except ValueError as exc:
            logger.error("Withings token exchange returned invalid payload", exc_info=True)
            raise ExternalServiceError("Token exchange returned invalid response payload") from exc

    def subscribe_to_notifications(self, access_token: str, callback_url: str) -> bool:
        """
        Subscribe to weight measurement notifications.

        Args:
            access_token: OAuth access token
            callback_url: Webhook callback URL

        Returns:
            True if subscription successful

        Raises:
            ExternalServiceError: If subscription fails
        """
        data = {
            "action": "subscribe",
            "callbackurl": callback_url,
            "appli": 1,  # Weight-related data
            "comment": "Health Assistant weight sync",
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        try:
            response = requests.post(
                WITHINGS_NOTIFY_URL, data=data, headers=headers, timeout=30
            )
            response.raise_for_status()
            result = response.json()

            if result.get("status") != 0:
                # Status 343 means already subscribed - that's OK
                if result.get("status") == 343:
                    logger.info("Webhook already subscribed")
                else:
                    raise ExternalServiceError(
                        f"Withings API error: {result.get('error')}"
                    )

            logger.info("Successfully subscribed to Withings notifications")
            return True

        except requests.RequestException as exc:
            logger.error("Failed to subscribe to notifications", exc_info=True)
            raise ExternalServiceError("Subscription failed") from exc
        except ValueError as exc:
            logger.error("Withings subscription returned invalid payload", exc_info=True)
            raise ExternalServiceError("Subscription returned invalid response payload") from exc

    def fetch_measurements(
        self,
        access_token: str,
        start_date: Optional[int] = None,
        end_date: Optional[int] = None,
        lastupdate: Optional[int] = None,
    ) -> List[Dict]:
        """
        Fetch weight and body composition measurements from Withings API.

        Args:
            access_token: OAuth access token
            start_date: Unix timestamp (start of range)
            end_date: Unix timestamp (end of range)
            lastupdate: Optional unix timestamp for incremental sync

        Returns:
            List of measurement dicts with parsed values:
                - measured_at: ISO timestamp
                - weight_kg: Weight in kg
                - fat_mass_kg: Fat mass in kg
                - muscle_mass_kg: Muscle mass in kg
                - bone_mass_kg: Bone mass in kg
                - body_fat_pct: Body fat percentage
                - visceral_fat_index: Visceral fat index
                - metabolic_age_years: Metabolic age

        Raises:
            ExternalServiceError: If API request fails
        """
        if lastupdate is None and (start_date is None or end_date is None):
            raise ValidationError(
                "Either lastupdate or both start_date and end_date must be provided"
            )

        try:
            measurements: List[Dict] = []
            offset: Optional[int] = None

            while True:
                body = self._fetch_measure_page(
                    access_token=access_token,
                    start_date=start_date,
                    end_date=end_date,
                    lastupdate=lastupdate,
                    offset=offset,
                )
                measure_groups = body.get("measuregrps", [])

                logger.info(
                    "Fetched %d Withings measurement groups (offset=%s)",
                    len(measure_groups),
                    offset,
                )

                measurements.extend(
                    self._parse_measurements_from_groups(
                        measure_groups,
                        self.parse_measurement_group,
                    )
                )

                next_offset = self._next_offset(body)
                if next_offset is None:
                    if bool(body.get("more", 0)):
                        logger.warning(
                            "Withings API reported more data but no offset was returned; stopping pagination"
                        )
                    break
                offset = next_offset

            return measurements

        except requests.RequestException as exc:
            logger.error("Failed to fetch measurements", exc_info=True)
            raise ExternalServiceError("Measurement fetch failed") from exc
        except ValueError as exc:
            logger.error("Withings measurements returned invalid payload", exc_info=True)
            raise ExternalServiceError("Measurement fetch returned invalid response payload") from exc

    def parse_measurement_group(self, group: Dict) -> Optional[Dict]:
        """
        Parse a Withings measurement group into standardized format.

        Args:
            group: Measurement group from Withings API

        Returns:
            Dict with parsed measurements, or None if no weight data
        """
        # Extract timestamp
        measured_at_unix = group.get("date")
        if not measured_at_unix:
            return None

        measured_at = datetime.fromtimestamp(measured_at_unix, tz=timezone.utc).isoformat()

        # Parse individual measures
        measures = group.get("measures", [])
        parsed_data: Dict[str, Any] = {
            "measured_at": measured_at,
            "data_source": "withings",
        }

        for measure in measures:
            measure_type = measure.get("type")
            value = measure.get("value")
            unit = measure.get("unit", 0)

            if value is None:
                continue

            # Calculate actual value: value × 10^unit
            actual_value = float(value * (10 ** unit))

            # Map to our schema
            if measure_type == TYPE_WEIGHT:
                parsed_data["weight_kg"] = actual_value
            elif measure_type == TYPE_FAT_MASS:
                parsed_data["fat_mass_kg"] = actual_value
            elif measure_type == TYPE_MUSCLE_MASS:
                parsed_data["muscle_mass_kg"] = actual_value
            elif measure_type == TYPE_BONE_MASS:
                parsed_data["bone_mass_kg"] = actual_value
            elif measure_type == TYPE_FAT_RATIO:
                parsed_data["body_fat_pct"] = actual_value
            elif measure_type == TYPE_VISCERAL_FAT:
                parsed_data["visceral_fat_index"] = actual_value
            elif measure_type == TYPE_METABOLIC_AGE:
                parsed_data["metabolic_age_years"] = int(actual_value)

        # Only return if we have weight data
        if "weight_kg" not in parsed_data:
            return None

        logger.debug("Parsed measurement: %s", parsed_data)
        return parsed_data

    def refresh_access_token(self, refresh_token: str) -> Dict:
        """
        Refresh an expired access token.

        Args:
            refresh_token: OAuth refresh token

        Returns:
            Dict with:
                - access_token: New access token
                - refresh_token: New refresh token
                - expires_in: Token lifetime in seconds

        Raises:
            AuthError: If refresh is rejected by Withings
            ExternalServiceError: If the refresh request fails unexpectedly
        """
        data = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }

        try:
            response = requests.post(WITHINGS_TOKEN_URL, data=data, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("status") != 0:
                raise AuthError(f"Withings API error: {result.get('error')}")

            body = result.get("body", {})
            logger.info("Successfully refreshed Withings access token")

            return {
                "access_token": body.get("access_token"),
                "refresh_token": body.get("refresh_token"),
                "expires_in": body.get("expires_in"),
            }

        except requests.RequestException as exc:
            logger.error("Failed to refresh access token", exc_info=True)
            raise ExternalServiceError("Token refresh failed") from exc
        except ValueError as exc:
            logger.error("Withings token refresh returned invalid payload", exc_info=True)
            raise ExternalServiceError("Token refresh returned invalid response payload") from exc
