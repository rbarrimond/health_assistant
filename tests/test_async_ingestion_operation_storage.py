from __future__ import annotations

import json
from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.models.async_operation import AsyncIngestionOperationState
from TrainingAnalyticsPlatform.storage.async_ingestion_operation_storage import AsyncIngestionOperationStorage


class _FakeInfrastructure:
    def __init__(self, table_client: MagicMock) -> None:
        self._table_client = table_client

    def get_table_client(self, _table_name: str) -> MagicMock:
        return self._table_client


def test_mark_status_serializes_result_payload_to_json_string(monkeypatch) -> None:
    table_client = MagicMock()
    storage = AsyncIngestionOperationStorage(_FakeInfrastructure(table_client))

    expected_state = AsyncIngestionOperationState.queued(
        athlete_id="rob",
        operation_id="op-123",
        source="garmin",
        lookback_days=1,
        mode="async",
        queued_at_utc="2026-03-20T00:00:00+00:00",
    )

    monkeypatch.setattr(storage, "get_state", lambda **_kwargs: expected_state)

    result_payload = {"workouts": 1, "window": {"days": 1}}
    storage.mark_status(
        athlete_id="rob",
        operation_id="op-123",
        status="succeeded",
        result=result_payload,
    )

    update_call = table_client.update_entity.call_args.kwargs
    assert update_call["entity"]["result"] == json.dumps(result_payload)
