"""Physiometrics (time-series body metrics) storage."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from pydantic import ValidationError as PydanticValidationError

from TrainingAnalyticsPlatform.analytics.physiometrics_resolution import (
    BASELINE_SOURCE_PRECEDENCE,
    build_source_rows_by_source,
    resolve_latest_metric_across_sources,
)
from TrainingAnalyticsPlatform.models.wellness import PhysiometricsSnapshot
from TrainingAnalyticsPlatform.platform.exceptions import StorageError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import StorageInfrastructure

logger = logging.getLogger(__name__)


class PhysiometricsStorage:
    """Handle physiometrics and body metrics operations."""

    _CONFIG_DATA_SOURCES = frozenset({"manual", "chatgpt"})

    # Field mapping constants (for _reconstruct_from_storage_entity)
    _BODY_COMPOSITION_FIELDS = [
        "weight_kg", "fat_mass_kg", "muscle_mass_kg", "bone_mass_kg",
        "body_fat_pct", "visceral_fat_index", "metabolic_age_years",
        "cycling_vo2max_ml_kg_min", "running_vo2max_ml_kg_min"
    ]
    _CORE_WELLNESS_FIELDS = ["hrv_ln_rmssd", "hrv_sdnn_ms", "sleep_duration_sec", "readiness_score"]
    _GARMIN_TRAINING_FIELDS = [
        "training_load",
        "training_effect_aerobic",
        "training_effect_anaerobic",
        "training_stress_score",
        "training_stress_balance",
        "atp_probability",
        "recovery_time_minutes",
        "lactate_threshold_hr_bpm",
        "training_status_label",
        "load_focus_low_aerobic_pct",
        "load_focus_high_aerobic_pct",
        "load_focus_anaerobic_pct",
    ]
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
        "spo2_pct": "spo2_pct",
        "systolic_bp": "systolic_bp",
        "diastolic_bp": "diastolic_bp",
        "vo2max_ml_kg_min": "vo2max_ml_kg_min",
        "menstrual_phase": "menstrual_phase",
        "menstrual_phase_predicted": "menstrual_phase_predicted",
        "sport_info_json": "sport_info_json",
        "source_updated_at_utc": "source_updated_at_utc",
        "raw_intervals_icu_json": "raw_intervals_icu_json",
        "ext_json": "ext_json",
    }
    _BASELINE_FIELD_ALIASES = {
        "ftp_watts": ["ftp_watts", "power_ftp_watts"],
        "hr_lthr_bpm": ["hr_lthr_bpm", "heart_rate_lthr_bpm", "lactate_threshold_hr_bpm"],
    }

    @staticmethod
    def _build_ext_json_payload(physiometrics_data: Dict[str, Any]) -> Optional[str]:
        """Build serialized extension payload for non-core physiometrics fields."""
        ext_payload: Dict[str, Any] = {}
        existing_ext = physiometrics_data.get("ext_json")

        if isinstance(existing_ext, str):
            try:
                parsed_ext = json.loads(existing_ext)
                if isinstance(parsed_ext, dict):
                    ext_payload.update(parsed_ext)
            except json.JSONDecodeError:
                ext_payload["raw_ext_json"] = existing_ext
        elif isinstance(existing_ext, dict):
            ext_payload.update(existing_ext)

        for key in ("athlete_info", "gear", "athlete_timezone"):
            value = physiometrics_data.get(key)
            if value is not None:
                ext_payload[key] = value

        if not ext_payload:
            return None
        return json.dumps(ext_payload)

    def __init__(self, infrastructure: StorageInfrastructure):
        """Initialize with storage infrastructure."""
        self.infra = infrastructure

    @staticmethod
    def _normalize_data_source(data_source: str) -> str:
        """Normalize physiometrics source identifiers for storage identity."""
        normalized = (data_source or "manual").strip().lower()
        return normalized or "manual"

    @classmethod
    def _build_row_key(cls, effective_date: str, data_source: str) -> str:
        """Build storage identity that preserves per-source daily snapshots."""
        return f"{effective_date}|{cls._normalize_data_source(data_source)}"

    @staticmethod
    def _parse_updated_at(value: Optional[str]) -> datetime:
        """Parse ISO timestamps for deterministic row ordering."""
        if not value:
            return datetime.min.replace(tzinfo=timezone.utc)
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @classmethod
    def _sort_key(cls, entity: Mapping[str, Any]) -> Tuple[str, datetime, str]:
        """Return a stable ordering key for physiometrics entities."""
        return (
            entity.get("effective_date", ""),
            cls._parse_updated_at(entity.get("updated_at_utc")),
            entity.get("RowKey", ""),
        )

    @classmethod
    def _sorted_entities(
        cls,
        entities: Sequence[Mapping[str, Any]],
        *,
        reverse: bool = False,
    ) -> List[Mapping[str, Any]]:
        """Sort physiometrics entities by effective date and update timestamp."""
        return sorted(entities, key=cls._sort_key, reverse=reverse)

    @classmethod
    def _is_config_entity(cls, entity: Mapping[str, Any]) -> bool:
        """Return whether an entity represents a user-authored configuration row."""
        data_source = cls._normalize_data_source(str(entity.get("data_source") or "manual"))
        return data_source in cls._CONFIG_DATA_SOURCES

    @classmethod
    def _latest_entity(
        cls,
        entities: Sequence[Mapping[str, Any]],
        *,
        config_only: bool = False,
    ) -> Optional[Mapping[str, Any]]:
        """Return the newest entity, optionally restricted to config sources."""
        candidates = [entity for entity in entities if cls._is_config_entity(entity)] if config_only else entities
        if not candidates:
            return None
        return cls._sorted_entities(candidates)[-1]

    def _hydrate_entity(self, latest: Mapping[str, Any]) -> Dict[str, Any]:
        """Convert a storage entity into canonical physiometrics payload."""
        if latest.get("ext_json"):
            return self._reconstruct_from_storage_entity(latest)

        if latest.get("full_config_json"):
            return json.loads(latest["full_config_json"])

        return self._reconstruct_from_storage_entity(latest)

    def _merge_resolved_baselines(
        self,
        payload: Dict[str, Any],
        entities: Sequence[Mapping[str, Any]],
        *,
        target_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Overlay recency-resolved FTP/LTHR baselines onto a hydrated payload."""
        source_rows_by_source = build_source_rows_by_source(
            entities,
            tracked_sources={"garmin", "chatgpt", "manual"},
            target_date=target_date,
        )

        ftp_watts, _, _ = resolve_latest_metric_across_sources(
            "ftp_watts",
            source_rows_by_source,
            field_aliases=self._BASELINE_FIELD_ALIASES,
            source_precedence=BASELINE_SOURCE_PRECEDENCE,
        )
        if ftp_watts is not None:
            payload.setdefault("power", {})["ftp_watts"] = ftp_watts

        lthr_bpm, _, _ = resolve_latest_metric_across_sources(
            "hr_lthr_bpm",
            source_rows_by_source,
            field_aliases=self._BASELINE_FIELD_ALIASES,
            source_precedence=BASELINE_SOURCE_PRECEDENCE,
        )
        if lthr_bpm is not None:
            payload.setdefault("heart_rate", {})["lthr_bpm"] = lthr_bpm

        return payload

    @staticmethod
    def _to_snapshot_payload(canonical: Mapping[str, Any]) -> Dict[str, Any]:
        """Build PhysiometricsSnapshot payload from reconstructed canonical dict."""
        payload = {
            field_name: canonical.get(field_name)
            for field_name in PhysiometricsSnapshot.model_fields
        }

        heart_rate = canonical.get("heart_rate") or {}
        power = canonical.get("power") or {}

        payload["resting_hr_bpm"] = payload.get("resting_hr_bpm") or heart_rate.get("resting_hr_bpm")
        payload["hr_lthr_bpm"] = payload.get("hr_lthr_bpm") or heart_rate.get("lthr_bpm") or canonical.get("lactate_threshold_hr_bpm")
        payload["hr_max_bpm"] = payload.get("hr_max_bpm") or heart_rate.get("hr_max_bpm")
        payload["ftp_watts"] = payload.get("ftp_watts") or power.get("ftp_watts")
        payload["athlete_id"] = payload.get("athlete_id") or canonical.get("athlete_id") or canonical.get("PartitionKey")
        payload["effective_date"] = payload.get("effective_date") or canonical.get("effective_date")
        payload["last_updated_utc"] = payload.get("last_updated_utc") or canonical.get("updated_at_utc")
        payload["data_sources"] = payload.get("data_sources") or canonical.get("data_source") or ""
        payload["canonical_version"] = payload.get("canonical_version") or "4.2.0"

        return payload

    def _hydrate_entity_snapshot(
        self,
        latest: Mapping[str, Any],
    ) -> PhysiometricsSnapshot:
        """Hydrate a storage entity into validated PhysiometricsSnapshot."""
        canonical = self._hydrate_entity(latest)
        canonical["athlete_id"] = canonical.get("athlete_id") or latest.get("PartitionKey")
        canonical["updated_at_utc"] = canonical.get("updated_at_utc") or latest.get("updated_at_utc")
        canonical["effective_date"] = canonical.get("effective_date") or latest.get("effective_date")
        payload = self._to_snapshot_payload(canonical)
        try:
            return PhysiometricsSnapshot(**payload)
        except PydanticValidationError as exc:
            logger.error(
                "Failed to hydrate physiometrics snapshot",
                extra={
                    "athlete_id": latest.get("PartitionKey"),
                    "effective_date": latest.get("effective_date"),
                    "data_source": latest.get("data_source"),
                },
                exc_info=True,
            )
            raise StorageError("Failed to hydrate physiometrics snapshot") from exc

    def store_physiometrics(
        self,
        athlete_id: str,
        physiometrics_data: Union[Dict[str, Any], PhysiometricsSnapshot],
        effective_date: Optional[str] = None,
        data_source: str = "manual",
    ) -> str:
        """Store a physiometrics snapshot."""
        timestamp = datetime.now(timezone.utc).isoformat()
        normalized_source = self._normalize_data_source(data_source)

        if isinstance(physiometrics_data, PhysiometricsSnapshot):
            payload = physiometrics_data.to_storage_dict()
            if effective_date is None:
                effective_date = physiometrics_data.effective_date
            if data_source == "manual" and physiometrics_data.data_sources:
                normalized_source = self._normalize_data_source(physiometrics_data.data_sources)
        else:
            payload = physiometrics_data

        if effective_date is None:
            effective_date = datetime.now(timezone.utc).date().isoformat()

        ext_json_payload = self._build_ext_json_payload(payload)

        entity = {
            "PartitionKey": athlete_id,
            "RowKey": self._build_row_key(effective_date, normalized_source),
            "updated_at_utc": timestamp,
            "effective_date": effective_date,
            "data_source": normalized_source,
            "heart_rate_basis": payload.get("heart_rate", {}).get("basis"),
            "heart_rate_lthr_bpm": payload.get("heart_rate", {}).get("lthr_bpm"),
            "heart_rate_hr_max_bpm": payload.get("heart_rate", {}).get("hr_max_bpm"),
            "heart_rate_resting_bpm": (
                # Try flat key first (from PhysiometricsSnapshot.to_storage_dict)
                payload.get("resting_hr_bpm")
                # Fall back to nested structure for backward compatibility
                or payload.get("heart_rate", {}).get("resting_hr_bpm")
                # Final default only if no source provided value
                or 60
            ),
            "power_ftp_watts": payload.get("power", {}).get("ftp_watts"),
            "weight_kg": payload.get("weight_kg"),
            "fat_mass_kg": payload.get("fat_mass_kg"),
            "muscle_mass_kg": payload.get("muscle_mass_kg"),
            "bone_mass_kg": payload.get("bone_mass_kg"),
            "body_fat_pct": payload.get("body_fat_pct"),
            "visceral_fat_index": payload.get("visceral_fat_index"),
            "metabolic_age_years": payload.get("metabolic_age_years"),
            "cycling_vo2max_ml_kg_min": payload.get("cycling_vo2max_ml_kg_min"),
            "running_vo2max_ml_kg_min": payload.get("running_vo2max_ml_kg_min"),
            "hrv_ln_rmssd": payload.get("hrv_ln_rmssd"),
            "hrv_sdnn_ms": payload.get("hrv_sdnn_ms"),
            "sleep_duration_sec": payload.get("sleep_duration_sec"),
            "readiness_score": payload.get("readiness_score"),
            "training_load": payload.get("training_load"),
            "training_effect_aerobic": payload.get("training_effect_aerobic"),
            "training_effect_anaerobic": payload.get("training_effect_anaerobic"),
            "training_stress_score": payload.get("training_stress_score"),
            "training_stress_balance": payload.get("training_stress_balance"),
            "atp_probability": payload.get("atp_probability"),
            "recovery_time_minutes": payload.get("recovery_time_minutes"),
            "lactate_threshold_hr_bpm": payload.get("lactate_threshold_hr_bpm") or payload.get("hr_lthr_bpm"),
            "training_status_label": payload.get("training_status_label"),
            "load_focus_low_aerobic_pct": payload.get("load_focus_low_aerobic_pct"),
            "load_focus_high_aerobic_pct": payload.get("load_focus_high_aerobic_pct"),
            "load_focus_anaerobic_pct": payload.get("load_focus_anaerobic_pct"),
            # Extended wellness columns
            "subjective_soreness": payload.get("soreness"),
            "subjective_fatigue": payload.get("fatigue"),
            "subjective_stress": payload.get("stress"),
            "subjective_mood": payload.get("mood"),
            "subjective_motivation": payload.get("motivation"),
            "subjective_injury": payload.get("injury"),
            # Nutrition columns
            "nutrition_calories_kcal": payload.get("calories_kcal"),
            "nutrition_carbs_g": payload.get("carbs_g"),
            "nutrition_protein_g": payload.get("protein_g"),
            "nutrition_fat_g": payload.get("fat_g"),
            # Activity columns
            "activity_steps": payload.get("steps"),
            # Body composition
            "body_abdomen_cm": payload.get("abdomen_cm"),
            "spo2_pct": payload.get("spo2_pct"),
            "systolic_bp": payload.get("systolic_bp"),
            "diastolic_bp": payload.get("diastolic_bp"),
            "vo2max_ml_kg_min": payload.get("vo2max_ml_kg_min"),
            "menstrual_phase": payload.get("menstrual_phase"),
            "menstrual_phase_predicted": payload.get("menstrual_phase_predicted"),
            # Sport metrics (serialized JSON)
            "sport_info_json": payload.get("sport_info_json"),
            # Raw source preservation (zero-loss ingestion)
            "source_updated_at_utc": payload.get("source_updated_at_utc"),
            "raw_intervals_icu_json": payload.get("raw_intervals_icu_json"),
            "ext_json": ext_json_payload,
        }

        try:
            table_client = self.infra.get_table_client("Physiometrics")
            table_client.upsert_entity(entity)
            logger.info(
                "Stored physiometrics",
                extra={
                    "athlete_id": athlete_id,
                    "effective_date": effective_date,
                    "data_source": normalized_source,
                },
            )
            return timestamp
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

    def _reconstruct_from_storage_entity(self, entity: Mapping[str, Any]) -> Dict[str, Any]:
        """Reconstruct canonical physiometrics from storage entity.
        
        Prevents silent field loss when legacy full_config_json is unavailable.
        Delegates to helpers to reduce cognitive complexity.
        """
        result: Dict[str, Any] = {"heart_rate": self._get_heart_rate(entity), "power": self._get_power(entity)}
        self._merge_fields(result, entity, self._BODY_COMPOSITION_FIELDS)
        self._merge_fields(result, entity, self._CORE_WELLNESS_FIELDS)
        self._merge_fields(result, entity, self._GARMIN_TRAINING_FIELDS)
        self._merge_mapped(result, entity, self._SUBJECTIVE_WELLNESS_MAP)
        self._merge_mapped(result, entity, self._NUTRITION_MAP)
        self._merge_mapped(result, entity, self._ACTIVITY_BODY_MAP)
        ext_json = entity.get("ext_json")
        if isinstance(ext_json, str):
            try:
                result.update(json.loads(ext_json))
            except json.JSONDecodeError:
                result["ext_json"] = ext_json
        if entity.get("effective_date"):
            result["effective_date"] = entity.get("effective_date")
        if entity.get("data_source"):
            result["data_source"] = entity.get("data_source")
        return result

    def _get_heart_rate(self, entity: Mapping[str, Any]) -> Dict[str, Any]:
        """Extract heart_rate nested structure."""
        return {
            "basis": entity.get("heart_rate_basis"),
            "lthr_bpm": entity.get("heart_rate_lthr_bpm"),
            "hr_max_bpm": entity.get("heart_rate_hr_max_bpm"),
            "resting_hr_bpm": entity.get("heart_rate_resting_bpm") or 60,
        }

    def _get_power(self, entity: Mapping[str, Any]) -> Dict[str, Any]:
        """Extract power nested structure."""
        return {"ftp_watts": entity.get("power_ftp_watts")}

    def _merge_fields(self, result: Dict[str, Any], entity: Mapping[str, Any], fields: list) -> None:
        """Merge fields with direct name mapping."""
        for field in fields:
            if entity.get(field) is not None:
                result[field] = entity.get(field)

    def _merge_mapped(
        self,
        result: Dict[str, Any],
        entity: Mapping[str, Any],
        mapping: Dict[str, str],
    ) -> None:
        """Merge fields with storage→canonical name mapping."""
        for storage_key, canonical_key in mapping.items():
            if entity.get(storage_key) is not None:
                result[canonical_key] = entity.get(storage_key)

    def get_physiometrics(self, athlete_id: str) -> Optional[Dict]:
        """Retrieve current physiometrics config with recency-aware FTP/LTHR baselines."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}'"
            entities = list(table_client.query_entities(query))

            if not entities:
                return None

            latest = self._latest_entity(entities, config_only=True)
            if latest is None:
                latest = self._latest_entity(entities)
            if latest is None:
                return None

            return self._merge_resolved_baselines(self._hydrate_entity(latest), entities)
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
        """Query physiometrics config effective on a specific date."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}' and effective_date le '{target_date}'"
            entities = [
                entity
                for entity in table_client.query_entities(query)
                if (entity.get("effective_date") or "") <= target_date
            ]

            if not entities:
                return self.get_physiometrics(athlete_id)

            latest = self._latest_entity(entities, config_only=True)
            if latest is None:
                latest = self._latest_entity(entities)
            if latest is None:
                return None

            return self._merge_resolved_baselines(
                self._hydrate_entity(latest),
                entities,
                target_date=target_date,
            )

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

    def get_physiometrics_snapshot_as_of(
        self,
        athlete_id: str,
        target_date: str,
    ) -> Optional[PhysiometricsSnapshot]:
        """Query physiometrics as-of date and hydrate to typed PhysiometricsSnapshot.

        Uses latest available source row (not config-priority) to preserve observed
        time-series signals such as Garmin training status and load focus.
        """
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}' and effective_date le '{target_date}'"
            entities = [
                entity
                for entity in table_client.query_entities(query)
                if (entity.get("effective_date") or "") <= target_date
            ]

            if not entities:
                fallback_query = f"PartitionKey eq '{athlete_id}'"
                entities = list(table_client.query_entities(fallback_query))
                if not entities:
                    return None

            latest = self._latest_entity(entities)
            if latest is None:
                return None

            return self._hydrate_entity_snapshot(latest)
        except HttpResponseError as e:
            logger.error(
                "Error retrieving physiometrics snapshot as of date",
                extra={
                    "athlete_id": athlete_id,
                    "target_date": target_date,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            raise StorageError("Failed to retrieve typed physiometrics history point") from e

    def list_physiometrics_history(
        self,
        athlete_id: str,
        limit: int = 10,
    ) -> list:
        """List historical user-authored physiometrics configs (limited)."""
        try:
            table_client = self.infra.get_table_client("Physiometrics")
            query = f"PartitionKey eq '{athlete_id}'"
            entities = [
                entity
                for entity in table_client.query_entities(query)
                if self._is_config_entity(entity)
            ]
            entities = self._sorted_entities(entities, reverse=True)
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
            entities = [
                entity
                for entity in table_client.query_entities(query)
                if start_date <= (entity.get("effective_date") or "") <= end_date
            ]
            entities = self._sorted_entities(entities)
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
        if metric_name == "ftp_watts":
            latest_config.setdefault("power", {})[metric_name] = value
        elif metric_name == "hr_lthr_bpm":
            latest_config.setdefault("heart_rate", {})["lthr_bpm"] = value
            latest_config[metric_name] = value
        elif metric_name == "hr_max_bpm":
            latest_config.setdefault("heart_rate", {})[metric_name] = value
        elif metric_name == "resting_hr_bpm":
            latest_config.setdefault("heart_rate", {})[metric_name] = value
        else:
            latest_config[metric_name] = value

        return self.store_physiometrics(
            athlete_id=athlete_id,
            physiometrics_data=latest_config,
            effective_date=effective_date,
            data_source=data_source,
        )
