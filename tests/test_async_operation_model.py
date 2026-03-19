from TrainingAnalyticsPlatform.models.async_operation import AsyncIngestionOperationState


class TestAsyncIngestionOperationStateSerialization:
    def test_to_entity_json_serializes_context_and_result(self):
        state = AsyncIngestionOperationState(
            partition_key="rob",
            row_key="op-1",
            athlete_id="rob",
            source="onedrive",
            lookback_days=14,
            status="queued",
            mode="async_queue",
            queued_at_utc="2026-03-19T00:00:00+00:00",
            created_at_utc="2026-03-19T00:00:01+00:00",
            updated_at_utc="2026-03-19T00:00:01+00:00",
            context={"force": True, "source": "onedrive"},
            result={"ingested": 2, "failed": 0},
        )

        entity = state.to_entity()

        assert entity["context"] == '{"force": true, "source": "onedrive"}'
        assert entity["result"] == '{"ingested": 2, "failed": 0}'

    def test_from_entity_deserializes_json_context_and_result(self):
        entity = {
            "PartitionKey": "rob",
            "RowKey": "op-2",
            "athlete_id": "rob",
            "source": "garmin",
            "lookback_days": 21,
            "status": "succeeded",
            "mode": "async_queue",
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
            "created_at_utc": "2026-03-19T00:00:01+00:00",
            "updated_at_utc": "2026-03-19T00:01:00+00:00",
            "context": '{"force": true, "api": "garmin"}',
            "result": '{"ingested": 3, "failed": 0}',
        }

        state = AsyncIngestionOperationState.from_entity(entity)

        assert state.context == {"force": True, "api": "garmin"}
        assert state.result == {"ingested": 3, "failed": 0}

    def test_from_entity_falls_back_for_malformed_or_non_object_json(self):
        malformed_entity = {
            "PartitionKey": "rob",
            "RowKey": "op-3",
            "athlete_id": "rob",
            "source": "onedrive",
            "lookback_days": 7,
            "status": "failed",
            "mode": "async_queue",
            "queued_at_utc": "2026-03-19T00:00:00+00:00",
            "created_at_utc": "2026-03-19T00:00:01+00:00",
            "updated_at_utc": "2026-03-19T00:01:00+00:00",
            "context": "{not-json}",
            "result": "[1,2,3]",
        }

        state = AsyncIngestionOperationState.from_entity(malformed_entity)

        assert state.context == {}
        assert state.result == {}
