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
            sleep_duration_sec=28800.0,
            readiness_score=85.0,
            resting_hr_bpm=52.0,
            ftp_watts=285.0,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["hrv_ln_rmssd"] == pytest.approx(4.2)
        assert storage_dict["sleep_duration_sec"] == pytest.approx(28800.0)
        assert storage_dict["readiness_score"] == pytest.approx(85.0)

    def test_to_storage_dict_includes_body_composition_fields(self) -> None:
        """Verify body composition fields are included in storage dict (v3.0.0)."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            weight_kg=75.5,
            fat_mass_kg=12.5,
            muscle_mass_kg=55.0,
            bone_mass_kg=3.2,
            body_fat_pct=16.5,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["weight_kg"] == pytest.approx(75.5)
        assert storage_dict["fat_mass_kg"] == pytest.approx(12.5)
        assert storage_dict["muscle_mass_kg"] == pytest.approx(55.0)
        assert storage_dict["bone_mass_kg"] == pytest.approx(3.2)
        assert storage_dict["body_fat_pct"] == pytest.approx(16.5)

    def test_to_storage_dict_heart_rate_fields(self) -> None:
        """Verify heart rate fields are flat (v3.0.0 simplified schema)."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            resting_hr_bpm=52.0,
            hr_lthr_bpm=175.0,
            hr_max_bpm=195.0,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["resting_hr_bpm"] == pytest.approx(52.0)
        assert storage_dict["hr_lthr_bpm"] == pytest.approx(175.0)
        assert storage_dict["hr_max_bpm"] == pytest.approx(195.0)

    def test_to_storage_dict_power_field(self) -> None:
        """Verify power field is flat (v3.0.0 simplified schema)."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            ftp_watts=285.0,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["ftp_watts"] == pytest.approx(285.0)

    def test_to_storage_dict_handles_null_wellness_fields(self) -> None:
        """Verify null wellness fields are included as None."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            hrv_ln_rmssd=None,
            sleep_duration_sec=None,
            readiness_score=None,
        )

        storage_dict = snapshot.to_storage_dict()

        assert "hrv_ln_rmssd" in storage_dict
        assert storage_dict["hrv_ln_rmssd"] is None
        assert "sleep_duration_sec" in storage_dict
        assert storage_dict["sleep_duration_sec"] is None
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
        """Verify complete v3.0.0 snapshot with all fields converts correctly."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            # Body composition (Withings exclusive)
            weight_kg=75.5,
            fat_mass_kg=12.5,
            muscle_mass_kg=55.0,
            bone_mass_kg=3.2,
            body_fat_pct=16.5,
            # Recovery (Intervals exclusive)
            hrv_ln_rmssd=4.2,
            sleep_duration_sec=28800.0,
            resting_hr_bpm=52.0,
            # Activity (Intervals exclusive)
            steps=12500,
            # Nutrition (Intervals exclusive)
            calories_kcal=2500.0,
            carbs_g=300.0,
            protein_g=150.0,
            fat_g=80.0,
            # Performance baselines (Garmin exclusive)
            ftp_watts=285.0,
            cycling_vo2max_ml_kg_min=55.2,
            hr_lthr_bpm=175.0,
            hr_max_bpm=195.0,
            # Training state (Garmin exclusive)
            training_load=425.0,
            recovery_time_minutes=36,
            readiness_score=85.0,
            # Extended training (Garmin exclusive)
            training_effect_aerobic=3.8,
            training_effect_anaerobic=2.1,
            training_stress_score=120.0,
            training_stress_balance=15.0,
            atp_probability=92.0,
        )

        storage_dict = snapshot.to_storage_dict()

        # Verify flat structure (no nested dicts in v3.0.0)
        assert "weight_kg" in storage_dict
        assert "hrv_ln_rmssd" in storage_dict
        assert "sleep_duration_sec" in storage_dict
        assert "resting_hr_bpm" in storage_dict
        assert "steps" in storage_dict
        assert "calories_kcal" in storage_dict
        assert "ftp_watts" in storage_dict
        assert "cycling_vo2max_ml_kg_min" in storage_dict
        assert "hr_lthr_bpm" in storage_dict
        assert "training_load" in storage_dict
        assert "readiness_score" in storage_dict
        assert "training_effect_aerobic" in storage_dict

        # Spot-check values
        assert storage_dict["hrv_ln_rmssd"] == pytest.approx(4.2)
        assert storage_dict["sleep_duration_sec"] == pytest.approx(28800.0)
        assert storage_dict["resting_hr_bpm"] == pytest.approx(52.0)
        assert storage_dict["steps"] == 12500
        assert storage_dict["ftp_watts"] == pytest.approx(285.0)
        assert storage_dict["training_load"] == pytest.approx(425.0)

    def test_to_storage_dict_includes_nutrition_and_activity_fields(self) -> None:
        """Verify nutrition and activity fields are included (v3.0.0)."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            # Nutrition (Intervals exclusive)
            calories_kcal=2500.0,
            carbs_g=300.0,
            protein_g=150.0,
            fat_g=80.0,
            # Activity (Intervals exclusive)
            steps=12500,
        )

        storage_dict = snapshot.to_storage_dict()

        # Verify nutrition fields
        assert storage_dict["calories_kcal"] == pytest.approx(2500.0)
        assert storage_dict["carbs_g"] == pytest.approx(300.0)
        assert storage_dict["protein_g"] == pytest.approx(150.0)
        assert storage_dict["fat_g"] == pytest.approx(80.0)

        # Verify activity fields
        assert storage_dict["steps"] == 12500

    def test_to_storage_dict_handles_null_nutrition_and_activity_fields(self) -> None:
        """Verify null nutrition and activity fields are included as None (v3.0.0)."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            steps=None,
        )

        storage_dict = snapshot.to_storage_dict()

        # Verify nutrition fields are present as None
        assert "calories_kcal" in storage_dict
        assert storage_dict["calories_kcal"] is None
        assert "carbs_g" in storage_dict
        assert storage_dict["carbs_g"] is None
        assert "protein_g" in storage_dict
        assert storage_dict["protein_g"] is None
        assert "fat_g" in storage_dict
        assert storage_dict["fat_g"] is None

        # Verify activity fields
        assert "steps" in storage_dict
        assert storage_dict["steps"] is None

    def test_to_storage_dict_training_metrics(self) -> None:
        """Verify training metrics (Garmin exclusive) are included (v3.0.0)."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            # Training state
            training_load=425.0,
            recovery_time_minutes=36,
            readiness_score=85.0,
            # Extended training metrics
            training_effect_aerobic=3.8,
            training_effect_anaerobic=2.1,
            training_stress_score=120.0,
            training_stress_balance=15.0,
            atp_probability=92.0,
        )

        storage_dict = snapshot.to_storage_dict()

        assert storage_dict["training_load"] == pytest.approx(425.0)
        assert storage_dict["recovery_time_minutes"] == 36
        assert storage_dict["readiness_score"] == pytest.approx(85.0)
        assert storage_dict["training_effect_aerobic"] == pytest.approx(3.8)
        assert storage_dict["training_effect_anaerobic"] == pytest.approx(2.1)
        assert storage_dict["training_stress_score"] == pytest.approx(120.0)
        assert storage_dict["training_stress_balance"] == pytest.approx(15.0)
        assert storage_dict["atp_probability"] == pytest.approx(92.0)

    def test_to_storage_dict_handles_null_training_metrics(self) -> None:
        """Verify null training metrics are included as None (v3.0.0)."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            training_load=None,
            recovery_time_minutes=None,
            readiness_score=None,
            training_effect_aerobic=None,
            training_effect_anaerobic=None,
            training_stress_score=None,
            training_stress_balance=None,
            atp_probability=None,
        )

        storage_dict = snapshot.to_storage_dict()

        assert "training_load" in storage_dict
        assert storage_dict["training_load"] is None
        assert "recovery_time_minutes" in storage_dict
        assert storage_dict["recovery_time_minutes"] is None
        assert "readiness_score" in storage_dict
        assert storage_dict["readiness_score"] is None
        assert "training_effect_aerobic" in storage_dict
        assert storage_dict["training_effect_aerobic"] is None
        assert "training_effect_anaerobic" in storage_dict
        assert storage_dict["training_effect_anaerobic"] is None
        assert "training_stress_score" in storage_dict
        assert storage_dict["training_stress_score"] is None
        assert "training_stress_balance" in storage_dict
        assert storage_dict["training_stress_balance"] is None
        assert "atp_probability" in storage_dict
        assert storage_dict["atp_probability"] is None
