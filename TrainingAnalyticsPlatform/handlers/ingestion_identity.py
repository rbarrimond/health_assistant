"""Identity and hashing policy for ingestion."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional


class IngestionIdentityPolicy:
    """Encapsulate deterministic IDs for ingestion and client-facing identity."""

    def __init__(self, source_system: Optional[str]) -> None:
        normalized = (source_system or "").strip() or "unknown"
        self._source_system = normalized.lower()

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """Compute SHA-256 hash of a file on disk."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for byte_block in iter(lambda: handle.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    @staticmethod
    def compute_bytes_hash(file_bytes: bytes) -> str:
        """Compute SHA-256 hash of in-memory bytes."""
        sha256_hash = hashlib.sha256()
        sha256_hash.update(file_bytes)
        return sha256_hash.hexdigest()

    def compute_ingestion_id(
        self,
        source_info: Dict[str, Any],
        *,
        start_time_utc: Optional[str] = None,
    ) -> str:
        """Compute a deterministic ingestion-scoped ID for idempotency."""
        source_item_id = source_info.get("source_item_id")
        file_sha256 = source_info.get("file_sha256")
        file_path = source_info.get("source_file_path")
        file_name = source_info.get("source_file_name")
        start_time_utc = start_time_utc or source_info.get("start_time_utc")

        if source_item_id:
            seed = f"{self._source_system}|item|{source_item_id}"
        elif file_sha256:
            seed = f"{self._source_system}|sha256|{file_sha256}"
        elif file_path and file_name and start_time_utc:
            seed = f"{self._source_system}|path|{file_path}#{file_name}#{start_time_utc}"
        else:
            raise ValueError(
                "Cannot compute ingestion_id without source_item_id, file_sha256, or file path info"
            )

        return hashlib.sha256(seed.encode()).hexdigest()

    @staticmethod
    def compute_stable_workout_id(
        semantic_workout_id: Optional[str],
        *,
        fallback_ingestion_id: Optional[str] = None,
    ) -> Optional[str]:
        """Return the stable workout id for client-facing identity."""
        if semantic_workout_id:
            return semantic_workout_id
        return fallback_ingestion_id
