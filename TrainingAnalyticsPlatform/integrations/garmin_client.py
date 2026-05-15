"""Garmin Connect client using garminconnect library for authentication and FIT download."""

from __future__ import annotations

import logging
import os
import re
from base64 import b64decode
from binascii import Error as BinasciiError
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
from TrainingAnalyticsPlatform.platform.exceptions import (
    GarminConnectRateLimitError,
    PreprocessingError,
)

logger = logging.getLogger(__name__)

NOT_AUTHENTICATED_ERROR = "Not authenticated. Call login() first."
DEPENDENCY_NOT_INSTALLED_ERROR = (
    "garminconnect dependency is not installed in this environment."
)
GARMIN_AUTH_RATE_LIMIT_COOLDOWN_SECONDS = "GARMIN_AUTH_RATE_LIMIT_COOLDOWN_SECONDS"


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
        self._rate_limited_until: Optional[datetime] = None
        self._rate_limit_cooldown_seconds = self._parse_rate_limit_cooldown_seconds()

    @staticmethod
    def _parse_rate_limit_cooldown_seconds() -> int:
        raw = os.getenv(GARMIN_AUTH_RATE_LIMIT_COOLDOWN_SECONDS, "3600")
        try:
            return max(60, int(raw))
        except ValueError:
            return 3600

    @staticmethod
    def _is_rate_limited_exception(exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            isinstance(exc, GarminConnectTooManyRequestsError)
            or "429" in text
            or "rate limit" in text
            or "rate limited" in text
            or "too many requests" in text
            or "throttle" in text
        )

    def _mark_rate_limited(self) -> None:
        self._rate_limited_until = datetime.now(timezone.utc) + timedelta(
            seconds=self._rate_limit_cooldown_seconds
        )
        logger.warning(
            "Garmin auth rate limit cooldown activated",
            extra={
                "cooldown_seconds": self._rate_limit_cooldown_seconds,
                "rate_limited_until": self._rate_limited_until.isoformat(),
            },
        )

    @property
    def rate_limited_until(self) -> Optional[datetime]:
        """Expiry time of the current in-process rate-limit cooldown, or None."""
        return self._rate_limited_until

    def _enforce_rate_limit_cooldown(self) -> None:
        if self._rate_limited_until is None:
            return
        if datetime.now(timezone.utc) < self._rate_limited_until:
            raise GarminConnectRateLimitError(
                "Garmin Connect auth temporarily rate limited; "
                f"retry after {self._rate_limited_until.isoformat()}"
            )
        self._rate_limited_until = None

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
        self._enforce_rate_limit_cooldown()

        try:
            candidate_client = GarminImpl(self.email, self.password)
            candidate_client.login()
            self.client = candidate_client
            self._rate_limited_until = None
            logger.info("Successfully authenticated with Garmin Connect")
        except GarminConnectAuthenticationError as exc:
            self.client = None
            logger.exception("Garmin authentication failed")
            raise GarminConnectError("Authentication failed - check credentials") from exc
        except GarminConnectTooManyRequestsError as exc:
            self.client = None
            self._mark_rate_limited()
            logger.exception("Garmin login throttled")
            raise GarminConnectRateLimitError(
                "Garmin Connect rate limited this login attempt"
            ) from exc
        except GarminConnectConnectionError as exc:
            self.client = None
            logger.exception("Garmin connection failed")
            raise GarminConnectError("Connection to Garmin Connect failed") from exc
        except Exception as exc:
            self.client = None
            if self._is_rate_limited_exception(exc):
                self._mark_rate_limited()
                logger.exception("Garmin login throttled")
                raise GarminConnectRateLimitError(
                    "Garmin Connect rate limited this login attempt"
                ) from exc
            logger.exception("Unexpected error during Garmin login")
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
            logger.exception("Failed to list Garmin activities")
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
            logger.exception("Failed to serialize Garmin tokens")
            raise GarminConnectError("Failed to serialize Garmin tokens") from exc

    @staticmethod
    def _normalize_stored_token(garth_token: str) -> str:
        """Normalize persisted token strings before handing them to garminconnect."""
        token = garth_token.strip()
        if not token:
            raise GarminConnectError("Stored Garmin token is empty")

        if (token.startswith("b'") and token.endswith("'")) or (
            token.startswith('b"') and token.endswith('"')
        ):
            token = token[2:-1]
        elif (token.startswith("'") and token.endswith("'")) or (
            token.startswith('"') and token.endswith('"')
        ):
            token = token[1:-1]

        token = re.sub(r"\s+", "", token)
        token_base = token.rstrip("=")
        remainder = len(token_base) % 4
        if remainder == 1:
            raise GarminConnectError("Stored Garmin token is invalid base64")
        token = token_base + ("=" * (4 - remainder) if remainder else "")

        try:
            b64decode(token, validate=True)
        except BinasciiError as exc:
            raise GarminConnectError("Stored Garmin token is invalid base64") from exc

        return token

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
        self._enforce_rate_limit_cooldown()
        try:
            normalized_token = self._normalize_stored_token(garth_token)
            candidate_client = GarminImpl()
            candidate_client.login(tokenstore=normalized_token)
            self.client = candidate_client
            self._rate_limited_until = None
            logger.info("Restored Garmin session from stored tokens")
        except Exception as exc:
            self.client = None
            if self._is_rate_limited_exception(exc):
                self._mark_rate_limited()
                logger.warning("Garmin token restore throttled: %s", exc)
                raise GarminConnectRateLimitError(
                    "Garmin Connect rate limited this token restore attempt"
                ) from exc
            logger.warning("Failed to restore Garmin session from stored tokens: %s", exc)
            raise GarminConnectError(
                f"Failed to restore Garmin session from stored tokens: {exc}"
            ) from exc

    def authenticate(self, stored_token: Optional[str] = None) -> None:
        """Authenticate using stored token if provided, falling back to fresh login.

        Mirrors the ``init_api()`` pattern from the garminconnect library example:
        try to resume from a previous session via token restore; if that fails (or
        if no token is available), perform a full credential-based login.

        If a session is already established in this process (``self.client`` is not
        ``None``), the call is a no-op: garth refreshes the OAuth2 access token
        transparently on each API call, so re-authenticating every invocation only
        adds unnecessary round-trips to Garmin's auth endpoint and raises the risk
        of 429 throttling in multi-instance deployments.

        Args:
            stored_token: Base64 garth token string produced by ``dump_tokens()``,
                or ``None`` to skip token restore and go straight to login.

        Raises:
            GarminConnectError: If both token restore (when attempted) and fresh
                login fail.
        """
        if self.client is not None:
            logger.debug("Garmin session already active in this process; skipping re-authentication")
            return
        if stored_token:
            try:
                self.restore_from_tokens(stored_token)
                return
            except GarminConnectRateLimitError:
                logger.warning("Stored Garmin token restore rate limited; skipping fresh login")
                raise
            except GarminConnectError:
                logger.warning("Stored Garmin tokens invalid; falling back to fresh login")
        self.login()

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
            logger.exception("Failed to fetch Garmin user summary for %s", date_str)
            raise GarminConnectError(
                f"Failed to fetch Garmin user summary: {exc}"
            ) from exc

    def get_training_status(self, date_str: str) -> Dict[str, Any]:
        """Fetch Garmin training status for a specific date (YYYY-MM-DD)."""
        client = self._ensure_authenticated_client()
        try:
            return cast(Dict[str, Any], client.get_training_status(date_str))
        except Exception as exc:
            logger.exception("Failed to fetch Garmin training status for %s", date_str)
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
            logger.exception("Failed to fetch Garmin training readiness for %s", date_str)
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
            logger.exception(
                "Failed to fetch Garmin morning training readiness for %s",
                date_str,
            )
            raise GarminConnectError(
                f"Failed to fetch Garmin morning training readiness: {exc}"
            ) from exc

    def get_cycling_ftp(self) -> Optional[Dict[str, Any]]:
        """Fetch Garmin's latest cycling FTP payload."""
        client = self._ensure_authenticated_client()
        try:
            value = client.get_cycling_ftp()
            if value is None:
                return None
            if isinstance(value, list):
                first = value[0] if value else None
                return cast(Optional[Dict[str, Any]], first if isinstance(first, dict) else None)
            if isinstance(value, dict):
                return cast(Dict[str, Any], value)
            logger.warning(
                "Unexpected Garmin cycling FTP payload type",
                extra={"payload_type": type(value).__name__},
            )
            return None
        except Exception as exc:
            logger.exception("Failed to fetch Garmin cycling FTP")
            raise GarminConnectError(f"Failed to fetch Garmin cycling FTP: {exc}") from exc

    def get_lactate_threshold(self) -> Optional[Dict[str, Any]]:
        """Fetch Garmin's latest lactate-threshold payload."""
        client = self._ensure_authenticated_client()
        try:
            value = client.get_lactate_threshold()
            if value is None:
                return None
            if isinstance(value, dict):
                return cast(Dict[str, Any], value)
            logger.warning(
                "Unexpected Garmin lactate-threshold payload type",
                extra={"payload_type": type(value).__name__},
            )
            return None
        except Exception as exc:
            logger.exception("Failed to fetch Garmin lactate threshold")
            raise GarminConnectError(f"Failed to fetch Garmin lactate threshold: {exc}") from exc

    def get_recovery_metrics(self, date_str: str) -> Optional[Dict[str, Any]]:
        """Fetch Garmin recovery metrics for a specific date.
        
        Recovery metrics often include lactate threshold HR, recovery time,
        recovery heart rate, and other baseline HR information.
        
        Args:
            date_str: Date in YYYY-MM-DD format
            
        Returns:
            Recovery metrics dict or None if unavailable
            
        Raises:
            GarminConnectError: If fetch fails
        """
        client = self._ensure_authenticated_client()
        try:
            value = client.get_recovery_metrics(date_str)  # type: ignore[attr-defined]
            if value is None:
                return None
            if isinstance(value, dict):
                return cast(Dict[str, Any], value)
            if isinstance(value, list):
                # Some endpoints return lists; take first element if present
                first = value[0] if value else None
                return cast(Optional[Dict[str, Any]], first if isinstance(first, dict) else None)
            logger.warning(
                "Unexpected Garmin recovery metrics payload type",
                extra={"payload_type": type(value).__name__, "date": date_str},
            )
            return None
        except Exception as exc:
            logger.debug(
                "Failed to fetch Garmin recovery metrics for %s: %s",
                date_str,
                exc,
            )
            # Don't raise; recovery metrics are optional
            return None

    def get_wellness(self, date_str: str) -> Optional[Dict[str, Any]]:
        """Fetch Garmin wellness metrics for a specific date.
        
        Wellness data includes daily HR metrics, activity level, sleep,
        and other baseline measurements.
        
        Args:
            date_str: Date in YYYY-MM-DD format
            
        Returns:
            Wellness dict or None if unavailable
            
        Raises:
            GarminConnectError: If fetch fails
        """
        client = self._ensure_authenticated_client()
        try:
            value = client.get_wellness(date_str)  # type: ignore[attr-defined]
            if value is None:
                return None
            if isinstance(value, dict):
                return cast(Dict[str, Any], value)
            if isinstance(value, list):
                first = value[0] if value else None
                return cast(Optional[Dict[str, Any]], first if isinstance(first, dict) else None)
            logger.warning(
                "Unexpected Garmin wellness payload type",
                extra={"payload_type": type(value).__name__, "date": date_str},
            )
            return None
        except Exception as exc:
            logger.debug(
                "Failed to fetch Garmin wellness for %s: %s",
                date_str,
                exc,
            )
            return None

    def get_heart_rate_variability(self, date_str: str) -> Optional[Dict[str, Any]]:
        """Fetch Garmin heart rate variability (HRV) data for a specific date.
        
        HRV data includes resting heart rate, HRV values, and other HR baselines.
        
        Args:
            date_str: Date in YYYY-MM-DD format
            
        Returns:
            HRV dict or None if unavailable
            
        Raises:
            GarminConnectError: If fetch fails
        """
        client = self._ensure_authenticated_client()
        try:
            # Try the direct HRV endpoint first
            value = client.get_heart_rate_variability(date_str)  # type: ignore[attr-defined]
            if value is None:
                return None
            if isinstance(value, dict):
                return cast(Dict[str, Any], value)
            if isinstance(value, list):
                first = value[0] if value else None
                return cast(Optional[Dict[str, Any]], first if isinstance(first, dict) else None)
            logger.warning(
                "Unexpected Garmin HRV payload type",
                extra={"payload_type": type(value).__name__, "date": date_str},
            )
            return None
        except Exception as exc:
            logger.debug(
                "Failed to fetch Garmin HRV for %s: %s",
                date_str,
                exc,
            )
            return None

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
            logger.exception("Garmin API call failed for activity %s", activity_id)
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
