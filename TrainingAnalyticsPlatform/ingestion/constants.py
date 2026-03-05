"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

METADATA_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v15.0.0"  # (v14.4.2→v15.0.0) BREAKING: PhysiometricsSnapshot v3.0.0 - simplified to 30 fields, exclusive source ownership, direct ingestion (no blob storage), TrainingState projection (no table), flattened storage schema

