"""OAuth token credential management."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from azure.core.exceptions import HttpResponseError

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
            logger.info("Stored Withings tokens for %s (userid: %s)", athlete_id, withings_userid)
        except HttpResponseError as e:
            logger.error("Error storing Withings tokens: %s", e)
            raise

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
            logger.warning("Error retrieving Withings tokens for %s: %s", athlete_id, e)
            return None

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
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            table_client = self.infra.get_table_client("OneDriveTokens")
            table_client.upsert_entity(entity)
            logger.info("Stored OneDrive tokens for %s", athlete_id)
        except HttpResponseError as e:
            logger.error("Error storing OneDrive tokens: %s", e)
            raise

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
            logger.warning("Error retrieving OneDrive tokens for %s: %s", athlete_id, e)
            return None

    def refresh_onedrive_token(
        self,
        athlete_id: str,
        new_access_token: str,
        new_refresh_token: str,
        expires_in: int,
        scope: Optional[str] = None,
        drive_id: Optional[str] = None,
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

        self.store_onedrive_tokens(
            athlete_id=athlete_id,
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=expires_in,
            scope=scope,
            drive_id=drive_id,
        )

    # ---- Garmin ----

    def store_garmin_tokens(
        self,
        athlete_id: str,
        oauth1_token: str,
        oauth2_token: str,
    ) -> None:
        """Store Garmin OAuth credentials."""

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": "garmin",
            "oauth1_token": oauth1_token,
            "oauth2_token": oauth2_token,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            table_client = self.infra.get_table_client("GarminTokens")
            table_client.upsert_entity(entity)
            logger.info("Stored Garmin tokens for %s", athlete_id)
        except HttpResponseError as e:
            logger.error("Error storing Garmin tokens: %s", e)
            raise

    def get_garmin_tokens(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve Garmin tokens by athlete."""
        try:
            table_client = self.infra.get_table_client("GarminTokens")
            query = f"PartitionKey eq '{athlete_id}' and RowKey eq 'garmin'"
            entities = list(table_client.query_entities(query, top=1))
            if not entities:
                return None
            return dict(entities[0])
        except HttpResponseError as e:
            logger.warning("Error retrieving Garmin tokens for %s: %s", athlete_id, e)
            return None
