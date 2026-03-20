"""Shared utilities for the Azure Functions HTTP adapter."""

from __future__ import annotations

import gzip
import json
import logging
import time
from collections.abc import Mapping
from functools import wraps
from dataclasses import dataclass
from typing import Any, Callable, Dict, cast

import azure.functions as func

from config.constants import (
    HTML_CONTENT_TYPE,
    INTERNAL_SERVER_ERROR,
    TEXT_PLAIN_CONTENT_TYPE,
)
from TrainingAnalyticsPlatform.platform.http_utils import (
    apply_correlation_headers,
    extract_correlation_context,
    json_response,
)

logger = logging.getLogger(__name__)

_SUPPORTED_RESPONSE_KINDS = {"json", "html", "text"}
_KNOWN_SOURCE_PREFIXES = {"garmin", "withings", "onedrive", "intervals"}
_RESERVED_CONTEXT_KEYS = {"athlete_id", "operation_id", "correlation_id"}
_OPERATIONAL_ENDPOINT_PREFIXES = (
    "config_",
    "garmin_",
    "health_check",
    "intervals_",
    "onedrive_",
    "serve_",
    "update_config",
    "update_physiometrics",
    "withings_",
    "force_weekly_rollups",
    "get_async_operation_status",
)
_OPERATIONAL_PATH_MARKERS = (
    "/.well-known/ai-plugin.json",
    "/api/async/operations/",
    "/api/config/",
    "/api/garmin/",
    "/api/health",
    "/api/intervals/",
    "/api/onedrive/",
    "/api/operations/",
    "/api/physiometrics/update",
    "/api/withings/",
    "/openapi.operations.yaml",
)
_ERROR_CODES_BY_STATUS = {
    400: "BAD_REQUEST",
    401: "AUTH_ERROR",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "UNPROCESSABLE_ENTITY",
    424: "FAILED_DEPENDENCY",
    429: "RATE_LIMITED",
    500: "INTERNAL_SERVER_ERROR",
    502: "EXTERNAL_SERVICE_ERROR",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


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
        try:
            from TrainingAnalyticsPlatform.platform.exceptions import HealthAssistantError

            if isinstance(exc, HealthAssistantError):
                body, _ = exc.to_response(include_message_alias=True)
                return body
        except ImportError:
            pass
        return {"error": str(exc)}
    if response_kind == "html":
        return (
            "<html><body><h1>Error</h1>"
            "<p>Request failed</p>"
            "</body></html>"
        )
    return INTERNAL_SERVER_ERROR


def _build_response(
    response_kind: str,
    body: Any,
    status: int,
    req: func.HttpRequest | None = None,
) -> func.HttpResponse:
    if response_kind == "json":
        return json_response(cast(Dict[str, Any], body), status, req=req)
    if response_kind == "html":
        return func.HttpResponse(body, status_code=status, mimetype=HTML_CONTENT_TYPE)
    return func.HttpResponse(body, status_code=status, mimetype=TEXT_PLAIN_CONTENT_TYPE)


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _extract_request_json_payload(req: func.HttpRequest | None) -> Dict[str, Any]:
    if req is None or not hasattr(req, "get_body"):
        return {}
    try:
        body = req.get_body()
    except Exception:  # pylint: disable=broad-exception-caught
        return {}
    if not body:
        return {}
    if isinstance(body, str):
        raw_body = body.encode("utf-8")
    elif isinstance(body, (bytes, bytearray)):
        raw_body = bytes(body)
    else:
        return {}

    headers = _coerce_mapping(getattr(req, "headers", None))
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "").lower()
    body_prefix = raw_body.lstrip()[:1]
    if content_type and "json" not in content_type and body_prefix not in {b"{", b"["}:
        return {}

    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return {}

    if isinstance(parsed, dict):
        return parsed
    return {}


def _first_present_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _extract_resource_id(*containers: Dict[str, Any]) -> Any:
    explicit_resource_id = _first_present_value(
        *(container.get("resource_id") for container in containers)
    )
    if explicit_resource_id is not None:
        return explicit_resource_id

    for container in containers:
        for key, value in container.items():
            if key in _RESERVED_CONTEXT_KEYS or not key.endswith("_id"):
                continue
            if value in (None, ""):
                continue
            return value
    return None


def _set_context_value(context: Dict[str, str], key: str, value: Any) -> None:
    if value not in (None, ""):
        context[key] = str(value)


def _extract_request_context(req: func.HttpRequest | None) -> Dict[str, str]:
    if req is None:
        return {}

    route_params = _coerce_mapping(getattr(req, "route_params", None))
    query_params = _coerce_mapping(getattr(req, "params", None))
    payload = _extract_request_json_payload(req)

    context: Dict[str, str] = {}
    _set_context_value(
        context,
        "athlete_id",
        _first_present_value(
            payload.get("athlete_id"),
            query_params.get("athlete_id"),
            route_params.get("athlete_id"),
        ),
    )
    _set_context_value(
        context,
        "provider",
        _first_present_value(payload.get("provider"), query_params.get("provider")),
    )
    _set_context_value(
        context,
        "source",
        _first_present_value(payload.get("source"), query_params.get("source")),
    )
    _set_context_value(
        context,
        "resource_id",
        _extract_resource_id(route_params, query_params, payload),
    )
    return context


def _infer_source(endpoint_name: str, request_context: Dict[str, str]) -> str | None:
    source = request_context.get("source")
    if source:
        return source
    provider = request_context.get("provider")
    if provider:
        return provider

    prefix = endpoint_name.split("_", maxsplit=1)[0]
    if prefix in _KNOWN_SOURCE_PREFIXES:
        return prefix
    return None


def _is_operational_endpoint(
    request: func.HttpRequest | None,
    endpoint_name: str,
) -> bool:
    if endpoint_name.startswith(_OPERATIONAL_ENDPOINT_PREFIXES):
        return True
    if request is None:
        return False

    request_url = getattr(request, "url", "") or ""
    return any(marker in request_url for marker in _OPERATIONAL_PATH_MARKERS)


def _default_error_code(status_code: int) -> str:
    return _ERROR_CODES_BY_STATUS.get(status_code, "OPERATIONAL_ERROR")


def _apply_error_metadata(
    payload: Dict[str, Any],
    *,
    status_code: int,
    endpoint_name: str,
    correlation: Dict[str, str],
    request_context: Dict[str, str],
) -> Dict[str, Any]:
    if "error" not in payload and payload.get("message"):
        payload["error"] = payload["message"]
    if "status" not in payload and status_code >= 400:
        payload["status"] = "error"
    if "error" in payload and "error_code" not in payload:
        payload["error_code"] = _default_error_code(status_code)

    payload.setdefault("correlation_id", correlation["correlation_id"])
    payload.setdefault("operation", endpoint_name)

    source = _infer_source(endpoint_name, request_context)
    if source:
        payload.setdefault("source", source)
        payload.setdefault("provider", request_context.get("provider", source))
    elif request_context.get("provider"):
        payload.setdefault("provider", request_context["provider"])

    for key in ("athlete_id", "resource_id"):
        if request_context.get(key):
            payload.setdefault(key, request_context[key])
    return payload


def _normalize_error_detail(
    error_item: Any,
    *,
    status_code: int,
    endpoint_name: str,
    correlation: Dict[str, str],
    request_context: Dict[str, str],
) -> Dict[str, Any]:
    if isinstance(error_item, dict):
        detail = dict(error_item)
    else:
        detail = {"error": str(error_item)}

    if "status" not in detail:
        detail["status"] = "error"
    if "error" not in detail and detail.get("message"):
        detail["error"] = detail["message"]
    if "error" in detail and "error_code" not in detail:
        detail["error_code"] = _default_error_code(status_code)

    return _apply_error_metadata(
        detail,
        status_code=status_code,
        endpoint_name=endpoint_name,
        correlation=correlation,
        request_context=request_context,
    )


def _response_is_json(response: func.HttpResponse) -> bool:
    mimetype = getattr(response, "mimetype", "") or ""
    if mimetype == "application/json":
        return True
    headers = _coerce_mapping(getattr(response, "headers", None))
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    return "application/json" in content_type.lower()


def _decode_json_response_body(response: func.HttpResponse) -> Dict[str, Any] | None:
    try:
        payload = response.get_body()
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    if not payload:
        return None

    headers = _coerce_mapping(getattr(response, "headers", None))
    content_encoding = str(headers.get("Content-Encoding") or headers.get("content-encoding") or "")
    if "gzip" in content_encoding.lower():
        try:
            payload = gzip.decompress(payload)
        except OSError:
            return None

    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if isinstance(parsed, dict):
        return parsed
    return None


def _rebuild_json_response(
    response: func.HttpResponse,
    body: Dict[str, Any],
    req: func.HttpRequest | None,
) -> func.HttpResponse:
    rebuilt = json_response(body, int(response.status_code), req=req)
    original_headers = _coerce_mapping(getattr(response, "headers", None))
    for key, value in original_headers.items():
        if key.lower() in {"content-type", "content-length", "content-encoding", "vary"}:
            continue
        rebuilt.headers.setdefault(str(key), str(value))
    return rebuilt


def _apply_partial_response_context(
    body: Dict[str, Any],
    *,
    endpoint_name: str,
    correlation: Dict[str, str],
    request_context: Dict[str, str],
) -> None:
    body.setdefault("correlation_id", correlation["correlation_id"])
    body.setdefault("operation", endpoint_name)

    source = _infer_source(endpoint_name, request_context)
    if source:
        body.setdefault("source", source)
        body.setdefault("provider", request_context.get("provider", source))
    if request_context.get("athlete_id"):
        body.setdefault("athlete_id", request_context["athlete_id"])
    if request_context.get("resource_id"):
        body.setdefault("resource_id", request_context["resource_id"])


def _add_partial_error_details(
    body: Dict[str, Any],
    *,
    status_code: int,
    endpoint_name: str,
    correlation: Dict[str, str],
    request_context: Dict[str, str],
) -> None:
    if "error_details" in body:
        return

    body["error_details"] = [
        _normalize_error_detail(
            error_item,
            status_code=status_code,
            endpoint_name=endpoint_name,
            correlation=correlation,
            request_context=request_context,
        )
        for error_item in cast(list[Any], body["errors"])
    ]
    _apply_partial_response_context(
        body,
        endpoint_name=endpoint_name,
        correlation=correlation,
        request_context=request_context,
    )


def _maybe_enrich_json_error_response(
    response: func.HttpResponse,
    *,
    request: func.HttpRequest | None,
    endpoint_name: str,
    correlation: Dict[str, str],
) -> func.HttpResponse:
    if not _is_operational_endpoint(request, endpoint_name):
        return response
    if not _response_is_json(response):
        return response

    body = _decode_json_response_body(response)
    if body is None:
        return response

    has_partial_errors = isinstance(body.get("errors"), list) and len(body["errors"]) > 0
    has_top_level_error = (
        int(response.status_code) >= 400
        or body.get("status") in {"error", "filtered"}
        or "error" in body
    )
    if not has_partial_errors and not has_top_level_error:
        return response

    request_context = _extract_request_context(request)
    if has_top_level_error:
        body = _apply_error_metadata(
            body,
            status_code=int(response.status_code),
            endpoint_name=endpoint_name,
            correlation=correlation,
            request_context=request_context,
        )

    if has_partial_errors:
        _add_partial_error_details(
            body,
            status_code=int(response.status_code),
            endpoint_name=endpoint_name,
            correlation=correlation,
            request_context=request_context,
        )

    return _rebuild_json_response(response, body, request)


def _finalize_response(
    response: func.HttpResponse,
    *,
    request: func.HttpRequest | None,
    endpoint_name: str,
    correlation: Dict[str, str],
) -> func.HttpResponse:
    enriched = _maybe_enrich_json_error_response(
        response,
        request=request,
        endpoint_name=endpoint_name,
        correlation=correlation,
    )
    return apply_correlation_headers(
        enriched,
        correlation_id=correlation["correlation_id"],
        traceparent=correlation["traceparent"],
    )


def _resolve_http_request(args: tuple[Any, ...], kwargs: Dict[str, Any]) -> func.HttpRequest | None:
    req = kwargs.get("req")
    if isinstance(req, func.HttpRequest):
        return req
    for arg in args:
        if isinstance(arg, func.HttpRequest):
            return arg
    return None


def _log_event(
    log: logging.Logger,
    level: int,
    event_name: str,
    endpoint_name: str,
    correlation: Dict[str, str],
    duration_ms: int,
    status_code: int,
    **extra_fields: Any,
) -> None:
    payload: Dict[str, Any] = {
        "event_name": event_name,
        "endpoint": endpoint_name,
        "operation_id": correlation["operation_id"],
        "correlation_id": correlation["correlation_id"],
        "traceparent": correlation["traceparent"],
        "duration_ms": duration_ms,
        "status_code": status_code,
    }
    payload.update(extra_fields)
    log.log(level, "endpoint_event", extra=payload)


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
    request = _resolve_http_request(args, kwargs)
    correlation = extract_correlation_context(request)
    started = time.perf_counter()
    try:
        result = inner_fn(*args, **kwargs)
        if isinstance(result, func.HttpResponse):
            duration_ms = int((time.perf_counter() - started) * 1000)
            status_code = int(result.status_code)
            _log_event(
                log,
                logging.INFO,
                "endpoint.success",
                endpoint_name,
                correlation,
                duration_ms,
                status_code,
            )
            return _finalize_response(
                result,
                request=request,
                endpoint_name=endpoint_name,
                correlation=correlation,
            )
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_event(
            log,
            logging.INFO,
            "endpoint.success",
            endpoint_name,
            correlation,
            duration_ms,
            200,
        )
        return result
    except config.bad_request_exceptions as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_event(
            log,
            logging.WARNING,
            "endpoint.bad_request",
            endpoint_name,
            correlation,
            duration_ms,
            config.bad_request_status,
            error=str(exc),
        )
        body = _resolve_error_body(config.response_kind, exc, config.error_body)
        response = _build_response(
            config.response_kind,
            body,
            config.bad_request_status,
            req=request,
        )
        return _finalize_response(
            response,
            request=request,
            endpoint_name=endpoint_name,
            correlation=correlation,
        )
    except config.not_found_exceptions as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_event(
            log,
            logging.WARNING,
            "endpoint.not_found",
            endpoint_name,
            correlation,
            duration_ms,
            config.not_found_status,
            error=str(exc),
        )
        body = _resolve_error_body(config.response_kind, exc, config.error_body)
        response = _build_response(
            config.response_kind,
            body,
            config.not_found_status,
            req=request,
        )
        return _finalize_response(
            response,
            request=request,
            endpoint_name=endpoint_name,
            correlation=correlation,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_event(
            log,
            logging.ERROR,
            "endpoint.error",
            endpoint_name,
            correlation,
            duration_ms,
            config.error_status,
            error=str(exc),
        )
        log.exception("Unhandled endpoint failure")
        if config.swallow_exceptions:
            response = _build_response(config.response_kind, "OK", 200, req=request)
            return _finalize_response(
                response,
                request=request,
                endpoint_name=endpoint_name,
                correlation=correlation,
            )
        body = _resolve_error_body(config.response_kind, exc, config.error_body)
        response = _build_response(
            config.response_kind,
            body,
            config.error_status,
            req=request,
        )
        return _finalize_response(
            response,
            request=request,
            endpoint_name=endpoint_name,
            correlation=correlation,
        )


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
