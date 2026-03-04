"""Physiometrics (time-series body metrics) storage."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)


class PhysiometricsStorage:
    """Handle physiometrics and body metrics operations."""

    # Field mapping constants (for _reconstruct_from_storage_entity)
    _BODY_COMPOSITION_FIELDS = [
        "weight_kg", "fat_mass_kg", "muscle_mass_kg", "bone_mass_kg",
        "body_fat_pct", "visceral_fat_index", "metabolic_age_years",
        "cycling_vo2max_ml_kg_min"
    ]
    _CORE_WELLNESS_FIELDS = ["hrv_ln_rmssd", "sleep_duration_min", "readiness_score"]
    _SUBJECTIVE_WELLNESS_MAP = {
        "subjective_soreness": "soreness",
        "subjective_fatigue": "fatigue",
        "subjective_stress": "stress",
        "subjective_mood": "mood",
        "subjective_motivation": "motivation",
        "subjective_injury": "injury",
    }
    _NUTRITION_MAP = {
        "nutrition_calories_kcal": "calories_kcal",
        "nutrition_carbs_g": "carbs_g",
        "nutrition_protein_g": "protein_g",
        "nutrition_fat_g": "fat_g",
    }
    _ACTIVITY_BODY_MAP = {
        "activity_steps": "steps",
        "body_abdomen_cm": "abdomen_cm",
        "sport_info_json": "sport_info_json",
    }

    def __init__(self, infrastructure: StorageInfrastructure):
        """Initialize with storage infrastructure."""
        self.infra = infrastructure

    def store_physiometrics(
        self,
        athlete_id: str,
        physiometrics_data: Dict,
        effective_date: Optional[str] = None,
        data_source: str = "manual",
    ) -> str:
        """Store a physiometrics snapshot."""
        timestamp = datetime.now(timezone.utc).isoformat()

        if effective_date is None:
            effective_date = datetime.now(timezone.utc).date().isoformat()

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": effective_date,
            "updated_at_utc": timestamp,
            "effective_date": effective_date,
            "data_source": data_source,
            "heart_rate_basis": (
                physiometrics_data.get("heart_rate", {}).get("basis", "HRmax")
            ),
            "heart_rate_lthr_bpm": physiometrics_data.get("heart_rate", {}).get("lthr_bpm"),
            "heart_rate_hr_max_bpm": physiometrics_data.get("heart_rate", {}).get("hr_max_bpm"),
            "heart_rate_resting_bpm": (
                physiometrics_data.get("heart_rate", {}).get("resting_hr_bpm") or 60
            ),
            "power_ftp_watts": physiometrics_data.get("power", {}).get("ftp_watts"),
            "weight_kg": physiometrics_data.get("weight_kg"),
            "fat_mass_kg": physiometrics_data.get("fat_mass_kg"),
            "muscle_mass_kg": physiometrics_data.get("muscle_mass_kg"),
            "bone_mass_kg": physiometrics_data.get("bone_mass_kg"),
            "body_fat_pct": physiometrics_data.get("body_fat_pct"),
            "visceral_fat_index": physiometrics_data.get("visceral_fat_index"),
            "metabolic_age_years": physiometrics_data.get("metabolic_age_years"),
            "cycling_vo2max_ml_kg_min": physiometrics_data.get("cycling_vo2max_ml_kg_min"),
            "hrv_ln_rmssd": physiometrics_data.get("hrv_ln_rmssd"),
            "sleep_duration_min": physiometrics_data.get("sleep_duration_min"),
            "readiness_score": physiometrics_data.get("readiness_score"),
            # Extended wellness columns
            "subjective_soreness": physiometrics_data.get("soreness"),
            "subjective_fatigue": physiometrics_data.get("fatigue"),
            "subjective_stress": physiometrics_data.get("stress"),
            "subjective_mood": physiometrics_data.get("mood"),
            "subjective_motivation": physiometrics_data.get("motivation"),
            "subjective_injury": physiometrics_data.get("injury"),
            # Nutrition columns
            "nutrition_calories_kcal": physiometrics_data.get("calories_kcal"),
            "nutrition_carbs_g": physiometrics_data.get("carbs_g"),
            "nutrition_protein_g": physiometrics_data.get("protein_g"),
            "nutrition_fat_g": physiometrics_data.get("fat_g"),
            # Activity columns
            "activity_steps": physiometrics_data.get("steps"),
            # Body composition
            "body_abdomen_cm": physiometrics_data.get("abdomen_cm"),
            # Sport metrics (serialized JSON)
            "sport_info_json": physiometrics_data.get("sport_info_json"),
            "full_config_json": json.dumps(physiometrics_data),
        }

        try:
            table_client = self.infra.get_table_client("Physiometrics")
            table_client.upsert_entity(entity)
            logger.info(
                "Stored physiometrics",
                extra={
                    "athlete_id": athlete_id,
                    "effective_date": effective_date,
                    "data_source": data_source,
                },
            )
            return effective_date
        except HttpResponseError as e:
            logger.error(
                "Error storing physiometrics",
                extra={
                    "athlete_id": athlete_id,
                    "timestamp": timestamp,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to store physiometrics") from e

    def _reconstruct_from_storage_entity(self, entity: Dict) -> Dict:
        """Reconstruct canonical physiometrics from storage entity.
        
        Prevents silent field loss when full_config_json unavailable.
        Delegates to helpers to reduce cognitive complexity.
        """
        result: Dict[str, Any] = {"heart_rate": self._get_heart_rate(entity), "power": self._get_power(entity)}
        self._merge_fields(result, entity, self._BODY_COMPOSITION_FIELDS)
        self._merge_fields(result, entity, self._CORE_WELLNESS_FIELDS)
        self._merge_mapped(result, entity, self._SUBJECTIVE_WELLNESS_MAP)
        self._merge_mapped(result, entity, self._NUTRITION_MAP)
        self._merge_mapped(result, entity, self._ACTIVITY_BODY_MAP)
        if entity.get("effective_date"):
            result["effective_date"] = entity.get("effective_date")
        if entity.get("data_source"):
            result["data_source"] = entity.get("data_source")
        return result

    def _get_heart_rate(self, entity: Dict) -> Dict:
        """Extract heart_rate nested structure."""
        return {
            "basis": entity.get("heart_rate_basis", "HRmax"),
            "lthr_bpm": entity.get("heart_rate_lthr_bpm"),
            "hr_max_bpm": entity.get("heart_rate_hr_max_bpm"),
            "resting_hr_bpm": entity.get("heart_rate_resting_bpm") or 60,
        }

    def _get_power(self, entity: Dict) -> Dict:
        """Extract power nested structure."""
        return {"ftp_watts": entity.get("power_ftp_watts")}

    def _merge_fields(self, result: Dict, entity: Dict, fields: list) -> None:
        """Merge fields with direct name mapping."""
        for field in fields:
            if entity.get(field) is not None:
                result[field] = entity.get(field)

    def _merge_mapped(self, result: Dict, entity: Dict, mapping: Dict) -> None:
        """Merge fields with storage→canonical name mapping."""
        for storage_key, canonical_key in mapping.items():
            if entity.get(storage_key) is not None:
                result[canonical_key] = entity.get(storage_key)

    def get_physiometrics(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve the latest physiometrics config for an athlete."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}'"
            entities = list(table_client.query_entities(query))

            if not entities:
                return None

            # RowKey is effective_date (YYYY-MM-DD); sort to get latest
            latest = sorted(entities, key=lambda e: e.get("RowKey", ""))[-1]
            if latest.get("full_config_json"):
                return json.loads(latest["full_config_json"])

            # Fallback: reconstruct from individual fields (prevents silent data loss)
            return self._reconstruct_from_storage_entity(latest)
        except ResourceNotFoundError:
            return None
        except HttpResponseError as e:
            logger.error(
                "Error retrieving physiometrics",
                extra={
                    "athlete_id": athlete_id,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve physiometrics") from e

    def get_physiometrics_as_of(
        self,
        athlete_id: str,
        target_date: str,
    ) -> Optional[Dict]:
        """Query physiometrics effective on a specific date."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}' and effective_date le '{target_date}'"
            entities = list(table_client.query_entities(query))

            if not entities:
                return self.get_physiometrics(athlete_id)

            entities.sort(key=lambda x: x.get("effective_date", ""), reverse=True)
            latest = entities[0]

            if latest.get("full_config_json"):
                return json.loads(latest["full_config_json"])

            # Fallback: reconstruct from individual fields
            return self._reconstruct_from_storage_entity(latest)

        except HttpResponseError as e:
            logger.error(
                "Error retrieving physiometrics as of date",
                extra={
                    "athlete_id": athlete_id,
                    "target_date": target_date,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve physiometrics history point") from e

    def list_physiometrics_history(
        self,
        athlete_id: str,
        limit: int = 10,
    ) -> list:
        """List historical physiometrics (limited)."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}'"
            entities = list(table_client.query_entities(query))
            entities.sort(key=lambda x: x.get("RowKey", ""), reverse=True)
            return entities[:limit]
        except HttpResponseError as e:
            logger.error(
                "Error retrieving physiometrics history",
                extra={
                    "athlete_id": athlete_id,
                    "limit": limit,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to list physiometrics history") from e

    def get_physiometrics_history(
        self,
        athlete_id: str,
        start_date: str,
        end_date: str,
        metrics: Optional[list] = None,
    ) -> list:
        """Query time-series physiometrics in date range."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = (
                f"PartitionKey eq '{athlete_id}' "
                f"and effective_date ge '{start_date}' "
                f"and effective_date le '{end_date}'"
            )
            entities = list(table_client.query_entities(query))
            entities.sort(key=lambda x: x.get("effective_date", ""))
            if metrics:
                result = []
                for entity in entities:
                    data_point = {
                        "effective_date": entity.get("effective_date"),
                        "updated_at_utc": entity.get("updated_at_utc"),
                        "data_source": entity.get("data_source"),
                    }
                    for metric in metrics:
                        if entity.get(metric) is not None:
                            data_point[metric] = entity.get(metric)
                    result.append(data_point)
                return result

            return entities

        except HttpResponseError as e:
            logger.error(
                "Error retrieving physiometrics history range",
                extra={
                    "athlete_id": athlete_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "metrics": metrics,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve physiometrics history") from e

    def update_single_metric(
        self,
        athlete_id: str,
        metric_name: str,
        value: float,
        effective_date: Optional[str] = None,
        data_source: str = "chatgpt",
    ) -> str:
        """Update a single physiometric value, preserving other fields."""
        latest_config = self.get_physiometrics(athlete_id) or {}
        latest_config[metric_name] = value

        return self.store_physiometrics(
            athlete_id=athlete_id,
            physiometrics_data=latest_config,
            effective_date=effective_date,
            data_source=data_source,
        )
