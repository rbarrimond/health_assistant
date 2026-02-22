"""Parse FIT files and extract workout metrics."""
# Refactored to use fit_models Pydantic hierarchy
# pylint: disable=trailing-whitespace, trailing-newlines

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Utility Functions
# ============================================================================

def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def compute_bytes_hash(file_bytes: bytes) -> str:
    """Compute SHA256 hash of in-memory bytes."""
    sha256_hash = hashlib.sha256()
    sha256_hash.update(file_bytes)
    return sha256_hash.hexdigest()


def compute_workout_id(
    source_item_id: Optional[str] = None,
    file_sha256: Optional[str] = None,
    file_path: Optional[str] = None,
    file_name: Optional[str] = None,
    start_time: Optional[str] = None,
) -> str:
    """Generate deterministic workout_id.

    Priority:
    1. source_item_id (OneDrive itemId)
    2. file_sha256
    3. file_path + file_name + start_time
    """
    if source_item_id:
        return hashlib.sha1(source_item_id.encode()).hexdigest()
    elif file_sha256:
        return hashlib.sha1(file_sha256.encode()).hexdigest()
    elif file_path and file_name and start_time:
        combined = f"{file_path}#{file_name}#{start_time}"
        return hashlib.sha1(combined.encode()).hexdigest()
    else:
        raise ValueError(
            "Must provide at least source_item_id, file_sha256, or file path info"
        )
