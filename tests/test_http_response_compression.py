"""Regression tests for HTTP response gzip handling."""

import gzip
import json
from unittest.mock import MagicMock

import azure.functions as func

from TrainingAnalyticsPlatform.platform.function_utils import (
    _build_response,
    _decode_json_response_body,
)
from TrainingAnalyticsPlatform.platform.http_utils import (
    gzip_encode_response_body,
    json_response,
)


def _request_with_accept_encoding(value: str | None = None) -> MagicMock:
    req = MagicMock(spec=func.HttpRequest)
    req.headers = {}
    if value is not None:
        req.headers["Accept-Encoding"] = value
    return req


class TestGzipEncodeResponseBody:
    def test_returns_original_payload_without_gzip_request(self) -> None:
        payload = b'{"status":"ok"}'

        encoded_payload, headers = gzip_encode_response_body(payload, req=_request_with_accept_encoding())

        assert encoded_payload == payload
        assert headers == {}

    def test_returns_gzipped_payload_when_requested(self) -> None:
        payload = b'{"status":"ok"}'

        encoded_payload, headers = gzip_encode_response_body(
            payload,
            req=_request_with_accept_encoding("gzip, deflate"),
        )

        assert encoded_payload != payload
        assert gzip.decompress(encoded_payload) == payload
        assert headers == {
            "Content-Encoding": "gzip",
            "Vary": "Accept-Encoding",
        }


class TestJsonResponseCompression:
    def test_json_response_sets_gzip_headers(self) -> None:
        response = json_response(
            {"status": "ok"},
            req=_request_with_accept_encoding("gzip"),
        )

        assert response.status_code == 200
        assert response.headers["Content-Encoding"] == "gzip"
        assert response.headers["Vary"] == "Accept-Encoding"
        assert json.loads(gzip.decompress(response.get_body()).decode("utf-8")) == {"status": "ok"}

    def test_decode_json_response_body_handles_gzipped_payload(self) -> None:
        response = json_response(
            {"status": "ok", "count": 2},
            req=_request_with_accept_encoding("gzip"),
        )

        assert _decode_json_response_body(response) == {"status": "ok", "count": 2}


class TestBuildResponseCompression:
    def test_build_response_gzips_html_when_requested(self) -> None:
        response = _build_response(
            "html",
            "<html><body>Hello</body></html>",
            200,
            req=_request_with_accept_encoding("gzip"),
        )

        assert response.headers["Content-Encoding"] == "gzip"
        assert response.headers["Vary"] == "Accept-Encoding"
        assert gzip.decompress(response.get_body()).decode("utf-8") == "<html><body>Hello</body></html>"

    def test_build_response_gzips_text_when_requested(self) -> None:
        response = _build_response(
            "text",
            "plain text",
            200,
            req=_request_with_accept_encoding("gzip"),
        )

        assert response.headers["Content-Encoding"] == "gzip"
        assert response.headers["Vary"] == "Accept-Encoding"
        assert gzip.decompress(response.get_body()).decode("utf-8") == "plain text"

    def test_build_response_leaves_text_uncompressed_without_request_header(self) -> None:
        response = _build_response(
            "text",
            "plain text",
            200,
            req=_request_with_accept_encoding(),
        )

        assert response.headers.get("Content-Encoding") is None
        assert response.get_body().decode("utf-8") == "plain text"

    def test_build_response_preserves_bytes_payload_for_text(self) -> None:
        response = _build_response(
            "text",
            b"plain-bytes",
            200,
            req=_request_with_accept_encoding(),
        )

        assert response.headers.get("Content-Encoding") is None
        assert response.get_body() == b"plain-bytes"
