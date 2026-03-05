"""Tests for time-series physiometrics functionality."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ResourceNotFoundError

from TrainingAnalyticsPlatform.storage.oauth_token_storage import OAuthTokenStorage
from TrainingAnalyticsPlatform.storage.physiometrics_storage import PhysiometricsStorage
from TrainingAnalyticsPlatform.storage.webhook_dedup_storage import WebhookDedupStorage

from TrainingAnalyticsPlatform.analytics.semantic_layer import SemanticLayer
from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient

class TestPhysiometricsTimeSeries:
    """Test time-series physiometrics storage and retrieval."""

    @pytest.fixture
    def storage(self):
        """Create storage instance with mocked table client."""
        mock_infra = MagicMock()
        mock_infra.get_table_client = MagicMock()
        physiometrics = PhysiometricsStorage.__new__(PhysiometricsStorage)
        physiometrics.infra = mock_infra
        oauth_tokens = OAuthTokenStorage.__new__(OAuthTokenStorage)
        oauth_tokens.infra = mock_infra
        webhooks = WebhookDedupStorage.__new__(WebhookDedupStorage)
        webhooks.infra = mock_infra

        return SimpleNamespace(
            physiometrics=physiometrics,
            oauth_tokens=oauth_tokens,
            webhooks=webhooks,
        )

    def test_store_physiometrics_with_body_composition(self, storage):
        """Test storing physiometrics with body composition data."""
        with patch.object(storage.physiometrics.infra, "get_table_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value = mock_table

            physio_data = {
                "weight_kg": 75.2,
                "fat_mass_kg": 12.5,
                "muscle_mass_kg": 38.2,
                "body_fat_pct": 16.6,
                "cycling_vo2max_ml_kg_min": 52.3,
                "heart_rate": {
                    "lthr_bpm": 175,
                    "hr_max_bpm": 195,
                    "resting_hr_bpm": 52,
                },
                "power": {"ftp_watts": 285},
            }

            timestamp = storage.physiometrics.store_physiometrics(
                athlete_id="rob",
                physiometrics_data=physio_data,
                effective_date="2026-01-19",
                data_source="withings",
            )

            # Verify entity was stored
            assert mock_table.upsert_entity.called
            entity = mock_table.upsert_entity.call_args[0][0]

            assert entity["PartitionKey"] == "rob"
            assert entity["effective_date"] == "2026-01-19"
            assert entity["data_source"] == "withings"
            # Use pytest.approx for float comparisons
            assert entity["weight_kg"] == pytest.approx(75.2)
            assert entity["cycling_vo2max_ml_kg_min"] == pytest.approx(52.3)
            assert timestamp is not None

    def test_update_single_metric(self, storage):
        """Test updating a single physiometric metric."""
        with patch.object(storage.physiometrics.infra, "get_table_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value = mock_table

            # Mock existing config
            mock_table.query_entities.return_value = [
                {
                    "PartitionKey": "rob",
                    "RowKey": "2026-01-18T10:00:00+00:00",
                    "full_config_json": json.dumps({
                        "heart_rate": {"lthr_bpm": 175, "hr_max_bpm": 195},
                        "power": {"ftp_watts": 285},
                        "weight_kg": 76.0,
                    }),
                }
            ]

            storage.physiometrics.update_single_metric(
                athlete_id="rob",
                metric_name="cycling_vo2max_ml_kg_min",
                value=52.3,
                effective_date="2026-01-19",
                data_source="chatgpt",
            )

            # Verify new entity was stored with updated value
            assert mock_table.upsert_entity.called
            entity = mock_table.upsert_entity.call_args[0][0]
            assert entity["cycling_vo2max_ml_kg_min"] == pytest.approx(52.3)
            assert entity["data_source"] == "chatgpt"

    def test_get_physiometrics_history(self, storage):
        """Test retrieving time-series physiometrics data."""
        with patch.object(storage.physiometrics.infra, "get_table_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value = mock_table

            # Mock historical data
            mock_table.query_entities.return_value = [
                {
                    "effective_date": "2026-01-17",
                    "weight_kg": 76.0,
                    "data_source": "withings",
                },
                {
                    "effective_date": "2026-01-18",
                    "weight_kg": 75.5,
                    "data_source": "withings",
                },
                {
                    "effective_date": "2026-01-19",
                    "weight_kg": 75.2,
                    "data_source": "withings",
                },
            ]

            history = storage.physiometrics.get_physiometrics_history(
                athlete_id="rob",
                start_date="2026-01-17",
                end_date="2026-01-19",
                metrics=["weight_kg"],
            )

            assert len(history) == 3
            assert history[0]["weight_kg"] == pytest.approx(76.0)
            assert history[-1]["weight_kg"] == pytest.approx(75.2)

    def test_get_physiometrics_as_of(self, storage):
        """Test retrieving physiometrics effective on a specific date."""
        with patch.object(storage.physiometrics.infra, "get_table_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value = mock_table

            # Mock entries with different effective dates
            mock_table.query_entities.return_value = [
                {
                    "effective_date": "2026-01-15",
                    "power_ftp_watts": 280,
                    "full_config_json": json.dumps({"power": {"ftp_watts": 280}}),
                },
                {
                    "effective_date": "2026-01-18",
                    "power_ftp_watts": 285,
                    "full_config_json": json.dumps({"power": {"ftp_watts": 285}}),
                },
            ]

            # Query for Jan 17 should return Jan 15 config
            config = storage.physiometrics.get_physiometrics_as_of(
                athlete_id="rob", target_date="2026-01-17"
            )

            assert config["power"]["ftp_watts"] == 285

    def test_withings_token_storage(self, storage):
        """Test storing and retrieving Withings OAuth tokens."""
        with patch.object(storage.oauth_tokens.infra, "get_table_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value = mock_table

            storage.oauth_tokens.store_withings_tokens(
                athlete_id="rob",
                withings_userid="12345",
                access_token="access_token_abc",
                refresh_token="refresh_token_xyz",
                expires_in=10800,
                scope="user.metrics,user.info",
            )

            assert mock_table.upsert_entity.called
            entity = mock_table.upsert_entity.call_args[0][0]
            assert entity["PartitionKey"] == "rob"
            assert entity["RowKey"] == "12345"
            assert entity["access_token"] == "access_token_abc"
            assert entity["scope"] == "user.metrics,user.info"

    def test_webhook_deduplication(self, storage):
        """Test webhook deduplication logic."""
        with patch.object(storage.webhooks.infra, "get_table_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value = mock_table

            # First check - not processed
            mock_table.get_entity.side_effect = ResourceNotFoundError("Not found")
            assert not storage.webhooks.webhook_already_processed("rob", "12345", "1705622500")

            # Mark as processed
            storage.webhooks.mark_webhook_processed("rob", "12345", "1705622500")
            assert mock_table.upsert_entity.called

            # Second check - already processed
            mock_table.get_entity.side_effect = None
            mock_table.get_entity.return_value = {"PartitionKey": "rob"}
            assert storage.webhooks.webhook_already_processed("rob", "12345", "1705622500")


class TestSemanticLayerPhysiometrics:
    """Test semantic layer physiometrics methods."""

    @pytest.fixture
    def layer(self):
        """Create semantic layer with mocked storage."""
        with patch("TrainingAnalyticsPlatform.storage.storage_coordinator.StorageCoordinator"):
            return SemanticLayer()

    def test_get_current_physiometrics(self, layer):
        """Test retrieving current physiometrics consolidated across sources."""
        mock_table = MagicMock()
        mock_table.query_entities.return_value = [
            {
                "PartitionKey": "rob",
                "RowKey": "2026-01-19",
                "effective_date": "2026-01-19",
                "data_source": "withings",
                "updated_at_utc": "2026-01-19T08:00:00+00:00",
                "weight_kg": 75.2,
                "body_fat_pct": 16.4,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-01-20",
                "effective_date": "2026-01-20",
                "data_source": "intervals",
                "updated_at_utc": "2026-01-20T08:15:00+00:00",
                "hrv_ln_rmssd": 3.9,
                "heart_rate_resting_bpm": 48,
                "sleep_duration_sec": 28600,
            },
            {
                "PartitionKey": "rob",
                "RowKey": "2026-01-20",
                "effective_date": "2026-01-20",
                "data_source": "garmin",
                "updated_at_utc": "2026-01-20T08:20:00+00:00",
                "power_ftp_watts": 285,
                "cycling_vo2max_ml_kg_min": 52.3,
                "training_load": 310.0,
            },
        ]
        layer.storage.infrastructure.get_table_client = MagicMock(return_value=mock_table)

        result = layer.get_current_physiometrics("rob")

        assert result["athlete_id"] == "rob"
        assert result["weight_kg"] == pytest.approx(75.2)
        assert result["cycling_vo2max_ml_kg_min"] == pytest.approx(52.3)
        assert result["power"]["ftp_watts"] == 285
        assert result["heart_rate"]["resting_hr_bpm"] == 48
        assert result["training_load"] == pytest.approx(310.0)
        assert sorted(result["data_sources"]) == ["garmin", "intervals", "withings"]

    def test_update_physiometric_value(self, layer):
        """Test updating a single physiometric value."""
        layer.storage.physiometrics.update_single_metric = MagicMock(
            return_value="2026-01-19T14:32:15+00:00"
        )

        result = layer.update_physiometric_value(
            athlete_id="rob",
            metric="cycling_vo2max_ml_kg_min",
            value=52.3,
            effective_date="2026-01-19",
            source="chatgpt",
        )

        assert result["status"] == "success"
        assert result["metric"] == "cycling_vo2max_ml_kg_min"
        assert result["value"] == pytest.approx(52.3)
        assert layer.storage.physiometrics.update_single_metric.called

    def test_get_physiometrics_trends(self, layer):
        """Test retrieving time-series trends."""
        layer.storage.physiometrics.get_physiometrics_history = MagicMock(
            return_value=[
                {"effective_date": "2026-01-17", "weight_kg": 76.0},
                {"effective_date": "2026-01-18", "weight_kg": 75.5},
                {"effective_date": "2026-01-19", "weight_kg": 75.2},
            ]
        )

        result = layer.get_physiometrics_trends(
            athlete_id="rob", days=7, metrics=["weight_kg"]
        )

        assert result["athlete_id"] == "rob"
        assert result["count"] == 3
        assert len(result["data_points"]) == 3


class TestWithingsClient:
    """Test Withings API client."""

    def test_parse_measurement_group(self):
        """Test parsing Withings measurement group."""
        client = WithingsClient()

        measurement_group = {
            "date": 1705622400,
            "measures": [
                {"type": 1, "value": 75200, "unit": -3},  # Weight: 75.2 kg
                {"type": 6, "value": 166, "unit": -1},  # Body fat: 16.6%
                {"type": 76, "value": 38200, "unit": -3},  # Muscle: 38.2 kg
            ],
        }

        parsed = client.parse_measurement_group(measurement_group)

        assert parsed is not None
        assert parsed["weight_kg"] == pytest.approx(75.2)
        assert parsed["body_fat_pct"] == pytest.approx(16.6)
        assert parsed["muscle_mass_kg"] == pytest.approx(38.2)
        assert parsed["data_source"] == "withings"

    def test_parse_measurement_group_no_weight(self):
        """Test that measurements without weight are ignored."""
        client = WithingsClient()

        measurement_group = {
            "date": 1705622400,
            "measures": [
                {"type": 76, "value": 38200, "unit": -3},  # Only muscle mass
            ],
        }

        parsed = client.parse_measurement_group(measurement_group)

        # Should return None if no weight data
        assert parsed is None
