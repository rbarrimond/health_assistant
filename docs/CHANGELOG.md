# Changelog

## 2026-02-07

- Move ingestion metadata (`ingest_version`, `ingested_at_utc`) from Workouts to IngestionState.
- Remove ingestion timestamps from semantic workout payloads.
- Bump ingestion version to v2.0.0.
- Add a backfill script for IngestionState metadata.
- Fix backfill script to query workouts with a filter.
- Exclude Azure Table system metadata from Workouts metrics.
- Stop storing minute-based zone fields; derive minutes from seconds at read time.
- Store low aerobic and intensity metrics in seconds only.
- Respect FIT-provided timezone names or device UTC offsets in adapter output.
- Add optional runtime chaos injection via `sitecustomize` for local ingestion testing.
