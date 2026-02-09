"""HTTP helper utilities for Azure Functions endpoints."""

from __future__ import annotations

import json
import os
from typing import Any, Dict
from urllib.parse import urlparse

import azure.functions as func

from config.constants import ENV_PUBLIC_BASE_URL, JSON_CONTENT_TYPE


def json_response(data: Dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    """Create JSON HTTP response."""
    return func.HttpResponse(
        json.dumps(data, default=str),
        status_code=status_code,
        mimetype=JSON_CONTENT_TYPE,
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
