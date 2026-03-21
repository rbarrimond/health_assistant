"""OAuth token credential management."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)


class OAuthTokenStorage:
    """Handle OAuth token storage for Withings, OneDrive, and Garmin."""

    def __init__(self, infrastructure: StorageInfrastructure):
        """Initialize with storage infrastructure."""
        self.infra = infrastructure

    # ---- Withings ----

    def store_withings_tokens(
        self,
        athlete_id: str,
        withings_userid: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        scope: str,
    ) -> None:
        """Store Withings OAuth credentials."""

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": withings_userid,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at_utc": expires_at.isoformat(),
            "scope": scope,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            table_client = self.infra.get_table_client("WithingsTokens")
            table_client.upsert_entity(entity)
            logger.info(
                "Stored Withings tokens",
                extra={
                    "athlete_id": athlete_id,
                    "withings_userid": withings_userid,
                    "source_system": "withings",
                },
            )
        except HttpResponseError as e:
            logger.error(
                "Error storing Withings tokens",
                extra={
                    "athlete_id": athlete_id,
                    "withings_userid": withings_userid,
                    "source_system": "withings",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to store Withings tokens") from e

    def get_withings_tokens(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve Withings tokens by athlete."""
        try:
            table_client = self.infra.get_table_client("WithingsTokens")
            query = f"PartitionKey eq '{athlete_id}'"
            entities = list(table_client.query_entities(query, top=1))

            if not entities:
                return None

            return dict(entities[0])

        except HttpResponseError as e:
            logger.error(
                "Error retrieving Withings tokens",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "withings",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve Withings tokens") from e

    def refresh_withings_token(
        self,
        athlete_id: str,
        withings_userid: str,
        new_access_token: str,
        new_refresh_token: str,
        expires_in: int,
    ) -> None:
        """Update Withings tokens after OAuth refresh."""
        existing = self.get_withings_tokens(athlete_id)
        scope = (
            str(existing.get("scope"))
            if existing and existing.get("scope")
            else "user.metrics,user.info"
        )

        self.store_withings_tokens(
            athlete_id=athlete_id,
            withings_userid=withings_userid,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            scope=scope,
        )

    # ---- OneDrive ----

    def store_onedrive_tokens(
        self,
        athlete_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        scope: str,
        drive_id: Optional[str] = None,
        delta_token: Optional[str] = None,
        last_delta_sync_at_utc: Optional[str] = None,
        delta_sync_state: str = "initial",
    ) -> None:
        """Store OneDrive OAuth credentials."""

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        entity = {
            "PartitionKey": athlete_id,
            "RowKey": "onedrive",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at_utc": expires_at.isoformat(),
            "scope": scope,
            "drive_id": drive_id or "",
            "delta_token": delta_token or "",
            "last_delta_sync_at_utc": last_delta_sync_at_utc or "",
            "delta_sync_state": delta_sync_state,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            table_client = self.infra.get_table_client("OneDriveTokens")
            table_client.upsert_entity(entity)
            logger.info(
                "Stored OneDrive tokens",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                },
            )
        except HttpResponseError as e:
            logger.error(
                "Error storing OneDrive tokens",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to store OneDrive tokens") from e

    def get_onedrive_tokens(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve OneDrive tokens by athlete."""
        try:
            table_client = self.infra.get_table_client("OneDriveTokens")
            query = f"PartitionKey eq '{athlete_id}' and RowKey eq 'onedrive'"
            entities = list(table_client.query_entities(query, top=1))
            if not entities:
                return None
            return dict(entities[0])
        except HttpResponseError as e:
            logger.error(
                "Error retrieving OneDrive tokens",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve OneDrive tokens") from e

    def refresh_onedrive_token(
        self,
        athlete_id: str,
        new_access_token: str,
        new_refresh_token: str,
        expires_in: int,
        scope: Optional[str] = None,
        drive_id: Optional[str] = None,
        delta_token: Optional[str] = None,
        last_delta_sync_at_utc: Optional[str] = None,
        delta_sync_state: Optional[str] = None,
    ) -> None:
        """Update OneDrive tokens after OAuth refresh."""
        existing = self.get_onedrive_tokens(athlete_id)
        scope = scope or (
            str(existing.get("scope"))
            if existing and existing.get("scope")
            else "Files.ReadWrite offline_access"
        )
        drive_id = drive_id or (
            existing.get("drive_id") if existing and existing.get("drive_id") else None
        )
        delta_token = self._existing_or_incoming(
            existing,
            incoming=delta_token,
            field_name="delta_token",
        )
        last_delta_sync_at_utc = self._existing_or_incoming(
            existing,
            incoming=last_delta_sync_at_utc,
            field_name="last_delta_sync_at_utc",
        )
        delta_sync_state = (
            self._existing_or_incoming(
                existing,
                incoming=delta_sync_state,
                field_name="delta_sync_state",
            )
            or "initial"
        )

        self.store_onedrive_tokens(
            athlete_id=athlete_id,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            scope=scope,
            drive_id=drive_id,
            delta_token=delta_token,
            last_delta_sync_at_utc=last_delta_sync_at_utc,
            delta_sync_state=delta_sync_state,
        )

    @staticmethod
    def _existing_or_incoming(
        existing: Optional[Dict],
        *,
        incoming: Optional[str],
        field_name: str,
    ) -> Optional[str]:
        """Return incoming value when provided, otherwise existing value."""
        if incoming is not None:
            return incoming
        if existing and existing.get(field_name):
            return str(existing.get(field_name))
        return None

    def update_onedrive_delta_state(
        self,
        athlete_id: str,
        *,
        delta_token: str,
        delta_sync_state: str = "active",
    ) -> None:
        """Persist OneDrive delta token state for incremental sync."""
        entity = {
            "PartitionKey": athlete_id,
            "RowKey": "onedrive",
            "delta_token": delta_token,
            "last_delta_sync_at_utc": datetime.now(timezone.utc).isoformat(),
            "delta_sync_state": delta_sync_state,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            table_client = self.infra.get_table_client("OneDriveTokens")
            table_client.upsert_entity(entity)
            logger.info(
                "Updated OneDrive delta state",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "delta_sync_state": delta_sync_state,
                },
            )
        except HttpResponseError as e:
            logger.error(
                "Error updating OneDrive delta state",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to update OneDrive delta state") from e

    def reset_onedrive_delta_state(self, athlete_id: str) -> bool:
        """Reset OneDrive delta state for a single athlete.

        Returns:
            True if an existing token row was reset, False if no row exists.
        """
        existing = self.get_onedrive_tokens(athlete_id)
        if not existing:
            logger.info(
                "Skipped OneDrive delta reset; no token row found",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "operation": "delta_reset",
                    "scope": "single",
                    "reset_applied": False,
                },
            )
            return False

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": "onedrive",
            "delta_token": "",
            "last_delta_sync_at_utc": "",
            "delta_sync_state": "initial",
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            table_client = self.infra.get_table_client("OneDriveTokens")
            table_client.upsert_entity(entity)
            logger.info(
                "Reset OneDrive delta state",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "operation": "delta_reset",
                    "scope": "single",
                    "reset_applied": True,
                },
            )
            return True
        except HttpResponseError as e:
            logger.error(
                "Error resetting OneDrive delta state",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "onedrive",
                    "operation": "delta_reset",
                    "scope": "single",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to reset OneDrive delta state") from e

    def reset_all_onedrive_delta_states(self) -> int:
        """Reset OneDrive delta state for all athlete token rows.

        Returns:
            Number of athlete token rows reset.
        """
        try:
            table_client = self.infra.get_table_client("OneDriveTokens")
            query = "RowKey eq 'onedrive'"
            entities = list(table_client.query_entities(query))

            reset_count = 0
            for entity in entities:
                athlete_id = str(entity.get("PartitionKey", ""))
                if not athlete_id:
                    continue

                reset_entity = {
                    "PartitionKey": athlete_id,
                    "RowKey": "onedrive",
                    "delta_token": "",
                    "last_delta_sync_at_utc": "",
                    "delta_sync_state": "initial",
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                table_client.upsert_entity(reset_entity)
                reset_count += 1

            logger.info(
                "Reset OneDrive delta state for all athletes",
                extra={
                    "source_system": "onedrive",
                    "operation": "delta_reset",
                    "scope": "bulk",
                    "reset_count": reset_count,
                },
            )
            return reset_count
        except HttpResponseError as e:
            logger.error(
                "Error resetting OneDrive delta state for all athletes",
                extra={
                    "source_system": "onedrive",
                    "operation": "delta_reset",
                    "scope": "bulk",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to reset all OneDrive delta states") from e

    # ---- Garmin ----

    def store_garmin_tokens(
        self,
        athlete_id: str,
        garth_token: str,
    ) -> None:
        """Store Garmin OAuth credentials."""

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": "garmin",
            "garth_token": garth_token,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            table_client = self.infra.get_table_client("GarminTokens")
            table_client.upsert_entity(entity)
            logger.info(
                "Stored Garmin tokens",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                },
            )
        except HttpResponseError as e:
            logger.error(
                "Error storing Garmin tokens",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to store Garmin tokens") from e

    def get_garmin_tokens(self, athlete_id: str) -> Optional[str]:
        """Retrieve the serialized garth token string for an athlete.

        Returns None if no token is stored or the stored entity pre-dates the
        garth_token schema (legacy two-column records are silently ignored).
        """
        try:
            table_client = self.infra.get_table_client("GarminTokens")
            query = f"PartitionKey eq '{athlete_id}' and RowKey eq 'garmin'"
            entities = list(table_client.query_entities(query, top=1))
            if not entities:
                return None
            token_value = entities[0].get("garth_token")
            if not token_value:
                return None
            return str(token_value)
        except HttpResponseError as e:
            logger.error(
                "Error retrieving Garmin tokens",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve Garmin tokens") from e

    def set_garmin_rate_limit_blocked_until(
        self,
        athlete_id: str,
        blocked_until_utc: datetime,
    ) -> None:
        """Persist Garmin auth rate-limit cooldown end time to the GarminTokens table.

        Uses a merge upsert so the garth_token column is left untouched.
        """
        entity = {
            "PartitionKey": athlete_id,
            "RowKey": "garmin",
            "rate_limit_blocked_until_utc": blocked_until_utc.isoformat(),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        try:
            table_client = self.infra.get_table_client("GarminTokens")
            table_client.upsert_entity(entity)
            logger.info(
                "Persisted Garmin auth rate-limit cooldown",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "blocked_until_utc": blocked_until_utc.isoformat(),
                },
            )
        except HttpResponseError as e:
            logger.error(
                "Error persisting Garmin rate-limit cooldown",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to persist Garmin rate-limit cooldown") from e

    def get_garmin_rate_limit_blocked_until(
        self,
        athlete_id: str,
    ) -> Optional[datetime]:
        """Return the persisted Garmin rate-limit cooldown end time, or None.

        Returns None if no cooldown row exists or the stored timestamp has already
        passed (expired cooldowns are treated as absent).
        """
        try:
            table_client = self.infra.get_table_client("GarminTokens")
            query = f"PartitionKey eq '{athlete_id}' and RowKey eq 'garmin'"
            entities = list(table_client.query_entities(query, top=1))
            if not entities:
                return None
            raw = entities[0].get("rate_limit_blocked_until_utc")
            if not raw:
                return None
            blocked_until = datetime.fromisoformat(str(raw))
            if datetime.now(timezone.utc) >= blocked_until:
                return None
            return blocked_until
        except HttpResponseError as e:
            logger.error(
                "Error retrieving Garmin rate-limit cooldown",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve Garmin rate-limit cooldown") from e
