"""Versioned constants for ingestion artifacts."""
# pylint: disable=trailing-whitespace, trailing-newlines, line-too-long

METADATA_SCHEMA_VERSION = "1.0.0"
LAPS_SCHEMA_VERSION = "1.0.0"
FIT_ANALYSIS_VERSION = "v1.0.0"
INGEST_VERSION = "v14.4.1"  # (v14.4.0→v14.4.1) Fixed FIT left_right_balance field decoding to mask raw byte (bits 0-6: percentage, bit 7: flag)

