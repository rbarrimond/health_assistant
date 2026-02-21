"""Parse FIT files and extract workout metrics."""
# Refactored to use fit_models Pydantic hierarchy
# pylint: disable=trailing-whitespace, trailing-newlines

import hashlib
import logging
from typing import Any, Dict, List, Optional

from .fit_models import BaseFitModel, create_fit_model
from .fit_analyzer import FitStructureAnalyzer

logger = logging.getLogger(__name__)


class FitParser:
    """Lightweight facade for FIT parsing delegating to fit_models hierarchy.
    
    Maintains backward compatibility while delegating heavy logic to Pydantic models.
    """

    def __init__(
        self,
        file_path: Optional[str] = None,
        source_file_name: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        source_activity_name: Optional[str] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
    ):
        """Initialize FIT parser by creating underlying model.

        Args:
            file_path: Path to the FIT file
            source_file_name: Optional original filename (legacy param, prefer source_metadata)
            file_bytes: Optional in-memory FIT bytes
            source_activity_name: Optional activity name (legacy param, prefer source_metadata)
            source_metadata: Optional dict with source-specific fields (recommended)
        """
        if not file_path and file_bytes is None:
            raise ValueError("file_path or file_bytes must be provided")
        
        # Build source_metadata from kwargs for backward compatibility
        if source_metadata is None:
            source_metadata = {}
        if source_file_name and "source_file_name" not in source_metadata:
            source_metadata["source_file_name"] = source_file_name
        if source_activity_name and "source_activity_name" not in source_metadata:
            source_metadata["source_activity_name"] = source_activity_name
        
        self.model: BaseFitModel = create_fit_model(
            source_metadata=source_metadata,
            file_path=file_path,
            file_bytes=file_bytes,
        )
        
        # Legacy attributes for backward compatibility
        self.file_path = file_path or "<in-memory>"
        self.file_bytes = file_bytes
        self.source_file_name = source_file_name
        self.source_activity_name = source_activity_name
    
    @property
    def file_id_msg(self):
        """Cached file_id message (delegates to model)."""
        return self.model.file_id_msg
    
    @property
    def session_msg(self):
        """Cached session message (delegates to model)."""
        return self.model.session_msg
    
    @property
    def messages(self) -> List[Any]:
        """Cached FIT messages (delegates to model)."""
        return self.model.messages
    
    # ========================================================================
    # Public API: Extract Methods (delegate to model)
    # ========================================================================
    
    def extract_canonical_records(self) -> List[Dict[str, Any]]:
        """Extract Section I canonical substrate records for parquet storage."""
        return self.model.build_canonical_records()

    def extract_canonical_metadata(self) -> Dict[str, Any]:
        """Extract canonical FIT metadata from file, device, event, activity, session."""
        return self.model.build_canonical_metadata()

    def extract_raw_fit_json(self) -> Dict[str, Any]:
        """Return full-fidelity JSON using fitdecode's RecordJSONEncoder."""
        return self.model.build_raw_fit_json()

    def extract_metadata_messages(self) -> Dict[str, Any]:
        """Return structured FIT metadata.json with raw messages and LLM enrichment placeholder."""
        return self.model.build_metadata_messages()

    def extract_laps_json(self) -> Dict[str, Any]:
        """Return lap messages JSON artifact with schema metadata."""
        return self.model.build_laps_json()

    def extract_fit_analysis(self) -> Dict[str, Any]:
        """Return deterministic FIT structural analysis payload."""
        analyzer = FitStructureAnalyzer(self.model.messages)
        return analyzer.analyze()

    def enrich_metadata_with_llm(
        self,
        metadata_json: Dict[str, Any],
        fit_analysis: Dict[str, Any],
        llm_client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Enrich metadata.json with semantic interpretation from LLM.
        
        Calls GPT-4o-mini to analyze raw_fit_messages + fit_analysis and provide
        semantic interpretation: inferred workout name, activity classification,
        virtual indicators, and anomalies.
        
        Args:
            metadata_json: Output from extract_metadata_messages()
            fit_analysis: Output from extract_fit_analysis()
            llm_client: Optional Azure OpenAI client. If None, returns metadata unchanged.
        
        Returns:
            metadata_json with llm_enrichment.status='complete' and filled fields.
            If llm_client is None, returns with status='skipped'.
        """
        if not llm_client:
            metadata_json["llm_enrichment"]["status"] = "skipped"
            return metadata_json

        _ = fit_analysis
        # LLM enrichment pending; prompt and output contract not finalized yet.
       
        logger.debug("LLM enrichment not yet implemented; returning metadata with pending status")
        return metadata_json


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
