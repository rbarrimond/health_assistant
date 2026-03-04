"""Unit tests for PhysiometricsSnapshot model and storage conversion."""

# Test instantiation with partial optional fields is intentional.
# pylint: disable=missing-kwoa

import pytest
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot


class TestPhysiometricsSnapshotToStorageDict:
    """Tests for PhysiometricsSnapshot.to_storage_dict() typed boundary."""

    def test_to_storage_dict_includes_all_wellness_fields(self) -> None:
        """Verify to_storage_dict() includes HRV, sleep, and readiness fields."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            hrv_ln_rmssd=4.2,
            sleep_duration_min=480.0,
            readiness_score=85.0,
            resting_hr_bpm=52.0,
            ftp_watts=285.0,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["hrv_ln_rmssd"] == pytest.approx(4.2)
        assert storage_dict["sleep_duration_min"] == pytest.approx(480.0)
        assert storage_dict["readiness_score"] == pytest.approx(85.0)

    def test_to_storage_dict_includes_body_composition_fields(self) -> None:
        """Verify body composition fields are included in storage dict."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            weight_kg=75.5,
            fat_mass_kg=12.5,
            muscle_mass_kg=55.0,
            bone_mass_kg=3.2,
            body_fat_pct=16.5,
            visceral_fat_index=8.0,
            metabolic_age_years=28,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["weight_kg"] == pytest.approx(75.5)
        assert storage_dict["fat_mass_kg"] == pytest.approx(12.5)
        assert storage_dict["muscle_mass_kg"] == pytest.approx(55.0)
        assert storage_dict["bone_mass_kg"] == pytest.approx(3.2)
        assert storage_dict["body_fat_pct"] == pytest.approx(16.5)
        assert storage_dict["visceral_fat_index"] == pytest.approx(8.0)
        assert storage_dict["metabolic_age_years"] == 28

    def test_to_storage_dict_nested_heart_rate_structure(self) -> None:
        """Verify heart_rate is nested dict for legacy compatibility."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            resting_hr_bpm=52.0,
            hr_lthr_bpm=175.0,
            hr_max_bpm=195.0,
        )

        storage_dict = snapshot.to_storage_dict()

        assert "heart_rate" in storage_dict
        assert storage_dict["heart_rate"]["basis"] == "LTHR"
        assert storage_dict["heart_rate"]["resting_hr_bpm"] == pytest.approx(52.0)
        assert storage_dict["heart_rate"]["lthr_bpm"] == pytest.approx(175.0)
        assert storage_dict["heart_rate"]["hr_max_bpm"] == pytest.approx(195.0)

    def test_to_storage_dict_nested_power_structure(self) -> None:
        """Verify power is nested dict for legacy compatibility."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            ftp_watts=285.0,
        )

        storage_dict = snapshot.to_storage_dict()

        assert "power" in storage_dict
        assert storage_dict["power"]["ftp_watts"] == pytest.approx(285.0)

    def test_to_storage_dict_handles_null_wellness_fields(self) -> None:
        """Verify null wellness fields are included as None."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            hrv_ln_rmssd=None,
            sleep_duration_min=None,
            readiness_score=None,
        )

        storage_dict = snapshot.to_storage_dict()

        assert "hrv_ln_rmssd" in storage_dict
        assert storage_dict["hrv_ln_rmssd"] is None
        assert "sleep_duration_min" in storage_dict
        assert storage_dict["sleep_duration_min"] is None
        assert "readiness_score" in storage_dict
        assert storage_dict["readiness_score"] is None

    def test_to_storage_dict_includes_vo2max(self) -> None:
        """Verify VO2max field is included."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            cycling_vo2max_ml_kg_min=55.2,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["cycling_vo2max_ml_kg_min"] == pytest.approx(55.2)

    def test_to_storage_dict_complete_snapshot(self) -> None:
        """Verify complete snapshot with all fields converts correctly."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            # Body composition
            weight_kg=75.5,
            fat_mass_kg=12.5,
            muscle_mass_kg=55.0,
            bone_mass_kg=3.2,
            body_fat_pct=16.5,
            visceral_fat_index=8.0,
            metabolic_age_years=28,
            # Wellness
            hrv_ln_rmssd=4.2,
            resting_hr_bpm=52.0,
            sleep_duration_min=480.0,
            readiness_score=85.0,
            # Performance
            ftp_watts=285.0,
            cycling_vo2max_ml_kg_min=55.2,
            hr_lthr_bpm=175.0,
            hr_max_bpm=195.0,
        )

        storage_dict = snapshot.to_storage_dict()

        # Verify all top-level fields present
        assert "weight_kg" in storage_dict
        assert "hrv_ln_rmssd" in storage_dict
        assert "sleep_duration_min" in storage_dict
        assert "readiness_score" in storage_dict
        assert "heart_rate" in storage_dict
        assert "power" in storage_dict
        assert "cycling_vo2max_ml_kg_min" in storage_dict

        # Verify nested structures
        assert isinstance(storage_dict["heart_rate"], dict)
        assert isinstance(storage_dict["power"], dict)

        # Spot-check values
        assert storage_dict["hrv_ln_rmssd"] == pytest.approx(4.2)
        assert storage_dict["sleep_duration_min"] == pytest.approx(480.0)
        assert storage_dict["heart_rate"]["resting_hr_bpm"] == pytest.approx(52.0)
