"""Unit normalization tests for canonical substrate record conversion."""

from datetime import datetime, timezone

import pytest

from TrainingAnalyticsPlatform.models.substrate import CanonicalRecord


class _FieldStub:
    def __init__(self, units: str) -> None:
        self.units = units


class _RecordMessageStub:
    def __init__(self, values: dict[str, object], units: dict[str, str]) -> None:
        self._values = values
        self._units = units

    def get_value(self, field_name: str, fallback: object = None) -> object:
        return self._values.get(field_name, fallback)

    def get_field(self, field_name_or_num: object, idx: int = 0) -> object:
        del idx
        key = str(field_name_or_num)
        if key in self._units:
            return _FieldStub(self._units[key])
        raise KeyError(key)

    def get_raw_value(self, field_name: str, fallback: object = None) -> object:
        return self._values.get(field_name, fallback)


def test_canonical_record_converts_record_distance_and_speed_units() -> None:
    msg = _RecordMessageStub(
        values={
            "timestamp": datetime(2026, 3, 10, 19, 55, 38, tzinfo=timezone.utc),
            "distance": 0.68253,
            "speed": 12.8124,
            "altitude": 4.2,
        },
        units={
            "distance": "km",
            "speed": "km/h",
        },
    )

    record = CanonicalRecord.from_fit_message(msg, start_dt=None)

    assert record is not None
    assert record.distance_m == pytest.approx(682.53)
    assert record.speed_mps == pytest.approx(3.559, abs=1e-3)


def test_canonical_record_prefers_enhanced_altitude_when_present() -> None:
    msg = _RecordMessageStub(
        values={
            "timestamp": datetime(2026, 4, 13, 16, 0, 49, tzinfo=timezone.utc),
            "distance": 1.25,
            "enhanced_altitude": 99.4,
        },
        units={
            "distance": "km",
            "enhanced_altitude": "m",
        },
    )

    record = CanonicalRecord.from_fit_message(msg, start_dt=None)

    assert record is not None
    assert record.elevation_m == pytest.approx(99.4)
