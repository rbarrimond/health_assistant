"""Unit tests for Withings client helper methods."""

from TrainingAnalyticsPlatform.integrations.withings_client import WithingsClient


class TestWithingsClientHelpers:
    def test_build_measure_params_prefers_lastupdate(self) -> None:
        params = WithingsClient._build_measure_params(
            start_date=100,
            end_date=200,
            lastupdate=300,
            offset=10,
        )

        assert params["action"] == "getmeas"
        assert params["lastupdate"] == 300
        assert "startdate" not in params
        assert "enddate" not in params
        assert params["offset"] == 10

    def test_build_measure_params_uses_date_range_when_no_lastupdate(self) -> None:
        params = WithingsClient._build_measure_params(
            start_date=100,
            end_date=200,
            lastupdate=None,
            offset=None,
        )

        assert params["startdate"] == 100
        assert params["enddate"] == 200
        assert "lastupdate" not in params
        assert "offset" not in params

    def test_next_offset_returns_none_when_no_more_pages(self) -> None:
        assert WithingsClient._next_offset({"more": 0, "offset": 12}) is None

    def test_next_offset_returns_none_when_offset_missing(self) -> None:
        assert WithingsClient._next_offset({"more": 1}) is None

    def test_next_offset_converts_to_int_when_present(self) -> None:
        assert WithingsClient._next_offset({"more": 1, "offset": "15"}) == 15

    def test_parse_measurements_from_groups_filters_out_none(self) -> None:
        groups = [{"id": 1}, {"id": 2}, {"id": 3}]

        def parser(group: dict):
            return None if group["id"] == 2 else {"group_id": group["id"]}

        parsed = WithingsClient._parse_measurements_from_groups(groups, parser)

        assert parsed == [{"group_id": 1}, {"group_id": 3}]
