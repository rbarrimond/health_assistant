"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

CANONICAL_METADATA_SCHEMA_VERSION = "2.4.0"
METADATA_MESSAGES_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v15.8.2"  # (v15.8.1->v15.8.2) PATCH: Garmin lactate-threshold ingestion now prefers the current Edge-reported threshold HR over stale cycling-specific fallback values when both are present

