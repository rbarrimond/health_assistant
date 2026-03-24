"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

CANONICAL_METADATA_SCHEMA_VERSION = "2.4.0"
METADATA_MESSAGES_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v15.6.0"  # (v15.5.1->v15.6.0) MINOR: force Garmin sync now bypasses unchanged-content skip and records fresh ingested_at_utc on successful re-ingestion

