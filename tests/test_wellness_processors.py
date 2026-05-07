"""Unit tests for TrainingAnalyticsPlatform.handlers.wellness_processors."""

from unittest.mock import MagicMock, patch

import pytest

from TrainingAnalyticsPlatform.handlers.wellness_processors import (
    BaseWellnessProcessor,
    GarminTrainingStateProcessor,
    IntervalsPhysiometricsProcessor,
    WithingsPhysiometricsProcessor,
    create_processor,
)
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot


# ---------------------------------------------------------------------------
# Concrete subclass for testing the abstract base
# ---------------------------------------------------------------------------

class _ConcreteProcessor(BaseWellnessProcessor):
    """Minimal concrete subclass to test BaseWellnessProcessor logic."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_physiometrics_snapshot() -> PhysiometricsSnapshot:
    return PhysiometricsSnapshot(  # type: ignore[call-arg]
        athlete_id="athlete1",
        effective_date="2026-01-15",
        resting_hr_bpm=52.0,
    )


def _make_processor() -> tuple[_ConcreteProcessor, MagicMock, MagicMock]:
    """Return (processor, mock_table_storage, mock_ingestion_state)."""
    mock_table_storage = MagicMock()
    mock_ingestion_state = MagicMock()
    processor = _ConcreteProcessor(
        source_name="withings",
        table_storage=mock_table_storage,
        ingestion_state=mock_ingestion_state,
    )
    return processor, mock_table_storage, mock_ingestion_state


# ---------------------------------------------------------------------------
# __init__ tests
# ---------------------------------------------------------------------------

class TestBaseWellnessProcessorInit:
    def test_stores_source_name(self) -> None:
        processor, _, _ = _make_processor()
        assert processor.source_name == "withings"

    def test_stores_table_storage(self) -> None:
        processor, mock_table_storage, _ = _make_processor()
        assert processor.table_storage is mock_table_storage

    def test_stores_ingestion_state(self) -> None:
        processor, _, mock_ingestion_state = _make_processor()
        assert processor.ingestion_state is mock_ingestion_state


# ---------------------------------------------------------------------------
# process() happy path — PhysiometricsSnapshot
# ---------------------------------------------------------------------------

class TestBaseWellnessProcessorHappyPath:
    def test_upserts_physiometrics_and_records_processed(self) -> None:
        processor, mock_table_storage, mock_ingestion_state = _make_processor()
        snapshot = _make_physiometrics_snapshot()
        mock_ingestion_state.is_processed.return_value = False

        mock_adapter = MagicMock()
        mock_adapter.adapt.return_value = snapshot
        mock_table_client = MagicMock()
        mock_table_storage.get_table_client.return_value = mock_table_client

        with patch(
            "TrainingAnalyticsPlatform.handlers.wellness_processors.create_wellness_adapter",
            return_value=mock_adapter,
        ):
            processor.process("blob/2026-01-15.json", {"raw": "data"})

        mock_adapter.adapt.assert_called_once_with({"raw": "data"}, athlete_id="unknown")
        mock_table_storage.get_table_client.assert_called_once_with("Physiometrics")
        mock_table_client.upsert_entity.assert_called_once()
        upserted = mock_table_client.upsert_entity.call_args[0][0]
        assert upserted["PartitionKey"] == "athlete1"
        assert upserted["RowKey"] == "2026-01-15"
        mock_ingestion_state.record_blob_processed.assert_called_once_with(
            "blob/2026-01-15.json"
        )

    def test_upserts_training_state_when_snapshot_is_training_state(self) -> None:
        from TrainingAnalyticsPlatform.models.wellness import TrainingStateSnapshot

        processor, mock_table_storage, mock_ingestion_state = _make_processor()
        mock_ingestion_state.is_processed.return_value = False

        training_snapshot = TrainingStateSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete1",
            effective_date="2026-01-15",
        )

        mock_adapter = MagicMock()
        mock_adapter.adapt.return_value = training_snapshot
        mock_table_client = MagicMock()
        mock_table_storage.get_table_client.return_value = mock_table_client

        with patch(
            "TrainingAnalyticsPlatform.handlers.wellness_processors.create_wellness_adapter",
            return_value=mock_adapter,
        ):
            processor.process("blob/training.json", {})

        mock_table_storage.get_table_client.assert_called_once_with("TrainingState")
        mock_ingestion_state.record_blob_processed.assert_called_once_with(
            "blob/training.json"
        )


# ---------------------------------------------------------------------------
# process() deduplication path
# ---------------------------------------------------------------------------

class TestBaseWellnessProcessorDedup:
    def test_skips_upsert_when_already_processed(self) -> None:
        processor, mock_table_storage, mock_ingestion_state = _make_processor()
        snapshot = _make_physiometrics_snapshot()
        mock_ingestion_state.is_processed.return_value = True

        mock_adapter = MagicMock()
        mock_adapter.adapt.return_value = snapshot

        with patch(
            "TrainingAnalyticsPlatform.handlers.wellness_processors.create_wellness_adapter",
            return_value=mock_adapter,
        ):
            processor.process("blob/already.json", {})

        mock_table_storage.get_table_client.assert_not_called()
        mock_ingestion_state.record_blob_processed.assert_not_called()


# ---------------------------------------------------------------------------
# process() error path
# ---------------------------------------------------------------------------

class TestBaseWellnessProcessorErrorPath:
    def test_records_failure_and_reraises_on_exception(self) -> None:
        processor, mock_table_storage, mock_ingestion_state = _make_processor()

        mock_adapter = MagicMock()
        mock_adapter.adapt.side_effect = ValueError("bad data")

        with patch(
            "TrainingAnalyticsPlatform.handlers.wellness_processors.create_wellness_adapter",
            return_value=mock_adapter,
        ):
            with pytest.raises(ValueError, match="bad data"):
                processor.process("blob/bad.json", {})

        mock_ingestion_state.record_blob_failed.assert_called_once_with(
            "blob/bad.json", "bad data"
        )
        mock_ingestion_state.record_blob_processed.assert_not_called()

    def test_upsert_failure_records_blob_failed(self) -> None:
        processor, mock_table_storage, mock_ingestion_state = _make_processor()
        snapshot = _make_physiometrics_snapshot()
        mock_ingestion_state.is_processed.return_value = False

        mock_adapter = MagicMock()
        mock_adapter.adapt.return_value = snapshot
        mock_table_client = MagicMock()
        mock_table_client.upsert_entity.side_effect = RuntimeError("storage error")
        mock_table_storage.get_table_client.return_value = mock_table_client

        with patch(
            "TrainingAnalyticsPlatform.handlers.wellness_processors.create_wellness_adapter",
            return_value=mock_adapter,
        ):
            with pytest.raises(RuntimeError, match="storage error"):
                processor.process("blob/fail.json", {})

        mock_ingestion_state.record_blob_failed.assert_called_once_with(
            "blob/fail.json", "storage error"
        )


# ---------------------------------------------------------------------------
# Concrete subclass smoke tests
# ---------------------------------------------------------------------------

class TestConcreteProcessorSubclasses:
    def test_withings_processor_instantiates(self) -> None:
        p = WithingsPhysiometricsProcessor(
            source_name="withings",
            table_storage=MagicMock(),
            ingestion_state=MagicMock(),
        )
        assert p.source_name == "withings"

    def test_garmin_processor_instantiates(self) -> None:
        p = GarminTrainingStateProcessor(
            source_name="garmin",
            table_storage=MagicMock(),
            ingestion_state=MagicMock(),
        )
        assert p.source_name == "garmin"

    def test_intervals_processor_instantiates(self) -> None:
        p = IntervalsPhysiometricsProcessor(
            source_name="intervals",
            table_storage=MagicMock(),
            ingestion_state=MagicMock(),
        )
        assert p.source_name == "intervals"


# ---------------------------------------------------------------------------
# create_processor factory
# ---------------------------------------------------------------------------

class TestCreateProcessorFactory:
    def test_create_withings_processor(self) -> None:
        p = create_processor(
            source_name="withings",
            table_storage=MagicMock(),
            ingestion_state=MagicMock(),
        )
        assert isinstance(p, WithingsPhysiometricsProcessor)

    def test_create_garmin_processor(self) -> None:
        p = create_processor(
            source_name="garmin",
            table_storage=MagicMock(),
            ingestion_state=MagicMock(),
        )
        assert isinstance(p, GarminTrainingStateProcessor)

    def test_create_intervals_processor(self) -> None:
        p = create_processor(
            source_name="intervals",
            table_storage=MagicMock(),
            ingestion_state=MagicMock(),
        )
        assert isinstance(p, IntervalsPhysiometricsProcessor)

    def test_create_unknown_source_raises(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            create_processor(
                source_name="unknown_source",
                table_storage=MagicMock(),
                ingestion_state=MagicMock(),
            )
