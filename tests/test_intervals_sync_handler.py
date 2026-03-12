"""Tests for Intervals.icu sync handler."""
from unittest.mock import MagicMock, Mock, patch

import pytest

from TrainingAnalyticsPlatform.handlers.intervals_sync_handler import IntervalsSyncHandler
from TrainingAnalyticsPlatform.ingestion.wellness_adapters import IntervalsPhysiometricsAdapter
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot
from TrainingAnalyticsPlatform.platform.exceptions import ExternalServiceError, StorageError


@pytest.fixture
def mock_storage():
    """Provide a mock storage coordinator."""
    storage = Mock()
    storage.physiometrics = Mock()
    storage.physiometrics.store_physiometrics = Mock(return_value="2025-03-01T00:00:00Z")
    return storage


@pytest.fixture
def mock_client():
    """Provide a mock Intervals.icu client."""
    client = Mock()
    return client


@pytest.fixture
def handler(mock_storage, mock_client):
    """Provide a handler with mocked dependencies."""
    return IntervalsSyncHandler(storage=mock_storage, client=mock_client)


class TestIntervalsSyncHandlerInit:
    """Tests for handler initialization."""

    def test_init_with_provided_client(self, mock_storage, mock_client):
        """Test initialization with provided client."""
        handler = IntervalsSyncHandler(storage=mock_storage, client=mock_client)
        assert handler.storage is mock_storage
        assert handler.client is mock_client
        assert isinstance(handler.adapter, IntervalsPhysiometricsAdapter)

    def test_init_without_client(self, mock_storage):
        """Test initialization without client (creates default)."""
        with patch(
            "TrainingAnalyticsPlatform.handlers.intervals_sync_handler.IntervalsicuClient"
        ):
            handler = IntervalsSyncHandler(storage=mock_storage)
            assert handler.storage is mock_storage


class TestIntervalsSyncHandlerHandle:
    """Tests for handler.handle() method with split IDs."""

    def test_handle_missing_intervals_athlete_id(self, handler):
        """Test handle with missing intervals_athlete_id returns 400."""
        response, status = handler.handle(
            intervals_athlete_id=None, athlete_id="rob"
        )
        assert status == 400
        assert "intervals_athlete_id" in response.get("error", "").lower()

    def test_handle_empty_intervals_athlete_id(self, handler):
        """Test handle with empty string intervals_athlete_id returns 400."""
        response, status = handler.handle(
            intervals_athlete_id="", athlete_id="rob"
        )
        assert status == 400
        assert "intervals_athlete_id" in response.get("error", "").lower()

    def test_handle_missing_storage_athlete_id(self, handler):
        """Test handle with missing athlete_id returns 400."""
        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id=None
        )
        assert status == 400
        assert "athlete_id" in response.get("error", "").lower()

    def test_handle_no_measurements(self, handler, mock_client):
        """Test handle when API returns no measurements."""
        mock_client.get_athlete_wellness.return_value = []

        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        assert status == 200
        assert response["count"] == 0
        assert "no measurements" in response.get("message", "").lower()
        # Verify client called with intervals_athlete_id
        mock_client.get_athlete_wellness.assert_called_once()
        call_kwargs = mock_client.get_athlete_wellness.call_args[1]
        assert call_kwargs["athlete_id"] == "i508584"

    def test_handle_success_single_measurement(self, handler, mock_storage, mock_client):
        """Test successful handling with split IDs."""
        measurement = {
            "id": "2025-03-01",
            "hrvRMSSD": 42.5,
            "restingHR": 52,
            "sleepSecs": 28800,
            "readiness": 78,
        }
        mock_client.get_athlete_wellness.return_value = [measurement]

        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        assert status == 200
        assert response["count"] == 1
        assert "synced" in response.get("message", "").lower()
        
        # Verify client called with intervals_athlete_id
        mock_client.get_athlete_wellness.assert_called_once()
        call_kwargs = mock_client.get_athlete_wellness.call_args[1]
        assert call_kwargs["athlete_id"] == "i508584"
        
        # Verify storage called with athlete_id (storage partition)
        mock_storage.physiometrics.store_physiometrics.assert_called_once()
        store_call_kwargs = mock_storage.physiometrics.store_physiometrics.call_args[1]
        assert store_call_kwargs["athlete_id"] == "rob"

    def test_handle_success_multiple_measurements(self, handler, mock_storage, mock_client):
        """Test successful handling of multiple measurements."""
        measurements = [
            {
                "id": "2025-02-28",
                "hrvRMSSD": 40.0,
                "restingHR": 53,
                "sleepSecs": 27000,
                "readiness": 75,
            },
            {
                "id": "2025-03-01",
                "hrvRMSSD": 42.5,
                "restingHR": 52,
                "sleepSecs": 28800,
                "readiness": 78,
            },
        ]
        mock_client.get_athlete_wellness.return_value = measurements

        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        assert status == 200
        assert response["count"] == 2
        assert mock_storage.physiometrics.store_physiometrics.call_count == 2
        
        # Verify all storage calls used correct athlete_id
        for call in mock_storage.physiometrics.store_physiometrics.call_args_list:
            assert call[1]["athlete_id"] == "rob"

    def test_handle_with_lookback_days(self, handler, mock_client):
        """Test handle with custom lookback days."""
        mock_client.get_athlete_wellness.return_value = []

        handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob", lookback_days=60
        )

        # Verify client was called with dates matching lookback
        assert mock_client.get_athlete_wellness.called
        call_kwargs = mock_client.get_athlete_wellness.call_args[1]
        assert call_kwargs["athlete_id"] == "i508584"
        assert "oldest" in call_kwargs
        assert "newest" in call_kwargs

    def test_handle_api_error(self, handler, mock_client):
        """Test handle when API call fails."""
        mock_client.get_athlete_wellness.side_effect = ExternalServiceError(
            "API connection failed"
        )

        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        assert status == 502
        assert "error" in response
        assert "api" in response.get("error", "").lower()

    def test_handle_storage_error(self, handler, mock_storage, mock_client):
        """Test handle when storage call fails."""
        measurement = {
            "id": "2025-03-01",
            "hrvRMSSD": 42.5,
            "restingHR": 52,
            "sleepSecs": 28800,
            "readiness": 78,
        }
        mock_client.get_athlete_wellness.return_value = [measurement]
        mock_storage.physiometrics.store_physiometrics.side_effect = StorageError(
            "Storage failed"
        )

        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        assert status == 200  # Partial success - error caught and logged
        assert response["count"] == 0
        assert response.get("errors") is not None

    def test_handle_partial_success_with_errors(self, handler, mock_storage, mock_client):
        """Test handle with partial success (some measurements fail)."""
        measurements = [
            {
                "id": "2025-02-28",
                "hrvRMSSD": 40.0,
                "restingHR": 53,
                "sleepSecs": 27000,
                "readiness": 75,
            },
            {
                "id": "2025-03-01",
                # Invalid - missing sleep field
            },
        ]
        mock_client.get_athlete_wellness.return_value = measurements

        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        # First measurement succeeds, second fails validation
        assert status == 200
        assert response["count"] == 1
        assert response.get("errors") is not None
        assert len(response["errors"]) > 0

    def test_handle_unexpected_error(self, handler, mock_client):
        """Test handle when unexpected error occurs."""
        mock_client.get_athlete_wellness.side_effect = RuntimeError("Unexpected error")

        response, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        assert status == 500
        assert "error" in response
        assert "internal" in response.get("error", "").lower()

    def test_handle_converts_snapshot_to_storage_dict(
        self, handler, mock_storage, mock_client
    ):
        """Test that snapshot is properly converted to storage dict."""
        measurement = {
            "id": "2025-03-01",
            "hrvRMSSD": 42.5,
            "restingHR": 52,
            "sleepSecs": 28800,
            "readiness": 78,
        }
        mock_client.get_athlete_wellness.return_value = [measurement]

        _, status = handler.handle(
            intervals_athlete_id="i508584", athlete_id="rob"
        )

        assert status == 200
        # Verify storage was called with proper structure
        call_args = mock_storage.physiometrics.store_physiometrics.call_args
        assert call_args is not None
        kwargs = call_args[1]
        assert kwargs["athlete_id"] == "rob"
        assert kwargs["data_source"] == "intervals"
        assert kwargs["effective_date"] == "2025-03-01"
        # Verify flat keys from schema v3.0.0 are present
        assert "resting_hr_bpm" in kwargs["physiometrics_data"]
        assert "hrv_ln_rmssd" in kwargs["physiometrics_data"]
        assert "readiness_score" in kwargs["physiometrics_data"]
        assert "sleep_duration_sec" in kwargs["physiometrics_data"]


class TestIntervalsPhysiometricsAdapter:
    """Direct tests for IntervalsPhysiometricsAdapter field mapping."""

    @pytest.fixture
    def adapter(self):
        """Provide an adapter instance."""
        return IntervalsPhysiometricsAdapter()

    def test_adapter_maps_extended_wellness_fields(self, adapter):
        """Verify adapter maps v3.0.0 fields and ignores removed extended fields."""
        raw_data = {
            "id": "2025-03-01",
            "updated": "2025-03-01T12:34:56.000+00:00",
            # Original fields
            "hrvRMSSD": 42.5,
            "hrvSDNN": 38.2,
            "restingHR": 52,
            "sleepSecs": 28800,
            "readiness": 78,
            "weight": 88.4,
            "bodyFat": 20.9,
            # Extended wellness fields (subjective)
            "soreness": 3.0,
            "fatigue": 4.0,
            "stress": 2.0,
            "mood": 8.0,
            "motivation": 7.0,
            "injury": 0.0,
            # Nutrition
            "kcalConsumed": 2500.0,
            "carbohydrates": 300.0,
            "protein": 150.0,
            "fatTotal": 80.0,
            # Activity
            "steps": 12500,
            # Body composition
            "abdomen": 85.5,
            "spO2": 97,
            "systolic": 128,
            "diastolic": 76,
            "vo2max": 46.2,
            "menstrualPhase": "follicular",
            "menstrualPhasePredicted": "ovulatory",
            # Sport-specific
            "sportInfo": [
                {"type": "Ride", "load": 120.5, "ctl": 85.2},
                {"type": "Run", "load": 45.3, "ctl": 42.1},
            ],
        }

        # Parse raw API response
        parsed = adapter._do_parse(raw_data)
        # Map to canonical model
        snapshot = adapter.map_to_canonical(parsed=parsed, athlete_id="test_athlete")

        # Verify v3.0.0 fields
        assert snapshot.effective_date == "2025-03-01"
        assert snapshot.hrv_ln_rmssd == pytest.approx(42.5)
        assert snapshot.resting_hr_bpm == pytest.approx(52.0)
        assert snapshot.sleep_duration_sec == pytest.approx(28800.0)
        assert snapshot.readiness_score == pytest.approx(78.0)
        assert snapshot.weight_kg is None
        assert snapshot.body_fat_pct is None

        # Verify nutrition fields
        assert snapshot.calories_kcal == pytest.approx(2500.0)
        assert snapshot.carbs_g == pytest.approx(300.0)
        assert snapshot.protein_g == pytest.approx(150.0)
        assert snapshot.fat_g == pytest.approx(80.0)

        # Verify activity fields
        assert snapshot.steps == 12500

        # Removed fields are intentionally not part of PhysiometricsSnapshot v3.0.0.
        assert not hasattr(snapshot, "hrv_sdnn_ms")
        assert not hasattr(snapshot, "soreness")
        assert not hasattr(snapshot, "sport_info")

    def test_adapter_handles_missing_extended_fields(self, adapter):
        """Verify adapter handles missing optional v3.0.0 fields gracefully."""
        raw_data = {
            "id": "2025-03-01",
            # Only minimal required fields
            "hrvRMSSD": 42.5,
            "restingHR": 52,
            "sleepSecs": 28800,
            "readiness": 78,
            # All extended fields missing
        }

        # Parse raw API response
        parsed = adapter._do_parse(raw_data)
        # Map to canonical model
        snapshot = adapter.map_to_canonical(parsed=parsed, athlete_id="test_athlete")

        assert snapshot.calories_kcal is None
        assert snapshot.carbs_g is None
        assert snapshot.protein_g is None
        assert snapshot.fat_g is None
        assert snapshot.steps is None
        assert not hasattr(snapshot, "soreness")
        assert not hasattr(snapshot, "sport_info")

    def test_adapter_handles_partial_extended_fields(self, adapter):
        """Verify adapter maps retained fields and ignores removed extended fields."""
        raw_data = {
            "id": "2025-03-01",
            "hrvRMSSD": 42.5,
            "restingHR": 52,
            "sleepSecs": 28800,
            "readiness": 78,
            # Only some extended fields present
            "soreness": 3.0,
            "steps": 10000,
            "protein": 120.0,
            # Others missing
        }

        # Parse raw API response
        parsed = adapter._do_parse(raw_data)
        # Map to canonical model
        snapshot = adapter.map_to_canonical(parsed=parsed, athlete_id="test_athlete")

        # Verify present retained fields are captured
        assert snapshot.steps == 10000
        assert snapshot.protein_g == pytest.approx(120.0)

        # Verify missing retained fields are None
        assert snapshot.calories_kcal is None
        assert not hasattr(snapshot, "soreness")
        assert not hasattr(snapshot, "sport_info")

    def test_adapter_sport_info_empty_list(self, adapter):
        """Verify removed sportInfo field is ignored by v3.0.0 adapter."""
        raw_data = {
            "id": "2025-03-01",
            "hrvRMSSD": 42.5,
            "restingHR": 52,
            "sleepSecs": 28800,
            "readiness": 78,
            "sportInfo": [],
        }

        # Parse raw API response
        parsed = adapter._do_parse(raw_data)
        # Map to canonical model
        snapshot = adapter.map_to_canonical(parsed=parsed, athlete_id="test_athlete")

        assert not hasattr(snapshot, "sport_info")

