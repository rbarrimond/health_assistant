"""Semantic Access Layer - Exposes meaningful questions about training data.

This layer sits between the raw metrics DB and the ChatGPT UI.
It shapes data for reasoning, constrains scope, and encodes how humans think about training.
"""
# pylint: disable=too-many-lines

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, TypedDict
import pandas as pd

from azure.core.exceptions import HttpResponseError

from TrainingAnalyticsPlatform.models.core import CanonicalAnalyticsEngine
from TrainingAnalyticsPlatform.storage.storage_infrastructure import WorkoutEntity

logger = logging.getLogger(__name__)
UTC_OFFSET = "+00:00"


class DevFieldSummary(TypedDict):
    """Summary of developer fields in a workout."""
    message_type: str
    field: str
    count: int
    units: set[str]
    sample_values: list[object]


class SemanticLayer:
    """Semantic access layer for workout intelligence queries."""

    def __init__(self, storage: Optional["StorageCoordinator"] = None):
        """Initialize semantic layer with storage backend."""
        if storage is None:
            from TrainingAnalyticsPlatform.storage.storage_coordinator import StorageCoordinator

            self.storage = StorageCoordinator()
        else:
            self.storage = storage

    # -------------------------------------------------------------------------
    # Planning Context - The Most Important Endpoint
    # -------------------------------------------------------------------------

    def get_planning_context(
        self, athlete_id: str, days: int = 45
    ) -> Dict:
        """
        Get planning context for training decisions.

        This is the single most important endpoint:
        GET /api/planning/context?days=N

        Returns everything needed to answer:
        "Given what I've actually done, what does tomorrow look like?"

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back (default 45)

        Returns:
            Dict containing:
            - recent_workouts: List of workout summaries (last N days)
            - weekly_rollups: Weekly aggregated data
            - last_hard_day: Date of last high-intensity workout
            - last_long_day: Date of last long aerobic workout
            - cumulative_z2_minutes: Total Z2 time in window
            - cumulative_intensity_minutes: Total Z4+ time in window
            - notable_flags: Warnings (missing HR, excessive drift, etc.)
            - query_window: Time range of data
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        # Get recent workouts
        workouts = self._get_workouts_in_range(
            athlete_id, start_date, end_date
        )

        # Analyze patterns
        last_hard_day = self._find_last_hard_day(workouts)
        last_long_day = self._find_last_long_day(workouts)
        z2_minutes = self._sum_zone_time(workouts, "hr_z2_min")
        intensity_minutes = self._sum_high_intensity(workouts)
        flags = self._detect_notable_flags(workouts)

        # Get weekly rollups
        weeks = self._get_weekly_rollups(athlete_id, days)

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "recent_workouts": workouts,
            "weekly_rollups": weeks,
            "summary": {
                "last_hard_day": last_hard_day,
                "last_long_day": last_long_day,
                "cumulative_z2_minutes": z2_minutes,
                "cumulative_intensity_minutes": intensity_minutes,
                "total_workouts": len(workouts),
            },
            "notable_flags": flags,
        }

    # -------------------------------------------------------------------------
    # Workout Queries
    # -------------------------------------------------------------------------

    def get_workouts(
        self,
        athlete_id: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: int = 50,
        sport: Optional[str] = None,
    ) -> List[Dict]:
        """
        Query workouts with filters.

        GET /api/workouts?since=2026-01-01&limit=50&sport=Cycling

        Args:
            athlete_id: Athlete identifier
            since: ISO date string (start of range)
            until: ISO date string (end of range)
            limit: Maximum number of workouts to return
            sport: Filter by sport type

        Returns:
            List of workout summaries
        """
        # Parse date range
        end_date = (
            datetime.fromisoformat(until.replace("Z", UTC_OFFSET))
            if until
            else datetime.now(timezone.utc)
        )

        # Default to 90 days if no start date
        start_date = (
            datetime.fromisoformat(since.replace("Z", UTC_OFFSET))
            if since
            else end_date - timedelta(days=90)
        )

        workouts = self._get_workouts_in_range(
            athlete_id, start_date, end_date
        )

        # Filter by sport if specified
        if sport:
            workouts = [w for w in workouts if w.get("sport") == sport]

        # Apply limit
        return workouts[:limit]

    def get_workout_detail(
        self,
        athlete_id: str,
        workout_id: str,
        include_laps: bool = False,
        include_developer_fields: bool = False,
    ) -> Optional[Dict]:
        """
        Get detailed workout data with optional lap summaries.

        GET /api/workouts/{workout_id}

        Args:
            athlete_id: Athlete identifier
            workout_id: Unique workout identifier

        Returns:
            Full workout data, or None if not found
        """
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access

            # Query by workout_id across partitions
            query = f"workout_id eq '{workout_id}'"
            entities = list(table_client.query_entities(query, top=1))

            if not entities:
                return None

            entity = entities[0]

            # Verify athlete_id matches
            if entity.get("athlete_id") != athlete_id:
                return None

            workout_entity = WorkoutEntity.from_table_entity(entity)
            workout = self._entity_to_workout_dict(entity)

            if include_laps:
                laps = self._load_stored_laps(workout_entity)
                errors: Dict[str, str] = {}
                if laps is None:
                    _, fit_laps, fit_errors = self._load_fit_timeseries(
                        entity,
                        include_records=False,
                        include_laps=True,
                    )
                    laps = fit_laps
                    errors.update(fit_errors)

                if laps is not None:
                    workout["laps"] = laps
                    workout["laps_count"] = len(laps)
                if errors:
                    workout.update(errors)

            if include_developer_fields:
                try:
                    ingestion_id = entity.get("ingestion_id") or workout_id
                    metadata_payload = self.storage.workouts.load_metadata_json(ingestion_id)
                    workout["developer_fields_summary"] = self._summarize_developer_fields(
                        metadata_payload
                    )
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    workout["developer_fields_error"] = str(exc)

            return workout

        except HttpResponseError as e:
            logger.error(
                "Error retrieving workout",
                extra={
                    "workout_id": workout_id,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    # -------------------------------------------------------------------------
    # Rollup Queries
    # -------------------------------------------------------------------------

    def get_weekly_rollups(
        self, athlete_id: str, weeks: int = 16
    ) -> List[Dict]:
        """
        Get weekly rollup data.

        GET /api/rollups/weekly?weeks=16

        Args:
            athlete_id: Athlete identifier
            weeks: Number of weeks to retrieve

        Returns:
            List of weekly rollup summaries
        """
        return self._get_weekly_rollups(athlete_id, weeks * 7)

    # -------------------------------------------------------------------------
    # Analysis Queries
    # -------------------------------------------------------------------------

    def get_zone_distribution(
        self, athlete_id: str, days: int = 30
    ) -> Dict:
        """
        Get time-in-zone distribution for planning.

        GET /api/analysis/zones?days=30

        Args:
            athlete_id: Athlete identifier
            days: Number of days to analyze

        Returns:
            Dict with zone distribution percentages
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        workouts = self._get_workouts_in_range(
            athlete_id, start_date, end_date
        )

        # Aggregate zone minutes (use HR zones as primary, fallback to power)
        zones = {
            "z1": 0.0,
            "z2": 0.0,
            "z3": 0.0,
            "z4": 0.0,
            "z5": 0.0,
        }

        for workout in workouts:
            for i, zone in enumerate(["z1", "z2", "z3", "z4", "z5"], 1):
                # Try HR zone first, then power zone
                hr_sec = workout.get(f"hr_z{i}_sec", 0) or 0
                pwr_sec = workout.get(f"pwr_z{i}_sec", 0) or 0
                # Use whichever has data, prefer HR
                zone_sec = hr_sec if hr_sec > 0 else pwr_sec
                zones[zone] += zone_sec / 60  # Convert to minutes

        total_minutes = sum(zones.values())

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "total_minutes": total_minutes,
            "zones": zones,
            "percentages": {
                zone: round((minutes / total_minutes * 100), 1) if total_minutes > 0 else 0
                for zone, minutes in zones.items()
            },
        }

    def get_efficiency_trends(
        self, athlete_id: str, days: int = 90
    ) -> Dict:
        """
        Get aerobic efficiency and decoupling trends.

        GET /api/analysis/efficiency?days=90

        Args:
            athlete_id: Athlete identifier
            days: Number of days to analyze

        Returns:
            Dict with efficiency metrics over time
        """
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        workouts = self._get_workouts_in_range(
            athlete_id, start_date, end_date
        )

        # Filter for workouts with efficiency data
        efficiency_data = []
        for workout in workouts:
            if workout.get("decoupling_pct") is not None:
                efficiency_data.append({
                    "date": workout.get("start_time_utc"),
                    "sport": workout.get("sport"),
                    "decoupling_pct": workout.get("decoupling_pct"),
                    "ef_overall": workout.get("ef_overall"),
                    "hr_drift_bpm": workout.get("hr_drift_bpm"),
                })

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "samples": efficiency_data,
            "summary": {
                "total_samples": len(efficiency_data),
                "avg_decoupling": (
                    round(
                        sum(d["decoupling_pct"] for d in efficiency_data) / len(efficiency_data),
                        2
                    )
                    if efficiency_data
                    else None
                ),
            },
        }

    # -------------------------------------------------------------------------
    # Private Helper Methods
    # -------------------------------------------------------------------------

    def _get_workouts_in_range(
        self,
        athlete_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict]:
        """
        Retrieve workouts within a date range.

        Args:
            athlete_id: Athlete identifier
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)
        Returns:
            List of workout dicts
        """
        try:
            table_client = self.storage.infrastructure.get_table_client("Workouts")  # pylint: disable=protected-access

            # Build query for athlete and date range
            # PartitionKey format: athlete_id|YYYY-MM
            # We need to query multiple partitions if range spans multiple months
            months = self._get_month_partitions(athlete_id, start_date, end_date)

            workouts = []
            for partition_key in months:
                query = f"PartitionKey eq '{partition_key}'"
                entities = table_client.query_entities(query)

                for entity in entities:
                    workout_start = entity.get("start_time_utc")
                    if workout_start:
                        # Parse workout date and filter
                        workout_date = datetime.fromisoformat(
                            workout_start.replace("Z", UTC_OFFSET)
                        ).astimezone(timezone.utc)

                        if start_date <= workout_date <= end_date:
                            workouts.append(self._entity_to_workout_dict(entity))

            # Sort by date descending (newest first)
            workouts.sort(
                key=lambda w: w.get("start_time_utc", ""), reverse=True
            )

            return workouts

        except HttpResponseError as e:
            logger.error(
                "Error querying workouts",
                extra={
                    "athlete_id": athlete_id,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return []

    def _get_month_partitions(
        self, athlete_id: str, start_date: datetime, end_date: datetime
    ) -> List[str]:
        """
        Generate partition keys for all months in date range.

        Args:
            athlete_id: Athlete identifier
            start_date: Start date
            end_date: End date

        Returns:
            List of partition key strings (e.g., ['rob|2026-01', 'rob|2026-02'])
        """
        partitions = []
        current = start_date.replace(day=1)

        while current <= end_date:
            partition_key = f"{athlete_id}|{current.strftime('%Y-%m')}"
            partitions.append(partition_key)

            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

        return partitions

    def _entity_to_workout_dict(self, entity: Dict) -> Dict:
        """
        Convert Azure Table entity to workout dict.

        Args:
            entity: Raw table entity

        Returns:
            Cleaned workout dict
        """
        workout_entity = WorkoutEntity.from_table_entity(entity)
        
        # Load metadata.json blob (authoritative source for session/enrichment zones)
        # Fallback to ingestion_id if workout_id not available
        lookup_id = entity.get("ingestion_id") or workout_entity.workout_id
        try:
            metadata_blob = self.storage.workouts.load_metadata_json(lookup_id)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug(
                "Could not load metadata blob",
                extra={
                    "lookup_id": lookup_id,
                    "workout_id": workout_entity.workout_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            metadata_blob = {}
        
        # Extract semantic zones from metadata blob (these contain session/enrichment data)
        session = metadata_blob.get("session", {})
        enrichment = metadata_blob.get("enrichment", {})
        activity_metadata = metadata_blob.get("activity_metadata", {})
        
        # Combine zones into a metrics dict for inferential methods
        # (This maintains backward compatibility with methods that read from metrics dict)
        metrics = {**session, **enrichment, **activity_metadata}
        metrics = self._apply_canonical_metrics(workout_entity, metrics)

        # Prefer entity core fields over metadata zones (schema 2.0.0+ stores these as queryable properties)
        sport = workout_entity.sport or self._infer_sport(metrics)
        sub_sport = workout_entity.sub_sport or enrichment.get("sub_sport") or sport
        is_indoor = enrichment.get("is_indoor") or self._infer_is_indoor(metrics)
        workout_name = enrichment.get("workout_name") or self._infer_workout_name(metrics, sport)
        calories = session.get("calories_kcal") or self._infer_calories(metrics, sport)

        # Core summary fields (prefer entity properties, fallback to metadata zones)
        local_tz_offset = activity_metadata.get("local_tz_offset")
        workout = {
            "workout_id": workout_entity.workout_id,
            "athlete_id": workout_entity.athlete_id,
            "sport": sport,
            "sub_sport": sub_sport,
            "workout_name": workout_name,
            "is_indoor": is_indoor,
            "start_time_utc": workout_entity.start_time_utc,
            "local_tz_offset": local_tz_offset,
            "timezone": local_tz_offset,
            "duration_sec": workout_entity.duration_sec or session.get("duration_sec"),
            "moving_time_sec": session.get("moving_time_sec"),
            "distance_m": workout_entity.distance_m or session.get("distance_m"),
            "elevation_gain_m": session.get("elevation_gain_m"),
            "elevation_loss_m": session.get("elevation_loss_m"),
            "calories_kcal": calories,
        }

        # Heart rate summary
        if metrics.get("hr_avg_bpm"):
            workout.update(self._select_fields(metrics, {
                "hr_avg_bpm",
                "hr_max_bpm",
                "hr_z1_sec",
                "hr_z2_sec",
                "hr_z3_sec",
                "hr_z4_sec",
                "hr_z5_sec",
                "hr_zone_basis",
                "hr_zone_reference_bpm",
            }))

        # Power summary
        if metrics.get("pwr_avg_watts"):
            workout.update(self._select_fields(metrics, {
                "pwr_avg_watts",
                "pwr_max_watts",
                "pwr_normalized_watts",
                "pwr_variability_index",
                "pwr_z1_sec",
                "pwr_z2_sec",
                "pwr_z3_sec",
                "pwr_z4_sec",
                "pwr_z5_sec",
                "pwr_z6_sec",
                "pwr_z7_sec",
                "low_aerobic_sec",
                "intensity_sec",
                "ftp_watts",
                "intensity_factor",
                "tss",
                "decoupling_pct",
                "hr_drift_bpm",
                "ef_first_half",
                "ef_second_half",
                "ef_overall",
            }))

        return workout

    def _apply_canonical_metrics(
        self,
        workout_entity: WorkoutEntity,
        metrics: Dict,
    ) -> Dict:
        """Derive metrics from canonical parquet when table metrics are missing."""
        if metrics.get("hr_avg_bpm") or metrics.get("pwr_avg_watts"):
            return metrics

        blob_name = workout_entity.canonical_records_blob or metrics.get(
            "canonical_records_blob"
        )
        if not blob_name:
            return metrics

        try:
            df = self.storage.workouts.load_canonical_records(blob_name)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to load canonical records",
                extra={
                    "blob_name": blob_name,
                    "workout_id": workout_entity.workout_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return metrics

        if df.empty:
            return metrics

        enriched = dict(metrics)
        enriched.update(self._compute_metrics_from_canonical(df, enriched))
        return enriched

    def _compute_metrics_from_canonical(
        self,
        df: pd.DataFrame,
        metadata: Dict,
    ) -> Dict:
        """Compute derived metrics using CanonicalAnalyticsEngine."""
        try:
            canonical = CanonicalAnalyticsEngine.from_dataframe(df, metadata)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Canonical analytics computation failed",
                extra={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "record_count": len(df),
                },
            )
            return {}
        return canonical.to_metrics_dict()

    def _load_stored_laps(self, workout_entity: WorkoutEntity) -> Optional[List[Dict]]:
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

            return {
                "workout_id": workout_id,
                "athlete_id": athlete_id,
                "lap_index": lap_index,
                "lap": lap_payload,
            }

        except HttpResponseError as e:
            logger.error(
                "Error retrieving lap",
                extra={
                    "workout_id": workout_id,
                    "athlete_id": athlete_id,
                    "lap_index": lap_index,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

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
    ) -> tuple[Optional[List[Dict]], Optional[str]]:
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
    ) -> tuple[Optional[List[Dict]], Optional[str]]:
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
    def _extract_units_and_value(field_payload: object) -> tuple[Optional[str], Optional[object]]:
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


    @staticmethod
    def _select_fields(source: Dict, fields: set[str]) -> Dict:
        return {field: source.get(field) for field in fields}


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
                    str(start_time).replace("Z", UTC_OFFSET)
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

    def _get_weekly_rollups(
        self, athlete_id: str, days: int
    ) -> List[Dict]:
        """
        Get weekly rollup data for specified number of days.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back

        Returns:
            List of weekly rollup dicts
        """
        # Calculate week range
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        try:
            table_client = self.storage.infrastructure.get_table_client("WeeklyRollups")  # pylint: disable=protected-access
            rollups = []

            # Query each year partition
            # Note: Currently queries all weeks in range years (can be optimized later)
            current = start_date
            years = set()
            while current <= end_date:
                years.add(current.year)
                current = current + timedelta(days=7)

            for year in sorted(years):
                partition_key = f"{athlete_id}#{year}"
                query = f"PartitionKey eq '{partition_key}'"
                entities = table_client.query_entities(query)

                for entity in entities:
                    rollups.append(dict(entity))

            # Sort by week descending
            rollups.sort(key=lambda r: r.get("RowKey", ""), reverse=True)

            return rollups

        except HttpResponseError as e:
            logger.error(
                "Error retrieving weekly rollups",
                extra={
                    "athlete_id": athlete_id,
                    "weeks": weeks,
                    "error_type": "HttpResponseError",
                    "error": str(e),
                },
                exc_info=True,
            )
            return []

    def _find_last_hard_day(self, workouts: List[Dict]) -> Optional[str]:
        """
        Find date of last high-intensity workout.

        High intensity = intensity_min > 5 or Z4+ seconds > 300
        """
        for workout in workouts:
            intensity = workout.get("intensity_min", 0) or 0
            if intensity > 5:
                return workout.get("start_time_utc")

            # Fallback: check HR zones
            hr_z4_sec = workout.get("hr_z4_sec", 0) or 0
            hr_z5_sec = workout.get("hr_z5_sec", 0) or 0
            if (hr_z4_sec + hr_z5_sec) / 60 > 5:
                return workout.get("start_time_utc")

        return None

    def _find_last_long_day(self, workouts: List[Dict]) -> Optional[str]:
        """
        Find date of last long aerobic workout.

        Long = Z2 minutes > 60
        """
        for workout in workouts:
            # Check HR Z2 or power Z2
            hr_z2 = workout.get("hr_z2_min", 0) or 0
            pwr_z2 = workout.get("pwr_z2_min", 0) or 0
            z2 = max(hr_z2, pwr_z2)

            if z2 > 60:
                return workout.get("start_time_utc")

        return None

    def _sum_zone_time(
        self, workouts: List[Dict], zone_field: str
    ) -> int:
        """Sum minutes in specific zone across workouts."""
        total = 0
        for workout in workouts:
            minutes = workout.get(zone_field, 0) or 0
            total += minutes
        return total

    def _sum_high_intensity(self, workouts: List[Dict]) -> float:
        """Sum high intensity minutes (Z4+) across workouts."""
        total = 0.0
        for workout in workouts:
            # Use intensity_min if available (power zones Z4-Z7)
            intensity = workout.get("intensity_min", 0) or 0
            if intensity > 0:
                total += intensity
            else:
                # Fallback: calculate from HR zones (Z4 + Z5)
                hr_z4_sec = workout.get("hr_z4_sec", 0) or 0
                hr_z5_sec = workout.get("hr_z5_sec", 0) or 0
                total += (hr_z4_sec + hr_z5_sec) / 60
        return total

    def _detect_notable_flags(self, workouts: List[Dict]) -> List[str]:
        """
        Detect notable issues in recent workouts.

        Returns list of human-readable warning strings.
        """
        flags = []

        # Check for workouts missing HR data
        no_hr_count = sum(1 for w in workouts if not w.get("hr_avg_bpm"))
        if no_hr_count > 0:
            flags.append(f"{no_hr_count} workout(s) missing heart rate data")

        # Check for excessive decoupling
        high_decoupling = [
            w for w in workouts
            if w.get("decoupling_pct", 0) and w["decoupling_pct"] > 5.0
        ]
        if high_decoupling:
            flags.append(
                f"{len(high_decoupling)} workout(s) with high decoupling (>5%)"
            )

        # Check for very short workouts (possible data issues)
        very_short = [
            w for w in workouts
            if w.get("duration_sec", 0) and w["duration_sec"] < 600  # < 10 min
        ]
        if very_short:
            flags.append(f"{len(very_short)} very short workout(s) (<10 min)")

        return flags

    # -------------------------------------------------------------------------
    # Physiometrics Management
    # -------------------------------------------------------------------------

    def get_current_physiometrics(self, athlete_id: str) -> Dict:
        """
        Get current physiometric values for an athlete.

        Args:
            athlete_id: Athlete identifier

        Returns:
            Dict containing current weight, FTP, LTHR, cycling VO2Max, body composition, etc.
        """
        config = self.storage.physiometrics.get_physiometrics(athlete_id)

        if not config:
            return {
                "athlete_id": athlete_id,
                "error": "No physiometrics data found"
            }

        # Extract values for easy consumption
        result = {
            "athlete_id": athlete_id,
            "heart_rate": {
                "basis": config.get("heart_rate", {}).get("basis"),
                "lthr_bpm": config.get("heart_rate", {}).get("lthr_bpm"),
                "hr_max_bpm": config.get("heart_rate", {}).get("hr_max_bpm"),
                "resting_hr_bpm": config.get("heart_rate", {}).get("resting_hr_bpm"),
            },
            "power": {
                "ftp_watts": config.get("power", {}).get("ftp_watts"),
            },
        }

        # Add body composition if present
        if config.get("weight_kg") is not None:
            result["weight_kg"] = config.get("weight_kg")
        if config.get("fat_mass_kg") is not None:
            result["fat_mass_kg"] = config.get("fat_mass_kg")
        if config.get("muscle_mass_kg") is not None:
            result["muscle_mass_kg"] = config.get("muscle_mass_kg")
        if config.get("bone_mass_kg") is not None:
            result["bone_mass_kg"] = config.get("bone_mass_kg")
        if config.get("body_fat_pct") is not None:
            result["body_fat_pct"] = config.get("body_fat_pct")
        if config.get("visceral_fat_index") is not None:
            result["visceral_fat_index"] = config.get("visceral_fat_index")
        if config.get("metabolic_age_years") is not None:
            result["metabolic_age_years"] = config.get("metabolic_age_years")
        if config.get("cycling_vo2max_ml_kg_min") is not None:
            result["cycling_vo2max_ml_kg_min"] = config.get("cycling_vo2max_ml_kg_min")

        # Add metadata
        if config.get("effective_date"):
            result["effective_date"] = config.get("effective_date")
        if config.get("data_source"):
            result["data_source"] = config.get("data_source")

        return result

    def get_physiometrics_trends(self, athlete_id: str, days: int = 90,
                                metrics: Optional[List[str]] = None) -> Dict:
        """
        Get time-series physiometric trends.

        Args:
            athlete_id: Athlete identifier
            days: Number of days to look back
            metrics: List of specific metrics to return (None = all)

        Returns:
            Dict with query window and time-series data points
        """
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        history = self.storage.physiometrics.get_physiometrics_history(
            athlete_id=athlete_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            metrics=metrics
        )

        return {
            "athlete_id": athlete_id,
            "query_window": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": days,
            },
            "count": len(history),
            "data_points": history,
        }

    def update_physiometric_value(self, athlete_id: str,
                                  metric: str,
                                  value: float,
                                  effective_date: Optional[str] = None,
                                  source: str = "chatgpt") -> Dict:
        """
        Update a single physiometric value.

        Args:
            athlete_id: Athlete identifier
            metric: Metric name (e.g., "weight_kg", "cycling_vo2max_ml_kg_min")
            value: New value
            effective_date: ISO date when effective (defaults to today)
            source: Source of update (chatgpt, manual, withings)

        Returns:
            Dict with update confirmation
        """
        try:
            timestamp = self.storage.physiometrics.update_single_metric(
                athlete_id=athlete_id,
                metric_name=metric,
                value=value,
                effective_date=effective_date,
                data_source=source
            )

            logger.info(
                "Updated physiometric",
                extra={
                    "athlete_id": athlete_id,
                    "metric": metric,
                    "value": value,
                    "effective_date": effective_date,
                    "source": source,
                },
            )

            return {
                "status": "success",
                "athlete_id": athlete_id,
                "metric": metric,
                "value": value,
                "effective_date": effective_date,
                "source": source,
                "updated_at_utc": timestamp,
            }

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Error updating physiometric",
                extra={
                    "athlete_id": athlete_id,
                    "metric": metric,
                    "value": value,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
                exc_info=True,
            )
            return {
                "status": "error",
                "error": str(e)
            }

    def recalculate_workout_zones(self, workout_id: str,
                                 physiometrics_override: Optional[Dict] = None) -> Dict:
        """
        Recalculate workout zones with different physiometric values (read-only).

        This provides a "what-if" view of how zones would look with different FTP/LTHR,
        without modifying the original workout data.

        Args:
            workout_id: Workout identifier
            physiometrics_override: Dict with ftp_watts and/or lthr_bpm to use

        Returns:
            Dict with recalculated zone data
        """
        # Placeholder until retroactive zone recalculation is implemented.
        # Expected steps:
        # 1. Fetch original workout and time series records
        # 2. Recompute zones using override values
        # 3. Return new zone distribution without storing

        return {
            "status": "not_implemented",
            "message": "Retroactive zone recalculation coming soon",
            "workout_id": workout_id,
            "override": physiometrics_override,
        }
