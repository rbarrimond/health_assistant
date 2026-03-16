"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

METADATA_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v15.2.0"  # (v15.1.9->v15.2.0) MINOR: remove session-based offset inference; activity local_timestamp is now the only generic FIT offset fallback; HealthFit ignores explicit timezone metadata keys

