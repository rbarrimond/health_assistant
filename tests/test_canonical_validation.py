"""Test suite for CanonicalAnalyticsEngine 1 Hz enforcement."""

# pylint: disable=redefined-outer-name, no-member

import json
from typing import cast

import pandas as pd
import pytest
from FitParser.models import CanonicalAnalyticsEngine


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
