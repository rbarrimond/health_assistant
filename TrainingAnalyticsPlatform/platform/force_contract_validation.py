"""Utilities for validating force-mode ingestion contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

FORCE_CONTRACT_BLOCKED_STATUSES = frozenset({"skipped_duplicate"})


def find_force_contract_violations(
    items: Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return item entries that violate the force contract."""
    violations: list[dict[str, Any]] = []
    if not items:
        return violations

    for item in items:
        status = str(item.get("status", "")).strip().lower()
        if status in FORCE_CONTRACT_BLOCKED_STATUSES:
            violations.append(
                {
                    "activity_id": item.get("activity_id"),
                    "activity_name": item.get("activity_name"),
                    "status": status,
                    "workout_id": item.get("workout_id"),
                }
            )

    return violations
