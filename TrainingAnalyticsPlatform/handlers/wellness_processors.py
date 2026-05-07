"""Processors for canonicalizing wellness source blobs.

Stateless processors read source blobs, validate, map to canonical models,
and upsert table storage. Similar to FitIngestionBaseHandler pattern.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union

from TrainingAnalyticsPlatform.ingestion.wellness_adapters import (
    create_wellness_adapter,
)
from TrainingAnalyticsPlatform.models.wellness import (
    PhysiometricsSnapshot,
    TrainingStateSnapshot,
)
from TrainingAnalyticsPlatform.storage.protocols import StorageInfrastructureProtocol
from TrainingAnalyticsPlatform.storage.source_ingestion_state import (
    SourceIngestionStateStorage,
)

logger = logging.getLogger(__name__)


class BaseWellnessProcessor(ABC):
    """Abstract base for wellness source processors."""

    def __init__(
        self,
        source_name: str,
        table_storage: StorageInfrastructureProtocol,
        ingestion_state: SourceIngestionStateStorage,
    ):
        """Initialize processor.

        Args:
            source_name: Source identifier (garmin, withings, intervals)
            table_storage: Table storage client
            ingestion_state: SourceIngestionState storage
        """
        self.source_name = source_name
        self.table_storage = table_storage
        self.ingestion_state = ingestion_state

    def process(self, blob_name: str, raw_data: Dict[str, Any]) -> None:
        """Orchestrate: deserialize → dedup → validate → map → upsert.

        Args:
            blob_name: Blob name (for audit trail)
            raw_data: Raw API response data

        Raises:
            Exception: If processing fails (will be caught by caller)
        """
        try:
            # Create adapter
            adapter = create_wellness_adapter(self.source_name)

            # Adapt (parse + validate + map)
            canonical_snapshot = adapter.adapt(raw_data, athlete_id="unknown")

            # Check idempotency
            if self.ingestion_state.is_processed(blob_name):
                logger.info("Blob already processed: %s", blob_name)
                return

            # Upsert to appropriate table
            if isinstance(canonical_snapshot, PhysiometricsSnapshot):
                self._upsert_physiometrics(canonical_snapshot)
            elif isinstance(canonical_snapshot, TrainingStateSnapshot):
                self._upsert_training_state(canonical_snapshot)

            # Mark as processed
            self.ingestion_state.record_blob_processed(blob_name)
            logger.info("Processed blob: %s", blob_name)

        except Exception as e:
            self.ingestion_state.record_blob_failed(blob_name, str(e))
            raise

    def _upsert_physiometrics(self, snapshot: PhysiometricsSnapshot) -> None:
        """Upsert PhysiometricsSnapshot to table.

        Args:
            snapshot: Canonical snapshot
        """
        table_client = self.table_storage.get_table_client("Physiometrics")
        entity = {
            "PartitionKey": snapshot.athlete_id,
            "RowKey": snapshot.effective_date,
            **snapshot.model_dump(),
        }
        table_client.upsert_entity(entity)

    def _upsert_training_state(self, snapshot: TrainingStateSnapshot) -> None:
        """Upsert TrainingStateSnapshot to table.

        Args:
            snapshot: Canonical snapshot
        """
        table_client = self.table_storage.get_table_client("TrainingState")
        entity = {
            "PartitionKey": snapshot.athlete_id,
            "RowKey": snapshot.effective_date,
            **snapshot.model_dump(),
        }
        table_client.upsert_entity(entity)


class WithingsPhysiometricsProcessor(BaseWellnessProcessor):
    """Processor for Withings measurement blobs."""

    pass


class GarminTrainingStateProcessor(BaseWellnessProcessor):
    """Processor for Garmin training state blobs."""

    pass


class IntervalsPhysiometricsProcessor(BaseWellnessProcessor):
    """Processor for Intervals physiometrics blobs."""

    pass


def create_processor(
    source_name: str,
    table_storage: StorageInfrastructureProtocol,
    ingestion_state: SourceIngestionStateStorage,
) -> BaseWellnessProcessor:
    """Factory: create appropriate processor by source name.

    Args:
        source_name: Source identifier (garmin, withings, intervals)
        table_storage: Table storage client
        ingestion_state: SourceIngestionState storage

    Returns:
        Processor instance

    Raises:
        ValueError: If source unknown
    """
    processors = {
        "garmin": GarminTrainingStateProcessor,
        "withings": WithingsPhysiometricsProcessor,
        "intervals": IntervalsPhysiometricsProcessor,
    }
    processor_class = processors.get(source_name)
    if not processor_class:
        raise ValueError(f"Unknown wellness source: {source_name}")
    return processor_class(source_name, table_storage, ingestion_state)
