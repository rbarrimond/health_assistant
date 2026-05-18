"""Workout query service — detail, projection, laps, and developer-field inspection."""
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple, TypedDict

import pandas as pd
from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.analytics import utils
from TrainingAnalyticsPlatform.analytics.physiometrics_resolution import parse_iso_timestamp
from TrainingAnalyticsPlatform.models.core import (
    CanonicalAnalyticsEngine,
    LapSummaryResponse,
    WorkoutDetailResponse,
    WorkoutLapDetailResponse,
    WorkoutMetricsModel,
    WorkoutProjection,
)
from TrainingAnalyticsPlatform.platform.exceptions import (
    StorageError,
    ValidationError,
    WorkoutDetailUnavailableError,
)
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity

if TYPE_CHECKING:
    from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

_LAP_PROMOTED_FIELDS = {
    "message_index",
    "start_time",
    "timestamp",
    "total_elapsed_time",
    "total_timer_time",
    "total_distance",
    "total_calories",
    "avg_heart_rate",
    "max_heart_rate",
    "avg_power",
    "max_power",
    "avg_cadence",
    "max_cadence",
    "avg_speed",
    "max_speed",
    "enhanced_avg_speed",
    "enhanced_max_speed",
    "intensity",
    "lap_trigger",
    "sport",
    "sub_sport",
}


def _get_physio_section(physiometrics: Dict, key: str) -> Dict:
    """Return a nested physiometrics section as a dict, or empty dict if absent or not a mapping."""
    section = physiometrics.get(key) or {}
    return section if isinstance(section, dict) else {}


def _resolve_physio_value(nested: Dict, nested_key: str, physiometrics: Dict, fallback_key: str) -> Any:
    """Return nested_key from nested, falling back to fallback_key on the top-level physiometrics."""
    value = nested.get(nested_key)
    return value if value is not None else physiometrics.get(fallback_key)


class DevFieldSummary(TypedDict):
    """Summary of developer fields in a workout."""
    message_type: str
    field: str
    count: int
    units: set[str]
    sample_values: list[object]


class WorkoutQueryService:
    """Workout detail, projection, and lap query service."""

    def __init__(self, storage: "StorageCoordinator") -> None:
        self.storage = storage

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_workouts(
        self,
        athlete_id: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 50,
        sport: Optional[str] = None,
    ) -> List[Dict]:
        """Query workouts with filters; returns lightweight WorkoutProjection dicts."""
        end_date = utils.parse_workout_query_bound(
            until,
            default_value=datetime.now(timezone.utc),
            is_end=True,
        )
        start_date = utils.parse_workout_query_bound(
            since,
            default_value=end_date - timedelta(days=90),
            is_end=False,
        )
        # Fetch raw entities (no blob reads) then sort, filter, and limit BEFORE
        # building projections so we only read metadata blobs for the final set.
        entities = utils.collect_all_workout_entities(self.storage, athlete_id, start_date, end_date)
        entities.sort(key=lambda e: e.get("start_time_utc", ""), reverse=True)
        if sport:
            entities = [e for e in entities if e.get("sport") == sport]
        entities = entities[:limit]

        projections = [
            p
            for entity in entities
            if (p := self.build_workout_projection(entity)) is not None
        ]
        return [p.model_dump() for p in projections]

    def get_workout_detail(
        self,
        athlete_id: str,
        workout_id: str,
        include_laps: bool = False,
        include_developer_fields: bool = False,
    ) -> Optional[Dict]:
        """Get detailed workout data with optional lap summaries."""
        try:
            entity = self._query_workout_entity(workout_id)
            if entity is None:
                return None
            if entity.get("athlete_id") != athlete_id:
                return None
            return self._build_workout_detail_response(
                entity,
                include_laps=include_laps,
                include_developer_fields=include_developer_fields,
            )
        except HttpResponseError as exc:
            logger.exception(
                "Error retrieving workout detail",
                extra={
                    "workout_id": workout_id,
                    "athlete_id": athlete_id,
                    "error_type": "HttpResponseError",
                    "error": str(exc),
                },
            )
            return None

    def get_workout_lap_detail(
        self,
        athlete_id: str,
        workout_id: str,
        lap_index: int,
    ) -> Optional[Dict]:
        """Get detailed lap data for a specific workout lap."""
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access
            query = f"workout_id eq '{workout_id}'"
            entities = list(table_client.query_entities(query, top=1))
            if not entities:
                return None

            entity = entities[0]
            if entity.get("athlete_id") != athlete_id:
                return None

            ingestion_id = entity.get("ingestion_id") or workout_id
            laps_payload = self.storage.workouts.load_laps_json(ingestion_id)
            laps = laps_payload.get("laps") if isinstance(laps_payload, dict) else None
            if not isinstance(laps, list) or not laps:
                return None

            lap_payload = None
            for lap in laps:
                if lap.get("message_index") == lap_index:
                    lap_payload = lap
                    break
            if lap_payload is None and 0 <= lap_index < len(laps):
                lap_payload = laps[lap_index]
            if lap_payload is None:
                return None

            lap_summary = self._summarize_lap_payload(lap_payload, lap_index)
            response = WorkoutLapDetailResponse(
                workout_id=workout_id,
                athlete_id=athlete_id,
                lap=lap_summary,
            )
            return response.model_dump(exclude_none=True)

        except HttpResponseError as exc:
            logger.exception(
                "Error retrieving lap",
                extra={
                    "workout_id": workout_id,
                    "athlete_id": athlete_id,
                    "lap_index": lap_index,
                    "error_type": "HttpResponseError",
                    "error": str(exc),
                },
            )
            return None

    def build_workout_projection(
        self,
        entity: Dict,
        ingestion_id: Optional[str] = None,
    ) -> Optional[WorkoutProjection]:
        """Build lightweight WorkoutProjection from Workouts table entity + metadata.json."""
        try:
            workout_entity = WorkoutEntity.from_table_entity(entity)
            lookup_id = ingestion_id or entity.get("ingestion_id") or workout_entity.workout_id
            metadata_blob = self._load_projection_metadata_blob(lookup_id, workout_entity.workout_id)
            metadata = self._extract_projection_metadata_sections(metadata_blob)
            projection_kwargs = self._build_workout_projection_kwargs(workout_entity, metadata)
            projection_kwargs.update(
                self._hydrate_projection_from_canonical(
                    workout_entity,
                    entity,
                    metadata_blob,
                    projection_kwargs,
                )
            )
            return WorkoutProjection(**projection_kwargs)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception(
                "Error building workout projection",
                extra={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None

    # -------------------------------------------------------------------------
    # Workout entity / detail helpers
    # -------------------------------------------------------------------------

    def _query_workout_entity(self, workout_id: str) -> Optional[Dict]:
        """Query Workouts table for a single entity by workout_id."""
        table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access
        query = f"workout_id eq '{workout_id}'"
        entities = list(table_client.query_entities(query, top=1))
        return entities[0] if entities else None

    def _build_workout_detail_response(
        self,
        entity: Dict,
        *,
        include_laps: bool,
        include_developer_fields: bool,
    ) -> Dict:
        """Assemble the full workout detail response dict."""
        workout_entity = WorkoutEntity.from_table_entity(entity)
        metadata_blob = self._load_metadata_blob_for_workout(entity, workout_entity)
        identity, session, enrichment, activity_metadata = self._extract_workout_metadata_sections(
            metadata_blob
        )
        detail_metrics = self._build_workout_detail_metrics(
            workout_entity,
            entity,
            metadata_blob,
        )
        base = self._build_workout_base_dict(
            workout_entity, identity, session, enrichment, activity_metadata, detail_metrics
        )
        detail_metrics.update(
            {
                "start_time_utc": base.get("start_time_utc"),
                "duration_sec": base.get("duration_sec"),
                "moving_time_sec": base.get("moving_time_sec"),
                "distance_m": base.get("distance_m"),
                "elevation_gain_m": base.get("elevation_gain_m"),
                "elevation_loss_m": base.get("elevation_loss_m"),
                "calories_kcal": base.get("calories_kcal"),
            }
        )
        metrics = WorkoutMetricsModel.from_canonical_metrics(
            detail_metrics,
            metadata={
                "sport": base.get("sport"),
                "sub_sport": base.get("sub_sport"),
                "workout_name": base.get("workout_name"),
                "apple_workout_type": enrichment.get("apple_workout_type"),
                "device_name": identity.get("device_name") or workout_entity.device_model,
                "is_indoor": base.get("is_indoor"),
                "start_time_utc": base.get("start_time_utc"),
                "local_tz_offset": base.get("local_tz_offset"),
                "timezone": base.get("timezone"),
                "duration_sec": base.get("duration_sec"),
                "moving_time_sec": base.get("moving_time_sec"),
                "has_gps": workout_entity.has_gps,
                "hr_resting_bpm": detail_metrics.get("hr_resting_bpm"),
                "identity": identity,
                "metadata_session": session,
                "activity_metadata": activity_metadata,
                "enrichment": enrichment,
            },
        )
        response = WorkoutDetailResponse(
            workout_id=workout_entity.workout_id,
            athlete_id=workout_entity.athlete_id,
            source_system=entity.get("source_system"),
            metrics=metrics,
        )
        result = response.model_dump(exclude_none=True)

        if include_laps:
            result = self._populate_workout_detail_laps(result, workout_entity)
        if include_developer_fields:
            result = self._populate_workout_detail_developer_fields(result, metadata_blob)

        return result

    def _build_workout_detail_metrics(
        self,
        workout_entity: WorkoutEntity,
        entity: Dict,
        metadata_blob: Dict,
    ) -> Dict:
        """Load canonical records and compute analytics metrics for detail response."""
        blob_name = workout_entity.canonical_records_blob or entity.get("canonical_records_blob")
        ingestion_id = workout_entity.ingestion_id or entity.get("ingestion_id")
        if not blob_name and ingestion_id:
            blob_name = f"{ingestion_id}/canonical.parquet"

        if not blob_name:
            raise WorkoutDetailUnavailableError(
                "No canonical records blob available for workout detail"
            )

        canonical_metadata = utils.prepare_rollup_metadata_for_canonical(
            metadata_blob, workout_entity
        )
        # Ensure canonical analytics use authoritative workout identity classification.
        # Some legacy metadata blobs can contain stale top-level sport fields.
        canonical_metadata["sport"] = (
            workout_entity.sport
            or metadata_blob.get("identity", {}).get("sport")
            or canonical_metadata.get("sport")
        )
        canonical_metadata["sub_sport"] = (
            workout_entity.sub_sport
            or metadata_blob.get("identity", {}).get("sub_sport")
            or metadata_blob.get("enrichment", {}).get("sub_sport")
            or canonical_metadata.get("sub_sport")
        )

        # Resolve physiometrics baselines before analytics so HR/power zone
        # computations use the values effective on the workout date.
        physiometrics_context = self._resolve_workout_physiometrics_context(
            workout_entity, metadata_blob
        )
        if physiometrics_context:
            canonical_metadata.update(physiometrics_context)

        try:
            df = self.storage.workouts.load_canonical_records(blob_name)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise WorkoutDetailUnavailableError(
                f"Failed to load canonical records for workout detail: {exc}"
            ) from exc

        if df.empty:
            raise WorkoutDetailUnavailableError("Canonical records parquet is empty")

        if self._needs_raw_fit_hydration(df):
            try:
                df = self._hydrate_missing_elevation_from_raw_fit(df, workout_entity, entity)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Raw FIT elevation hydration failed",
                    extra={
                        "workout_id": workout_entity.workout_id,
                        "error": str(exc),
                    },
                )

        try:
            metrics = self._compute_metrics_from_canonical(df, canonical_metadata)
        except StorageError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Canonical analytics failed; using basic fallback",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "error": str(exc),
                },
            )
            metrics = utils.compute_basic_metrics_from_canonical(df)

        if physiometrics_context:
            metrics.update(physiometrics_context)

        return metrics

    def _resolve_workout_physiometrics_context(
        self,
        workout_entity: WorkoutEntity,
        metadata_blob: Dict,
    ) -> Optional[Dict]:
        """Resolve physiometrics context for workout detail (FTP/LTHR as-of workout date)."""
        target_date = self._resolve_workout_target_date(workout_entity, metadata_blob)
        if not target_date:
            return None

        try:
            physiometrics = self.storage.physiometrics.get_physiometrics_as_of(
                athlete_id=workout_entity.athlete_id,
                target_date=target_date,
            )
        except StorageError:
            return None

        if not isinstance(physiometrics, dict):
            return None

        resolved = self._extract_workout_baseline_overrides(physiometrics)
        updated_at = physiometrics.get("updated_at_utc")
        if updated_at:
            resolved["physiometrics_snapshot_timestamp"] = updated_at
        return resolved or None

    @staticmethod
    def _extract_workout_baseline_overrides(physiometrics: Dict) -> Dict:
        """Extract FTP and HR baseline overrides from a physiometrics payload."""
        resolved: Dict = {}

        ftp_watts = _resolve_physio_value(
            _get_physio_section(physiometrics, "power"), "ftp_watts", physiometrics, "ftp_watts"
        )
        if ftp_watts is not None:
            resolved["ftp_watts"] = ftp_watts

        heart_rate = _get_physio_section(physiometrics, "heart_rate")
        for resolved_key, nested_key in (
            ("hr_lthr_bpm", "lthr_bpm"),
            ("hr_lthr_cycling_bpm", "lthr_cycling_bpm"),
            ("hr_max_bpm", "hr_max_bpm"),
            ("hr_resting_bpm", "resting_hr_bpm"),
        ):
            value = _resolve_physio_value(heart_rate, nested_key, physiometrics, resolved_key)
            if value is not None:
                resolved[resolved_key] = value

        weight_kg = _resolve_physio_value(
            _get_physio_section(physiometrics, "body_composition"), "weight_kg", physiometrics, "weight_kg"
        )
        if weight_kg is not None:
            resolved["weight_kg"] = weight_kg

        return resolved

    @staticmethod
    def _resolve_workout_target_date(
        workout_entity: WorkoutEntity,
        metadata_blob: Dict,
    ) -> Optional[str]:
        """Resolve the effective date to use for physio snapshot lookup."""
        start_time = (
            workout_entity.start_time_utc
            or metadata_blob.get("identity", {}).get("start_time_utc")
        )
        if not start_time:
            return None
        try:
            return datetime.fromisoformat(
                str(start_time).replace("Z", utils.UTC_OFFSET)
            ).date().isoformat()
        except (ValueError, AttributeError):
            return None

    def _hydrate_missing_elevation_from_raw_fit(
        self,
        df: pd.DataFrame,
        workout_entity: WorkoutEntity,
        entity: Dict,
    ) -> pd.DataFrame:
        """Backfill climb-related context from archived raw FIT frames when canonical rows are sparse."""
        if not self._needs_raw_fit_hydration(df):
            return df

        raw_context = self._load_raw_fit_record_context(workout_entity, entity)
        if raw_context.empty:
            return df

        hydrated = df.copy()
        restored_counts: Dict[str, int] = {}

        if "timestamp_utc" in hydrated:
            timestamps = pd.to_datetime(hydrated["timestamp_utc"], errors="coerce", utc=True)
            aligned = raw_context.reindex(timestamps, method="nearest", tolerance=pd.Timedelta(seconds=1))
            aligned = aligned.reset_index(drop=True)
            for column in ["elevation_m", "position_lat", "position_long"]:
                if column in aligned:
                    restored_counts[column] = self._fill_missing_numeric_column(
                        hydrated,
                        column,
                        pd.Series(aligned[column].to_numpy(dtype=float), index=hydrated.index, dtype=float),
                    )

        if any(restored_counts.values()):
            logger.info(
                "Recovered canonical climb context from archived raw FIT frames",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "ingestion_id": workout_entity.ingestion_id,
                    "restored_columns": {k: v for k, v in restored_counts.items() if v > 0},
                },
            )
        return hydrated

    @staticmethod
    def _fill_missing_numeric_column(
        df: pd.DataFrame,
        column: str,
        fallback: pd.Series,
    ) -> int:
        existing = (
            pd.to_numeric(df[column], errors="coerce")
            if column in df
            else pd.Series(index=df.index, dtype=float)
        )
        before = int(existing.notna().sum())
        df[column] = existing.where(existing.notna(), fallback)
        after = int(pd.to_numeric(df[column], errors="coerce").notna().sum())
        return after - before

    @staticmethod
    def _needs_raw_fit_hydration(df: pd.DataFrame) -> bool:
        if df.empty or "distance_m" not in df:
            return False
        return any(
            WorkoutQueryService._is_missing_numeric_column(df, column)
            for column in ["elevation_m", "position_lat", "position_long"]
        )

    @staticmethod
    def _is_missing_numeric_column(df: pd.DataFrame, column: str) -> bool:
        if column not in df:
            return True
        return int(pd.to_numeric(df[column], errors="coerce").notna().sum()) == 0

    def _load_raw_fit_record_context(
        self,
        workout_entity: WorkoutEntity,
        entity: Dict,
    ) -> pd.DataFrame:
        """Load timestamp-indexed elevation and GPS coordinates from archived raw FIT frames."""
        infra = getattr(self.storage.workouts, "infra", None)
        if infra is None:
            return pd.DataFrame()

        ingestion_id = workout_entity.ingestion_id or entity.get("ingestion_id")
        for identifier in (ingestion_id, workout_entity.workout_id):
            context = self._load_raw_fit_record_context_for_identifier(infra, identifier)
            if not context.empty:
                return context
        return pd.DataFrame()

    def _load_raw_fit_record_context_for_identifier(
        self,
        infra: Any,
        identifier: Optional[str],
    ) -> pd.DataFrame:
        if not identifier:
            return pd.DataFrame()
        try:
            blob_name = infra.raw_fit_blob_name(identifier)
            payload = infra.load_json_blob(blob_name, gzipped=True)
        except Exception:  # pylint: disable=broad-exception-caught
            return pd.DataFrame()
        frames = payload if isinstance(payload, list) else []
        return self._raw_fit_frames_to_record_context(frames)

    @staticmethod
    def _raw_fit_frames_to_record_context(frames: List[Dict]) -> pd.DataFrame:
        rows = [
            row
            for row in (WorkoutQueryService._raw_fit_record_row(frame) for frame in frames)
            if row is not None
        ]
        if not rows:
            return pd.DataFrame()

        raw_df = pd.DataFrame(rows)
        raw_df["timestamp_utc"] = pd.to_datetime(raw_df["timestamp_utc"], errors="coerce", utc=True)
        for column in ["elevation_m", "position_lat", "position_long"]:
            if column in raw_df:
                raw_df[column] = pd.to_numeric(raw_df[column], errors="coerce")
        raw_df = raw_df.dropna(subset=["timestamp_utc"]).drop_duplicates(
            subset=["timestamp_utc"],
            keep="last",
        )
        return raw_df.set_index("timestamp_utc") if not raw_df.empty else pd.DataFrame()

    @staticmethod
    def _raw_fit_record_row(frame: Dict) -> Optional[Dict[str, Any]]:
        if frame.get("frame_type") != "data_message" or frame.get("name") != "record":
            return None
        fields = frame.get("fields", [])
        if not isinstance(fields, list):
            return None
        field_map = {
            field.get("name"): field.get("value")
            for field in fields
            if isinstance(field, dict) and field.get("name") is not None
        }
        timestamp = field_map.get("timestamp")
        if timestamp is None:
            return None
        return {
            "timestamp_utc": timestamp,
            "elevation_m": field_map.get("enhanced_altitude", field_map.get("altitude")),
            "position_lat": field_map.get("position_lat"),
            "position_long": field_map.get("position_long"),
        }

    # -------------------------------------------------------------------------
    # Lap helpers
    # -------------------------------------------------------------------------

    def _populate_workout_detail_laps(
        self,
        result: Dict,
        workout_entity: WorkoutEntity,
    ) -> Dict:
        """Load laps.json and attach lap summaries to result dict."""
        stored_laps = self._load_stored_laps(workout_entity)
        if stored_laps is None:
            result["laps_error"] = "No lap data available"
            return result

        lap_summaries = []
        for i, lap in enumerate(stored_laps):
            lap_summary = self._summarize_lap_payload(lap, i)
            lap_summaries.append(lap_summary.model_dump(exclude_none=True))

        result["laps"] = lap_summaries
        return result

    @staticmethod
    def _is_meaningful_units(units: Any) -> bool:
        """Return True when units is a non-empty, non-trivial string."""
        return bool(units and str(units).strip() not in {"", "N/A", "none"})

    @staticmethod
    def _lap_field_map(lap: Dict) -> Dict[str, Any]:
        """Convert lap's fields list-of-dicts into {name: {value, units}} map."""
        fields = lap.get("fields") if isinstance(lap, dict) else None
        field_map: Dict[str, Any] = {}
        if not isinstance(fields, list):
            return field_map
        for field in fields:
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if not isinstance(name, str) or not name:
                continue
            field_map[name] = {"value": field.get("value"), "units": field.get("units")}
        return field_map

    @staticmethod
    def _lap_value(field_map_or_payload: Any, name: Optional[str] = None) -> Any:
        """Extract value from field_map by name, or from a single field payload (dict or scalar)."""
        if name is not None:
            return field_map_or_payload.get(name, {}).get("value") if isinstance(field_map_or_payload, dict) else None
        if isinstance(field_map_or_payload, dict):
            return field_map_or_payload.get("value")
        return field_map_or_payload

    @classmethod
    def _lap_extra_fields(cls, field_map: Dict) -> Dict[str, Any]:
        """Return non-promoted, non-dev fields from a lap field_map."""
        extra: Dict[str, Any] = {}
        for field_name, data in field_map.items():
            if field_name in _LAP_PROMOTED_FIELDS:
                continue
            value = data.get("value") if isinstance(data, dict) else data
            if value is None:
                continue
            units = data.get("units") if isinstance(data, dict) else None
            if cls._is_meaningful_units(units):
                extra[field_name] = {"value": value, "units": units}
            else:
                extra[field_name] = value
        return extra

    @classmethod
    def _summarize_lap_payload(cls, lap: Dict, lap_index: int) -> LapSummaryResponse:
        """Build a LapSummaryResponse from a raw lap dict."""
        field_map = cls._lap_field_map(lap)
        extra = cls._lap_extra_fields(field_map)

        def v(name: str) -> Any:
            return cls._lap_value(field_map, name)

        message_index = v("message_index")
        effective_lap_index = int(message_index) if isinstance(message_index, (int, float)) else lap_index
        return LapSummaryResponse(
            lap_index=effective_lap_index,
            message_index=int(message_index) if isinstance(message_index, (int, float)) else None,
            start_time=v("start_time"),
            total_elapsed_time=v("total_elapsed_time"),
            total_timer_time=v("total_timer_time"),
            total_distance=v("total_distance"),
            total_calories=v("total_calories"),
            avg_heart_rate=v("avg_heart_rate"),
            max_heart_rate=v("max_heart_rate"),
            avg_power=v("avg_power"),
            max_power=v("max_power"),
            avg_cadence=v("avg_cadence"),
            max_cadence=v("max_cadence"),
            avg_speed=v("enhanced_avg_speed") or v("avg_speed"),
            max_speed=v("enhanced_max_speed") or v("max_speed"),
            intensity=v("intensity"),
            lap_trigger=v("lap_trigger"),
            sport=v("sport"),
            sub_sport=v("sub_sport"),
            extra_fields=extra or None,
        )

    def _populate_workout_detail_developer_fields(
        self,
        result: Dict,
        metadata_blob: Dict,
    ) -> Dict:
        """Attach developer field summary to result dict."""
        if not isinstance(metadata_blob, dict) or not metadata_blob:
            result["developer_fields_summary"] = None
            return result

        summary = self._summarize_developer_fields(metadata_blob)
        result["developer_fields_summary"] = summary
        return result

    # -------------------------------------------------------------------------
    # Metadata extraction
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_workout_metadata_sections(
        metadata_blob: Dict,
    ) -> Tuple[Dict, Dict, Dict, Dict]:
        """Return (identity, session, enrichment, activity_metadata) from a metadata blob."""
        return (
            metadata_blob.get("identity", {}),
            metadata_blob.get("session", {}),
            metadata_blob.get("enrichment", {}),
            metadata_blob.get("activity_metadata", {}),
        )

    def _build_workout_base_dict(
        self,
        workout_entity: WorkoutEntity,
        identity: Dict,
        session: Dict,
        enrichment: Dict,
        activity_metadata: Dict,
        metrics: Dict,
    ) -> Dict:
        """Assemble top-level base fields for WorkoutDetailResponse."""
        sport = workout_entity.sport or identity.get("sport") or self._infer_sport(metrics)
        sub_sport = (
            workout_entity.sub_sport
            or identity.get("sub_sport")
            or enrichment.get("sub_sport")
        )
        workout_name = enrichment.get("workout_name") or self._infer_workout_name(
            {**identity, **session, **enrichment, **activity_metadata}, sport
        )
        is_indoor = enrichment.get("is_indoor") or self._infer_is_indoor(
            {**session, **enrichment}
        )
        start_time_utc = (
            workout_entity.start_time_utc
            or identity.get("start_time_utc")
            or session.get("start_time_utc")
        )
        local_tz_offset = activity_metadata.get("local_tz_offset")
        timezone_name = activity_metadata.get("timezone") or local_tz_offset
        duration_sec = (
            workout_entity.duration_sec
            or session.get("duration_sec")
            or metrics.get("duration_sec")
            or 0
        )
        moving_time_sec = session.get("moving_time_sec") or metrics.get("moving_time_sec")
        distance_m = session.get("distance_m") or workout_entity.distance_m
        elevation_gain_m = session.get("elevation_gain_m")
        elevation_loss_m = session.get("elevation_loss_m")
        calories_kcal = session.get("calories_kcal") or self._infer_calories(metrics, sport)

        return {
            "workout_id": workout_entity.workout_id,
            "athlete_id": workout_entity.athlete_id,
            "sport": sport,
            "sub_sport": sub_sport,
            "workout_name": workout_name,
            "is_indoor": is_indoor,
            "start_time_utc": start_time_utc,
            "local_tz_offset": local_tz_offset,
            "timezone": timezone_name,
            "duration_sec": duration_sec,
            "moving_time_sec": moving_time_sec,
            "distance_m": distance_m,
            "elevation_gain_m": elevation_gain_m,
            "elevation_loss_m": elevation_loss_m,
            "calories_kcal": calories_kcal,
        }

    # -------------------------------------------------------------------------
    # Canonical metrics helpers
    # -------------------------------------------------------------------------

    def _compute_metrics_from_canonical(
        self,
        df: pd.DataFrame,
        metadata: Dict,
    ) -> Dict:
        """Compute derived metrics using CanonicalAnalyticsEngine."""
        try:
            canonical = CanonicalAnalyticsEngine.from_dataframe(df, metadata)
        except ValidationError as exc:
            distortion = utils.canonical_sampling_distortion(df)
            try:
                canonical = CanonicalAnalyticsEngine.from_dataframe(df, metadata, resample=True)
            except ValidationError as resample_exc:
                logger.exception(
                    "Workout detail canonical validation failed",
                    extra={
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "record_count": len(df),
                        "failure_category": "canonical_sampling_validation",
                        "is_1hz_validation_failure": True,
                        **distortion,
                    },
                )
                raise WorkoutDetailUnavailableError() from resample_exc

            utils.log_canonical_resample_fallback(
                scope="semantic_metrics",
                strict_error=exc,
                record_count=len(df),
                distortion=distortion,
            )
        return canonical.to_metrics_dict()

    def _load_metadata_blob_for_workout(
        self,
        entity: Dict,
        workout_entity: WorkoutEntity,
    ) -> Dict:
        """Load metadata blob for workout detail path."""
        return utils.load_metadata_blob_for_workout(self.storage, entity, workout_entity)

    # -------------------------------------------------------------------------
    # Projection helpers
    # -------------------------------------------------------------------------

    def _load_projection_metadata_blob(self, lookup_id: str, workout_id: str) -> Dict[str, Any]:
        """Load metadata blob used by projection paths and normalize non-dict payloads."""
        metadata_blob = utils.load_metadata_blob(self.storage, lookup_id, workout_id)
        if metadata_blob:
            return metadata_blob
        logger.debug(
            "Could not load metadata blob for projection",
            extra={"lookup_id": lookup_id, "workout_id": workout_id},
        )
        return {}

    def _extract_projection_metadata_sections(
        self,
        metadata_blob: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Extract projection metadata sections — returns 6 keys."""
        return {
            "identity": metadata_blob.get("identity", {}),
            "session": metadata_blob.get("session", {}),
            "enrichment": metadata_blob.get("enrichment", {}),
            "capabilities": metadata_blob.get("capabilities", {}),
            "activity_metadata": metadata_blob.get("activity_metadata", {}),
            "provenance": metadata_blob.get("provenance", {}),
        }

    def _build_workout_projection_kwargs(
        self,
        workout_entity: WorkoutEntity,
        metadata: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble validated kwargs for WorkoutProjection construction."""
        start_time_utc = self._resolve_projection_start_time(workout_entity, metadata)
        if not start_time_utc:
            raise ValueError("Missing required start_time_utc for workout projection")

        has_power = bool(workout_entity.has_power or metadata["capabilities"].get("has_power", False))
        has_hr = bool(workout_entity.has_hr or metadata["capabilities"].get("has_hr", False))
        has_gps = bool(workout_entity.has_gps or metadata["capabilities"].get("has_gps", False))
        capability_metrics = self._projection_capability_metrics(
            metadata["session"],
            has_hr,
            has_power,
        )

        projection_kwargs: Dict[str, Any] = {
            "workout_id": workout_entity.workout_id,
            "athlete_id": workout_entity.athlete_id,
            "sport": workout_entity.sport or metadata["identity"].get("sport") or "unknown",
            "sub_sport": workout_entity.sub_sport or metadata["identity"].get("sub_sport") or metadata["enrichment"].get("sub_sport"),
            "workout_name": metadata["enrichment"].get("workout_name") or metadata["identity"].get("workout_name"),
            "device_name": metadata["identity"].get("device_name") or workout_entity.device_model,
            "device_manufacturer": workout_entity.device_manufacturer or metadata["identity"].get("device_manufacturer"),
            "start_time_utc": start_time_utc,
            "local_tz_offset": metadata["activity_metadata"].get("local_tz_offset"),
            "timezone": metadata["activity_metadata"].get("timezone") or metadata["activity_metadata"].get("local_tz_offset"),
            "duration_sec": workout_entity.duration_sec or metadata["session"].get("duration_sec") or 0,
            "moving_time_sec": metadata["session"].get("moving_time_sec"),
            "distance_m": workout_entity.distance_m or metadata["session"].get("distance_m"),
            "elevation_gain_m": metadata["session"].get("elevation_gain_m"),
            "elevation_loss_m": metadata["session"].get("elevation_loss_m"),
            "calories_kcal": metadata["session"].get("calories_kcal"),
            "has_power": has_power,
            "has_hr": has_hr,
            "has_gps": has_gps,
            "is_indoor": bool(metadata["enrichment"].get("is_indoor", False)),
            "race_flag": bool(metadata["enrichment"].get("race_flag", False)),
            "commute_flag": bool(metadata["enrichment"].get("commute_flag", False)),
            "ingestion_version": metadata["provenance"].get("ingestion_version"),
            "ingestion_timestamp_utc": metadata["provenance"].get("ingestion_timestamp_utc"),
        }
        projection_kwargs.update(capability_metrics)
        return projection_kwargs

    def _projection_capability_metrics(
        self,
        session_metrics: Dict[str, Any],
        has_hr: bool,
        has_power: bool,
    ) -> Dict[str, Any]:
        """Return capability-dependent projection metrics (HR/power) plus cadence values."""
        return {
            "hr_avg_bpm": session_metrics.get("hr_avg_bpm") if has_hr else None,
            "hr_max_bpm": session_metrics.get("hr_max_bpm") if has_hr else None,
            "pwr_avg_watts": session_metrics.get("pwr_avg_watts") if has_power else None,
            "pwr_max_watts": session_metrics.get("pwr_max_watts") if has_power else None,
            "pwr_normalized_watts": session_metrics.get("pwr_normalized_watts") if has_power else None,
            "cad_avg_rpm": session_metrics.get("cad_avg_rpm"),
            "cad_max_rpm": session_metrics.get("cad_max_rpm"),
        }

    def _resolve_projection_start_time(
        self,
        workout_entity: WorkoutEntity,
        metadata: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        """Resolve start time for projection from entity first, then metadata fallbacks."""
        return (
            workout_entity.start_time_utc
            or metadata["identity"].get("start_time_utc")
            or metadata["session"].get("start_time_utc")
        )

    def _load_projection_canonical_records(
        self,
        workout_entity: WorkoutEntity,
        entity: Dict[str, Any],
    ) -> Tuple[Optional[str], Optional[pd.DataFrame]]:
        """Load canonical records used for optional projection hydration."""
        ingestion_id = workout_entity.ingestion_id or entity.get("ingestion_id")
        blob_name = workout_entity.canonical_records_blob or entity.get("canonical_records_blob")
        if not blob_name and ingestion_id:
            blob_name = f"{ingestion_id}/canonical.parquet"
        if not blob_name:
            return None, None

        try:
            df = self.storage.workouts.load_canonical_records(blob_name)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Canonical projection hydration skipped: failed to load canonical records",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "blob_name": blob_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return blob_name, None

        if df.empty:
            return blob_name, None
        return blob_name, df

    def _hydrate_projection_from_canonical(
        self,
        workout_entity: WorkoutEntity,
        entity: Dict[str, Any],
        metadata_blob: Dict[str, Any],
        projection_kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Hydrate missing capability-dependent projection fields from canonical analytics."""
        has_hr = bool(projection_kwargs.get("has_hr"))
        has_power = bool(projection_kwargs.get("has_power"))

        target_fields: List[str] = []
        if has_hr:
            target_fields.extend(["hr_avg_bpm", "hr_max_bpm"])
        if has_power:
            target_fields.extend(["pwr_avg_watts", "pwr_max_watts", "pwr_normalized_watts"])
        target_fields.extend(["cad_avg_rpm", "cad_max_rpm"])

        if not target_fields:
            return {}

        needs_hydration = any(projection_kwargs.get(field) is None for field in target_fields)
        if not needs_hydration:
            return {}

        blob_name, df = self._load_projection_canonical_records(workout_entity, entity)
        if df is None:
            return {}

        canonical_metadata = utils.prepare_rollup_metadata_for_canonical(
            metadata_blob, workout_entity
        )
        canonical_metadata["sport"] = (
            workout_entity.sport
            or metadata_blob.get("identity", {}).get("sport")
            or canonical_metadata.get("sport")
        )
        canonical_metadata["sub_sport"] = (
            workout_entity.sub_sport
            or metadata_blob.get("identity", {}).get("sub_sport")
            or metadata_blob.get("enrichment", {}).get("sub_sport")
            or canonical_metadata.get("sub_sport")
        )

        try:
            canonical = CanonicalAnalyticsEngine.from_dataframe(df, canonical_metadata)
        except ValidationError:
            try:
                canonical = CanonicalAnalyticsEngine.from_dataframe(
                    df, canonical_metadata, resample=True
                )
            except ValidationError as exc:
                logger.warning(
                    "Canonical projection hydration skipped: canonical validation failed",
                    extra={
                        "workout_id": workout_entity.workout_id,
                        "blob_name": blob_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "status_code": exc.status_code,
                    },
                )
                return {}

        canonical_metrics = canonical.to_metrics_dict()
        updates: Dict[str, Any] = {}
        for field in target_fields:
            if projection_kwargs.get(field) is None and canonical_metrics.get(field) is not None:
                updates[field] = canonical_metrics[field]

        if updates:
            logger.debug(
                "WorkoutProjection hydrated missing fields from canonical",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "blob_name": blob_name,
                    "hydrated_fields": sorted(updates.keys()),
                },
            )
        return updates

    # -------------------------------------------------------------------------
    # Lap / FIT timeseries loading
    # -------------------------------------------------------------------------

    def _load_stored_laps(self, workout_entity: WorkoutEntity) -> Optional[List[Dict]]:
        ingestion_id: str = ""
        try:
            ingestion_id = workout_entity.ingestion_id or workout_entity.workout_id
            payload = self.storage.workouts.load_laps_json(ingestion_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to load laps.json",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "ingestion_id": ingestion_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None
        laps = payload.get("laps") if isinstance(payload, dict) else None
        if not isinstance(laps, list) or not laps:
            return None
        return laps

    def _load_fit_timeseries(
        self,
        entity: Dict,
        *,
        include_records: bool,
        include_laps: bool,
    ) -> Tuple[Optional[List[Dict]], Optional[List[Dict]], Dict[str, str]]:
        records: Optional[List[Dict]] = None
        laps: Optional[List[Dict]] = None
        errors: Dict[str, str] = {}

        if include_records:
            records, error = self._load_canonical_records_payload(entity)
            if error:
                errors["records_error"] = error

        if include_laps:
            laps, error = self._load_laps_json_payload(entity)
            if error:
                errors["laps_error"] = error

        return records, laps, errors

    def _load_canonical_records_payload(
        self, entity: Dict
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        workout_id = entity.get("workout_id")
        ingestion_id = entity.get("ingestion_id") or workout_id
        if not ingestion_id:
            return None, "No workout id available"

        records_blob = entity.get("canonical_records_blob") or f"{ingestion_id}/canonical.parquet"
        try:
            records_df = self.storage.workouts.load_canonical_records(records_blob)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, str(exc)

        if records_df.empty:
            return None, None
        return records_df.to_dict(orient="records"), None

    def _load_laps_json_payload(
        self, entity: Dict
    ) -> Tuple[Optional[List[Dict]], Optional[str]]:
        workout_id = entity.get("workout_id")
        ingestion_id = entity.get("ingestion_id") or workout_id
        if not ingestion_id:
            return None, "No workout id available"

        try:
            payload = self.storage.workouts.load_laps_json(ingestion_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, str(exc)

        laps = payload.get("laps") if isinstance(payload, dict) else None
        if not isinstance(laps, list) or not laps:
            return None, None
        return laps, None

    @staticmethod
    def _set_timeseries_error(
        errors: Dict[str, str],
        include_records: bool,
        include_laps: bool,
        message: str,
    ) -> None:
        if include_records:
            errors["records_error"] = message
        if include_laps:
            errors["laps_error"] = message

    # -------------------------------------------------------------------------
    # Developer fields
    # -------------------------------------------------------------------------

    @staticmethod
    def _iter_metadata_messages(metadata_payload: Dict):
        for message_type, messages in metadata_payload.items():
            if not isinstance(messages, list):
                continue
            for message in messages:
                yield message_type, message

    @staticmethod
    def _iter_developer_fields(message: Dict):
        msg_fields = message.get("fields", {})
        if not isinstance(msg_fields, dict):
            return
        for field_name, field_payload in msg_fields.items():
            if str(field_name).startswith("dev_"):
                yield field_name, field_payload

    @staticmethod
    def _extract_units_and_value(field_payload: object) -> Tuple[Optional[str], Optional[object]]:
        if isinstance(field_payload, dict):
            return field_payload.get("units"), field_payload.get("value")
        return None, None

    def _summarize_developer_fields(self, metadata_payload: Dict) -> Dict:
        """Build a compact developer-field summary from metadata artifact."""
        fields_by_key: Dict[str, DevFieldSummary] = {}
        for message_type, message in self._iter_metadata_messages(metadata_payload):
            for field_name, field_payload in self._iter_developer_fields(message):
                key = f"{message_type}.{field_name}"
                entry = fields_by_key.setdefault(
                    key,
                    DevFieldSummary(
                        {
                            "message_type": message_type,
                            "field": field_name,
                            "count": 0,
                            "units": set(),
                            "sample_values": [],
                        }
                    ),
                )
                entry["count"] = int(entry["count"]) + 1
                units, value = self._extract_units_and_value(field_payload)
                if units:
                    entry["units"].add(units)
                if value is not None and len(entry["sample_values"]) < 3:
                    entry["sample_values"].append(value)

        fields = []
        for entry in fields_by_key.values():
            fields.append(
                {
                    "message_type": entry["message_type"],
                    "field": entry["field"],
                    "count": entry["count"],
                    "units": sorted(entry["units"]),
                    "sample_values": entry["sample_values"],
                }
            )
        fields.sort(key=lambda item: (item["message_type"], item["field"]))
        return {
            "field_count": len(fields),
            "fields": fields,
        }

    # -------------------------------------------------------------------------
    # Static inference helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _infer_sport(metrics: Dict) -> str:
        sport = metrics.get("sport")
        if sport:
            return sport
        sub_sport = metrics.get("sub_sport")
        if sub_sport:
            lowered = sub_sport.lower()
            if "cycling" in lowered or "bike" in lowered:
                return "cycling"
            if "run" in lowered:
                return "running"
            if "swim" in lowered:
                return "swimming"
        return "unknown"

    @staticmethod
    def _infer_is_indoor(metrics: Dict) -> bool:
        is_indoor = metrics.get("is_indoor")
        if is_indoor is not None:
            return bool(is_indoor)
        elevation = metrics.get("elevation_gain_m", 0) or 0
        distance = metrics.get("distance_m", 0) or 0
        return bool(distance > 100 and elevation < 5)

    @staticmethod
    def _infer_workout_name(metrics: Dict, sport: str) -> str:
        workout_name = metrics.get("workout_name")
        if workout_name:
            return workout_name
        start_time = metrics.get("start_time_utc")
        if start_time:
            try:
                parsed = datetime.fromisoformat(
                    str(start_time).replace("Z", utils.UTC_OFFSET)
                )
                return f"{sport.title()} - {parsed.strftime('%b %d, %Y')}"
            except (ValueError, AttributeError):
                return f"{sport.title()} Workout"
        return f"{sport.title()} Workout"

    @staticmethod
    def _infer_calories(metrics: Dict, sport: str) -> Optional[int]:
        calories = metrics.get("calories_kcal")
        if calories is not None:
            return calories
        duration_min = (metrics.get("duration_sec") or 0) / 60
        if "run" in sport.lower():
            return int(duration_min * 15)
        return int(duration_min * 10)
