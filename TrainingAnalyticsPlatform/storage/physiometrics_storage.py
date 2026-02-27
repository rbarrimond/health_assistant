"""Physiometrics (time-series body metrics) storage."""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)


class PhysiometricsStorage:
    """Handle physiometrics and body metrics operations."""

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
            "RowKey": timestamp,
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
            "full_config_json": json.dumps(physiometrics_data),
        }

        try:
            table_client = self.infra.get_table_client("Physiometrics")
            table_client.upsert_entity(entity)
            logger.info("Stored physiometrics for %s at %s", athlete_id, timestamp)
            return timestamp
        except HttpResponseError as e:
            logger.error("Error storing physiometrics: %s", e)
            raise

    def get_physiometrics(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve the latest physiometrics config for an athlete."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}'"
            entities = list(table_client.query_entities(query, top=1))

            if not entities:
                return None

            latest = entities[0]
            if latest.get("full_config_json"):
                return json.loads(latest["full_config_json"])

            # Fallback: reconstruct from individual fields
            result = {
                "heart_rate": {
                    "basis": latest.get("heart_rate_basis", "HRmax"),
                    "lthr_bpm": latest.get("heart_rate_lthr_bpm"),
                    "hr_max_bpm": latest.get("heart_rate_hr_max_bpm"),
                    "resting_hr_bpm": latest.get("heart_rate_resting_bpm") or 60,
                },
                "power": {"ftp_watts": latest.get("power_ftp_watts")},
            }

            for metric_field in ["weight_kg", "fat_mass_kg", "muscle_mass_kg", "bone_mass_kg"]:
                if latest.get(metric_field) is not None:
                    result[metric_field] = latest.get(metric_field)

            if latest.get("effective_date"):
                result["effective_date"] = latest.get("effective_date")
            if latest.get("data_source"):
                result["data_source"] = latest.get("data_source")

            return result
        except ResourceNotFoundError:
            return None
        except HttpResponseError as e:
            logger.warning("Error retrieving physiometrics for %s: %s", athlete_id, e)
            return None

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

            result = {
                "heart_rate": {
                    "basis": latest.get("heart_rate_basis", "HRmax"),
                    "lthr_bpm": latest.get("heart_rate_lthr_bpm"),
                    "hr_max_bpm": latest.get("heart_rate_hr_max_bpm"),
                    "resting_hr_bpm": latest.get("heart_rate_resting_bpm") or 60,
                },
                "power": {"ftp_watts": latest.get("power_ftp_watts")},
            }

            for metric_field in [
                "weight_kg",
                "fat_mass_kg",
                "muscle_mass_kg",
                "bone_mass_kg",
                "body_fat_pct",
                "visceral_fat_index",
                "metabolic_age_years",
                "cycling_vo2max_ml_kg_min",
            ]:
                if latest.get(metric_field) is not None:
                    result[metric_field] = latest.get(metric_field)

            if latest.get("effective_date"):
                result["effective_date"] = latest.get("effective_date")
            if latest.get("data_source"):
                result["data_source"] = latest.get("data_source")

            return result

        except HttpResponseError as e:
            logger.warning(
                "Error retrieving physiometrics as of %s for %s: %s",
                target_date,
                athlete_id,
                e,
            )
            return None

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
            logger.warning(
                "Error retrieving physiometrics history for %s: %s",
                athlete_id,
                e,
            )
            return []

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
            logger.warning(
                "Error retrieving physiometrics history for %s: %s",
                athlete_id,
                e,
            )
            return []

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
