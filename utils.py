"""Shared utilities for the Azure Functions HTTP adapter."""

from __future__ import annotations

import logging
from functools import wraps
from dataclasses import dataclass
from typing import Any, Callable, Dict, cast

import azure.functions as func

from config.constants import (
    HTML_CONTENT_TYPE,
    INTERNAL_SERVER_ERROR,
    TEXT_PLAIN_CONTENT_TYPE,
)
from TrainingAnalyticsPlatform.http_utils import json_response

logger = logging.getLogger(__name__)

_SUPPORTED_RESPONSE_KINDS = {"json", "html", "text"}


def _validate_response_kind(response_kind: str) -> None:
    if response_kind not in _SUPPORTED_RESPONSE_KINDS:
        raise ValueError(f"Unsupported response kind: {response_kind}")


def _resolve_error_body(
    response_kind: str,
    exc: BaseException | None,
    error_body: Callable[[BaseException], Any] | None,
) -> Any:
    if error_body is not None and exc is not None:
        return error_body(exc)
    if response_kind == "json":
        if exc is None:
            return {"error": INTERNAL_SERVER_ERROR}
        return {"error": str(exc)}
    if response_kind == "html":
        return (
            "<html><body><h1>Error</h1>"
            "<p>Request failed</p>"
            "</body></html>"
        )
    return INTERNAL_SERVER_ERROR


def _build_response(response_kind: str, body: Any, status: int) -> func.HttpResponse:
    if response_kind == "json":
        return json_response(cast(Dict[str, Any], body), status)
    if response_kind == "html":
        return func.HttpResponse(body, status_code=status, mimetype=HTML_CONTENT_TYPE)
    return func.HttpResponse(body, status_code=status, mimetype=TEXT_PLAIN_CONTENT_TYPE)


@dataclass(frozen=True)
class _EndpointConfig:
    name: str | None
    response_kind: str
    bad_request_exceptions: tuple[type[BaseException], ...]
    bad_request_status: int
    not_found_exceptions: tuple[type[BaseException], ...]
    not_found_status: int
    error_status: int
    error_body: Callable[[BaseException], Any] | None
    swallow_exceptions: bool
    logger_override: logging.Logger | None


def _execute_endpoint(
    inner_fn: Callable[..., Any],
    config: _EndpointConfig,
    *args: Any,
    **kwargs: Any,
) -> func.HttpResponse | Any:
    endpoint_name = config.name or inner_fn.__name__
    log = config.logger_override or logger
    try:
        result = inner_fn(*args, **kwargs)
        if isinstance(result, func.HttpResponse):
            return result
        return result
    except config.bad_request_exceptions as exc:
        log.warning("%s (bad request): %s", endpoint_name, exc)
        body = _resolve_error_body(config.response_kind, exc, config.error_body)
        return _build_response(config.response_kind, body, config.bad_request_status)
    except config.not_found_exceptions as exc:
        log.warning("%s (not found): %s", endpoint_name, exc)
        body = _resolve_error_body(config.response_kind, exc, config.error_body)
        return _build_response(config.response_kind, body, config.not_found_status)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        log.error("%s failed: %s", endpoint_name, exc, exc_info=True)
        if config.swallow_exceptions:
            return _build_response(config.response_kind, "OK", 200)
        body = _resolve_error_body(config.response_kind, exc, config.error_body)
        return _build_response(config.response_kind, body, config.error_status)


def _build_decorator(config: _EndpointConfig) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(inner_fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(inner_fn)
        def wrapper(*args: Any, **kwargs: Any) -> func.HttpResponse | Any:
            return _execute_endpoint(inner_fn, config, *args, **kwargs)

        return wrapper

    return decorator


def endpoint(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    response_kind: str = "json",
    bad_request_exceptions: tuple[type[BaseException], ...] = (ValueError,),
    bad_request_status: int = 400,
    not_found_exceptions: tuple[type[BaseException], ...] = (),
    not_found_status: int = 404,
    error_status: int = 500,
    error_body: Callable[[BaseException], Any] | None = None,
    swallow_exceptions: bool = False,
    logger_override: logging.Logger | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]] | Callable[..., Any]:
    """Decorator to standardize error handling for HTTP endpoints."""
    _validate_response_kind(response_kind)
    config = _EndpointConfig(
        name=name,
        response_kind=response_kind,
        bad_request_exceptions=bad_request_exceptions,
        bad_request_status=bad_request_status,
        not_found_exceptions=not_found_exceptions,
        not_found_status=not_found_status,
        error_status=error_status,
        error_body=error_body,
        swallow_exceptions=swallow_exceptions,
        logger_override=logger_override,
    )

    decorator = _build_decorator(config)
    if fn is not None:
        return decorator(fn)

    return decorator


def parse_ingest_payload(req: func.HttpRequest) -> Dict[str, Any]:
    """Parse FIT file ingestion payload from HTTP request."""
    try:
        payload = req.get_json()

        required_fields = ["athlete_id", "source_file_name", "file_content_b64"]
        for field in required_fields:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")

        return payload
    except (ValueError, TypeError) as exc:
        msg = f"Invalid payload: {str(exc)}"
        raise ValueError(msg) from exc
