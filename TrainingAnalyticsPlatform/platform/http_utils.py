"""HTTP helper utilities for Azure Functions endpoints."""

from __future__ import annotations

import json
import gzip
import os
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import azure.functions as func

from TrainingAnalyticsPlatform.platform.http_constants import (
    ENV_PUBLIC_BASE_URL,
    JSON_CONTENT_TYPE,
)


def extract_correlation_context(req: Optional[func.HttpRequest]) -> Dict[str, str]:
    """Extract request correlation values for logs and responses."""
    if req is None:
        operation_id = str(uuid.uuid4())
        return {
            "operation_id": operation_id,
            "correlation_id": operation_id,
            "traceparent": "",
        }

    traceparent = req.headers.get("traceparent", "").strip()
    fallback_correlation_id = req.headers.get("x-correlation-id", "").strip()
    operation_id = ""

    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 2 and parts[1]:
            operation_id = parts[1]

    if not operation_id:
        operation_id = fallback_correlation_id or str(uuid.uuid4())

    correlation_id = fallback_correlation_id or operation_id
    return {
        "operation_id": operation_id,
        "correlation_id": correlation_id,
        "traceparent": traceparent,
    }


def apply_correlation_headers(
    response: func.HttpResponse,
    correlation_id: str,
    traceparent: str,
) -> func.HttpResponse:
    """Attach correlation headers to outgoing responses."""
    response.headers["x-correlation-id"] = correlation_id
    if traceparent:
        response.headers["traceparent"] = traceparent
    return response


def json_response(
    data: Dict[str, Any],
    status_code: int = 200,
    *,
    req: Optional[func.HttpRequest] = None,
) -> func.HttpResponse:
    """Create JSON HTTP response, optionally gzip-compressed."""
    payload, headers = gzip_encode_response_body(
        json.dumps(data, default=str).encode("utf-8"),
        req=req,
    )

    return func.HttpResponse(
        body=payload,
        status_code=status_code,
        mimetype=JSON_CONTENT_TYPE,
        headers=headers,
    )


def gzip_encode_response_body(
    payload: bytes,
    *,
    req: Optional[func.HttpRequest] = None,
) -> Tuple[bytes, Dict[str, str]]:
    """Optionally gzip-encode an HTTP response body based on request headers."""
    headers: Dict[str, str] = {}
    accept_encoding = ""
    if req is not None:
        accept_encoding = req.headers.get("Accept-Encoding", "")
        if not accept_encoding:
            accept_encoding = req.headers.get("accept-encoding", "")
    if "gzip" not in accept_encoding.lower():
        return payload, headers

    headers["Content-Encoding"] = "gzip"
    headers["Vary"] = "Accept-Encoding"
    return gzip.compress(payload), headers


def public_base_url(req: func.HttpRequest) -> str:
    """Return the externally reachable base URL, overridable via env."""
    override = os.getenv(ENV_PUBLIC_BASE_URL)
    if override:
        return override.rstrip("/")

    parsed = urlparse(req.url)
    return f"{parsed.scheme}://{parsed.netloc}"


def response_missing_file(name: str) -> func.HttpResponse:
    """Return 500 error for missing file."""
    return func.HttpResponse(
        json.dumps({"error": f"{name} not found"}),
        status_code=500,
        mimetype=JSON_CONTENT_TYPE,
    )
