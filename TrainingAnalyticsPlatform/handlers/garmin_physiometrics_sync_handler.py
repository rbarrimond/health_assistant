"""Handle Garmin physiometrics sync requests."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, Union

from TrainingAnalyticsPlatform.ingestion.wellness_adapters import (
    AdapterError,
    create_wellness_adapter,
)
from TrainingAnalyticsPlatform.integrations.garmin_client import (
    GarminConnectClient,
    GarminConnectError,
)
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.source_ingestion_state import (
    SourceIngestionStateStorage,
)
from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS = "GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS"


class GarminPhysiometricsSyncHandler:
    """Fetch and ingest daily physiometrics from Garmin summary + training status."""

    def __init__(
        self,
        storage: StorageCoordinator,
        client: Optional[GarminConnectClient] = None,
    ) -> None:
        self.storage = storage
        self.client = client or GarminConnectClient()
        self.adapter = create_wellness_adapter("garmin")
        self.ingestion_state = SourceIngestionStateStorage(storage.infrastructure)

    def handle(
        self,
        athlete_id: str,
        lookback_days: Optional[Union[int, str]] = None,
        *,
        force: bool = False,
    ) -> Tuple[Dict[str, Any], int]:
        """Fetch and store Garmin physiometrics snapshots by day."""
        if not athlete_id:
            logger.warning("Missing athlete_id for Garmin physiometrics sync")
            return {"error": "athlete_id parameter required"}, 400

        parsed_lookback = self._parse_lookback_days(lookback_days)
        if parsed_lookback is None:
            return {"error": "lookback_days must be a non-negative integer"}, 400

        start_date, end_date = self._resolve_sync_window(parsed_lookback)

        logger.info(
            "Syncing Garmin physiometrics for athlete %s from %s to %s",
            athlete_id,
            start_date.isoformat(),
            end_date.isoformat(),
        )

        auth_error = self._authenticate_client(athlete_id)
        if auth_error is not None:
            return auth_error

        stored_count = 0
        fetched_count = 0
        skipped_count = 0
        errors: list[Dict[str, Any]] = []

        stored_dates = self._prefetch_stored_dates(
            athlete_id=athlete_id,
            start_date_iso=start_date.isoformat(),
            end_date_iso=end_date.isoformat(),
            force=force,
        )

        for current_date in self._iter_dates(start_date, end_date):
            date_str = current_date.isoformat()
            if not force and date_str in stored_dates:
                skipped_count += 1
                logger.debug(
                    "Skipping previously stored Garmin physiometrics date",
                    extra={"athlete_id": athlete_id, "effective_date": date_str},
                )
                continue
            success, error, abort = self._ingest_date(athlete_id, date_str)
            if success:
                fetched_count += 1
                stored_count += 1
            if error is not None:
                errors.append(error)
            if abort:
                break

        failed_count = len(errors)
        status = 207 if failed_count > 0 else 200

        self._persist_tokens(athlete_id)

        return {
            "message": f"Synced {stored_count} Garmin physiometrics records",
            "count": stored_count,
            "records_fetched": fetched_count,
            "records_processed": stored_count,
            "records_skipped": skipped_count,
            "records_failed": failed_count,
            "errors": errors or None,
        }, status

    def _ingest_date(
        self, athlete_id: str, date_str: str
    ) -> tuple[bool, Optional[Dict[str, Any]], bool]:
        """Attempt to fetch and store one day of physiometrics.

        Returns:
            success: True when the record was stored successfully.
            error: Failure dict when an error occurred, else None.
            abort: True when the sync loop should terminate immediately.
        """
        blob_name: Optional[str] = None
        try:
            blob_name = self._process_single_day(athlete_id, date_str)
            return True, None, False
        except GarminConnectError as exc:
            issue = self._build_failure(
                date_str=date_str,
                error=str(exc),
                recoverable=self._is_recoverable_garmin_failure(exc),
                **self._classify_garmin_failure(exc),
            )
            logger.warning("Garmin physiometrics sync error: %s", issue["message"])
            self._record_blob_failure(blob_name, str(issue["message"]))
            if self._is_fatal_garmin_error(exc):
                logger.error(
                    "Garmin physiometrics sync aborted due to fatal Garmin error",
                    extra={
                        "athlete_id": athlete_id,
                        "effective_date": date_str,
                        "error": str(exc),
                    },
                )
                return False, issue, True
            return False, issue, False
        except (AdapterError, StorageError) as exc:
            issue = self._build_failure(
                date_str=date_str,
                error=str(exc),
                error_code="OPERATIONAL_ERROR",
                category=type(exc).__name__,
                recoverable=True,
            )
            logger.warning("Garmin physiometrics sync error: %s", issue["message"])
            self._record_blob_failure(blob_name, str(issue["message"]))
            return False, issue, False
        except Exception as exc:  # pylint: disable=broad-exception-caught
            issue = self._build_failure(
                date_str=date_str,
                error=f"unexpected error: {exc}",
                error_code="INTERNAL_SERVER_ERROR",
                category=type(exc).__name__,
                recoverable=False,
            )
            logger.error("Garmin physiometrics sync unexpected error", exc_info=True)
            self._record_blob_failure(blob_name, str(issue["message"]))
            return False, issue, False

    def _persist_rate_limit_cooldown(self, athlete_id: str) -> None:
        """Write the in-process rate-limit expiry to Table Storage for cross-process coordination."""
        blocked_until = self.client.rate_limited_until
        if blocked_until is None:
            return
        try:
            self.storage.oauth_tokens.set_garmin_rate_limit_blocked_until(athlete_id, blocked_until)
        except StorageError:
            logger.warning(
                "Failed to persist Garmin rate-limit cooldown to storage",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

    def _authenticate_client(self, athlete_id: str) -> Optional[Tuple[Dict[str, Any], int]]:
        """Authenticate Garmin client using stored token when possible.

        Returns an HTTP response tuple when authentication fails, else None.
        Checks and persists a shared cross-process rate-limit cooldown via Table Storage.
        """
        # Guard: honour any cross-process rate-limit cooldown before hitting Garmin.
        try:
            blocked_until = self.storage.oauth_tokens.get_garmin_rate_limit_blocked_until(athlete_id)
            if blocked_until is not None:
                logger.warning(
                    "Garmin auth rate-limited (cross-process cooldown active)",
                    extra={
                        "athlete_id": athlete_id,
                        "source_system": "garmin",
                        "blocked_until_utc": blocked_until.isoformat(),
                    },
                )
                return {
                    "error": f"Authentication rate-limited until {blocked_until.isoformat()}",
                    "error_code": "GARMIN_RATE_LIMITED",
                }, 429
        except StorageError:
            # Best-effort: proceed and let the auth attempt surface any live rate limit.
            logger.warning(
                "Could not read Garmin rate-limit cooldown from storage; proceeding with auth",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

        stored_token: Optional[str] = None
        try:
            stored_token = self.storage.oauth_tokens.get_garmin_tokens(athlete_id)
        except StorageError:
            logger.warning(
                "Failed to retrieve stored Garmin tokens; will attempt fresh login",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )

        try:
            self.client.authenticate(stored_token)
            return None
        except GarminConnectError as exc:
            if self._is_rate_limited_error(exc):
                self._persist_rate_limit_cooldown(athlete_id)
                logger.error(
                    "Garmin login rate limited for physiometrics sync",
                    extra={
                        "athlete_id": athlete_id,
                        "source_system": "garmin",
                        "error": str(exc),
                    },
                    exc_info=True,
                )
                return {
                    "error": str(exc),
                    "error_code": "GARMIN_RATE_LIMITED",
                }, 429
            logger.error(
                "Failed to authenticate with Garmin Connect for physiometrics sync",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": "GarminConnectError",
                    "error": str(exc),
                },
                exc_info=True,
            )
            return {
                "error": f"Authentication failed: {exc}",
                "error_code": "GARMIN_AUTH_ERROR",
            }, 401

    @staticmethod
    def _is_rate_limited_error(exc: GarminConnectError) -> bool:
        text = str(exc).lower()
        return "rate limit" in text or "rate limited" in text or "throttle" in text

    @classmethod
    def _is_fatal_garmin_error(cls, exc: GarminConnectError) -> bool:
        text = str(exc).lower()
        if cls._is_rate_limited_error(exc):
            return True
        fatal_markers = (
            "not authenticated",
            "authentication failed",
            "failed to restore garmin session",
            "invalid garmin credentials",
            "missing credentials",
        )
        return any(marker in text for marker in fatal_markers)

    @classmethod
    def _classify_garmin_failure(cls, exc: GarminConnectError) -> Dict[str, str]:
        if cls._is_rate_limited_error(exc):
            return {
                "error_code": "GARMIN_RATE_LIMITED",
                "category": "garmin-auth",
            }
        if cls._is_fatal_garmin_error(exc):
            return {
                "error_code": "GARMIN_AUTH_ERROR",
                "category": "garmin-auth",
            }
        return {
            "error_code": "GARMIN_UPSTREAM_ERROR",
            "category": "garmin-upstream",
        }

    @classmethod
    def _is_recoverable_garmin_failure(cls, exc: GarminConnectError) -> bool:
        return not cls._is_fatal_garmin_error(exc)

    @staticmethod
    def _build_failure(
        *,
        date_str: str,
        error: str,
        error_code: str,
        category: str,
        recoverable: bool,
    ) -> Dict[str, Any]:
        """Build unified error detail object per openapi.operations.yaml contract."""
        now_utc = datetime.now(timezone.utc)
        # Format as ISO-8601 with Z suffix: "2026-03-20T10:30:45Z"
        timestamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "error_code": error_code,
            "recoverable": recoverable,
            "message": f"{date_str}: {error}",
            "timestamp": timestamp,
        }

    def _persist_tokens(self, athlete_id: str) -> None:
        """Persist current Garmin token state for reuse in future invocations."""
        try:
            self.storage.oauth_tokens.store_garmin_tokens(
                athlete_id, self.client.dump_tokens()
            )
            logger.debug(
                "Garmin tokens persisted after physiometrics sync",
                extra={"athlete_id": athlete_id, "source_system": "garmin"},
            )
        except (GarminConnectError, StorageError) as exc:
            logger.warning(
                "Failed to persist Garmin tokens after physiometrics sync; session will not be cached",
                extra={
                    "athlete_id": athlete_id,
                    "source_system": "garmin",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

    def _prefetch_stored_dates(
        self,
        *,
        athlete_id: str,
        start_date_iso: str,
        end_date_iso: str,
        force: bool,
    ) -> set[str]:
        """Prefetch already stored effective dates for skip optimization."""
        if force:
            return set()

        try:
            existing = self.storage.physiometrics.get_physiometrics_history(
                athlete_id,
                start_date_iso,
                end_date_iso,
            )
            return {
                str(entity.get("effective_date"))
                for entity in existing
                if entity.get("effective_date")
            }
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to prefetch stored Garmin physiometrics dates; continuing without skip optimization",
                extra={
                    "athlete_id": athlete_id,
                    "effective_start": start_date_iso,
                    "effective_end": end_date_iso,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return set()

    def _parse_lookback_days(
        self,
        lookback_days: Optional[Union[int, str]],
    ) -> Optional[int]:
        """Resolve sync lookback with env fallback and validation."""
        if lookback_days is None:
            raw_value = os.getenv(GARMIN_PHYSIOMETRICS_SYNC_LOOKBACK_DAYS, "7")
        else:
            raw_value = lookback_days

        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            if lookback_days is None:
                return 7
            return None

    @staticmethod
    def _resolve_sync_window(lookback_days: int) -> tuple[date, date]:
        """Resolve physiometrics sync date window.

        Semantics:
        - lookback_days == 0 -> sync today only
        - lookback_days > 0 -> sync exactly N completed days ending yesterday
        """
        today = datetime.now(timezone.utc).date()
        if lookback_days == 0:
            return today, today

        end_date = today - timedelta(days=1)
        start_date = end_date - timedelta(days=lookback_days - 1)
        return start_date, end_date

    def _process_single_day(self, athlete_id: str, date_str: str) -> str:
        """Fetch, archive, parse, and persist one Garmin physiometrics day."""
        summary = self.client.get_user_summary(date_str)
        training_status = self.client.get_training_status(date_str)
        training_readiness, morning_training_readiness = self._fetch_training_readiness_payloads(date_str)

        blob_name = self._store_raw_payload(
            athlete_id=athlete_id,
            effective_date=date_str,
            summary=summary,
            training_status=training_status,
            training_readiness=training_readiness,
            morning_training_readiness=morning_training_readiness,
        )
        self.ingestion_state.record_blob_fetched(
            source_name="garmin",
            athlete_id=athlete_id,
            blob_name=blob_name,
        )

        parsed = self.adapter._do_parse(
            {
                "summary": summary,
                "training_status": training_status,
                "training_readiness": training_readiness,
                "morning_training_readiness": morning_training_readiness,
            }
        )
        self.adapter.validate_semantic_contract(parsed)
        snapshot = self.adapter.map_to_canonical(parsed, athlete_id)
        storage_dict = snapshot.to_storage_dict()
        storage_dict["ext_json"] = parsed.get("ext_json")

        self._log_storage_metric_presence(
            athlete_id=athlete_id,
            effective_date=snapshot.effective_date,
            storage_dict=storage_dict,
        )
        self.storage.physiometrics.store_physiometrics(
            athlete_id=athlete_id,
            physiometrics_data=storage_dict,
            effective_date=snapshot.effective_date,
            data_source="garmin",
        )
        self.ingestion_state.record_blob_processed(blob_name)
        return blob_name

    def _fetch_training_readiness_payloads(
        self,
        date_str: str,
    ) -> Tuple[
        Optional[Union[Dict[str, Any], list[Dict[str, Any]]]],
        Optional[Dict[str, Any]],
    ]:
        """Fetch Garmin readiness payloads; degrade gracefully when unavailable."""
        training_readiness: Optional[Union[Dict[str, Any], list[Dict[str, Any]]]] = None
        morning_training_readiness: Optional[Dict[str, Any]] = None

        try:
            training_readiness = self.client.get_training_readiness(date_str)
        except GarminConnectError:
            logger.warning(
                "Garmin training readiness unavailable for date",
                extra={"effective_date": date_str},
                exc_info=True,
            )

        try:
            morning_training_readiness = self.client.get_morning_training_readiness(date_str)
        except GarminConnectError:
            logger.warning(
                "Garmin morning training readiness unavailable for date",
                extra={"effective_date": date_str},
                exc_info=True,
            )

        return training_readiness, morning_training_readiness

    def _store_raw_payload(
        self,
        athlete_id: str,
        effective_date: str,
        summary: Dict[str, Any],
        training_status: Dict[str, Any],
        training_readiness: Optional[Union[Dict[str, Any], list[Dict[str, Any]]]],
        morning_training_readiness: Optional[Dict[str, Any]],
    ) -> str:
        """Persist one Garmin daily physiometrics fetch envelope to blob storage."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        blob_name = (
            f"physiometrics/{athlete_id}/garmin/daily/"
            f"{effective_date}_{timestamp}.json"
        )
        envelope = {
            "source": "garmin",
            "athlete_id": athlete_id,
            "effective_date": effective_date,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "summary": summary,
                "training_status": training_status,
                "training_readiness": training_readiness,
                "morning_training_readiness": morning_training_readiness,
            },
        }
        self.storage.infrastructure.upload_external_source_json(blob_name, envelope)
        logger.info(
            "Stored Garmin physiometrics raw payload",
            extra={
                "athlete_id": athlete_id,
                "effective_date": effective_date,
                "blob_name": blob_name,
            },
        )
        return blob_name

    def _record_blob_failure(self, blob_name: Optional[str], message: str) -> None:
        """Record Garmin blob processing failure when archival already succeeded."""
        if blob_name:
            self.ingestion_state.record_blob_failed(blob_name, message)

    @staticmethod
    def _log_storage_metric_presence(
        athlete_id: str,
        effective_date: str,
        storage_dict: Dict[str, Any],
    ) -> None:
        """Log the Garmin metrics that reached the storage boundary."""
        logger.info(
            "Prepared Garmin physiometrics storage payload",
            extra={
                "athlete_id": athlete_id,
                "effective_date": effective_date,
                "has_cycling_vo2max": storage_dict.get("cycling_vo2max_ml_kg_min") is not None,
                "has_running_vo2max": storage_dict.get("running_vo2max_ml_kg_min") is not None,
                "has_training_load": storage_dict.get("training_load") is not None,
                "has_readiness": storage_dict.get("readiness_score") is not None,
                "has_training_status_label": storage_dict.get("training_status_label") is not None,
                "has_load_focus": any(
                    storage_dict.get(k) is not None 
                    for k in ["load_focus_low_aerobic_pct", "load_focus_high_aerobic_pct", "load_focus_anaerobic_pct"]
                ),
                "has_ext_json": bool(storage_dict.get("ext_json")),
            },
        )

    @staticmethod
    def _iter_dates(start_date: date, end_date: date):
        """Yield each date in the inclusive range [start_date, end_date]."""
        current = start_date
        while current <= end_date:
            yield current
            current += timedelta(days=1)
