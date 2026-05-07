"""Unit tests for TrainingAnalyticsPlatform.ingestion.value_utils."""

from TrainingAnalyticsPlatform.ingestion.value_utils import coerce_float


class TestCoerceFloat:
    """Tests for coerce_float value coercion helper."""

    def test_none_returns_none(self) -> None:
        assert coerce_float(None) is None

    def test_integer_returns_float(self) -> None:
        assert coerce_float(5) == 5.0
        assert isinstance(coerce_float(5), float)

    def test_float_returns_float(self) -> None:
        assert coerce_float(3.14) == 3.14

    def test_zero_returns_zero_float(self) -> None:
        assert coerce_float(0) == 0.0
        assert isinstance(coerce_float(0), float)

    def test_negative_number_returns_float(self) -> None:
        assert coerce_float(-7) == -7.0
        assert isinstance(coerce_float(-7), float)

    def test_string_returns_none(self) -> None:
        assert coerce_float("hello") is None

    def test_numeric_string_returns_none(self) -> None:
        assert coerce_float("3.14") is None

    def test_list_returns_none(self) -> None:
        assert coerce_float([1.0]) is None

    def test_bool_returns_float(self) -> None:
        # bool is a subclass of int in Python
        assert coerce_float(True) == 1.0
        assert coerce_float(False) == 0.0
