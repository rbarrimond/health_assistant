"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

METADATA_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v15.3.0"  # (v15.2.0->v15.3.0) MINOR: add deferred retry persistence surface (RateLimitDeferrals table + queue-backed timeout-risk deferral metadata)

