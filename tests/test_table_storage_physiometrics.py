"""Unit tests for physiometrics Azure Table Storage methods."""

# Allow protected member access in tests for internal state verification.
# pylint: disable=protected-access

import json
from unittest.mock import MagicMock

import pytest
from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.physiometrics_storage import PhysiometricsStorage
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure


def _make_storage(mock_table_client: MagicMock) -> PhysiometricsStorage:
    storage = PhysiometricsStorage.__new__(PhysiometricsStorage)
    storage.infra = MagicMock()
    storage.infra.get_table_client = MagicMock(return_value=mock_table_client)
    return storage


class TestStorePhysiometrics:
    """Tests for store_physiometrics method."""

    def test_store_physiometrics_success(self) -> None:
        """Verify physiometrics are stored with a source-qualified RowKey."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "heart_rate": {
                "basis": "HRmax",
                "lthr_bpm": 175,
                "hr_max_bpm": 195,
                "resting_hr_bpm": 52,
            },
            "power": {"ftp_watts": 285}
        }

        updated_at = storage.store_physiometrics("rob", physiometrics_data)

        assert isinstance(updated_at, str)
        assert "T" in updated_at
        mock_table_client.upsert_entity.assert_called_once()

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["PartitionKey"] == "rob"
        assert entity["RowKey"].endswith("|manual")
        assert entity["effective_date"] in entity["RowKey"]
        assert entity["heart_rate_basis"] == "HRmax"
        assert entity["power_ftp_watts"] == 285

    def test_store_physiometrics_uses_source_qualified_row_key(self) -> None:
        """Verify same-day source snapshots keep distinct row identities."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        storage.store_physiometrics(
            "rob",
            {"heart_rate": {"basis": "HRmax"}, "power": {}},
            effective_date="2026-03-13",
            data_source="withings",
        )

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["RowKey"] == "2026-03-13|withings"

    def test_store_physiometrics_stores_raw_and_ext_json(self) -> None:
        """Verify raw source blob and canonical ext blob are stored."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "heart_rate": {"basis": "HRmax"},
            "power": {"ftp_watts": 250},
            "raw_intervals_icu_json": '{"id":"2026-01-18"}',
            "ext_json": '{"hrv_sdnn_ms":40.1}',
        }

        storage.store_physiometrics("rob", physiometrics_data)

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["raw_intervals_icu_json"] == '{"id":"2026-01-18"}'
        assert json.loads(entity["ext_json"]) == {"hrv_sdnn_ms": 40.1}
        assert "full_config_json" not in entity

    def test_store_physiometrics_handles_null_values(self) -> None:
        """Verify null values are handled gracefully."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "heart_rate": {
                "basis": "HRmax",
                "lthr_bpm": None,
                "hr_max_bpm": None
            },
            "power": {"ftp_watts": None}
        }

        storage.store_physiometrics("rob", physiometrics_data)

        mock_table_client.upsert_entity.assert_called_once()

    def test_store_physiometrics_leaves_basis_null_when_missing(self) -> None:
        """Verify source rows preserve null basis when source does not provide one."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "resting_hr_bpm": 52,
            "power": {"ftp_watts": 285},
        }

        storage.store_physiometrics("rob", physiometrics_data, data_source="intervals")

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["heart_rate_basis"] is None

    def test_store_physiometrics_error(self) -> None:
        """Verify error is raised on storage failure."""
        mock_table_client = MagicMock()
        mock_table_client.upsert_entity.side_effect = HttpResponseError("Storage error")
        storage = _make_storage(mock_table_client)

        physiometrics_data = {"heart_rate": {}, "power": {}}

        with pytest.raises(StorageError):
            storage.store_physiometrics("rob", physiometrics_data)

    def test_store_physiometrics_accepts_typed_snapshot(self) -> None:
        """Verify typed PhysiometricsSnapshot input persists Garmin status/load-focus fields."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="rob",
            effective_date="2026-03-16",
            data_sources="garmin",
            ftp_watts=224,
            hr_lthr_bpm=173,
            hr_lthr_cycling_bpm=176,
            hr_max_bpm=195,
            training_status_label="RECOVERY_2",
            load_focus_low_aerobic_pct=66.7,
            load_focus_high_aerobic_pct=17.0,
            load_focus_anaerobic_pct=16.3,
            training_load=107.0,
        )

        storage.store_physiometrics("rob", snapshot, data_source="garmin")

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["RowKey"] == "2026-03-16|garmin"
        assert entity["power_ftp_watts"] == 224
        assert entity["heart_rate_lthr_bpm"] == 173
        assert entity["heart_rate_lthr_cycling_bpm"] == 176
        assert "lactate_threshold_hr_bpm" not in entity
        assert entity["heart_rate_hr_max_bpm"] == 195
        assert entity["training_status_label"] == "RECOVERY_2"
        assert entity["load_focus_low_aerobic_pct"] == pytest.approx(66.7)
        assert entity["load_focus_high_aerobic_pct"] == pytest.approx(17.0)
        assert entity["load_focus_anaerobic_pct"] == pytest.approx(16.3)
        assert entity["training_load"] == pytest.approx(107.0)


class TestGetPhysiometrics:
    """Tests for get_physiometrics method."""

    def test_get_physiometrics_latest(self) -> None:
        """Verify config reads prefer the latest config-sourced row."""
        mock_table_client = MagicMock()

        config_json = json.dumps({
            "heart_rate": {"basis": "HRmax", "hr_max_bpm": 195},
            "power": {"ftp_watts": 285}
        })
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-02|withings",
                "effective_date": "2026-03-02",
                "updated_at_utc": "2026-03-02T09:00:00+00:00",
                "data_source": "withings",
                "weight_kg": 73.4,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-01|manual",
                "effective_date": "2026-03-01",
                "updated_at_utc": "2026-03-01T10:30:00+00:00",
                "full_config_json": config_json,
                "heart_rate_basis": "HRmax",
                "data_source": "manual",
            },
        ]
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is not None
        assert result["heart_rate"]["basis"] == "HRmax"
        assert result["power"]["ftp_watts"] == 285

    def test_get_physiometrics_fallback_to_fields(self) -> None:
        """Verify fallback reconstruction from individual fields."""
        mock_table_client = MagicMock()

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "2026-01-18|manual",
            "effective_date": "2026-01-18",
            "updated_at_utc": "2026-01-18T10:30:00+00:00",
            "data_source": "manual",
            "full_config_json": None,
            "heart_rate_basis": "LTHR",
            "heart_rate_lthr_bpm": 170,
            "heart_rate_hr_max_bpm": 190,
            "heart_rate_resting_bpm": 48,
            "power_ftp_watts": 300,
        }

        mock_table_client.query_entities.return_value = [mock_entity]
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is not None
        assert result["heart_rate"]["basis"] == "LTHR"
        assert result["heart_rate"]["lthr_bpm"] == 170
        assert result["power"]["ftp_watts"] == 300

    def test_get_physiometrics_fallback_to_fields_without_basis(self) -> None:
        """Verify reconstructed basis remains null when not stored."""
        mock_table_client = MagicMock()

        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "2026-01-18|intervals",
            "effective_date": "2026-01-18",
            "updated_at_utc": "2026-01-18T10:30:00+00:00",
            "data_source": "intervals",
            "full_config_json": None,
            "heart_rate_lthr_bpm": None,
            "heart_rate_hr_max_bpm": None,
            "heart_rate_resting_bpm": 52,
            "power_ftp_watts": None,
        }

        mock_table_client.query_entities.return_value = [mock_entity]
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is not None
        assert result["heart_rate"]["basis"] is None
        assert result["heart_rate"]["resting_hr_bpm"] == 52

    def test_get_physiometrics_not_found(self) -> None:
        """Verify None returned when no physiometrics found."""
        mock_table_client = MagicMock()
        mock_table_client.query_entities.return_value = []
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is None

    def test_get_physiometrics_query_error(self) -> None:
        """Verify typed error raised on query failure."""
        mock_table_client = MagicMock()
        mock_table_client.query_entities.side_effect = HttpResponseError("Query error")
        storage = _make_storage(mock_table_client)

        with pytest.raises(StorageError):
            storage.get_physiometrics("rob")


class TestGetPhysiometricsHistoryRange:
    """Tests for date-range physiometrics history queries."""

    def test_get_physiometrics_history_exposes_canonical_aliases(self) -> None:
        """Verify unfiltered history rows expose canonical FTP and HR fields only."""
        mock_table_client = MagicMock()
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-04-10|garmin",
                "effective_date": "2026-04-10",
                "updated_at_utc": "2026-04-10T18:00:00+00:00",
                "data_source": "garmin",
                "power_ftp_watts": 224,
                "heart_rate_hr_max_bpm": 195,
                "heart_rate_lthr_bpm": 173,
                "heart_rate_lthr_cycling_bpm": 176,
                "lactate_threshold_hr_bpm": 173,
            }
        ]
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics_history("rob", "2026-04-10", "2026-04-10")

        assert result[0]["ftp_watts"] == 224
        assert result[0]["hr_max_bpm"] == 195
        assert result[0]["hr_lthr_bpm"] == 173
        assert result[0]["hr_lthr_cycling_bpm"] == 176
        assert "lactate_threshold_hr_bpm" not in result[0]
        assert "heart_rate_lthr_bpm" not in result[0]
        assert "heart_rate_lthr_cycling_bpm" not in result[0]

    def test_get_physiometrics_history_filters_with_canonical_metric_names(self) -> None:
        """Verify metric filters resolve canonical names from storage alias columns."""
        mock_table_client = MagicMock()
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-04-10|garmin",
                "effective_date": "2026-04-10",
                "updated_at_utc": "2026-04-10T18:00:00+00:00",
                "data_source": "garmin",
                "power_ftp_watts": 224,
                "heart_rate_hr_max_bpm": 195,
                "heart_rate_lthr_bpm": 173,
                "heart_rate_lthr_cycling_bpm": 176,
            }
        ]
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics_history(
            "rob",
            "2026-04-10",
            "2026-04-10",
            metrics=["ftp_watts", "hr_max_bpm", "lactate_threshold_hr_bpm", "heart_rate_lthr_cycling_bpm"],
        )

        assert result == [
            {
                "effective_date": "2026-04-10",
                "updated_at_utc": "2026-04-10T18:00:00+00:00",
                "data_source": "garmin",
                "ftp_watts": 224,
                "hr_max_bpm": 195,
                "hr_lthr_bpm": 173,
                "hr_lthr_cycling_bpm": 176,
            }
        ]


class TestListPhysiometricsHistory:
    """Tests for list_physiometrics_history method."""

    def test_list_physiometrics_history_success(self) -> None:
        """Verify config history is filtered and sorted newest first."""
        mock_table_client = MagicMock()

        mock_entities = [
            {
                "RowKey": "2026-01-18|manual",
                "effective_date": "2026-01-18",
                "updated_at_utc": "2026-01-18T09:30:00+00:00",
                "heart_rate_basis": "HRmax",
                "data_source": "manual",
            },
            {
                "RowKey": "2026-01-18|chatgpt",
                "effective_date": "2026-01-18",
                "updated_at_utc": "2026-01-18T10:30:00+00:00",
                "heart_rate_basis": "LTHR",
                "data_source": "chatgpt",
            },
            {
                "RowKey": "2026-01-18|withings",
                "effective_date": "2026-01-18",
                "updated_at_utc": "2026-01-18T11:00:00+00:00",
                "heart_rate_basis": "HRR",
                "data_source": "withings",
            },
        ]

        mock_table_client.query_entities.return_value = mock_entities
        storage = _make_storage(mock_table_client)

        result = storage.list_physiometrics_history("rob", limit=10)

        assert [entry["RowKey"] for entry in result] == [
            "2026-01-18|chatgpt",
            "2026-01-18|manual",
        ]

    def test_list_physiometrics_history_limit(self) -> None:
        """Verify limit is respected."""
        mock_table_client = MagicMock()

        mock_entities = [
            {
                "RowKey": f"2026-01-{18 + (i // 2):02d}|{'manual' if i % 2 == 0 else 'chatgpt'}",
                "effective_date": f"2026-01-{18 + (i // 2):02d}",
                "updated_at_utc": f"2026-01-{18 + (i // 2):02d}T{i:02d}:30:00+00:00",
                "data_source": "manual" if i % 2 == 0 else "chatgpt",
            }
            for i in range(10)
        ]

        mock_table_client.query_entities.return_value = mock_entities
        storage = _make_storage(mock_table_client)

        result = storage.list_physiometrics_history("rob", limit=5)

        assert len(result) == 5

    def test_list_physiometrics_history_query_error(self) -> None:
        """Verify typed error raised on query failure."""
        mock_table_client = MagicMock()
        mock_table_client.query_entities.side_effect = HttpResponseError("Query error")
        storage = _make_storage(mock_table_client)

        with pytest.raises(StorageError):
            storage.list_physiometrics_history("rob", limit=10)


class TestTypedSnapshotAsOf:
    """Tests for typed physiometrics as-of retrieval."""

    def test_get_physiometrics_snapshot_as_of_prefers_latest_source_row(self) -> None:
        """Typed as-of retrieval should use newest row, not config-priority selection."""
        mock_table_client = MagicMock()
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-16|manual",
                "effective_date": "2026-03-16",
                "updated_at_utc": "2026-03-16T01:00:00+00:00",
                "data_source": "manual",
                "heart_rate_basis": "HRmax",
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-03-16|garmin",
                "effective_date": "2026-03-16",
                "updated_at_utc": "2026-03-16T02:00:00+00:00",
                "data_source": "garmin",
                "training_status_label": "RECOVERY_2",
                "training_load": 107.0,
                "load_focus_low_aerobic_pct": 66.7,
                "load_focus_high_aerobic_pct": 17.0,
                "load_focus_anaerobic_pct": 16.3,
            },
        ]
        storage = _make_storage(mock_table_client)

        snapshot = storage.get_physiometrics_snapshot_as_of("rob", "2026-03-16")

        assert snapshot is not None
        assert snapshot.training_status_label == "RECOVERY_2"
        assert snapshot.training_load == pytest.approx(107.0)
        assert snapshot.load_focus_low_aerobic_pct == pytest.approx(66.7)


class TestEnsurePhysiometricsTable:
    """Tests for Physiometrics table creation."""

    # Test classes don't need multiple public methods.
    # pylint: disable=too-few-public-methods
    def test_ensure_tables_exist_includes_physiometrics(self) -> None:
        """Verify Physiometrics table is created on init."""
        mock_service_client = MagicMock()

        infrastructure = StorageInfrastructure.__new__(StorageInfrastructure)
        infrastructure.service_client = mock_service_client
        infrastructure._ensure_tables_exist()

        table_names = [
            call[0][0]
            for call in (
                mock_service_client
                .create_table_if_not_exists
                .call_args_list
            )
        ]
        assert "Physiometrics" in table_names

class TestWellnessFieldsPersistence:
    """Tests for wellness fields (HRV, sleep, readiness) storage."""

    def test_store_physiometrics_persists_wellness_fields(self) -> None:
        """Verify wellness fields are stored as table columns."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "hrv_ln_rmssd": 4.2,
            "sleep_duration_sec": 28800.0,
            "readiness_score": 85.0,
            "heart_rate": {"basis": "LTHR", "resting_hr_bpm": 52},
            "power": {"ftp_watts": 285},
        }

        storage.store_physiometrics("athlete123", physiometrics_data)

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["hrv_ln_rmssd"] == pytest.approx(4.2)
        assert entity["sleep_duration_sec"] == pytest.approx(28800.0)
        assert entity["readiness_score"] == pytest.approx(85.0)

    def test_store_physiometrics_handles_null_wellness_fields(self) -> None:
        """Verify null wellness fields are stored as None for backward compatibility."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "hrv_ln_rmssd": None,
            "sleep_duration_sec": None,
            "readiness_score": None,
            "heart_rate": {"basis": "LTHR", "resting_hr_bpm": 52},
            "power": {"ftp_watts": 285},
        }

        storage.store_physiometrics("athlete123", physiometrics_data)

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["hrv_ln_rmssd"] is None
        assert entity["sleep_duration_sec"] is None
        assert entity["readiness_score"] is None

    def test_wellness_fields_in_ext_json(self) -> None:
        """Verify wellness fields are preserved in ext_json blob."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "hrv_ln_rmssd": 4.2,
            "hrv_sdnn_ms": 41.8,
            "sleep_duration_sec": 28800.0,
            "readiness_score": 85.0,
            "heart_rate": {"basis": "LTHR", "resting_hr_bpm": 52},
            "power": {"ftp_watts": 285},
            "ext_json": '{"hrv_sdnn_ms":41.8,"sleep_duration_sec":28800.0}',
        }

        storage.store_physiometrics("athlete123", physiometrics_data)

        entity = mock_table_client.upsert_entity.call_args[0][0]
        ext_json = json.loads(entity["ext_json"])
        assert ext_json["hrv_sdnn_ms"] == pytest.approx(41.8)
        assert ext_json["sleep_duration_sec"] == pytest.approx(28800.0)

    def test_get_physiometrics_uses_ext_json_when_present(self) -> None:
        """Verify reconstruction path is used when ext_json is present."""
        mock_table_client = MagicMock()
        mock_entity = {
            "PartitionKey": "rob",
            "RowKey": "2026-01-18",
            "heart_rate_basis": "LTHR",
            "heart_rate_resting_bpm": 50,
            "power_ftp_watts": 285,
            "weight_kg": 75.2,
            "ext_json": '{"soreness":3,"menstrual_phase":"follicular"}',
            "raw_intervals_icu_json": '{"id":"2026-01-18","ctl":22}',
        }
        mock_table_client.query_entities.return_value = [mock_entity]
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics("rob")

        assert result is not None
        assert result["heart_rate"]["resting_hr_bpm"] == pytest.approx(50)
        assert result["soreness"] == 3
        assert result["menstrual_phase"] == "follicular"
        assert result["raw_intervals_icu_json"] == '{"id":"2026-01-18","ctl":22}'

    def test_store_physiometrics_resting_hr_from_flat_key(self) -> None:
        """Verify resting HR from flat key (Intervals) is persisted correctly."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        # Intervals path provides flat resting_hr_bpm from PhysiometricsSnapshot.to_storage_dict()
        physiometrics_data = {
            "resting_hr_bpm": 52,
            "hrv_ln_rmssd": 4.2,
            "sleep_duration_sec": 28800.0,
            "readiness_score": 78.0,
        }

        storage.store_physiometrics("athlete123", physiometrics_data)

        entity = mock_table_client.upsert_entity.call_args[0][0]
        # Should use flat key, not default 60
        assert entity["heart_rate_resting_bpm"] == pytest.approx(52)

    def test_store_physiometrics_resting_hr_remains_none_when_absent(self) -> None:
        """Verify resting HR is stored as None when upstream source omits it."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        # No resting HR provided from any source
        physiometrics_data = {
            "hrv_ln_rmssd": 4.2,
            "sleep_duration_sec": 28800.0,
        }

        storage.store_physiometrics("athlete123", physiometrics_data, data_source="garmin")

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["heart_rate_resting_bpm"] is None

    def test_get_physiometrics_history_preserves_null_resting_hr_for_garmin(self) -> None:
        """Verify history rows do not synthesize resting HR for Garmin rows."""
        mock_table_client = MagicMock()
        mock_table_client.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-05-13|garmin",
                "effective_date": "2026-05-13",
                "updated_at_utc": "2026-05-14T19:17:46.496066+00:00",
                "data_source": "garmin",
                "heart_rate_resting_bpm": None,
                "heart_rate_lthr_bpm": 165,
            }
        ]
        storage = _make_storage(mock_table_client)

        result = storage.get_physiometrics_history("rob", "2026-05-13", "2026-05-13")

        assert result[0]["resting_hr_bpm"] is None
        assert result[0]["hr_lthr_bpm"] == 165

    def test_store_physiometrics_nutrition_macros_persisted(self) -> None:
        """Verify nutrition macro columns are persisted when present."""
        mock_table_client = MagicMock()
        storage = _make_storage(mock_table_client)

        physiometrics_data = {
            "carbs_g": 300.0,
            "protein_g": 150.0,
            "fat_g": 80.0,
            "calories_kcal": 2500.0,
        }

        storage.store_physiometrics("athlete123", physiometrics_data)

        entity = mock_table_client.upsert_entity.call_args[0][0]
        assert entity["nutrition_carbs_g"] == pytest.approx(300.0)
        assert entity["nutrition_protein_g"] == pytest.approx(150.0)
        assert entity["nutrition_fat_g"] == pytest.approx(80.0)
        assert entity["nutrition_calories_kcal"] == pytest.approx(2500.0)