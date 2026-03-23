"""Storage abstraction for Garmin activity index table operations."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.garmin_activity_index import (
    GARMIN_ACTIVITY_INDEX_TABLE,
    GarminActivityIndexEntity,
)
from TrainingAnalyticsPlatform.storage.protocols import StorageInfrastructureProtocol

logger = logging.getLogger(__name__)


class GarminActivityIndexStorage:
    """Persist and query Garmin activity list index rows."""

    def __init__(self, infrastructure: StorageInfrastructureProtocol):
        self._infra = infrastructure

    def upsert_activity_payload(
        self,
        *,
        athlete_id: str,
        activity_payload: Dict[str, Any],
        listed_at_utc: Optional[datetime] = None,
    ) -> None:
        """Upsert a single Garmin list payload row into index storage."""
        try:
            entity = GarminActivityIndexEntity.from_activity_payload(
                athlete_id=athlete_id,
                activity_payload=activity_payload,
                listed_at_utc=listed_at_utc,
            )
            table_client = self._infra.get_table_client(GARMIN_ACTIVITY_INDEX_TABLE)
            table_client.upsert_entity(entity.to_table_entity(), mode="merge")
        except (HttpResponseError, ValueError) as exc:
            logger.error(
                "Failed upserting Garmin activity index row",
                extra={"athlete_id": athlete_id},
                exc_info=True,
            )
            raise StorageError("Failed upserting Garmin activity index row") from exc

    def query_activity_payloads_by_lookback(
        self,
        *,
        athlete_id: str,
        lookback_days: int,
        now_utc: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Query raw Garmin activity payloads in lookback window."""
        window_days = max(1, lookback_days)
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = now - timedelta(days=window_days)

        lower_row_key = f"{start.strftime('%Y%m%dT%H%M%SZ')}|"
        upper_row_key = f"{now.strftime('%Y%m%dT%H%M%SZ')}|~"
        filter_query = (
            "PartitionKey eq @pk and RowKey ge @lower and RowKey le @upper"
        )
        parameters = {
            "pk": athlete_id,
            "lower": lower_row_key,
            "upper": upper_row_key,
        }

        try:
            table_client = self._infra.get_table_client(GARMIN_ACTIVITY_INDEX_TABLE)
            entities = list(
                table_client.query_entities(
                    query_filter=filter_query,
                    parameters=parameters,
                )
            )
            payloads: List[Dict[str, Any]] = []
            for entity in entities:
                raw_payload = entity.get("raw_activity_payload_json")
                if not raw_payload:
                    continue
                payloads.append(json.loads(raw_payload))
            return payloads
        except (HttpResponseError, json.JSONDecodeError) as exc:
            logger.error(
                "Failed querying Garmin activity index lookback window",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": window_days,
                },
                exc_info=True,
            )
            raise StorageError("Failed querying Garmin activity index lookback window") from exc

    def get_latest_indexed_start_time_utc(
        self,
        *,
        athlete_id: str,
    ) -> Optional[str]:
        """Return the most recent indexed Garmin activity start timestamp."""
        filter_query = "PartitionKey eq @pk"
        parameters = {"pk": athlete_id}

        try:
            table_client = self._infra.get_table_client(GARMIN_ACTIVITY_INDEX_TABLE)
            entities = list(
                table_client.query_entities(
                    query_filter=filter_query,
                    parameters=parameters,
                    select=["source_start_time_utc"],
                )
            )
            if not entities:
                return None

            latest_entity = max(
                entities,
                key=lambda item: str(item.get("source_start_time_utc", "")),
            )
            latest_value = latest_entity.get("source_start_time_utc")
            return str(latest_value) if latest_value else None
        except HttpResponseError as exc:
            logger.error(
                "Failed reading latest Garmin activity index timestamp",
                extra={"athlete_id": athlete_id},
                exc_info=True,
            )
            raise StorageError("Failed reading latest Garmin activity index timestamp") from exc

    def get_indexed_day_coverage(
        self,
        *,
        athlete_id: str,
        lookback_days: int,
        now_utc: Optional[datetime] = None,
    ) -> Set[str]:
        """Return set of UTC dates (YYYY-MM-DD) covered by indexed rows."""
        window_days = max(1, lookback_days)
        now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = now - timedelta(days=window_days)

        lower_row_key = f"{start.strftime('%Y%m%dT%H%M%SZ')}|"
        upper_row_key = f"{now.strftime('%Y%m%dT%H%M%SZ')}|~"
        filter_query = (
            "PartitionKey eq @pk and RowKey ge @lower and RowKey le @upper"
        )
        parameters = {
            "pk": athlete_id,
            "lower": lower_row_key,
            "upper": upper_row_key,
        }

        try:
            table_client = self._infra.get_table_client(GARMIN_ACTIVITY_INDEX_TABLE)
            entities = list(
                table_client.query_entities(
                    query_filter=filter_query,
                    parameters=parameters,
                    select=["source_start_time_utc"],
                )
            )
            covered_days: Set[str] = set()
            for entity in entities:
                source_start_time_utc = entity.get("source_start_time_utc")
                if not source_start_time_utc:
                    continue
                covered_days.add(str(source_start_time_utc)[:10])
            return covered_days
        except HttpResponseError as exc:
            logger.error(
                "Failed reading Garmin activity index day coverage",
                extra={
                    "athlete_id": athlete_id,
                    "lookback_days": window_days,
                },
                exc_info=True,
            )
            raise StorageError("Failed reading Garmin activity index day coverage") from exc