"""Deterministic FIT structure analyzer."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class FitStructureAnalyzer:
    """Analyze decoded FIT message structure and emit normalized JSON."""

    def __init__(self, messages: Optional[List[Dict[str, Any]]] = None):
        self.messages = messages or []

    def analyze(self) -> Dict[str, Any]:
        message_counts = Counter(msg.get("name", "unknown") for msg in self.messages)
        has_records = message_counts.get("record", 0) > 0
        has_laps = message_counts.get("lap", 0) > 0
        virtual_indicators = self._virtual_indicators()
        indoor_indicators = self._indoor_indicators()
        outdoor_indicators = self._outdoor_indicators()
        developer_summary = self._developer_fields_summary()
        anomalies = self._anomalies(virtual_indicators, indoor_indicators, outdoor_indicators)

        return {
            "analysis_version": "v1.0.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "file_profile": {
                "total_messages": len(self.messages),
                "has_records": has_records,
                "has_laps": has_laps,
            },
            "message_inventory": dict(message_counts),
            "classification_evidence": {
                "virtual_indicators": virtual_indicators,
                "indoor_indicators": indoor_indicators,
                "outdoor_indicators": outdoor_indicators,
                "classification_confidence": self._classification_confidence(
                    virtual_indicators, indoor_indicators, outdoor_indicators
                ),
            },
            "developer_fields_summary": developer_summary,
            "anomalies": anomalies,
            "summary_flags": {
                "is_virtual_hint": bool(virtual_indicators),
                "has_developer_fields": bool(developer_summary.get("fields")),
                "has_gps_records": self._has_gps_records(),
                "has_indoor_message_flag": self._has_indoor_flag(),
            },
        }

    def _messages(self, name: str) -> List[Dict[str, Any]]:
        return [msg for msg in self.messages if msg.get("name") == name]

    @staticmethod
    def _value(msg: Dict[str, Any], field_name: str) -> Any:
        fields = msg.get("fields", {})
        field = fields.get(field_name)
        return getattr(field, "value", None) if field is not None else None

    def _virtual_indicators(self) -> List[str]:
        indicators: List[str] = []
        for session in self._messages("session"):
            sub_sport = self._value(session, "sub_sport")
            name = self._value(session, "session_name")
            if sub_sport and "virtual" in str(getattr(sub_sport, "name", sub_sport)).lower():
                indicators.append("session.sub_sport=virtual")
            if name and any(
                token in str(name).lower() for token in ("zwift", "virtual", "trainerroad", "peloton")
            ):
                indicators.append("session.session_name=virtual_keyword")
        for msg in self.messages:
            for field_name in msg.get("fields", {}).keys():
                if str(field_name).startswith("dev_") and "virtual" in str(field_name).lower():
                    indicators.append(f"{msg.get('name')}.{field_name}=virtual_keyword")
        return sorted(set(indicators))

    def _indoor_indicators(self) -> List[str]:
        indicators: List[str] = []
        for session in self._messages("session"):
            indoor = self._value(session, "indoor")
            if indoor in (True, 1, "1", "true", "True"):
                indicators.append("session.indoor=true")
            sub_sport = self._value(session, "sub_sport")
            if sub_sport and "indoor" in str(getattr(sub_sport, "name", sub_sport)).lower():
                indicators.append("session.sub_sport=indoor")
        return sorted(set(indicators))

    def _outdoor_indicators(self) -> List[str]:
        indicators: List[str] = []
        if self._has_gps_records():
            indicators.append("record.position_lat/long=present")
        for session in self._messages("session"):
            indoor = self._value(session, "indoor")
            if indoor in (False, 0, "0", "false", "False"):
                indicators.append("session.indoor=false")
        return sorted(set(indicators))

    def _has_gps_records(self) -> bool:
        for rec in self._messages("record"):
            lat = self._value(rec, "position_lat")
            lon = self._value(rec, "position_long")
            if lat is not None and lon is not None:
                return True
        return False

    def _has_indoor_flag(self) -> bool:
        for session in self._messages("session"):
            if self._value(session, "indoor") is not None:
                return True
        return False

    @staticmethod
    def _classification_confidence(
        virtual_indicators: List[str],
        indoor_indicators: List[str],
        outdoor_indicators: List[str],
    ) -> str:
        if virtual_indicators:
            return "high"
        if indoor_indicators and not outdoor_indicators:
            return "medium"
        if outdoor_indicators and not indoor_indicators:
            return "medium"
        return "low"

    def _developer_fields_summary(self) -> Dict[str, Any]:
        fields_by_key: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "units": set(), "sample_values": []}
        )
        for msg in self.messages:
            msg_name = msg.get("name", "unknown")
            frame = msg.get("frame")
            dev_fields = getattr(frame, "developer_fields", []) if frame is not None else []
            for field in dev_fields:
                key = f"{msg_name}.dev_{field.name}"
                rec = fields_by_key[key]
                rec["count"] += 1
                units = getattr(field, "units", None)
                if units:
                    rec["units"].add(units)
                value = getattr(field, "value", None)
                if value is not None and len(rec["sample_values"]) < 3:
                    rec["sample_values"].append(value)

        fields = []
        for key in sorted(fields_by_key):
            msg_name, field_name = key.split(".", 1)
            rec = fields_by_key[key]
            fields.append(
                {
                    "message_type": msg_name,
                    "field": field_name,
                    "count": rec["count"],
                    "units": sorted(rec["units"]),
                    "sample_values": rec["sample_values"],
                }
            )
        return {
            "field_count": len(fields),
            "fields": fields,
        }

    @staticmethod
    def _anomalies(
        virtual_indicators: List[str],
        indoor_indicators: List[str],
        outdoor_indicators: List[str],
    ) -> List[Dict[str, str]]:
        anomalies: List[Dict[str, str]] = []
        if virtual_indicators and any("position_lat/long" in item for item in outdoor_indicators):
            anomalies.append(
                {
                    "code": "VIRTUAL_WITH_GPS",
                    "severity": "warning",
                    "message": "Virtual indicators present with GPS records; classify carefully.",
                }
            )
        if indoor_indicators and any("session.indoor=false" in item for item in outdoor_indicators):
            anomalies.append(
                {
                    "code": "INDOOR_FLAG_CONFLICT",
                    "severity": "warning",
                    "message": "Conflicting indoor/outdoor indicators detected.",
                }
            )
        return anomalies
