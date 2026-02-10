"""Integration tests for FIT parser with real FIT files."""

from pathlib import Path

import pytest

from FitParser.fit_parser import FitParser


pytestmark = pytest.mark.integration


class TestFitParserRealFiles:
    """Integration tests using real FIT files."""

    def test_parse_real_fit_file_extracts_sport_and_subsport(self) -> None:
        """Verify parser extracts sport and sub_sport from real FIT file."""
        fit_file = Path("./tests/data/2026-01-12-183000-Indoor Cycling-RunGap.fit")

        if not fit_file.exists():
            pytest.skip(f"Test FIT file not found: {fit_file}")

        parser = FitParser(str(fit_file))
        metrics = parser.parse()

        # Verify sport and sub_sport are populated
        assert metrics.get("sport") == "cycling"
        assert metrics.get("sub_sport") == "indoor_cycling"

    def test_parse_real_fit_file_extracts_all_metrics(self) -> None:
        """Verify parser extracts all metrics from real FIT file."""
        fit_file = Path("./tests/data/2026-01-12-183000-Indoor Cycling-RunGap.fit")

        if not fit_file.exists():
            pytest.skip(f"Test FIT file not found: {fit_file}")

        parser = FitParser(str(fit_file))
        metrics = parser.parse()

        # Verify key metrics are present and not None
        assert metrics.get("sport") is not None
        assert metrics.get("sub_sport") is not None
        assert metrics.get("start_time_utc") is not None
        assert metrics.get("end_time_utc") is not None
        assert metrics.get("duration_sec") is not None
        assert metrics.get("distance_m") is not None
        assert metrics.get("calories_kcal") is not None
        assert metrics.get("hr_avg_bpm") is not None
        assert metrics.get("hr_max_bpm") is not None

        # Verify values are reasonable
        duration_sec = metrics.get("duration_sec")
        distance_m = metrics.get("distance_m")
        calories_kcal = metrics.get("calories_kcal")
        assert duration_sec is not None and duration_sec > 0
        assert distance_m is not None and distance_m > 0
        assert calories_kcal is not None and calories_kcal > 0
