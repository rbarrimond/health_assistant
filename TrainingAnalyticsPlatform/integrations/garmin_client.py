"""Garmin Connect client using garminconnect library for authentication and FIT download."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

if TYPE_CHECKING:
    from garminconnect import Garmin

# Define fallback exception classes first
class GarminConnectAuthenticationError(Exception):
    """Exception raised for Garmin Connect authentication failures."""

class GarminConnectConnectionError(Exception):
    """Exception raised for Garmin Connect connection failures."""


class GarminConnectTooManyRequestsError(Exception):
    """Exception raised when Garmin Connect throttles requests."""

# Try to use the real implementations from garminconnect
try:
    from garminconnect import (
        Garmin as GarminImpl,
        GarminConnectAuthenticationError as _GarminAuthError,
        GarminConnectConnectionError as _GarminConnError,
        GarminConnectTooManyRequestsError as _GarminTooManyRequestsError,
    )
    # Update our namespace to use the real implementations if available
    GarminConnectAuthenticationError = _GarminAuthError  # type: ignore[assignment]
    GarminConnectConnectionError = _GarminConnError  # type: ignore[assignment]
    GarminConnectTooManyRequestsError = _GarminTooManyRequestsError  # type: ignore[assignment]
except ImportError:  # pragma: no cover - optional dependency in test/runtime variants
    GarminImpl = None  # type: ignore[assignment]

from TrainingAnalyticsPlatform.ingestion.fit_file_preprocessor import FitFilePreprocessor
from TrainingAnalyticsPlatform.platform.exceptions import PreprocessingError

logger = logging.getLogger(__name__)

NOT_AUTHENTICATED_ERROR = "Not authenticated. Call login() first."
DEPENDENCY_NOT_INSTALLED_ERROR = (
    "garminconnect dependency is not installed in this environment."
)


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
        self.client: Optional[Garmin] = None  # type: ignore[name-defined]

    def login(self) -> None:
        """Authenticate with Garmin Connect using credentials.
        
        Raises:
            GarminConnectError: If authentication fails
        """
        if not self.email or not self.password:
            raise GarminConnectError(
                "Missing credentials. Set GARMIN_EMAIL and GARMIN_PASSWORD environment variables."
            )
        if GarminImpl is None:
            raise GarminConnectError(DEPENDENCY_NOT_INSTALLED_ERROR)

        try:
            candidate_client = GarminImpl(self.email, self.password)
            candidate_client.login()
            self.client = candidate_client
            logger.info("Successfully authenticated with Garmin Connect")
        except GarminConnectAuthenticationError as exc:
            self.client = None
            logger.error("Garmin authentication failed: %s", exc)
            raise GarminConnectError("Authentication failed - check credentials") from exc
        except GarminConnectTooManyRequestsError as exc:
            self.client = None
            logger.error("Garmin login throttled: %s", exc)
            raise GarminConnectError(
                "Garmin Connect rate limited this login attempt"
            ) from exc
        except GarminConnectConnectionError as exc:
            self.client = None
            logger.error("Garmin connection failed: %s", exc)
            raise GarminConnectError("Connection to Garmin Connect failed") from exc
        except Exception as exc:
            self.client = None
            logger.error("Unexpected error during Garmin login: %s", exc)
            raise GarminConnectError("Failed to authenticate with Garmin Connect") from exc

    def list_activities(
        self,
        start_date: Optional[datetime] = None,
    ) -> List[Dict]:
        """List recent activities from Garmin Connect.

        Args:
            start_date: Only return activities after this date (default: 30 days ago)

        Returns:
            List of activity dicts from Garmin API

        Raises:
            GarminConnectError: If API call fails
        """
        if not self.client:
            raise GarminConnectError(NOT_AUTHENTICATED_ERROR)

        try:
            # Default lookback: 30 days
            if start_date is None:
                start_date = datetime.now() - timedelta(days=30)

            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)

            start_date_str = start_date.date().isoformat()
            end_date_str = datetime.now(timezone.utc).date().isoformat()

            activities = cast(
                List[Dict[str, Any]],
                self.client.get_activities_by_date(
                    startdate=start_date_str,
                    enddate=end_date_str,
                ),
            )

            return activities
        except Exception as exc:
            logger.error("Failed to list Garmin activities: %s", exc)
            raise GarminConnectError(f"Failed to fetch activity list: {exc}") from exc

    def dump_tokens(self) -> str:
        """Serialize the current garth session state to a string for later restoration.

        Returns:
            Base64-encoded string containing OAuth1 + OAuth2 token data.

        Raises:
            GarminConnectError: If not authenticated or serialization fails.
        """
        if self.client is None:
            raise GarminConnectError(NOT_AUTHENTICATED_ERROR)
        try:
            return self.client.garth.dumps()
        except Exception as exc:
            logger.error("Failed to serialize Garmin tokens: %s", exc)
            raise GarminConnectError("Failed to serialize Garmin tokens") from exc

    def restore_from_tokens(self, garth_token: str) -> None:
        """Restore a previous Garmin session from a serialized garth token string.

        Calls login(tokenstore=garth_token) which is the library's public API for
        token-based restore. Because garth_token is a base64 string (>512 chars),
        the library routes through garth.loads() rather than SSO — no username/password
        exchange, no 429 risk. The library also fetches the user profile to populate
        display_name, which is required for user-scoped API URL construction
        (e.g. usersummary-service/usersummary/daily/{display_name}).

        Args:
            garth_token: Base64-encoded token string produced by dump_tokens().

        Raises:
            GarminConnectError: If the token is invalid or restoration fails.
        """
        if GarminImpl is None:
            raise GarminConnectError(DEPENDENCY_NOT_INSTALLED_ERROR)
        try:
            candidate_client = GarminImpl()
            candidate_client.login(tokenstore=garth_token)
            self.client = candidate_client
            logger.info("Restored Garmin session from stored tokens")
        except Exception as exc:
            self.client = None
            logger.warning("Failed to restore Garmin session from stored tokens: %s", exc)
            raise GarminConnectError(
                f"Failed to restore Garmin session from stored tokens: {exc}"
            ) from exc

    def _ensure_authenticated_client(self) -> Garmin:
        """Return authenticated Garmin client, logging in lazily if needed."""
        if self.client is None:
            self.login()
        if self.client is None:
            raise GarminConnectError(NOT_AUTHENTICATED_ERROR)
        return self.client

    def get_user_summary(self, date_str: str) -> Dict[str, Any]:
        """Fetch Garmin daily user summary for a specific date (YYYY-MM-DD)."""
        client = self._ensure_authenticated_client()
        try:
            return cast(Dict[str, Any], client.get_user_summary(date_str))
        except Exception as exc:
            logger.error("Failed to fetch Garmin user summary for %s: %s", date_str, exc)
            raise GarminConnectError(
                f"Failed to fetch Garmin user summary: {exc}"
            ) from exc

    def get_training_status(self, date_str: str) -> Dict[str, Any]:
        """Fetch Garmin training status for a specific date (YYYY-MM-DD)."""
        client = self._ensure_authenticated_client()
        try:
            return cast(Dict[str, Any], client.get_training_status(date_str))
        except Exception as exc:
            logger.error(
                "Failed to fetch Garmin training status for %s: %s", date_str, exc
            )
            raise GarminConnectError(
                f"Failed to fetch Garmin training status: {exc}"
            ) from exc

    def get_training_readiness(
        self,
        date_str: str,
    ) -> Optional[Union[Dict[str, Any], list[Dict[str, Any]]]]:
        """Fetch Garmin training readiness payload for a specific date (YYYY-MM-DD)."""
        client = self._ensure_authenticated_client()
        try:
            value = client.get_training_readiness(date_str)
            if value is None:
                return None
            if isinstance(value, dict):
                return cast(Dict[str, Any], value)
            if isinstance(value, list):
                return cast(list[Dict[str, Any]], value)
            logger.warning(
                "Unexpected Garmin training readiness payload type for %s",
                date_str,
                extra={"payload_type": type(value).__name__},
            )
            return None
        except Exception as exc:
            logger.error(
                "Failed to fetch Garmin training readiness for %s: %s", date_str, exc
            )
            raise GarminConnectError(
                f"Failed to fetch Garmin training readiness: {exc}"
            ) from exc

    def get_morning_training_readiness(self, date_str: str) -> Optional[Dict[str, Any]]:
        """Fetch Garmin morning training readiness payload for a specific date (YYYY-MM-DD)."""
        client = self._ensure_authenticated_client()
        try:
            value = client.get_morning_training_readiness(date_str)
            if value is None:
                return None
            return cast(Dict[str, Any], value)
        except Exception as exc:
            logger.error(
                "Failed to fetch Garmin morning training readiness for %s: %s",
                date_str,
                exc,
            )
            raise GarminConnectError(
                f"Failed to fetch Garmin morning training readiness: {exc}"
            ) from exc

    def download_activity_fit(self, activity_id: str) -> bytes:
        """Download FIT file for a specific activity.
        
        Args:
            activity_id: Garmin activity ID
            
        Returns:
            Raw FIT file bytes (decompressed if gzipped)
            
        Raises:
            GarminConnectError: If download fails or file cannot be processed
        """
        if not self.client:
            raise GarminConnectError(NOT_AUTHENTICATED_ERROR)

        try:
            # Use ORIGINAL format to get the FIT file
            if GarminImpl is None:
                raise GarminConnectError(DEPENDENCY_NOT_INSTALLED_ERROR)
            fit_data = self.client.download_activity(
                activity_id,
                dl_fmt=GarminImpl.ActivityDownloadFormat.ORIGINAL,
            )
        except GarminConnectError:
            raise  # Re-raise authentication or connection errors as-is
        except Exception as exc:
            logger.error(
                "Garmin API call failed for activity %s: %s",
                activity_id,
                exc,
            )
            raise GarminConnectError(
                f"Failed to download activity {activity_id} from Garmin API: {exc}"
            ) from exc

        # Validate response
        if not fit_data:
            raise GarminConnectError(
                f"Empty response from Garmin API for activity {activity_id}"
            )

        if len(fit_data) < 2:
            raise GarminConnectError(
                f"Invalid FIT data for activity {activity_id}: "
                f"only {len(fit_data)} byte(s) received"
            )

        # Log file format details for diagnostics
        header_hex = fit_data[:32].hex() if len(fit_data) >= 32 else fit_data.hex()
        logger.info(
            "Downloaded file for activity %s: %d bytes, header (first %d bytes): %s",
            activity_id,
            len(fit_data),
            min(32, len(fit_data)),
            header_hex,
        )

        # Preprocess file: handle decompression (ZIP/gzip) and validate FIT format
        # Garmin API returns ZIP archives for ORIGINAL format, but format varies
        try:
            preprocessor = FitFilePreprocessor()
            preprocessed = preprocessor.preprocess(fit_data, f"activity_{activity_id}.fit")
            fit_data = preprocessed.content
            logger.info(
                "Successfully preprocessed FIT file for activity %s (%s, %d bytes)",
                activity_id,
                preprocessed.compression_type or "uncompressed",
                len(fit_data),
            )
        except PreprocessingError as exc:
            # Convert preprocessing error to Garmin-specific error for consistent API
            raise GarminConnectError(
                f"Failed to preprocess FIT file for activity {activity_id}: {exc}"
            ) from exc

        return fit_data
