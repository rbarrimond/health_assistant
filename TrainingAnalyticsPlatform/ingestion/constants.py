"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

METADATA_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v14.3.11"  # (v14.3.10→v14.3.11) BREAKING: Sleep duration now stored in seconds (sleep_duration_sec), not minutes; removed conversion in Intervals adapter

