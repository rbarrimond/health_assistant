# Changelog

## 2026-02-07

- Move ingestion metadata (`ingest_version`, `ingested_at_utc`) from Workouts to IngestionState.
- Remove ingestion timestamps from semantic workout payloads.
- Bump ingestion version to v2.0.0.
- Add a backfill script for IngestionState metadata.
- Fix backfill script to query workouts with a filter.
