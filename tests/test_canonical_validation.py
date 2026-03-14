"""Test suite for CanonicalAnalyticsEngine 1 Hz enforcement."""

# pylint: disable=redefined-outer-name, no-member

import json
from datetime import datetime, timedelta, timezone
from typing import cast

import pandas as pd
import pytest
from pydantic import ValidationError

from TrainingAnalyticsPlatform.models import (
    CanonicalAnalyticsEngine,
    CanonicalRecord,
    CanonicalRecordSet,
)


@pytest.fixture
def df_non1hz():
    """Non-1Hz test data (2-second intervals)."""
    return pd.DataFrame({
        'elapsed_sec': [0, 2, 4, 6, 8],
        'power_watts': [100, 150, 200, 180, 160],
        'heart_rate_bpm': [120, 125, 130, 128, 126]
    })


@pytest.fixture
def df_1hz():
    """1Hz test data (1-second intervals)."""
    return pd.DataFrame({
        'elapsed_sec': [0, 1, 2, 3, 4],
        'power_watts': [100, 150, 200, 180, 160],
        'heart_rate_bpm': [120, 125, 130, 128, 126]
    })


@pytest.fixture
def df_no_time():
    """Test data without temporal columns."""
    return pd.DataFrame({
        'power_watts': [100, 150, 200, 180, 160],
        'heart_rate_bpm': [120, 125, 130, 128, 126]
    })


def test_reject_non1hz_without_resample_flag(df_non1hz):
    """Non-1Hz data should be rejected when resample=False (default)."""
    with pytest.raises(Exception, match=".*not 1 Hz sampled.*"):
        CanonicalAnalyticsEngine(df=df_non1hz, metadata={})


def test_accept_non1hz_with_resample_flag(df_non1hz):
    """Non-1Hz data should be resampled when resample=True."""
    metrics = CanonicalAnalyticsEngine(df=df_non1hz, metadata={}, resample=True)
    df = cast(pd.DataFrame, metrics.df)

    # After resampling 5 rows at 2s intervals (0-8s) should become 9 rows at 1s intervals
    assert df.shape[0] == 9
    assert 'elapsed_sec' in df.columns or df.index.name == 'timestamp_utc'

    # Verify computed fields work
    assert metrics.pwr_avg_watts is not None
    assert metrics.pwr_avg_watts == pytest.approx(158.0, rel=0.1)


def test_accept_1hz_data_without_resampling(df_1hz):
    """1Hz data should be accepted without modification."""
    metrics = CanonicalAnalyticsEngine(df=df_1hz, metadata={})
    df = cast(pd.DataFrame, metrics.df)

    assert df.shape[0] == 5
    assert 'elapsed_sec' in df.columns or df.index.name == 'timestamp_utc'

    # Verify computed fields work
    assert metrics.pwr_avg_watts == pytest.approx(158.0, rel=0.01)
    assert metrics.hr_avg_bpm == pytest.approx(125.8, rel=0.01)


def test_model_dump_returns_metrics_only(df_1hz):
    """model_dump should return the metrics dict without raw fields."""
    metrics = CanonicalAnalyticsEngine(df=df_1hz, metadata={})

    dumped = metrics.model_dump()
    assert dumped == metrics.to_metrics_dict()
    assert "df" not in dumped


def test_model_dump_json_returns_metrics_only(df_1hz):
    """model_dump_json should serialize the metrics-only payload."""
    metrics = CanonicalAnalyticsEngine(df=df_1hz, metadata={})

    dumped_json = metrics.model_dump_json()
    dumped = json.loads(dumped_json)

    assert dumped == metrics.to_metrics_dict()
    assert "df" not in dumped


def test_from_dataframe_supports_resample(df_non1hz):
    """from_dataframe classmethod should support resample parameter."""
    metrics = CanonicalAnalyticsEngine.from_dataframe(df_non1hz, {}, resample=True)
    df = cast(pd.DataFrame, metrics.df)

    # After resampling 5 rows at 2s intervals should become 9 rows at 1s intervals
    assert df.shape[0] == 9
    assert 'elapsed_sec' in df.columns or df.index.name == 'timestamp_utc'


def test_reject_data_without_temporal_columns(df_no_time):
    """Data without timestamp_utc or elapsed_sec should be rejected."""
    with pytest.raises(ValueError, match=".*temporal index.*"):
        CanonicalAnalyticsEngine(df=df_no_time, metadata={})


# =========================================================================
# RR Intervals Field Type and Validation Tests
# =========================================================================


def test_canonical_record_rr_intervals_field_type():
    """rr_intervals_sec field must be tuple type, never None or list."""
    # Default should be empty tuple
    rec = CanonicalRecord(timestamp_utc="2026-01-01T00:00:00+00:00")  # type: ignore
    assert rec.rr_intervals_sec == ()
    assert isinstance(rec.rr_intervals_sec, tuple)


def test_canonical_record_rr_intervals_accepts_tuple():
    """rr_intervals_sec should accept tuple input."""
    rec = CanonicalRecord(  # type: ignore
        timestamp_utc="2026-01-01T00:00:00+00:00",
        rr_intervals_sec=(0.6, 0.7, 0.8),
    )
    assert rec.rr_intervals_sec == (0.6, 0.7, 0.8)


def test_canonical_record_rr_intervals_converts_list_to_tuple():
    """rr_intervals_sec should convert list input to tuple."""
    rec = CanonicalRecord(  # type: ignore
        timestamp_utc="2026-01-01T00:00:00+00:00",
        rr_intervals_sec=[0.6, 0.7, 0.8],
    )
    assert rec.rr_intervals_sec == (0.6, 0.7, 0.8)
    assert isinstance(rec.rr_intervals_sec, tuple)


def test_canonical_record_rr_intervals_validates_non_negative():
    """rr_intervals_sec should reject negative values."""
    with pytest.raises(ValidationError, match="non-negative"):
        CanonicalRecord(  # type: ignore
            timestamp_utc="2026-01-01T00:00:00+00:00",
            rr_intervals_sec=[0.6, -0.7, 0.8],
        )


def test_canonical_record_rr_intervals_immutable():
    """rr_intervals_sec tuple should be immutable."""
    rec = CanonicalRecord(  # type: ignore
        timestamp_utc="2026-01-01T00:00:00+00:00",
        rr_intervals_sec=(0.6, 0.7, 0.8),
    )
    with pytest.raises(AttributeError):
        rec.rr_intervals_sec.append(0.9)  # type: ignore


# =========================================================================
# HRV Merging and Order Preservation Tests
# =========================================================================


class MockFitDataMessage:
    """Mock FitDataMessage for testing HRV merging and grouping."""

    def __init__(self, name: str, **field_values):
        self.name = name
        self._field_values = field_values
        self.fields = []

        # Mock fields list for time extraction
        for key, value in field_values.items():
            if key.startswith("time"):
                self.fields.append(type("Field", (), {"name": key, "value": value})())

    def get_value(self, field_name: str, fallback=None):
        """Mock get_value method to retrieve field values."""
        return self._field_values.get(field_name, fallback)

    def get_raw_value(self, field_name: str, fallback=None):
        """Mock get_raw_value method (same as get_value since mock doesn't apply enum rendering)."""
        return self._field_values.get(field_name, fallback)


def test_hrv_merging_with_timestamped_message():  # pylint: disable=protected-access
    """Test HRV grouping with timestamped messages (Mode 1: authoritative timestamp)."""
    # Create mock messages
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # One record at the start
    record_msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
        power=100,
    )

    # One HRV message with explicit timestamp and RR intervals
    # RR intervals: 0.6s after timestamp, 0.7s after that (cross 1Hz boundary)
    hrv_msg = MockFitDataMessage(
        "hrv",
        timestamp=base_time + timedelta(seconds=0.5),
        time0=0.6,
        time1=0.7,
    )

    record_set = CanonicalRecordSet(  # type: ignore
        messages=[record_msg],  # type: ignore
        all_messages=[record_msg, hrv_msg],  # type: ignore
    )

    hrv_map = record_set._build_hrv_interval_map([record_msg, hrv_msg])  # type: ignore  # pylint: disable=protected-access

    # Beats should be at:
    # - 0.5 + 0.6 = 1.1s (floor = base_time + 1s)
    # - 0.5 + 0.6 + 0.7 = 1.8s (floor = base_time + 1s)
    floor_1s = int((base_time + timedelta(seconds=1)).timestamp())
    assert floor_1s in hrv_map
    assert hrv_map[floor_1s] == (0.6, 0.7)


def test_hrv_stream_order_preservation():  # pylint: disable=protected-access
    """Test that HRV grouper preserves original stream order (not sorted)."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    record_msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
    )

    # HRV with intervals in non-monotonic order within same second
    # This tests that we don't implicitly sort
    hrv_msg = MockFitDataMessage(
        "hrv",
        timestamp=base_time + timedelta(seconds=0.2),
        time0=0.5,
        time1=0.3,
        time2=0.4,
    )

    record_set = CanonicalRecordSet(  # type: ignore
        messages=[record_msg],  # type: ignore
        all_messages=[record_msg, hrv_msg],  # type: ignore
    )

    hrv_map = record_set._build_hrv_interval_map([record_msg, hrv_msg])  # type: ignore  # pylint: disable=protected-access

    # Beats:
    # - 0.2 + 0.5 = 0.7s (floor = base_time + 0s)
    # - 0.2 + 0.5 + 0.3 = 1.0s (floor = base_time + 1s)
    # - 0.2 + 0.5 + 0.3 + 0.4 = 1.4s (floor = base_time + 1s)
    floor_0s = int(base_time.timestamp())
    floor_1s = int((base_time + timedelta(seconds=1)).timestamp())

    assert floor_0s in hrv_map
    assert floor_1s in hrv_map
    # Order must be preserved: 0.5 in first second, then 0.3, 0.4 in second second
    assert hrv_map[floor_0s] == (0.5,)
    assert hrv_map[floor_1s] == (0.3, 0.4)


def test_hrv_grouping_multiple_messages():  # pylint: disable=protected-access
    """Test HRV grouping across multiple HRV messages (preserves order)."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    record_msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
    )

    # First HRV message at +0.2s
    hrv_msg1 = MockFitDataMessage(
        "hrv",
        timestamp=base_time + timedelta(seconds=0.2),
        time0=0.5,
        time1=0.3,
    )

    # Second HRV message at +1.5s (should start new second)
    hrv_msg2 = MockFitDataMessage(
        "hrv",
        timestamp=base_time + timedelta(seconds=1.5),
        time0=0.4,
        time1=0.6,
    )

    record_set = CanonicalRecordSet(  # type: ignore
        messages=[record_msg],  # type: ignore
        all_messages=[record_msg, hrv_msg1, hrv_msg2],  # type: ignore
    )

    hrv_map = record_set._build_hrv_interval_map([record_msg, hrv_msg1, hrv_msg2])  # type: ignore  # pylint: disable=protected-access

    # First HRV message: 0.2 + 0.5 = 0.7 (floor=base_time+0s),
    # 0.2 + 0.5 + 0.3 = 1.0 (floor=base_time+1s)
    # Second HRV message: 1.5 + 0.4 = 1.9 (floor=base_time+1s),
    # 1.5 + 0.4 + 0.6 = 2.5 (floor=base_time+2s)
    floor_0s = int(base_time.timestamp())
    floor_1s = int((base_time + timedelta(seconds=1)).timestamp())
    floor_2s = int((base_time + timedelta(seconds=2)).timestamp())

    assert floor_0s in hrv_map
    assert floor_1s in hrv_map
    assert floor_2s in hrv_map

    assert hrv_map[floor_0s] == (0.5,)
    assert hrv_map[floor_2s] == (0.6,)


def test_hrv_no_intervals_dropped():  # pylint: disable=protected-access
    """Test that RR intervals are never dropped (count preservation)."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    record_msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
    )

    hrv_msg = MockFitDataMessage(
        "hrv",
        timestamp=base_time + timedelta(seconds=0.1),
        time0=0.6,
        time1=0.7,
        time2=0.5,
        time3=0.8,
    )

    record_set = CanonicalRecordSet(  # type: ignore
        messages=[record_msg],  # type: ignore
        all_messages=[record_msg, hrv_msg],  # type: ignore
    )

    hrv_map = record_set._build_hrv_interval_map([record_msg, hrv_msg])  # type: ignore  # pylint: disable=protected-access

    # Total RR intervals in FIT
    total_fit_intervals = 4

    # Total intervals in output
    total_output_intervals = sum(len(intervals) for intervals in hrv_map.values())

    assert total_output_intervals == total_fit_intervals


# =========================================================================
# Parquet Serialization Tests
# =========================================================================


def test_canonical_record_parquet_roundtrip_tuple():
    """Test that rr_intervals_sec tuple serializes and deserializes correctly."""
    rec = CanonicalRecord(  # type: ignore
        timestamp_utc="2026-01-01T00:00:00+00:00",
        power_watts=100.0,
        rr_intervals_sec=(0.6, 0.7, 0.8),
    )

    # Serialize to dict (what model_dump does)
    dumped = rec.model_dump()
    assert isinstance(dumped["rr_intervals_sec"], (list, tuple))

    # Create DataFrame (what to_dataframe does)
    df = pd.DataFrame([dumped])

    # Verify column exists and has tuple/list value
    assert "rr_intervals_sec" in df.columns
    assert len(df) == 1


def test_canonical_recordset_to_dataframe_with_rr_intervals():
    """Test CanonicalRecordSet.to_dataframe includes merged RR intervals."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    record_msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
        power=100,
    )

    hrv_msg = MockFitDataMessage(
        "hrv",
        timestamp=base_time,
        time0=0.6,
        time1=0.7,
    )

    record_set = CanonicalRecordSet(  # type: ignore
        messages=[record_msg],  # type: ignore
        all_messages=[record_msg, hrv_msg],  # type: ignore
    )

    df = record_set.to_dataframe

    assert not df.empty
    assert "rr_intervals_sec" in df.columns
    # First row should have the merged RR intervals
    rr_val = df["rr_intervals_sec"].iloc[0]
    assert isinstance(rr_val, (tuple, list))


# =========================================================================
# Resampling Tests
# =========================================================================


def test_resampling_aggregates_rr_intervals():
    """Test that resampling concatenates RR interval tuples (not .first())."""
    df = pd.DataFrame({
        "timestamp_utc": [
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:01+00:00",
            "2026-01-01T00:00:02+00:00",
        ],
        "elapsed_sec": [0, 1, 2],
        "power_watts": [100, 150, 200],
        "rr_intervals_sec": [
            (0.6,),
            (0.7, 0.8),
            (0.5,),
        ],
    })

    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
    df.set_index("timestamp_utc", inplace=True)

    # Create engine with resample (will combine 3 x 1Hz records into fewer)
    metrics = CanonicalAnalyticsEngine(df=df, metadata={}, resample=True)

    # After resampling, check that RR intervals are preserved (concatenated)
    assert "rr_intervals_sec" in metrics.df.columns
    rr_vals = metrics.df["rr_intervals_sec"]
    # At least one cell should have multiple intervals (concatenated)
    assert any(
        isinstance(rv, (tuple, list)) and len(rv) > 1
        for rv in rr_vals
        if rv is not None
    )


# =========================================================================
# FIT Field Decoding Tests
# =========================================================================


def test_canonical_record_from_fit_message_masks_left_right_balance():
    """Test that left_right_balance is masked from raw byte (bits 0-6) to percentage."""
    # FIT spec: left_right_balance uint8 where bits 0-6 = percentage, bit 7 = right flag
    # Raw byte 184 (0xB8 = 10111000) → bits 0-6 = 0111000 = 56%
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
        power=100,
        left_right_balance=184,  # Raw FIT byte with flag bit set
    )

    record = CanonicalRecord.from_fit_message(msg)  # type: ignore

    # Should be masked to 56 (184 & 0x7F = 56)
    assert record is not None
    assert record.lr_balance_pct == pytest.approx(56.0)


def test_canonical_record_from_fit_message_preserves_clean_balance():
    """Test that left_right_balance within 0-100 range passes through correctly."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
        power=100,
        left_right_balance=75,  # Already within range
    )

    record = CanonicalRecord.from_fit_message(msg)  # type: ignore

    # Should pass through unchanged (75 & 0x7F = 75)
    assert record is not None
    assert record.lr_balance_pct == pytest.approx(75.0)


def test_canonical_record_from_fit_message_handles_none_balance():
    """Test that left_right_balance=None is handled gracefully."""
    base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    msg = MockFitDataMessage(
        "record",
        timestamp=base_time,
        power=100,
        left_right_balance=None,
    )

    record = CanonicalRecord.from_fit_message(msg)  # type: ignore

    # Should pass through as None
    assert record is not None
    assert record.lr_balance_pct is None


# =========================================================================
# HR–Power Lag Signed Semantics Tests
# =========================================================================
# Regression tests for https://github.com/rbarrimond/health_assistant issues
# where DurabilityMetricsModel.hr_power_lag_sec incorrectly enforced ge=0,
# rejecting valid negative lag values produced by the cross-correlation
# algorithm (τ search range [-60, +60] per formula contract).


def test_durability_metrics_model_accepts_negative_lag():
    """DurabilityMetricsModel must accept negative hr_power_lag_sec values.

    Formula contract defines τ ∈ [-60, +60]; negative values are semantically
    valid (HR leads power). The previous ge=0 constraint was incorrect.
    Bug: production error with input_value=-27 aborting athlete rollups.
    """
    from TrainingAnalyticsPlatform.models import DurabilityMetricsModel

    # Should not raise — negative lag is contractually valid
    model = DurabilityMetricsModel(hr_power_lag_sec=-27)  # type: ignore
    assert model.hr_power_lag_sec == -27


def test_durability_metrics_model_accepts_positive_lag():
    """DurabilityMetricsModel accepts positive hr_power_lag_sec (normal physiological lag)."""
    from TrainingAnalyticsPlatform.models import DurabilityMetricsModel

    model = DurabilityMetricsModel(hr_power_lag_sec=15)  # type: ignore
    assert model.hr_power_lag_sec == 15


def test_durability_metrics_model_accepts_zero_lag():
    """DurabilityMetricsModel accepts zero hr_power_lag_sec."""
    from TrainingAnalyticsPlatform.models import DurabilityMetricsModel

    model = DurabilityMetricsModel(hr_power_lag_sec=0)  # type: ignore
    assert model.hr_power_lag_sec == 0


def test_durability_metrics_model_accepts_none_lag():
    """DurabilityMetricsModel accepts None hr_power_lag_sec (insufficient data)."""
    from TrainingAnalyticsPlatform.models import DurabilityMetricsModel

    model = DurabilityMetricsModel(hr_power_lag_sec=None)  # type: ignore
    assert model.hr_power_lag_sec is None


def test_durability_metrics_model_rejects_lag_below_minus_60():
    """DurabilityMetricsModel rejects lag below -60 (outside formula contract search range)."""
    from pydantic import ValidationError as PydanticValidationError

    from TrainingAnalyticsPlatform.models import DurabilityMetricsModel

    with pytest.raises(PydanticValidationError):
        DurabilityMetricsModel(hr_power_lag_sec=-61)  # type: ignore


def test_durability_metrics_model_rejects_lag_above_60():
    """DurabilityMetricsModel rejects lag above +60 (outside formula contract search range)."""
    from pydantic import ValidationError as PydanticValidationError

    from TrainingAnalyticsPlatform.models import DurabilityMetricsModel

    with pytest.raises(PydanticValidationError):
        DurabilityMetricsModel(hr_power_lag_sec=61)  # type: ignore


def test_canonical_engine_produces_lag_within_signed_range():
    """CanonicalAnalyticsEngine.hr_power_lag_sec must fall within [-60, +60] or be None."""
    # Construct 1Hz data where HR rises before power drops (should yield negative lag)
    n = 120
    elapsed = list(range(n))
    # Power drops after 60s; HR anticipates and starts dropping from 50s
    power = [200] * 60 + [150] * 60
    hr = [140] * 50 + [130] * 70  # HR drops 10s before power

    df = pd.DataFrame({
        "elapsed_sec": elapsed,
        "power_watts": [float(p) for p in power],
        "heart_rate_bpm": [float(h) for h in hr],
    })

    engine = CanonicalAnalyticsEngine(df=df, metadata={})
    lag = engine.hr_power_lag_sec

    assert lag is None or -60 <= lag <= 60


def test_canonical_engine_negative_lag_does_not_raise():
    """CanonicalAnalyticsEngine should not raise when hr_power_lag_sec is negative.

    This is a regression test for the production crash where negative lag
    propagated to DurabilityMetricsModel and was rejected by ge=0.
    """
    n = 120
    elapsed = list(range(n))
    power = [200] * 60 + [150] * 60
    hr = [140] * 50 + [130] * 70  # HR leads power drop

    df = pd.DataFrame({
        "elapsed_sec": elapsed,
        "power_watts": [float(p) for p in power],
        "heart_rate_bpm": [float(h) for h in hr],
    })

    # Must not raise — DurabilityMetricsModel now accepts signed lag
    engine = CanonicalAnalyticsEngine(df=df, metadata={})
    metrics = engine.to_metrics_dict()

    assert "hr_power_lag_sec" in metrics
    lag = metrics["hr_power_lag_sec"]
    assert lag is None or isinstance(lag, int)
