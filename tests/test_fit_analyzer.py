"""Unit tests for deterministic FIT structure analyzer."""

from types import SimpleNamespace

from TrainingAnalyticsPlatform.ingestion.fit_analyzer import FitStructureAnalyzer


class _FakeMessage:
    def __init__(self, name: str, values: dict | None = None, developer_fields: list | None = None):
        self.name = name
        self._values = values or {}
        self.developer_fields = developer_fields or []

    def get_value(self, key: str, fallback=None):
        return self._values.get(key, fallback)


def _enum_name(value: str) -> SimpleNamespace:
    return SimpleNamespace(name=value)


def _dev_field(name: str, value=None, units: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, value=value, units=units)


class TestFitStructureAnalyzer:
    def test_analyze_includes_expected_sections_and_flags(self) -> None:
        messages = [
            _FakeMessage(
                "session",
                values={
                    "sub_sport": _enum_name("virtual_cycling"),
                    "session_name": "Zwift Workout",
                    "indoor": True,
                },
                developer_fields=[_dev_field("virtual_power", 250, "watts")],
            ),
            _FakeMessage("record", values={"position_lat": 1, "position_long": 2}),
            _FakeMessage("lap"),
        ]

        result = FitStructureAnalyzer(messages).analyze()

        assert result["file_profile"]["total_messages"] == 3
        assert result["file_profile"]["has_records"] is True
        assert result["file_profile"]["has_laps"] is True
        assert result["message_inventory"]["session"] == 1
        assert result["message_inventory"]["record"] == 1

        evidence = result["classification_evidence"]
        assert "session.sub_sport=virtual" in evidence["virtual_indicators"]
        assert "session.session_name=virtual_keyword" in evidence["virtual_indicators"]
        assert "record.position_lat/long=present" in evidence["outdoor_indicators"]
        assert evidence["classification_confidence"] == "high"

        flags = result["summary_flags"]
        assert flags["is_virtual_hint"] is True
        assert flags["has_gps_records"] is True
        assert flags["has_indoor_message_flag"] is True
        assert flags["has_developer_fields"] is True

        dev_summary = result["developer_fields_summary"]
        assert dev_summary["field_count"] == 1
        assert dev_summary["fields"][0]["field"] == "dev_virtual_power"
        assert dev_summary["fields"][0]["units"] == ["watts"]

    def test_analyze_detects_indoor_outdoor_conflict_anomaly(self) -> None:
        messages = [
            _FakeMessage("session", values={"indoor": True}),
            _FakeMessage("session", values={"indoor": False}),
        ]

        result = FitStructureAnalyzer(messages).analyze()

        anomaly_codes = {item["code"] for item in result["anomalies"]}
        assert "INDOOR_FLAG_CONFLICT" in anomaly_codes

    def test_classification_confidence_levels(self) -> None:
        assert FitStructureAnalyzer._classification_confidence(["virtual"], [], []) == "high"
        assert FitStructureAnalyzer._classification_confidence([], ["indoor"], []) == "medium"
        assert FitStructureAnalyzer._classification_confidence([], [], ["outdoor"]) == "medium"
        assert FitStructureAnalyzer._classification_confidence([], [], []) == "low"

    def test_messages_filter_returns_matching_message_type_only(self) -> None:
        messages = [
            _FakeMessage("session"),
            _FakeMessage("record"),
            _FakeMessage("record"),
        ]

        analyzer = FitStructureAnalyzer(messages)
        record_messages = analyzer._messages("record")

        assert len(record_messages) == 2
        assert all(message.name == "record" for message in record_messages)
