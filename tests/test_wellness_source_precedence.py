"""Tests for physiometrics source precedence consolidation."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from TrainingAnalyticsPlatform.handlers.wellness_consolidation import (
    PhysiometricsConsolidationHandler,
    TrainingStateConsolidationHandler,
)
from TrainingAnalyticsPlatform.models.wellness import TrainingStateSnapshot


class _FakeTableClient:
    def __init__(self, entities):
        self._entities = entities

    def query_entities(self, _filter_str):
        return self._entities


class _FakeStorageClient:
    def __init__(self, entities):
        self._entities = entities

    def get_table_client(self, _table_name):
        return _FakeTableClient(self._entities)


def test_consolidation_applies_metric_source_precedence():
    """Intervals dominates wellness, Garmin training, Withings body composition."""
    entities = [
        {
            "PartitionKey": "rob",
            "RowKey": "2026-03-05",
            "effective_date": "2026-03-05",
            "data_source": "withings",
            "weight_kg": 73.2,
            "body_fat_pct": 14.8,
        },
        {
            "PartitionKey": "rob",
            "RowKey": "2026-03-05",
            "effective_date": "2026-03-05",
            "data_source": "intervals",
            "hrv_ln_rmssd": 3.95,
            "sleep_duration_sec": 28000,
            "activity_steps": 11500,
        },
        {
            "PartitionKey": "rob",
            "RowKey": "2026-03-05",
            "effective_date": "2026-03-05",
            "data_source": "garmin",
            "power_ftp_watts": 320,
            "cycling_vo2max_ml_kg_min": 62.5,
            "running_vo2max_ml_kg_min": 58.1,
            "training_load": 310.0,
            "training_stress_score": 310.0,
            "training_stress_balance": 0.88,
        },
    ]

    handler = PhysiometricsConsolidationHandler(_FakeStorageClient(entities))
    consolidated = handler.consolidate_day("rob", "2026-03-05")

    assert consolidated.weight_kg == pytest.approx(73.2)
    assert consolidated.body_fat_pct == pytest.approx(14.8)
    assert consolidated.hrv_ln_rmssd == pytest.approx(3.95)
    assert consolidated.sleep_duration_sec == 28000
    assert consolidated.steps == 11500
    assert consolidated.ftp_watts == 320
    assert consolidated.cycling_vo2max_ml_kg_min == pytest.approx(62.5)
    assert consolidated.running_vo2max_ml_kg_min == pytest.approx(58.1)
    assert consolidated.training_load == pytest.approx(310.0)
    assert consolidated.training_stress_score == pytest.approx(310.0)
    assert consolidated.training_stress_balance == pytest.approx(0.88)
    assert not hasattr(consolidated, "fatigue")


def test_consolidation_handles_data_sources_csv_and_alias_fields():
    """Consolidation should read both data_source and data_sources formats."""
    entities = [
        {
            "PartitionKey": "rob",
            "RowKey": "2026-03-04",
            "effective_date": "2026-03-04",
            "data_sources": "intervals,garmin",
            "heart_rate_resting_bpm": 48,
            "heart_rate_lthr_bpm": 172,
        }
    ]

    handler = PhysiometricsConsolidationHandler(_FakeStorageClient(entities))
    consolidated = handler.consolidate_day("rob", "2026-03-04")

    assert consolidated.resting_hr_bpm == 48
    assert consolidated.hr_lthr_bpm == 172
    assert consolidated.data_sources == "garmin,intervals"


def test_training_state_consolidation_delegates_to_semantic_layer():
    """Training-state consolidation should use the semantic-layer canonical path."""
    snapshot = TrainingStateSnapshot(
        athlete_id="rob",
        effective_date="2026-03-17",
        cts_rolling_7d=12.0,
        cts_rolling_28d=18.0,
        ats_rolling=12.0,
        fatigue_index=0.67,
        readiness_score=81.0,
        garmin_readiness_score=79.0,
        mood=None,
        soreness=None,
        pred_recovery_days=None,
        data_sources="workouts,physiometrics",
        canonical_version="4.0.0",
    )
    semantic_layer = MagicMock()
    semantic_layer._compute_training_state_for_date.return_value = snapshot

    handler = TrainingStateConsolidationHandler(
        _FakeStorageClient([]),
        semantic_layer=semantic_layer,
    )

    result = handler.compute_day("rob", "2026-03-17")

    semantic_layer._compute_training_state_for_date.assert_called_once_with(
        "rob",
        date(2026, 3, 17),
    )
    assert result == snapshot


def test_new_garmin_fields_registered_in_metric_sources():
    """Verify that new training status + load focus fields are Garmin-exclusive."""
    from TrainingAnalyticsPlatform.handlers.wellness_consolidation import (
        SourcePrecedenceResolver,
    )

    # New fields added in v4.2.0 should be Garmin-exclusive
    new_fields = [
        "training_status_label",
        "load_focus_low_aerobic_pct",
        "load_focus_high_aerobic_pct",
        "load_focus_anaerobic_pct",
    ]

    for field in new_fields:
        assert field in SourcePrecedenceResolver.METRIC_SOURCES, f"Field {field} not registered"
        sources = SourcePrecedenceResolver.METRIC_SOURCES[field]
        assert sources == ["garmin"], f"Field {field} should be Garmin-exclusive, got {sources}"
