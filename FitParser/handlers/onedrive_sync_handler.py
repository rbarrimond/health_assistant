"""Handle OneDrive sync requests."""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Tuple

from FitParser.handlers.ingestion_base_handler import IngestionBaseHandler
from FitParser.onedrive_sync import OneDrivePersonalSyncService

logger = logging.getLogger(__name__)


class OneDriveSyncRequest:
    """Encapsulates OneDrive sync request parsing."""

    def __init__(self, body: Dict, query_params: Dict):
        self.body = body or {}
        self.query_params = query_params or {}

    @property
    def athlete_id(self) -> str:
        """Extract athlete_id from body or query params."""
        athlete_id = self.body.get("athlete_id") or self.query_params.get("athlete_id")
        return athlete_id or "rob"

    @property
    def lookback_days(self) -> int | None:
        """Extract and validate lookback days."""
        days = self.body.get("days") or self.query_params.get("days")
        if days is None:
            return None
        try:
            return int(days)
        except (ValueError, TypeError):
            return None

    @property
    def async_mode(self) -> bool:
        """Extract async flag from body or query params."""
        async_param = self.body.get("async") or self.query_params.get("async")
        if async_param is None:
            return False
        return str(async_param).lower() in {"1", "true", "yes", "y"}


class OneDriveSyncHandler(IngestionBaseHandler):
    """Orchestrates OneDrive sync workflow."""

    def __init__(self, service: OneDrivePersonalSyncService):
        super().__init__(storage=None)
        self.service = service

    def handle(self, req: OneDriveSyncRequest) -> Tuple[Dict, int]:
        """
        Execute OneDrive sync.

        Args:
            req: Parsed sync request

        Returns:
            (response_dict, HTTP status code)
        """
        lookback_days = req.lookback_days or self.service.config.lookback_days

        if req.async_mode:
            return self._handle_async(req.athlete_id, lookback_days)

        return self._handle_sync(req.athlete_id, lookback_days)

    def _handle_sync(self, athlete_id: str, lookback_days: int) -> Tuple[Dict, int]:
        """Execute synchronous sync."""
        try:
            result = self.service.sync(
                athlete_id=athlete_id, lookback_days=lookback_days
            )
            return result, 200
        except ValueError as exc:
            logger.warning("Sync validation failed: %s", exc)
            return {"error": str(exc)}, 400
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Sync failed: %s", exc, exc_info=True)
            return {"error": "Sync failed"}, 500

    def _handle_async(self, athlete_id: str, lookback_days: int) -> Tuple[Dict, int]:
        """Queue asynchronous sync."""

        def _run_background_sync() -> None:
            try:
                result = self.service.sync(
                    athlete_id=athlete_id, lookback_days=lookback_days
                )
                logger.info("Async sync completed: %s", result)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Async sync failed: %s", exc, exc_info=True)

        threading.Thread(target=_run_background_sync, daemon=True).start()

        return {
            "status": "queued",
            "athlete_id": athlete_id,
            "lookback_days": lookback_days,
            "mode": "async",
            "queued_at_utc": datetime.now(timezone.utc).isoformat(),
        }, 202
