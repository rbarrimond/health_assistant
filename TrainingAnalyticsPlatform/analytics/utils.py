"""Shared utility functions for analytics services.

Module-level functions used across multiple analytics services.
No class or service state — all functions are pure or take explicit storage arguments.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import pandas as pd

from TrainingAnalyticsPlatform.models.core import WorkoutMetricsModel, WorkoutProjection
from TrainingAnalyticsPlatform.platform.exceptions import StorageError, ValidationError
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity

if TYPE_CHECKING:
    from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

logger = logging.getLogger(__name__)

UTC_OFFSET = "+00:00"
CANONICAL_DISTORTION_WARN_PCT = float(os.getenv("CANONICAL_DISTORTION_WARN_PCT", "5.0"))
_NON_1HZ_EPSILON_SEC = 1.01


# ---------------------------------------------------------------------------
# Date / Partition helpers
# ---------------------------------------------------------------------------

def parse_workout_query_bound(
    value: Optional[str],
    *,
    default_value: datetime,
    is_end: bool,
) -> datetime:
    """Parse workout query bounds into UTC-aware datetimes.

    Date-only values are treated as UTC day bounds so `until=YYYY-MM-DD`
    remains inclusive for the full day.
    """
    if value is None:
        parsed = default_value
    else:
        normalized_value = value.replace("Z", UTC_OFFSET)
        parsed = datetime.fromisoformat(normalized_value)
        if parsed.tzinfo is None:
            if "T" not in value:
                parsed = datetime.combine(
                    parsed.date(),
                    time.max if is_end else time.min,
                    tzinfo=timezone.utc,
                )
            else:
                parsed = parsed.replace(tzinfo=timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def get_month_partitions(
    athlete_id: str,
    start_date: datetime,
    end_date: datetime,
) -> List[str]:
    """Generate partition keys for all months in date range.

    Returns:
        List of partition key strings (e.g., ['rob|2026-01', 'rob|2026-02'])
    """
    partitions = []
    current = start_date.replace(day=1)

    while current <= end_date:
        partition_key = f"{athlete_id}|{current.strftime('%Y-%m')}"
        partitions.append(partition_key)

        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return partitions


def build_partition_date_range_query(
    partition_key: str,
    start_date: datetime,
    end_date: datetime,
) -> str:
    """Build a PartitionKey-scoped query with UTC `start_time_utc` bounds."""
    start_utc = start_date.astimezone(timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
    end_utc = end_date.astimezone(timezone.utc).isoformat().replace(UTC_OFFSET, "Z")
    return (
        f"PartitionKey eq '{partition_key}' "
        f"and start_time_utc ge '{start_utc}' "
        f"and start_time_utc le '{end_utc}'"
    )


def entity_within_date_range(
    entity: Dict[str, Any],
    start_date: datetime,
    end_date: datetime,
) -> bool:
    """Return True when entity start time exists and falls within [start_date, end_date]."""
    workout_start = entity.get("start_time_utc")
    if not workout_start:
        return False
    workout_date = datetime.fromisoformat(
        workout_start.replace("Z", UTC_OFFSET)
    ).astimezone(timezone.utc)
    return start_date <= workout_date <= end_date


# ---------------------------------------------------------------------------
# Metadata blob helpers
# ---------------------------------------------------------------------------

def load_metadata_blob(
    storage: "StorageCoordinator",
    lookup_id: str,
    workout_id: str,
) -> Dict[str, Any]:
    """Load metadata blob and normalize non-dict payloads to an empty dict."""
    try:
        metadata_blob = storage.workouts.load_metadata_json(lookup_id)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug(
            "Could not load metadata blob",
            extra={
                "lookup_id": lookup_id,
                "workout_id": workout_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        return {}
    return metadata_blob if isinstance(metadata_blob, dict) else {}


def load_metadata_blob_for_workout(
    storage: "StorageCoordinator",
    entity: Dict[str, Any],
    workout_entity: WorkoutEntity,
) -> Dict[str, Any]:
    """Load metadata.json blob for workout-centric transformations."""
    lookup_id = entity.get("ingestion_id") or workout_entity.workout_id
    return load_metadata_blob(storage, lookup_id, workout_entity.workout_id)


# ---------------------------------------------------------------------------
# Canonical sampling helpers
# ---------------------------------------------------------------------------

def canonical_sampling_distortion(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute sparse-gap distortion summary for canonical timeline."""
    if "timestamp_utc" not in df.columns or df.empty:
        return {
            "gap_count": 0,
            "max_gap_sec": 0.0,
            "inserted_missing_bins": 0,
            "distortion_pct": None,
        }

    timestamps = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    timestamps = timestamps.dropna().sort_values().reset_index(drop=True)
    if len(timestamps) < 2:
        return {
            "gap_count": 0,
            "max_gap_sec": 0.0,
            "inserted_missing_bins": 0,
            "distortion_pct": None,
        }

    diffs = timestamps.diff().dt.total_seconds().dropna()
    gaps = diffs[diffs > _NON_1HZ_EPSILON_SEC]
    if gaps.empty:
        return {
            "gap_count": 0,
            "max_gap_sec": 0.0,
            "inserted_missing_bins": 0,
            "distortion_pct": 0.0,
        }

    span_sec = float((timestamps.iloc[-1] - timestamps.iloc[0]).total_seconds())
    inserted_missing_bins = int(sum(max(int(round(float(gap))) - 1, 0) for gap in gaps))
    distortion_pct = (
        round((inserted_missing_bins / span_sec) * 100, 3)
        if span_sec > 0
        else None
    )
    return {
        "gap_count": int(len(gaps)),
        "max_gap_sec": round(float(gaps.max()), 3),
        "inserted_missing_bins": inserted_missing_bins,
        "distortion_pct": distortion_pct,
    }


def log_canonical_resample_fallback(
    *,
    scope: str,
    strict_error: ValidationError,
    record_count: int,
    distortion: Dict[str, Any],
    workout_id: Optional[str] = None,
    blob_name: Optional[str] = None,
) -> None:
    """Log strict->resample canonical fallback with thresholded warning level."""
    distortion_pct = distortion.get("distortion_pct")
    exceeds_threshold = (
        isinstance(distortion_pct, (int, float))
        and distortion_pct > CANONICAL_DISTORTION_WARN_PCT
    )
    log_level = logger.warning if exceeds_threshold else logger.info
    log_level(
        "Canonical analytics strict validation failed; resample fallback applied",
        extra={
            "scope": scope,
            "workout_id": workout_id,
            "blob_name": blob_name,
            "error_type": type(strict_error).__name__,
            "error": str(strict_error),
            "record_count": record_count,
            "failure_category": "canonical_sampling_validation",
            "is_1hz_validation_failure": True,
            "resample_fallback_applied": True,
            "distortion_warn_threshold_pct": CANONICAL_DISTORTION_WARN_PCT,
            "distortion_warn_exceeded": exceeds_threshold,
            **distortion,
        },
    )


def compute_basic_metrics_from_canonical(df: pd.DataFrame) -> Dict[str, Any]:
    """Compute minimal sample statistics when full canonical analytics are unavailable."""
    metrics: Dict[str, Any] = {}
    row_count = len(df)
    if row_count == 0:
        return metrics

    if "heart_rate_bpm" in df.columns:
        hr = pd.to_numeric(df["heart_rate_bpm"], errors="coerce")
        hr_valid = hr.notna()
        hr_count = int(hr_valid.sum())
        metrics["hr_samples_count"] = hr_count
        metrics["hr_missing_pct"] = float((1 - (hr_count / row_count)) * 100)
        if hr_count > 0:
            metrics["hr_avg_bpm"] = float(hr[hr_valid].mean())
            metrics["hr_max_bpm"] = float(hr[hr_valid].max())
            metrics["hr_min_bpm"] = float(hr[hr_valid].min())

    if "power_watts" in df.columns:
        pwr = pd.to_numeric(df["power_watts"], errors="coerce")
        pwr_valid = pwr.notna()
        pwr_count = int(pwr_valid.sum())
        metrics["pwr_samples_count"] = pwr_count
        metrics["pwr_missing_pct"] = float((1 - (pwr_count / row_count)) * 100)
        if pwr_count > 0:
            metrics["pwr_avg_watts"] = float(pwr[pwr_valid].mean())
            metrics["pwr_max_watts"] = float(pwr[pwr_valid].max())

    if "cadence_rpm" in df.columns:
        cad = pd.to_numeric(df["cadence_rpm"], errors="coerce")
        cad_valid = cad.notna()
        cad_count = int(cad_valid.sum())
        metrics["cad_samples_count"] = cad_count
        if cad_count > 0:
            metrics["cad_avg_rpm"] = float(cad[cad_valid].mean())
            metrics["cad_max_rpm"] = float(cad[cad_valid].max())

    return metrics


# ---------------------------------------------------------------------------
# Field-selection helpers
# ---------------------------------------------------------------------------

def select_fields(source: Dict[str, Any], fields: List[str]) -> Dict[str, Any]:
    """Return a dict containing only the requested fields from source."""
    return {field: source.get(field) for field in fields}


def as_metadata_dict(value: Any) -> Dict[str, Any]:
    """Return a dict metadata section or empty dict."""
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rollup metadata helpers
# ---------------------------------------------------------------------------

def rollup_promoted_defaults(
    *,
    identity: Dict[str, Any],
    session: Dict[str, Any],
    enrichment: Dict[str, Any],
    activity: Dict[str, Any],
    workout_entity: WorkoutEntity,
) -> Dict[str, Any]:
    """Build promoted top-level defaults for canonical rollup metadata."""
    timezone_value = activity.get("timezone") or activity.get("local_tz_offset")
    return {
        "start_time_utc": (
            identity.get("start_time_utc")
            or session.get("start_time_utc")
            or workout_entity.start_time_utc
        ),
        "sport": identity.get("sport") or workout_entity.sport,
        "sub_sport": identity.get("sub_sport") or workout_entity.sub_sport,
        "workout_name": enrichment.get("workout_name"),
        "device_name": identity.get("device_name") or workout_entity.device_model,
        "is_indoor": enrichment.get("is_indoor"),
        "local_tz_offset": activity.get("local_tz_offset"),
        "timezone": timezone_value,
        "duration_sec": session.get("duration_sec") or workout_entity.duration_sec,
        "moving_time_sec": session.get("moving_time_sec"),
        "distance_m": session.get("distance_m") or workout_entity.distance_m,
        "elevation_gain_m": session.get("elevation_gain_m"),
        "elevation_loss_m": session.get("elevation_loss_m"),
        "calories_kcal": session.get("calories_kcal"),
    }


def prepare_rollup_metadata_for_canonical(
    metadata_blob: Dict[str, Any],
    workout_entity: WorkoutEntity,
) -> Dict[str, Any]:
    """Prepare canonical metadata for analytics engine with authoritative metadata precedence.

    Weekly rollup metadata artifacts are stored in semantic zones (`identity`, `session`,
    `enrichment`, `activity_metadata`). `CanonicalAnalyticsEngine` expects top-level keys,
    so this method projects authoritative metadata fields to top level while preserving any
    existing top-level values already present.
    """
    metadata = dict(metadata_blob) if isinstance(metadata_blob, dict) else {}
    identity = as_metadata_dict(metadata.get("identity"))
    session = as_metadata_dict(metadata.get("session"))
    enrichment = as_metadata_dict(metadata.get("enrichment"))
    activity = as_metadata_dict(metadata.get("activity_metadata"))
    promoted_defaults = rollup_promoted_defaults(
        identity=identity,
        session=session,
        enrichment=enrichment,
        activity=activity,
        workout_entity=workout_entity,
    )

    for key, value in promoted_defaults.items():
        if metadata.get(key) is None and value is not None:
            metadata[key] = value

    return metadata


# ---------------------------------------------------------------------------
# Rollup metrics model builder
# ---------------------------------------------------------------------------

def build_rollup_metrics_model(
    storage: "StorageCoordinator",
    entity: Dict[str, Any],
) -> WorkoutMetricsModel:
    """Build WorkoutMetricsModel from canonical records for rollup/analytics use.

    Applies strict 1Hz validation then resamples on failure.

    Raises:
        StorageError: When canonical records cannot be loaded.
        ValidationError: When canonical validation fails even after resampling.
    """
    workout_entity = WorkoutEntity.from_table_entity(entity)
    blob_name = workout_entity.canonical_records_blob or entity.get("canonical_records_blob")
    if not blob_name:
        ingestion_id = workout_entity.ingestion_id or entity.get("ingestion_id")
        if ingestion_id:
            blob_name = f"{ingestion_id}/canonical.parquet"

    if not blob_name:
        raise StorageError(
            f"No canonical records blob for workout {workout_entity.workout_id}"
        )

    try:
        df = storage.workouts.load_canonical_records(blob_name)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "Failed to load canonical records for weekly rollup",
            extra={
                "workout_id": workout_entity.workout_id,
                "blob_name": blob_name,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "failure_category": "canonical_load_failure",
            },
            exc_info=True,
        )
        raise StorageError(
            f"Failed to load canonical records for workout {workout_entity.workout_id}"
        ) from exc

    metadata = load_metadata_blob(storage, workout_entity.ingestion_id or workout_entity.workout_id, workout_entity.workout_id)
    metadata = prepare_rollup_metadata_for_canonical(metadata, workout_entity)

    try:
        model = WorkoutMetricsModel.from_canonical(df, metadata, resample=False)
        return model
    except ValidationError as exc:
        distortion = canonical_sampling_distortion(df)
        try:
            model = WorkoutMetricsModel.from_canonical(df, metadata, resample=True)
        except ValidationError:
            logger.error(
                "Weekly rollup canonical validation failed",
                extra={
                    "workout_id": workout_entity.workout_id,
                    "blob_name": blob_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "failure_category": "canonical_sampling_validation",
                    "is_1hz_validation_failure": True,
                    "status_code": exc.status_code,
                    **distortion,
                },
                exc_info=True,
            )
            raise ValidationError(
                "Weekly rollup canonical validation failed for workout "
                f"{workout_entity.workout_id} (blob={blob_name}): {exc}",
                status_code=exc.status_code,
            ) from exc

        log_canonical_resample_fallback(
            scope="weekly_rollup",
            workout_id=workout_entity.workout_id,
            blob_name=blob_name,
            strict_error=exc,
            record_count=len(df),
            distortion=distortion,
        )
        return model
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(
            "Failed to build WorkoutMetricsModel for weekly rollup",
            extra={
                "workout_id": workout_entity.workout_id,
                "blob_name": blob_name,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "failure_category": "workout_metrics_model_build",
                "is_1hz_validation_failure": False,
            },
            exc_info=True,
        )
        raise StorageError("Failed to build WorkoutMetricsModel for weekly rollup") from exc


def workout_summary_from_metrics_model(
    entity: Dict[str, Any],
    metrics_model: WorkoutMetricsModel,
) -> Dict[str, Any]:
    """Project WorkoutMetricsModel into planning/analysis summary fields."""
    zones_hr = metrics_model.zones_hr
    zones_power = metrics_model.zones_power
    durability = metrics_model.durability
    session = metrics_model.session
    samples = metrics_model.samples

    return {
        "workout_id": entity.get("workout_id"),
        "athlete_id": entity.get("athlete_id"),
        "sport": session.sport,
        "start_time_utc": session.start_time_utc,
        "duration_sec": session.duration_sec,
        "hr_avg_bpm": samples.hr_avg_bpm,
        "hr_z1_sec": zones_hr.hr_z1_sec if zones_hr else 0,
        "hr_z2_sec": zones_hr.hr_z2_sec if zones_hr else 0,
        "hr_z3_sec": zones_hr.hr_z3_sec if zones_hr else 0,
        "hr_z4_sec": zones_hr.hr_z4_sec if zones_hr else 0,
        "hr_z5_sec": zones_hr.hr_z5_sec if zones_hr else 0,
        "pwr_z1_sec": zones_power.pwr_z1_sec if zones_power else 0,
        "pwr_z2_sec": zones_power.pwr_z2_sec if zones_power else 0,
        "pwr_z3_sec": zones_power.pwr_z3_sec if zones_power else 0,
        "pwr_z4_sec": zones_power.pwr_z4_sec if zones_power else 0,
        "pwr_z5_sec": zones_power.pwr_z5_sec if zones_power else 0,
        "intensity_sec": zones_power.intensity_sec if zones_power else 0,
        "decoupling_pct": durability.decoupling_pct if durability else None,
        "ef_overall": durability.ef_overall if durability else None,
        "hr_drift_bpm": durability.hr_drift_bpm if durability else None,
    }


# ---------------------------------------------------------------------------
# Range query helpers (shared by AnalysisService, PlanningService)
# ---------------------------------------------------------------------------

def get_workouts_in_range(
    storage: "StorageCoordinator",
    athlete_id: str,
    start_date: datetime,
    end_date: datetime,
) -> List[Dict[str, Any]]:
    """Retrieve workouts within a date range as summary dicts."""
    from azure.core.exceptions import HttpResponseError  # local import to avoid top-level dep

    try:
        table_client = storage.infrastructure.get_table_client("Workouts")
        months = get_month_partitions(athlete_id, start_date, end_date)

        workouts = []
        for partition_key in months:
            workouts.extend(
                collect_partition_workout_metrics(
                    storage=storage,
                    table_client=table_client,
                    partition_key=partition_key,
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        workouts.sort(key=lambda w: w.get("start_time_utc", ""), reverse=True)
        return workouts

    except HttpResponseError as exc:
        logger.error(
            "Error querying workouts",
            extra={
                "athlete_id": athlete_id,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "error_type": "HttpResponseError",
                "error": str(exc),
            },
            exc_info=True,
        )
        return []


def build_workout_summaries_from_entities(
    storage: "StorageCoordinator",
    entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build workout summary dicts from a pre-fetched entity list using parallel blob reads."""
    workouts: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(build_rollup_metrics_model, storage, entity): entity
            for entity in entities
        }
        for future in as_completed(futures):
            entity = futures[future]
            try:
                metrics_model = future.result()
            except StorageError as exc:
                logger.warning(
                    "Skipping workout in range: canonical metrics unavailable",
                    extra={
                        "workout_id": entity.get("workout_id"),
                        "partition_key": entity.get("PartitionKey"),
                        "error": str(exc),
                    },
                )
                continue
            workouts.append(workout_summary_from_metrics_model(entity, metrics_model))
    return workouts


def collect_all_workout_entities(
    storage: "StorageCoordinator",
    athlete_id: str,
    start_date: datetime,
    end_date: datetime,
) -> List[Dict[str, Any]]:
    """Return all raw Workouts table entities for the athlete in the date range."""
    table_client = storage.infrastructure.get_table_client("Workouts")
    months = get_month_partitions(athlete_id, start_date, end_date)
    entities: List[Dict[str, Any]] = []
    for partition_key in months:
        query = build_partition_date_range_query(partition_key, start_date, end_date)
        for entity in table_client.query_entities(query):
            if entity_within_date_range(entity, start_date, end_date):
                entities.append(dict(entity))
    return entities


def collect_partition_workout_metrics(
    storage: "StorageCoordinator",
    table_client: Any,
    partition_key: str,
    start_date: datetime,
    end_date: datetime,
) -> List[Dict[str, Any]]:
    """Collect workouts for a single partition constrained to date window."""
    query = build_partition_date_range_query(partition_key, start_date, end_date)
    entities = [
        entity
        for entity in table_client.query_entities(query)
        if entity_within_date_range(entity, start_date, end_date)
    ]
    return build_workout_summaries_from_entities(storage, entities)


def get_workout_projections_in_range(
    storage: "StorageCoordinator",
    athlete_id: str,
    start_date: datetime,
    end_date: datetime,
    workout_service: Any,
) -> List[WorkoutProjection]:
    """Retrieve WorkoutProjection objects for a date range."""
    from azure.core.exceptions import HttpResponseError  # local import

    try:
        table_client = storage.infrastructure.get_table_client("Workouts")
        months = get_month_partitions(athlete_id, start_date, end_date)
        projections = collect_workout_projections(
            workout_service=workout_service,
            table_client=table_client,
            months=months,
            start_date=start_date,
            end_date=end_date,
        )
        projections.sort(key=lambda p: p.start_time_utc or "", reverse=True)
        return projections

    except HttpResponseError as exc:
        logger.error(
            "Error querying workout projections",
            extra={
                "athlete_id": athlete_id,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "error_type": "HttpResponseError",
                "error": str(exc),
            },
            exc_info=True,
        )
        return []


def collect_workout_projections(
    workout_service: Any,
    table_client: Any,
    months: List[str],
    start_date: datetime,
    end_date: datetime,
) -> List[WorkoutProjection]:
    """Collect projections for entities that fall in the requested date window."""
    projections: List[WorkoutProjection] = []
    for partition_key in months:
        query = build_partition_date_range_query(partition_key, start_date, end_date)
        entities = table_client.query_entities(query)
        for entity in entities:
            if not entity_within_date_range(entity, start_date, end_date):
                continue
            projection = workout_service.build_workout_projection(entity)
            if projection is not None:
                projections.append(projection)
    return projections
