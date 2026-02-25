"""Shared value coercion helpers for FIT ingestion models."""

from __future__ import annotations

from typing import Any, Optional


def coerce_float(value: Any) -> Optional[float]:
    """Coerce value to float, returning ``None`` for non-numeric inputs."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
