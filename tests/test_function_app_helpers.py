"""Focused coverage for function_app helper utilities."""

from unittest.mock import MagicMock

import azure.functions as func

import function_app


class TestFunctionAppStateHelpers:
    def test_build_onedrive_state_contains_athlete_prefix(self) -> None:
        state = function_app._build_onedrive_state("rob")

        assert state.startswith("rob|")
        assert len(state.split("|", 1)) == 2

    def test_get_athlete_id_from_state_handles_missing_and_empty(self) -> None:
        assert function_app._get_athlete_id_from_state(None) is None
        assert function_app._get_athlete_id_from_state("") is None
        assert function_app._get_athlete_id_from_state("rob|1715000000") == "rob"
        assert function_app._get_athlete_id_from_state("|1715000000") is None


class TestFunctionAppRequestHelpers:
    def test_extract_request_id_prefers_header_priority(self) -> None:
        req = MagicMock(spec=func.HttpRequest)
        req.headers = {
            "x-ms-client-request-id": " client-id ",
            "x-ms-request-id": "request-id",
        }

        assert function_app._extract_request_id(req) == "client-id"

    def test_extract_request_id_returns_none_for_blank_value(self) -> None:
        req = MagicMock(spec=func.HttpRequest)
        req.headers = {"x-request-id": "   "}

        assert function_app._extract_request_id(req) is None

    def test_get_request_json_body_returns_empty_for_non_post(self) -> None:
        req = MagicMock(spec=func.HttpRequest)
        req.method = "GET"

        assert function_app._get_request_json_body(req) == {}

    def test_get_request_json_body_returns_empty_for_invalid_or_non_dict_json(self) -> None:
        req_invalid = MagicMock(spec=func.HttpRequest)
        req_invalid.method = "POST"
        req_invalid.get_json.side_effect = ValueError("bad json")
        assert function_app._get_request_json_body(req_invalid) == {}

        req_list = MagicMock(spec=func.HttpRequest)
        req_list.method = "POST"
        req_list.get_json.return_value = ["not", "a", "dict"]
        assert function_app._get_request_json_body(req_list) == {}

    def test_get_request_json_body_returns_dict_payload(self) -> None:
        req = MagicMock(spec=func.HttpRequest)
        req.method = "POST"
        req.get_json.return_value = {"enabled": True}

        assert function_app._get_request_json_body(req) == {"enabled": True}
