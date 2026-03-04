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

    def test_to_storage_dict_includes_extended_wellness_fields(self) -> None:
        """Verify extended wellness fields (subjective, nutrition, activity, body composition) are included."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            # Subjective wellness (0-10 scales)
            soreness=3.0,
            fatigue=4.0,
            stress=2.0,
            mood=8.0,
            motivation=7.0,
            injury=0.0,
            # Nutrition (macros)
            calories_kcal=2500.0,
            carbs_g=300.0,
            protein_g=150.0,
            fat_g=80.0,
            # Activity metrics
            steps=12500,
            # Body composition
            abdomen_cm=85.5,
            # Sport-specific info (nested array)
            sport_info=[
                {"type": "Ride", "load": 120.5, "ctl": 85.2},
                {"type": "Run", "load": 45.3, "ctl": 42.1},
            ],
        )

        storage_dict = snapshot.to_storage_dict()

        # Verify subjective wellness fields
        assert storage_dict["soreness"] == pytest.approx(3.0)
        assert storage_dict["fatigue"] == pytest.approx(4.0)
        assert storage_dict["stress"] == pytest.approx(2.0)
        assert storage_dict["mood"] == pytest.approx(8.0)
        assert storage_dict["motivation"] == pytest.approx(7.0)
        assert storage_dict["injury"] == pytest.approx(0.0)

        # Verify nutrition fields
        assert storage_dict["calories_kcal"] == pytest.approx(2500.0)
        assert storage_dict["carbs_g"] == pytest.approx(300.0)
        assert storage_dict["protein_g"] == pytest.approx(150.0)
        assert storage_dict["fat_g"] == pytest.approx(80.0)

        # Verify activity fields
        assert storage_dict["steps"] == 12500

        # Verify body composition fields
        assert storage_dict["abdomen_cm"] == pytest.approx(85.5)

        # Verify sport_info is JSON-serialized
        assert "sport_info_json" in storage_dict
        assert isinstance(storage_dict["sport_info_json"], str)
        import json
        sport_data = json.loads(storage_dict["sport_info_json"])
        assert len(sport_data) == 2
        assert sport_data[0]["type"] == "Ride"
        assert sport_data[1]["type"] == "Run"

    def test_to_storage_dict_handles_null_extended_fields(self) -> None:
        """Verify null extended wellness fields are included as None."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            soreness=None,
            fatigue=None,
            stress=None,
            mood=None,
            motivation=None,
            injury=None,
            calories_kcal=None,
            carbs_g=None,
            protein_g=None,
            fat_g=None,
            steps=None,
            abdomen_cm=None,
            sport_info=None,
        )

        storage_dict = snapshot.to_storage_dict()

        # Verify subjective wellness fields are present as None
        assert "soreness" in storage_dict
        assert storage_dict["soreness"] is None
        assert "fatigue" in storage_dict
        assert storage_dict["fatigue"] is None
        assert "stress" in storage_dict
        assert storage_dict["stress"] is None
        assert "mood" in storage_dict
        assert storage_dict["mood"] is None
        assert "motivation" in storage_dict
        assert storage_dict["motivation"] is None
        assert "injury" in storage_dict
        assert storage_dict["injury"] is None

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

        # Verify body composition fields
        assert "abdomen_cm" in storage_dict
        assert storage_dict["abdomen_cm"] is None

        # Verify sport_info_json is None when sport_info is None
        assert "sport_info_json" in storage_dict
        assert storage_dict["sport_info_json"] is None

    def test_to_storage_dict_sport_info_empty_list(self) -> None:
        """Verify empty sport_info list serializes to empty JSON array."""
        snapshot = PhysiometricsSnapshot(  # type: ignore[call-arg]
            athlete_id="athlete123",
            effective_date="2026-03-04",
            sport_info=[],
        )

        storage_dict = snapshot.to_storage_dict()

        assert "sport_info_json" in storage_dict
        assert isinstance(storage_dict["sport_info_json"], str)
        import json
        sport_data = json.loads(storage_dict["sport_info_json"])
        assert sport_data == []
