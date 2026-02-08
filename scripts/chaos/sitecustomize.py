"""Runtime fault injection via Python's sitecustomize hook.

This module is only active when CHAOS_TARGET is set. It lets you inject
failures or delays without modifying application code.

Example:
  CHAOS_TARGET=FitParser.fit_parser.FitParser.parse
  CHAOS_RATE=0.2
  CHAOS_SLEEP_MS=250
"""

from __future__ import annotations

import importlib
import logging
import os
import random
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("chaos")


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _resolve_target(dotted_path: str) -> tuple[Any, str]:
    """Resolve a dotted path to (parent_obj, attr_name)."""
    parts = dotted_path.split(".")
    if len(parts) < 2:
        raise ValueError("CHAOS_TARGET must include module and attribute")

    module_name = parts[0]
    module = importlib.import_module(module_name)
    parent: Any = module
    for part in parts[1:-1]:
        parent = getattr(parent, part)
    return parent, parts[-1]


def _wrap_callable(func: Callable[..., Any]) -> Callable[..., Any]:
    rate = _parse_float(os.getenv("CHAOS_RATE"))
    after = _parse_int(os.getenv("CHAOS_AFTER"))
    sleep_ms = _parse_int(os.getenv("CHAOS_SLEEP_MS"))
    once = os.getenv("CHAOS_ONCE", "").lower() in {"1", "true", "yes", "y"}
    message = os.getenv("CHAOS_MESSAGE", "Injected failure")

    counter = {"calls": 0, "raised": False}

    def should_raise() -> bool:
        if once and counter["raised"]:
            return False
        if after is not None and counter["calls"] < after:
            return False
        if rate is not None:
            return random.random() < rate
        return True

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        counter["calls"] += 1
        if sleep_ms:
            time.sleep(sleep_ms / 1000.0)
        if should_raise():
            counter["raised"] = True
            logger.warning("CHAOS: raising in %s", func.__qualname__)
            raise RuntimeError(message)
        return func(*args, **kwargs)

    return wrapper


def _install_chaos() -> None:
    target = os.getenv("CHAOS_TARGET")
    if not target:
        return

    try:
        parent, attr_name = _resolve_target(target)
        original = getattr(parent, attr_name)
        if not callable(original):
            logger.warning("CHAOS_TARGET is not callable: %s", target)
            return
        setattr(parent, attr_name, _wrap_callable(original))
        logger.warning("CHAOS: installed on %s", target)
    except Exception as exc:  # pragma: no cover - best effort only pylint: disable=broad-except
        logger.warning("CHAOS: failed to install (%s)", exc)


_install_chaos()
