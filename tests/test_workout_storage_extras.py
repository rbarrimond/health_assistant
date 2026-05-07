"""Additional unit coverage for workout storage wrappers and hashing."""

import hashlib
import json
from unittest.mock import MagicMock

from TrainingAnalyticsPlatform.storage.workout_storage import WorkoutStorage


class TestWorkoutStorageProxyMethods:
    def test_store_raw_fit_json_uses_raw_fit_blob_name_and_upload(self) -> None:
        storage = WorkoutStorage.__new__(WorkoutStorage)
        storage.infra = MagicMock()
        storage.infra.raw_fit_blob_name.return_value = "raw/workout-1.json.gz"
        storage.infra.upload_json_gzip.return_value = "raw/workout-1.json.gz"

        result = storage.store_raw_fit_json("workout-1", {"foo": "bar"})

        assert result == "raw/workout-1.json.gz"
        storage.infra.raw_fit_blob_name.assert_called_once_with("workout-1")
        storage.infra.upload_json_gzip.assert_called_once_with(
            "raw/workout-1.json.gz", {"foo": "bar"}
        )

    def test_store_fit_analysis_uses_fit_analysis_blob_name_and_upload(self) -> None:
        storage = WorkoutStorage.__new__(WorkoutStorage)
        storage.infra = MagicMock()
        storage.infra.fit_analysis_blob_name.return_value = "analysis/workout-2.json"
        storage.infra.upload_json_blob.return_value = "analysis/workout-2.json"

        result = storage.store_fit_analysis("workout-2", {"score": 42})

        assert result == "analysis/workout-2.json"
        storage.infra.fit_analysis_blob_name.assert_called_once_with("workout-2")
        storage.infra.upload_json_blob.assert_called_once_with(
            "analysis/workout-2.json", {"score": 42}
        )

    def test_store_metadata_json_uses_metadata_blob_name_and_upload(self) -> None:
        storage = WorkoutStorage.__new__(WorkoutStorage)
        storage.infra = MagicMock()
        storage.infra.metadata_blob_name.return_value = "meta/workout-3.json"
        storage.infra.upload_json_blob.return_value = "meta/workout-3.json"

        result = storage.store_metadata_json("workout-3", {"a": 1})

        assert result == "meta/workout-3.json"
        storage.infra.metadata_blob_name.assert_called_once_with("workout-3")
        storage.infra.upload_json_blob.assert_called_once_with("meta/workout-3.json", {"a": 1})


class TestUpsertMetricsHashing:
    def test_upsert_metrics_dict_uses_stable_sha256_ingestion_id(self) -> None:
        storage = WorkoutStorage.__new__(WorkoutStorage)
        storage.infra = MagicMock()
        storage.store_workout = MagicMock(return_value="workout-abc")

        metrics = {
            "sport": "running",
            "distance_m": 10000,
            "start_time_utc": "2026-05-01T10:00:00+00:00",
        }

        result = storage.upsert_metrics("rob", metrics)

        assert result == "workout-abc"

        payload = json.dumps(metrics, separators=(",", ":"), default=str, sort_keys=True)
        expected_ingestion_id = hashlib.sha256(payload.encode()).hexdigest()

        storage.store_workout.assert_called_once_with(
            "rob",
            metrics,
            ingestion_id=expected_ingestion_id,
        )
