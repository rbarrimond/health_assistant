# Changelog

## 2026-02-09

- Refactor FIT ingestion handlers (payload + OneDrive sync) under abstract base; remove FitUploadHandler.
- Route `process_fit` through payload handler to align HTTP ingestion behavior.
- Bump ingest version to v3.0.0 (ingestion API response shape change).

## 2026-02-08

- Fix OpenAPI nullability schema and markdown table pipes; refactor ingestion state preservation.
- Align workout list endpoint filters and API specs with semantic layer.
- Update ingestion schema requirements and documentation; bump ingest version to v2.3.1.
- Expand OpenAPI workout fields and document plugin/asset endpoints.
- Refresh Postman collection and API alignment report to include asset endpoints.
- Remove file provenance fields from Workouts; keep source filename and drive ID in IngestionState.
- Resolve workout names from FIT session_name, falling back to filename without extension.
- Resolve Apple workout types from workout_name instead of source filenames.
- Reuse existing workout_id from ingestion state when reprocessing.
- Bump ingest version to v2.3.0.
- Rename chatmodes to agents and remove unknown tool entries.
- Guard OneDrive sync idempotency checks when storage context is mocked; bump ingest version to v2.2.7.
- Backfill IngestionState with OneDrive cTag/quickXor hash/modified timestamp when present.
- Bump ingest version to v2.2.6.
- Enforce required fields for FIT payload ingestion requests.
- Allow OneDrive content metadata fields on process_fit payloads.
- Bump ingest version to v2.2.5.
- Prefer file SHA over OneDrive etag for unchanged detection during ingestion.
- Use OneDrive cTag/quickXor hash/modified time to skip unchanged files before download.
- Store OneDrive cTag, quickXor hash, and modified timestamp in ingestion state.
- Preserve ingested metadata when recording skipped ingestion state.
- Bump ingest version to v2.2.4.

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
- Add a dummy tasks.json entry to work around VS Code task ordering issues.
- Skip ingestion when OneDrive etag or file hash is unchanged; record `skipped` status without incrementing retries.
- Store `source_etag` and `file_sha256` in IngestionState; bump ingest version to v2.2.2.
