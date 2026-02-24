"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

METADATA_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v13.0.19"  # (v13.0.18→v13.0.19) Derive session start_time_utc from FIT UTC timestamp minus elapsed duration; enforce no local start_time/file fallback

