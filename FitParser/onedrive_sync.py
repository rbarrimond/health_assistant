"""OneDrive Personal sync service (delegated OAuth + polling)."""

from __future__ import annotations

import base64
import gzip
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from typing import Callable, Dict

from .onedrive_client import OneDriveGraphClient
from .table_storage import WorkoutTableStorage


logger = logging.getLogger(__name__)

ONEDRIVE_CLIENT_ID = "ONEDRIVE_CLIENT_ID"
ONEDRIVE_CLIENT_SECRET = "ONEDRIVE_CLIENT_SECRET"
ONEDRIVE_REDIRECT_URI = "ONEDRIVE_REDIRECT_URI"
ONEDRIVE_SCOPES = "ONEDRIVE_SCOPES"
ONEDRIVE_FOLDER_PATH = "ONEDRIVE_FOLDER_PATH"
ONEDRIVE_SYNC_LOOKBACK_DAYS = "ONEDRIVE_SYNC_LOOKBACK_DAYS"


@dataclass(frozen=True)
class OneDriveSyncConfig:
    """Configuration for OneDrive Personal sync (OAuth + folder + lookback)."""
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str
    folder_path: str
    lookback_days: int

    @classmethod
    def from_env(cls) -> "OneDriveSyncConfig":
        """Build OneDrive sync config from environment variables."""
        client_id = os.getenv(ONEDRIVE_CLIENT_ID)
        client_secret = os.getenv(ONEDRIVE_CLIENT_SECRET)
        redirect_uri = os.getenv(ONEDRIVE_REDIRECT_URI)
        scopes = os.getenv(ONEDRIVE_SCOPES, "Files.ReadWrite offline_access")
        folder_path = os.getenv(ONEDRIVE_FOLDER_PATH, "/Apps/HealthFit")

        try:
            lookback_days = max(
                1, int(os.getenv(ONEDRIVE_SYNC_LOOKBACK_DAYS, "30")))
        except ValueError:
            lookback_days = 30

        if not client_id or not client_secret or not redirect_uri:
            raise ValueError(
                "Missing OneDrive credentials. Set ONEDRIVE_CLIENT_ID, "
                "ONEDRIVE_CLIENT_SECRET, and ONEDRIVE_REDIRECT_URI."
            )

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=scopes,
            folder_path=folder_path,
            lookback_days=lookback_days,
        )


class OneDrivePersonalSyncService:
    """Service to sync OneDrive Personal folders and ingest FIT files."""

    def __init__(
        self,
        config: OneDriveSyncConfig,
        storage: WorkoutTableStorage,
        ingest_payload_fn: Callable[[Dict], tuple[Dict, int]],
    ) -> None:
        """Initialize the OneDrive sync service with configuration and storage."""
        self._config = config
        self._storage = storage
        self._ingest_payload = ingest_payload_fn
        self._client = OneDriveGraphClient(
            client_id=config.client_id,
            client_secret=config.client_secret,
            redirect_uri=config.redirect_uri,
            scopes=config.scopes,
        )

    @property
    def config(self) -> OneDriveSyncConfig:
        """Return the OneDrive sync configuration."""
        return self._config

    def build_authorize_url(self, *, state: str) -> str:
        """Build the OAuth authorization URL for OneDrive."""
        return self._client.build_authorize_url(state=state)

    def complete_authorization(self, *, athlete_id: str, code: str) -> Dict:
        """Exchange OAuth code, store tokens, and return token payload."""
        token_data = self._client.exchange_code(code)
        drive_id = self._client.get_drive_id(token_data["access_token"])
        self._storage.store_onedrive_tokens(
            athlete_id=athlete_id,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_in=int(token_data.get("expires_in", 3600)),
            scope=token_data.get("scope", ""),
            drive_id=drive_id,
        )
        return token_data

    def sync(self, *, athlete_id: str, lookback_days: int) -> Dict:
        """Sync OneDrive folder and ingest qualifying FIT files."""
        access_token = self._get_access_token(athlete_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cutoff_date = cutoff.date()
        files = self._client.list_files(
            access_token=access_token,
            folder_path=self._config.folder_path,
            modified_since=None,
            extensions={".fit", ".fit.gz"},
        )
        pre_filter_count = len(files)
        files = [
            item for item in files
            if _is_within_lookback(item, cutoff_date, cutoff)
        ]
        logger.info(
            "OneDrive filename/date filter: %s/%s within lookback_days=%s (cutoff=%s)",
            len(files),
            pre_filter_count,
            lookback_days,
            cutoff_date.isoformat(),
        )

        results = {
            "status": "success",
            "lookback_days": lookback_days,
            "folder_path": self._config.folder_path,
            "found": len(files),
            "ingested": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
            "items": [],
        }

        tokens = self._get_tokens(athlete_id)
        drive_id = tokens.get("drive_id") or None

        for item in files:
            try:
                item_meta = self._extract_item_metadata(item, drive_id)
                source_info = self._build_source_info(item, item_meta)

                context = self._storage.get_ingestion_context(
                    athlete_id,
                    source_info,
                    ingestion_key=item_meta["source_item_id"],
                )
                if context.should_skip():
                    self._record_skip_result(
                        results,
                        athlete_id,
                        source_info,
                        context=context,
                        item=item,
                    )
                    continue

                body, status_code = self._ingest_item(
                    athlete_id=athlete_id,
                    access_token=access_token,
                    item=item,
                    item_meta=item_meta,
                )
                self._record_ingest_result(results, item, body, status_code)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._record_error_result(results, item, exc)

        return results

    def _extract_item_metadata(self, item: Dict, drive_id: str | None) -> Dict:
        """Extract OneDrive fields used for ingest and state tracking."""
        parent_path = item.get("parentReference", {}).get("path", "")
        file_path = f"{parent_path}/{item['name']}" if parent_path else item["name"]
        return {
            "file_path": file_path,
            "source_item_id": f"onedrive:{item['id']}",
            "source_etag": item.get("eTag"),
            "source_ctag": item.get("cTag"),
            "source_modified_at_utc": item.get("lastModifiedDateTime"),
            "source_quickxor_hash": item.get("file", {}).get("hashes", {}).get("quickXorHash"),
            "source_drive_id": item.get("parentReference", {}).get("driveId") or drive_id,
        }

    def _build_source_info(self, item: Dict, item_meta: Dict) -> Dict:
        """Build source info metadata for ingestion state tracking."""
        return {
            "source_system": "HealthFit",
            "source_file_name": item.get("name"),
            "source_file_path": item_meta["file_path"],
            "source_item_id": item_meta["source_item_id"],
            "source_drive_id": item_meta["source_drive_id"],
            "source_etag": item_meta["source_etag"],
            "source_ctag": item_meta["source_ctag"],
            "source_quickxor_hash": item_meta["source_quickxor_hash"],
            "source_modified_at_utc": item_meta["source_modified_at_utc"],
            "file_size_bytes": item.get("size"),
        }

    def _record_skip_result(
        self,
        results: Dict,
        athlete_id: str,
        source_info: Dict,
        *,
        context,
        item: Dict,
    ) -> None:
        workout_id = (
            context.existing_state.get("workout_id")
            if context.existing_state
            else None
        )
        self._storage.record_ingestion_state(
            athlete_id,
            source_info,
            status="skipped",
            workout_id=workout_id,
            ingestion_key=context.ingestion_key,
            existing_state=context.existing_state,
        )
        results["skipped"] += 1
        results["items"].append({
            "name": item["name"],
            "id": item["id"],
            "status": "skipped",
            "message": "Unchanged content",
            "workout_id": workout_id,
        })

    def _ingest_item(
        self,
        *,
        athlete_id: str,
        access_token: str,
        item: Dict,
        item_meta: Dict,
    ) -> tuple[Dict, int]:
        raw_content = self._client.download_file(
            access_token=access_token, item_id=item["id"])
        file_name, content = _maybe_decode_gzip(item["name"], raw_content)
        payload = _build_source_payload(
            athlete_id=athlete_id,
            file_name=file_name,
            file_path=item_meta["file_path"],
            file_content=content,
            source_item_id=item_meta["source_item_id"],
            drive_id=item_meta["source_drive_id"],
            file_size_bytes=item.get("size"),
            source_etag=item_meta["source_etag"],
            source_ctag=item_meta["source_ctag"],
            source_quickxor_hash=item_meta["source_quickxor_hash"],
            source_modified_at_utc=item_meta["source_modified_at_utc"],
        )
        return self._ingest_payload(payload)

    def _record_ingest_result(
        self,
        results: Dict,
        item: Dict,
        body: Dict,
        status_code: int,
    ) -> None:
        if status_code == 200 and body.get("status") == "success":
            results["ingested"] += 1
        elif status_code == 200 and body.get("status") == "skipped":
            results["skipped"] += 1
        else:
            results["failed"] += 1
        results["items"].append({
            "name": item["name"],
            "id": item["id"],
            "status": body.get("status", "error"),
            "message": body.get("message") or body.get("error"),
            "workout_id": body.get("workout_id"),
        })

    def _record_error_result(self, results: Dict, item: Dict, exc: Exception) -> None:
        results["failed"] += 1
        results["errors"].append(str(exc))
        results["items"].append({
            "name": item.get("name"),
            "id": item.get("id"),
            "status": "error",
            "message": str(exc),
        })

    def _get_tokens(self, athlete_id: str) -> Dict:
        """Load stored OneDrive tokens for the athlete."""
        tokens = self._storage.get_onedrive_tokens(athlete_id)
        if not tokens:
            raise ValueError("No OneDrive tokens stored. Authorize first.")
        return tokens

    def _refresh_tokens(self, athlete_id: str, refresh_token: str) -> Dict:
        """Refresh access token and persist updated token values."""
        token_data = self._client.refresh_access_token(refresh_token)
        self._storage.refresh_onedrive_token(
            athlete_id=athlete_id,
            new_access_token=token_data["access_token"],
            new_refresh_token=token_data.get("refresh_token", refresh_token),
            expires_in=int(token_data.get("expires_in", 3600)),
            scope=token_data.get("scope"),
        )
        return token_data

    def _get_access_token(self, athlete_id: str) -> str:
        """Return a valid access token, refreshing if near expiry."""
        tokens = self._get_tokens(athlete_id)
        expires_at = tokens.get("expires_at_utc")
        if expires_at:
            try:
                expires_at_dt = datetime.fromisoformat(
                    expires_at.replace("Z", "+00:00")).astimezone(timezone.utc)
                if datetime.now(timezone.utc) >= (expires_at_dt - timedelta(minutes=5)):
                    token_data = self._refresh_tokens(
                        athlete_id, tokens["refresh_token"])
                    return token_data["access_token"]
            except ValueError:
                pass
        return tokens["access_token"]


def _build_source_payload(
    athlete_id: str,
    file_name: str,
    file_path: str,
    file_content: bytes,
    source_item_id: str,
    drive_id: str | None,
    file_size_bytes: int | None,
    source_etag: str | None,
    source_ctag: str | None,
    source_quickxor_hash: str | None,
    source_modified_at_utc: str | None,
) -> Dict:
    """Build the ingestion payload from a OneDrive file."""
    payload = {
        "athlete_id": athlete_id,
        "source_item_id": source_item_id,
        "source_file_name": file_name,
        "source_file_path": file_path,
        "source_system": "HealthFit",
        "file_size_bytes": file_size_bytes or len(file_content),
        "file_content_b64": base64.b64encode(file_content).decode("utf-8"),
    }
    if drive_id:
        payload["source_drive_id"] = drive_id
    if source_etag:
        payload["source_etag"] = source_etag
    if source_ctag:
        payload["source_ctag"] = source_ctag
    if source_quickxor_hash:
        payload["source_quickxor_hash"] = source_quickxor_hash
    if source_modified_at_utc:
        payload["source_modified_at_utc"] = source_modified_at_utc
    return payload


def _maybe_decode_gzip(file_name: str, content: bytes) -> tuple[str, bytes]:
    """Decode gzip content when the filename ends with .gz."""
    if file_name.lower().endswith(".gz"):
        try:
            return file_name[:-3], gzip.decompress(content)
        except (OSError, EOFError) as exc:
            raise ValueError(
                f"Failed to decompress {file_name}: {exc}") from exc
    return file_name, content


def _parse_workout_date(file_name: str) -> date | None:
    """Extract a YYYY-MM-DD date from the filename, if present."""
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", file_name)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_modified_datetime(item: Dict) -> datetime | None:
    """Parse OneDrive lastModifiedDateTime into a timezone-aware datetime."""
    raw = item.get("lastModifiedDateTime")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _is_within_lookback(item: Dict, cutoff_date: date, cutoff_dt: datetime) -> bool:
    """Determine whether a OneDrive item is within the lookback window."""
    name = item.get("name", "")
    workout_date = _parse_workout_date(name)
    if workout_date is not None:
        keep = workout_date >= cutoff_date
        logger.debug(
            "OneDrive lookback (filename): %s date=%s cutoff=%s keep=%s",
            name,
            workout_date.isoformat(),
            cutoff_date.isoformat(),
            keep,
        )
        return keep

    logger.debug("OneDrive lookback (filename): no date found in %s", name)
    modified_dt = _parse_modified_datetime(item)
    if modified_dt is not None:
        keep = modified_dt >= cutoff_dt
        logger.debug(
            "OneDrive lookback (modified): %s modified=%s cutoff=%s keep=%s",
            name,
            modified_dt.isoformat(),
            cutoff_dt.isoformat(),
            keep,
        )
        return keep

    logger.debug("OneDrive lookback (fallback): %s keep=True", name)
    return True
