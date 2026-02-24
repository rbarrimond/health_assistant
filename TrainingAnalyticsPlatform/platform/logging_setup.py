"""Logging configuration for Azure Functions."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict


class JsonLogFormatter(logging.Formatter):
    """Emit structured JSON logs to stdout for Azure ingestion."""

    _reserved = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": os.getenv("SERVICE_NAME", "health-assistant"),
            "environment": os.getenv("APP_ENV", "unknown"),
        }
        for key, value in record.__dict__.items():
            if key not in self._reserved and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> logging.Logger:
    """Configure root logging for Azure Functions execution."""
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_format = os.getenv("LOG_FORMAT", "json").lower()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    if getattr(root_logger, "_health_assistant_logging_configured", False):
        return root_logger

    for handler in root_logger.handlers:
        handler.setLevel(log_level)
        if log_format == "json":
            handler.setFormatter(JsonLogFormatter())

    if not root_logger.handlers:
        console = logging.StreamHandler()
        console.setLevel(log_level)
        if log_format == "json":
            console.setFormatter(JsonLogFormatter())
        else:
            console.setFormatter(
                logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            )
        root_logger.addHandler(console)

    setattr(root_logger, "_health_assistant_logging_configured", True)
    return root_logger
