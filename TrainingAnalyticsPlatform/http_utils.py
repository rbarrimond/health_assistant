"""HTTP helper utilities for Azure Functions endpoints."""

from __future__ import annotations

import json
import gzip
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import azure.functions as func

from config.constants import ENV_PUBLIC_BASE_URL, JSON_CONTENT_TYPE


def json_response(
    data: Dict[str, Any],
    status_code: int = 200,
    *,
    req: Optional[func.HttpRequest] = None,
) -> func.HttpResponse:
    """Create JSON HTTP response, optionally gzip-compressed."""
    payload = json.dumps(data, default=str).encode("utf-8")
    headers: Dict[str, str] = {}

    accept_encoding = (
        req.headers.get("Accept-Encoding", "")
        if req is not None
        else ""
    )
    if "gzip" in accept_encoding.lower():
        payload = gzip.compress(payload)
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"

    return func.HttpResponse(
        body=payload,
        status_code=status_code,
        mimetype=JSON_CONTENT_TYPE,
        headers=headers,
    )


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
