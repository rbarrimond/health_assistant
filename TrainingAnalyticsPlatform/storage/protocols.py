"""Storage protocol abstractions for typed interfaces."""

from datetime import datetime
from typing import Dict, Optional, Protocol

import pandas as pd
from azure.data.tables import TableClient
from azure.storage.blob import ContainerClient

from TrainingAnalyticsPlatform.models import CanonicalRecordSet, WorkoutMetricsModel


class WorkoutStorageProtocol(Protocol):
    """Protocol for workout artifact and metadata operations."""

    def store_workout(
        self,
        athlete_id: str,
        metadata: Dict,
        *,
        workout_id: Optional[str] = None,
        ingestion_id: Optional[str] = None,
        canonical_schema_version: Optional[str] = None,
        canonical_records_blob: Optional[str] = None,
        records_count: Optional[int] = None,
        laps_count: Optional[int] = None,
    ) -> None:
        """Store a canonical workout entity to the Workouts table."""
        ...

    def record_ingestion_state(
        self,
        athlete_id: str,
        file_info: Dict,
        status: str,
        error: Optional[str] = None,
        workout_id: Optional[str] = None,
        ingestion_id: Optional[str] = None,
        ingestion_key: Optional[str] = None,
        existing_state: Optional[Dict] = None,
    ) -> None:
        """Record ingestion state for idempotency tracking."""
        ...

    def get_ingestion_state(
        self,
        athlete_id: str,
        ingestion_key: str,
    ) -> Optional[Dict]:
        """Retrieve ingestion state for a file by athlete and ingestion key."""
        ...

    def get_ingestion_context(
        self,
        athlete_id: str,
        file_info: Dict,
        workout_id: Optional[str],
        ingestion_id: Optional[str] = None,
        ingestion_key: Optional[str] = None,
    ):
        """Create an IngestionContext instance for idempotency checks."""
        ...

    def store_canonical_records(
        self,
        workout_id: str,
        records: CanonicalRecordSet,
    ) -> None:
        """Store canonical workout records to blob as parquet."""
        ...

    def load_canonical_records(self, blob_name: str) -> pd.DataFrame:
        """Load canonical workout records from blob (parquet)."""
        ...

    def store_raw_fit_json(
        self,
        workout_id: str,
        raw_fit_json: Dict,
    ) -> str:
        """Store raw FIT JSON (gzip compressed) to blob."""
        ...

    def store_fit_analysis(
        self,
        workout_id: str,
        fit_analysis: Dict,
    ) -> str:
        """Store FIT analysis JSON to blob."""
        ...

    def store_metadata_json(
        self,
        workout_id: str,
        metadata: Dict,
    ) -> str:
        """Store FIT metadata messages JSON to blob."""
        ...

    def load_metadata_json(self, workout_id: str) -> Dict:
        """Load FIT metadata messages from blob."""
        ...

    def store_laps_json(
        self,
        workout_id: str,
        laps: Dict,
    ) -> str:
        """Store lap records JSON to blob."""
        ...

    def load_laps_json(self, workout_id: str) -> Dict:
        """Load lap records from blob."""
        ...

    def upsert_metrics(
        self,
        athlete_id: str,
        metrics: WorkoutMetricsModel,
    ) -> str:
        """Store parsed workout metrics, returning the workout_id."""
        ...


class PhysiometricsStorageProtocol(Protocol):
    """Protocol for physiometrics (time-series body metrics) operations."""

    def store_physiometrics(
        self,
        athlete_id: str,
        physiometrics_data: Dict,
        effective_date: Optional[str] = None,
        data_source: str = "manual",
    ) -> str:
        """Store a physiometrics snapshot."""
        ...

    def get_physiometrics(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve the latest physiometrics config for an athlete."""
        ...

    def get_physiometrics_as_of(
        self,
        athlete_id: str,
        effective_date: str,
    ) -> Optional[Dict]:
        """Query physiometrics effective on a specific date."""
        ...

    def list_physiometrics_history(
        self,
        athlete_id: str,
        limit: int = 10,
    ) -> list:
        """List historical physiometrics (limited)."""
        ...

    def get_physiometrics_history(
        self,
        athlete_id: str,
        start_date: str,
        end_date: str,
        metrics: Optional[list] = None,
    ) -> list:
        """Query time-series physiometrics in date range."""
        ...

    def update_single_metric(
        self,
        athlete_id: str,
        metric_name: str,
        value: float,
        effective_date: Optional[str] = None,
        data_source: str = "chatgpt",
    ) -> str:
        """Update a single physiometric value."""
        ...


class OAuthTokenStorageProtocol(Protocol):
    """Protocol for OAuth token credential management."""

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
        ...

    def get_withings_tokens(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve Withings tokens by athlete."""
        ...

    def refresh_withings_token(
        self,
        athlete_id: str,
        withings_userid: str,
        new_access_token: str,
        new_refresh_token: str,
        expires_in: int,
    ) -> None:
        """Update Withings tokens after OAuth refresh."""
        ...

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
        ...

    def get_onedrive_tokens(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve OneDrive tokens by athlete."""
        ...

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
        ...

    def store_garmin_tokens(
        self,
        athlete_id: str,
        garth_token: str,
    ) -> None:
        """Store Garmin OAuth credentials."""
        ...

    def get_garmin_tokens(self, athlete_id: str) -> Optional[str]:
        """Retrieve the serialized garth token string for an athlete."""
        ...

    def set_garmin_rate_limit_blocked_until(
        self,
        athlete_id: str,
        blocked_until_utc: datetime,
    ) -> None:
        """Persist Garmin auth rate-limit cooldown end time."""
        ...

    def get_garmin_rate_limit_blocked_until(
        self,
        athlete_id: str,
    ) -> Optional[datetime]:
        """Return persisted rate-limit cooldown end time, or None if not active."""
        ...


class IngestionStorageProtocol(Protocol):
    """Protocol for ingestion state and deduplication tracking."""

    def get_ingestion_context(
        self,
        athlete_id: str,
        file_info: Dict,
        workout_id: Optional[str],
        ingestion_id: Optional[str] = None,
        ingestion_key: Optional[str] = None,
    ):
        """Create an IngestionContext instance for idempotency checks."""
        ...

    def record_ingestion_state(
        self,
        athlete_id: str,
        ingestion_key: str,
        state_entity: Dict,
    ) -> None:
        """Record ingestion state for idempotency tracking."""
        ...

    def get_ingestion_state(
        self,
        athlete_id: str,
        ingestion_key: str,
    ) -> Optional[Dict]:
        """Retrieve ingestion state for a file by athlete and ingestion key."""
        ...

    def webhook_already_processed(
        self,
        webhook_id: str,
    ) -> bool:
        """Check if Withings webhook was already processed."""
        ...

    def mark_webhook_processed(
        self,
        webhook_id: str,
        processed_at: str,
    ) -> None:
        """Record webhook as processed."""
        ...


class WebhookDeduplicationProtocol(Protocol):
    """Protocol for webhook deduplication markers."""

    def webhook_already_processed(
        self,
        athlete_id: str,
        withings_userid: str,
        enddate: str,
    ) -> bool:
        """Check if webhook was already processed."""
        ...

    def mark_webhook_processed(
        self,
        athlete_id: str,
        withings_userid: str,
        enddate: str,
    ) -> None:
        """Record webhook as processed."""
        ...


class TrainingAggregationStorageProtocol(Protocol):
    """Protocol for training aggregation operations."""

    def update_weekly_rollup(
        self,
        athlete_id: str,
        year: str,
        week: str,
        rollup_data: Dict,
    ) -> None:
        """Store or update aggregated weekly metrics."""
        ...


class StorageInfrastructureProtocol(Protocol):
    """Protocol for storage infrastructure access (shared clients)."""

    def get_table_client(self, table_name: str) -> TableClient:
        """Get a TableClient for the specified table."""
        ...

    def get_blob_client(self) -> ContainerClient:
        """Get a BlobContainerClient for workouts container."""
        ...
