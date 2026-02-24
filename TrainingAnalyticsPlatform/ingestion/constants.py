"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

METADATA_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v13.0.18"  # (v13.0.17→v13.0.18) Reject semantic IDs without FIT-derived start timestamps; disallow filename-local -> UTC start-time fallback

