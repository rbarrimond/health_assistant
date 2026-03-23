"""Typed normalization contract for Garmin activity list payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Mapping, Tuple


AliasPaths = Tuple[Tuple[str, ...], ...]


@dataclass(frozen=True)
class GarminActivityContract:
    """Normalized view over a raw Garmin activity-list payload."""

    payload: Mapping[str, Any]

    _CORE_ALIASES: ClassVar[Dict[str, AliasPaths]] = {
        "activity_id": (("activityId",), ("activity_id",)),
        "activity_name": (("activityName",), ("activity_name",)),
        "activity_type_key": (
            ("activityType", "typeKey"),
            ("activityTypeDTO", "typeKey"),
            ("typeKey",),
        ),
        "start_time_utc": (("startTimeGMT",), ("startTimeGmt",)),
        "start_time_local": (("startTimeLocal",), ("startTimeGmtLocal",)),
        "duration_sec": (("duration",), ("durationInSeconds",), ("movingDuration",)),
        "distance_meters": (("distance",), ("distanceMeters",)),
    }

    _COMMON_OPTIONAL_ALIASES: ClassVar[Dict[str, AliasPaths]] = {
        "average_hr_bpm": (("averageHR",), ("avgHR",)),
        "max_hr_bpm": (("maxHR",), ("maximumHR",)),
        "calories": (("calories",),),
    }

    _TYPE_SPECIFIC_ALIASES: ClassVar[Dict[str, Dict[str, AliasPaths]]] = {
        "strength_training": {
            "total_reps": (("totalReps",),),
        },
        "walking": {
            "steps": (("steps",),),
            "average_run_cadence": (("averageRunCadence",),),
        },
        "cycling": {
            "average_power_watts": (("averagePower",), ("avgPower",)),
            "normalized_power_watts": (("normPower",), ("normalizedPower",)),
        },
        "indoor_cycling": {
            "average_power_watts": (("averagePower",), ("avgPower",)),
            "normalized_power_watts": (("normPower",), ("normalizedPower",)),
        },
        "virtual_ride": {
            "average_power_watts": (("averagePower",), ("avgPower",)),
            "normalized_power_watts": (("normPower",), ("normalizedPower",)),
        },
    }

    _SOURCE_KEY_BY_FIELD: ClassVar[Dict[str, str]] = {
        "activity_name": "source_activity_name",
        "activity_type_key": "source_activity_type",
        "start_time_utc": "source_start_time_utc",
        "start_time_local": "source_start_time_local",
        "duration_sec": "source_duration_sec",
        "distance_meters": "source_distance_meters",
        "average_hr_bpm": "source_average_hr_bpm",
        "max_hr_bpm": "source_max_hr_bpm",
        "calories": "source_calories",
        "total_reps": "source_total_reps",
        "steps": "source_steps",
        "average_run_cadence": "source_average_run_cadence",
        "average_power_watts": "source_average_power_watts",
        "normalized_power_watts": "source_normalized_power_watts",
    }

    @property
    def activity_id(self) -> str:
        value = self._extract("activity_id")
        return "" if value is None else str(value)

    @property
    def activity_name(self) -> str | None:
        value = self._extract("activity_name")
        return None if value is None else str(value)

    @property
    def activity_type_key(self) -> str | None:
        value = self._extract("activity_type_key")
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

    @property
    def start_time_utc(self) -> str | None:
        value = self._extract("start_time_utc")
        return None if value is None else str(value)

    @property
    def duration_sec(self) -> float | None:
        value = self._extract("duration_sec")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def to_source_metadata_fields(self) -> Dict[str, Any]:
        """Return normalized source-metadata fields for ingestion tracking."""
        source_fields: Dict[str, Any] = {}

        for field_name in self._CORE_ALIASES:
            if field_name == "activity_id":
                continue
            value = self._extract(field_name)
            if value is not None:
                source_fields[self._SOURCE_KEY_BY_FIELD[field_name]] = value

        for field_name in self._COMMON_OPTIONAL_ALIASES:
            value = self._extract(field_name)
            if value is not None:
                source_fields[self._SOURCE_KEY_BY_FIELD[field_name]] = value

        type_key = self.activity_type_key
        type_aliases = self._TYPE_SPECIFIC_ALIASES.get(type_key or "", {})
        for field_name in type_aliases:
            value = self._extract(field_name)
            if value is not None:
                source_fields[self._SOURCE_KEY_BY_FIELD[field_name]] = value

        return source_fields

    def _extract(self, field_name: str) -> Any:
        if field_name in self._CORE_ALIASES:
            paths = self._CORE_ALIASES[field_name]
        elif field_name in self._COMMON_OPTIONAL_ALIASES:
            paths = self._COMMON_OPTIONAL_ALIASES[field_name]
        else:
            type_key = self.activity_type_key
            if not type_key:
                return None
            paths = self._TYPE_SPECIFIC_ALIASES.get(type_key, {}).get(field_name, ())

        for path in paths:  # pragma: no branch
            value = self._deep_get(self.payload, path)
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def _deep_get(payload: Mapping[str, Any], path: Tuple[str, ...]) -> Any:
        current: Any = payload
        for key in path:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
            if current is None:
                return None
        return current