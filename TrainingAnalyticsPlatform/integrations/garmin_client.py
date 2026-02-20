"""Garmin Connect client using garminconnect library for authentication and FIT download."""

from __future__ import annotations

import gzip
import io
import logging
import os
import zipfile
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast

try:
    from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError
except ImportError:  # pragma: no cover - optional dependency in test/runtime variants
    Garmin = None  # type: ignore[assignment]

    class GarminConnectAuthenticationError(Exception):
        """Fallback authentication exception when garminconnect is unavailable."""

    class GarminConnectConnectionError(Exception):
        """Fallback connection exception when garminconnect is unavailable."""

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
        if Garmin is None:
            raise GarminConnectError(
                "garminconnect dependency is not installed in this environment."
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

    def _extract_fit_from_zip(self, zip_data: bytes, activity_id: str) -> bytes:
        """Extract FIT file from ZIP archive.
        
        Garmin's API returns ZIP files for ORIGINAL format downloads.
        However, the actual format varies - sometimes it's a standard ZIP,
        sometimes it's just a raw FIT file despite the API documentation.
        
        Args:
            zip_data: ZIP file bytes (or potentially raw FIT)
            activity_id: Garmin activity ID (for error messages)
            
        Returns:
            Extracted FIT file bytes
            
        Raises:
            GarminConnectError: If extraction fails
        """
        logger.info(
            "Attempting ZIP extraction for activity %s (%d bytes)",
            activity_id,
            len(zip_data),
        )
        try:
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_file:
                # Find .fit file in the archive
                fit_files = [name for name in zip_file.namelist() if name.lower().endswith('.fit')]
                if not fit_files:
                    raise GarminConnectError(
                        f"No .fit file found in ZIP archive for activity {activity_id}. "
                        f"Archive contains: {', '.join(zip_file.namelist())}"
                    )
                if len(fit_files) > 1:
                    logger.warning(
                        "Multiple FIT files in archive for activity %s: %s. Using first file.",
                        activity_id,
                        fit_files,
                    )
                fit_filename = fit_files[0]
                fit_data = zip_file.read(fit_filename)
                logger.info(
                    "Successfully extracted %s from ZIP archive (%d bytes)",
                    fit_filename,
                    len(fit_data),
                )
                return fit_data
        except zipfile.BadZipFile as zip_exc:
            # ZIP extraction failed - this might actually be raw FIT data
            # mislabeled by Garmin's API
            logger.warning(
                "ZIP extraction failed for activity %s: %s. "
                "File might be raw FIT data despite API format.",
                activity_id,
                zip_exc,
            )
            # Return original data - let caller validate if it's a valid FIT file
            return zip_data

    def _decompress_gzip(self, gzip_data: bytes, activity_id: str) -> bytes:
        """Decompress gzipped FIT file.
        
        Args:
            gzip_data: Gzipped file bytes
            activity_id: Garmin activity ID (for error messages)
            
        Returns:
            Decompressed FIT file bytes
            
        Raises:
            GarminConnectError: If decompression fails
        """
        compressed_size = len(gzip_data)
        logger.info(
            "Decompressing gzipped FIT file for activity %s (%d compressed bytes)",
            activity_id,
            compressed_size,
        )
        try:
            fit_data = gzip.decompress(gzip_data)
            decompressed_size = len(fit_data)
            logger.info(
                "Successfully decompressed to %d bytes (%.1fx compression ratio)",
                decompressed_size,
                compressed_size / decompressed_size if decompressed_size > 0 else 0,
            )
            return fit_data
        except OSError as gzip_exc:
            # Catches BadGzipFile, EOFError, and other decompression errors
            logger.error(
                "Gzip decompression failed for activity %s: %s",
                activity_id,
                gzip_exc,
            )
            raise GarminConnectError(
                f"Downloaded file for activity {activity_id} appears to be corrupted "
                f"(gzip decompression failed: {gzip_exc})"
            ) from gzip_exc

    def _validate_fit_format(self, fit_data: bytes, activity_id: str) -> None:
        """Validate FIT file format.
        
        Args:
            fit_data: FIT file bytes to validate
            activity_id: Garmin activity ID (for error messages)
            
        Raises:
            GarminConnectError: If validation fails
        """
        if not fit_data:
            raise GarminConnectError(
                f"FIT file for activity {activity_id} is empty"
            )

        # FIT files start with 14-byte header
        if len(fit_data) < 14:
            raise GarminConnectError(
                f"Invalid FIT file for activity {activity_id}: "
                f"file too small ({len(fit_data)} bytes, minimum 14 bytes required)"
            )

        # Check for FIT file signature ".FIT" at bytes 8-11
        if fit_data[8:12] != b'.FIT':
            header_hex = fit_data[:16].hex()
            logger.error(
                "Invalid FIT file format for activity %s. Expected '.FIT' at bytes 8-11, got %r. "
                "First 16 bytes (hex): %s",
                activity_id,
                fit_data[8:12],
                header_hex,
            )
            raise GarminConnectError(
                f"Downloaded file for activity {activity_id} is not a valid FIT file. "
                f"Expected '.FIT' signature at offset 8-11, but got {fit_data[8:12]!r}. "
                f"First 16 bytes (hex): {header_hex}. "
                f"This may indicate a format issue with the Garmin API response."
            )

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
            raise GarminConnectError("Not authenticated. Call login() first.")

        try:
            # Use ORIGINAL format to get the FIT file
            fit_data = self.client.download_activity(
                activity_id,
                dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL,
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

        # According to garminconnect library docs: "For 'Original' will return the zip
        # file content, up to user to extract it." However, in practice the format varies.
        # Try extraction methods in order of likelihood:

        # 1. Always try ZIP extraction first (API docs say it returns ZIP for ORIGINAL)
        # Note: _extract_fit_from_zip returns original data on BadZipFile, so we check
        # if extraction actually occurred by comparing data identity
        extracted_data = self._extract_fit_from_zip(fit_data, activity_id)
        if extracted_data != fit_data:  # ZIP extraction succeeded
            fit_data = extracted_data
            logger.info("Successfully extracted FIT from ZIP for activity %s", activity_id)

        # 2. Check if data is gzipped
        if fit_data[:2] == b'\x1f\x8b':  # gzip magic number
            logger.info("Detected gzip compression for activity %s, decompressing", activity_id)
            fit_data = self._decompress_gzip(fit_data, activity_id)

        # 3. Validate final FIT file format
        self._validate_fit_format(fit_data, activity_id)

        logger.info(
            "Successfully processed FIT file for activity %s (%d bytes after processing)",
            activity_id,
            len(fit_data),
        )
        return fit_data
