# Changelog

## 2026-02-20

- Fix Garmin FIT file ingestion by adding proper format detection and extraction in `GarminConnectClient.download_activity_fit()` method. Investigation of garminconnect library source code revealed that Garmin's ORIGINAL format downloads return ZIP archives containing FIT files, not raw FIT files as initially assumed. Updated implementation to:
  1. Always attempt ZIP extraction first (per garminconnect library documentation: "For 'Original' will return the zip file content, up to user to extract it")
  2. Fall back gracefully if ZIP extraction fails (handles cases where API returns raw FIT or gzipped FIT despite documentation)
  3. Check for and decompress gzip format (magic number `\x1f\x8b`)
  4. Validate final FIT file format with detailed diagnostic logging (first 32 bytes hex dump)
- Refactor `download_activity_fit()` into focused helper methods (`_extract_fit_from_zip`, `_decompress_gzip`, `_validate_fit_format`) to reduce cognitive complexity and improve testability.
- Improve exception handling: `_extract_fit_from_zip()` now returns original data on BadZipFile instead of raising, allowing graceful fallback to other format detection methods.
- Add comprehensive diagnostic logging at INFO level for format detection steps (file size, header hex, extraction/decompression attempts, final validation).
- Bump ingest version to v7.0.1 for Garmin ingestion fix (patch bump, no schema changes).

## 2026-02-19

- Add `TrainingAnalyticsPlatform/ingestion/code_mappings.py` with FIT protocol manufacturer and product code mappings extracted from fitdecode SDK v21.171 (330+ manufacturer codes, Garmin, Favero, and Apple product models with bidirectional helper functions).
- Update `config/README.md` documentation for application-level constants.
- Bump ingestion schema to 5.1.0 for Apple Watch device model integration (non-breaking feature addition).

## 2026-02-18

- Migrate FIT ingestion to fitdecode with a compatibility shim and update JSON dump utility to decoded-only output.
- Consolidate blob storage into the `workouts` container and add canonical artifact writes (raw FIT, metadata, laps, analysis).
- Add `canonical_schema_version` to Workouts and bump ingestion schema to 5.0.0 and ingest version to v6.0.0.

## 2026-02-17

- Fold canonical analytics metrics into `WorkoutMetricsModel` with compositional submodels (training load, power-duration anchors, envelope scores, variability, durability, artifacts) and align zone boundaries/summary fields.
- Add `WorkoutMetricsModel.from_canonical()` classmethod for constructing from canonical DataFrame with in-memory caching.
- Refactor `from_canonical()` into helper methods (`_build_hr_zones`, `_build_power_zones`, etc.) to reduce cognitive complexity.
- Rename `CanonicalWorkoutMetrics` to `CanonicalAnalyticsEngine` to clarify its role as a computation engine rather than an output model.
- Split monolithic `FitParser/models.py` (2311 lines) into organized multi-file package structure with focused submodules: `core.py`, `constants.py`, `substrate.py`, `legacy.py`, `agent.py`, and `metrics/` (session, samples, distance, zones, training, performance, artifacts); maintain backward compatibility via package `__init__.py` exports.
- Update Workout Schema to 10.0.0 to document the expanded canonical analytics surface.
- Bump ingestion schema to 4.1.1 and ingest version to v4.1.1 for parsing/model changes.
- Fix semantic layer tests to use correct `_get_table_client` mock and include required WorkoutEntity fields.

## 2026-02-15

- Treat unchanged skipped ingestions as terminal to prevent reingestion and preserve `ingested_at_utc`; bump ingest version to v3.1.1 and ingestion schema to 3.1.1.

## 2026-02-16

- Expand Canonical Analytics Surface substrate section with core vs extended telemetry, nullability guidance, and HRV RR-interval integration notes; bump version to 1.1.0.
- Extend CanonicalRecord with extended telemetry fields, preserve sparse RR intervals during 1 Hz resampling, and pass through calories_kcal from metadata.
- Harden FIT dump script to use safe attribute access for fitparse message fields and developer fields.
- Add canonical FIT parquet substrate + lap parquet storage, store canonical pointers in Workouts, compute derived metrics from canonical records in semantic layer, and bump ingestion/workout schema versions to 4.0.0 and 7.0.0.
- Store activity local timestamps without UTC conversion and rename field to `activity_local_time`; keep workout schema at 7.0.0 for this commit.
- Remove redundant metadata fields (`file_type`, `event_count`, `event_types`, `end_time_utc`) - end_time_utc is derivable from start_time_utc + duration_sec, others provide no discriminatory value.
- Split logical workout schema from operational storage details, move storage layout into ingestion schema, and update GPT semantic API docs/rollups to remove storage keys; bump workout schema to 8.0.0, ingestion schema to 4.1.0, semantic API doc to 5.0.0, and GPT OpenAPI spec to 2.1.0.
- Trim logical workout schema device/file fields to `device_name` only, make device labels include product when available, and bump WORKOUT_SCHEMA to 9.0.0, SEMANTIC_LAYER_API to 6.0.0, and GPT OpenAPI to 3.0.0.
- Refactor `CanonicalWorkoutMetrics` to own canonical records + metadata and expose calculated metrics as properties on the model.
- Remove cached metrics in `CanonicalWorkoutMetrics` so computed fields recompute on access.
- Remove cached DataFrame in `CanonicalWorkoutMetrics` so metrics always derive from current records.
- Compute canonical metrics once per `CanonicalWorkoutMetrics` instance and reuse a snapshot when serving computed fields.
- Update `CanonicalWorkoutMetrics` to own a canonical DataFrame (schema `CanonicalRecord`) instead of a list of records.
- Remove cached metrics snapshot so computed fields calculate from DataFrame columns on access.
- Compute canonical metrics per property group on-demand (no full-metrics cache for computed fields).
- Add power curve helper and `power_curve_watts` computed field for best-average power by minute duration.
- Expand `CanonicalWorkoutMetrics` to the full Canonical Analytics Surface with 1 Hz resampling, Coggan normalized power, anchor/envelope/variability/durability metrics, and structured artifact projections.
- Standardize FTP naming to `ftp_watts` across the Canonical Analytics Surface and deterministic formula contract (rename only).
- Rewrite `CanonicalWorkoutMetrics` to compute analytics directly from the canonical DataFrame with vectorized pandas operations and no metric-routing lookups.
- Remove unused legacy helper methods from `CanonicalWorkoutMetrics` (`_compute_time_bounds`, `_compute_distance_metrics`, `_compute_speed_metrics`, `_compute_hr_metrics`, `_compute_power_metrics`, `_compute_cadence_metrics`, `_compute_missing_pct`, `_compute_training_load`, `_compute_aerobic_efficiency`) - superseded by direct computed field implementations.
- Refactor `CanonicalWorkoutMetrics` to validate input DataFrame is 1 Hz sampled during initialization; add explicit `resample=True` flag to enable automatic resampling instead of implicit on-demand resampling.
- Keep direct `_numeric_series` usage in computed fields to avoid decorator/tooling conflicts.

## 2026-02-14

- Align GPT Actions guide with read-only scope by removing physiometrics update examples, adding current physiometrics read example, and clarifying weight trend response; bump GPT Actions guide version to 3.5.0.
- Remove Withings auth example and clarify weight trend phrasing in GPT Actions guide; bump version to 3.5.1.
- Remove physiometrics update write details from GPT-facing semantic layer API doc; bump version to 4.1.3.
- Document operations-spec endpoints in Operations API (healthcheck, agent memory, Withings auth/callback, workout recalculated); bump Operations API version to 1.1.0.
- Remove agent memory endpoints from operations OpenAPI and Operations API docs so only healthcheck overlaps with GPT endpoints; bump Operations API version to 1.2.0.
- Tighten GPT Actions guide to require the initial context calls before any natural-language response; bump version to 3.6.0.
- Change HTTP request code blocks from bash to http language in GPT Actions guide examples; bump version to 3.6.1.
- Remove redundant "Do Not Call" section from GPT Actions guide (spec is authoritative boundary); bump version to 3.7.0.
- Clarify that context calls must be made automatically by the agent as needed (not passively).

## 2026-02-12

- Add physiometrics API walkthrough and update examples to semantic layer docs; bump SEMANTIC_LAYER_API to 4.1.2.
- **Secure agent memory read endpoints (GET /api/agent/{context,preferences,observations}) with function key requirement for data protection.**
- **Refactor agent preferences to multi-item list with stable IDs and PATCH updates (parity with observations); bump OpenAPI v2.0.0, SEMANTIC_LAYER_API v4.0.0, AGENT_MEMORY v2.0.0.**
- Bump operations OpenAPI spec version to v2.0.0 to reflect breaking agent memory changes.
- Validate `lap_index` route param before casting to int in workout lap detail endpoint.
- Add healthcheck and agent write endpoints to the GPT-facing OpenAPI spec.
- Allow preference/observation updates in GPT docs; bump instruction and actions guide versions.
- Clarify observation discretion vs preference confirmation in GPT docs; bump versions.
- Clarify that runtime context requires calling agent/planning endpoints at conversation start.
- Add a conversation-start checklist to GPT Actions guide and mirror runtime context note in GPT OpenAPI spec.
- Fix GPT Actions guide list formatting and bump version.
- Fix GPT Actions guide ordered list numbering and bump version.
- Align agent memory, instructions, and actions guide; add epistemic/temporal rules to actions guide; standardize ordered list numbering style; bump doc versions.
- Deduplicate behavioral rules into INSTRUCTIONS and keep GPT Actions guide focused on operational API usage; bump doc versions.
- Streamline INSTRUCTIONS to remove operational checklists and endpoint ordering in favor of GPT Actions guide; bump version.
- Clarify ChatGPT-facing vs admin endpoints in semantic layer API and move parameter defaults to the API contract; bump versions.
- Remove duplicated agent memory API details from semantic layer API, move usage example to GPT Actions guide, and align memory call-order references; bump doc versions.
- Move ChatGPT integration examples out of semantic layer API into GPT Actions guide; add references and bump doc versions.
- Merge usage pattern into integration examples in GPT Actions guide to remove duplication; bump version.
- Remove duplicate memory contract walkthrough from WORKOUT_INTELLIGENCE_AGENT_VISION; replace with pointer to GPT Actions guide and Agent Memory; bump version to 1.5.1.
- Remove duplicate usage pattern and example flow from AGENT_MEMORY; add reference to GPT Actions guide for operational usage; bump version to 1.2.0.
- Add docs/README.md to provide file organization overview and usage notes for Custom GPTs and developers; maintain flat structure for GPT compatibility.
- Remove redundant Knowledge References sections from GPT_ACTIONS_GUIDE and INSTRUCTIONS; bump versions to 3.4.3 and 4.1.4.
- **Reorganize documentation into gpt/ and devops/ folders; split SEMANTIC_LAYER_API.md into GPT version (3.0.0) and OPERATIONS_API.md (1.0.0) to mirror openapi.yaml vs openapi.operations.yaml split; move context files to gpt/context/ subfolder; update README.md with new structure.**
- Fix cross-references in DEPLOYMENT.md to reference gpt/ folder files; add version 1.0.1 to DEPLOYMENT.md.
- Align SEMANTIC_LAYER_API.md with agent memory POST/PATCH endpoints; bump version to 3.0.1.
- Format agent memory endpoints in SEMANTIC_LAYER_API.md to match workout example structure; bump version to 3.0.2.
- Align agent memory examples in SEMANTIC_LAYER_API.md with OpenAPI schemas; bump version to 3.0.3.

## 2026-02-10

- Split OpenAPI spec into semantic (read) and operations (admin/write) to stay under 30-operation ChatGPT Actions limit.
- Skip dependency warmup during pytest, avoid blob container creation in tests that instantiate storage, and keep integration tests opt-in via env flags.
- Store lap summaries in a WorkoutLaps table and per-lap record blobs with ordered record indices; bump ingest version to v3.1.0.
- Standardize stored timestamps on ISO 8601 UTC offsets (no trailing Z).
- Prefer Activity local time vs UTC timestamp when inferring FIT timezones; keep raw local values for inference.
- Bump ingest version to v3.0.8.

## 2026-02-09

- Normalize FIT timestamps to UTC and infer timezone offsets; bump ingest version to v3.0.6.
- Include the config package in Azure Functions deployments to resolve missing module errors.
- Move OneDrive sync orchestration into `OneDriveSyncHandler` and slim the ingestion handler to single-file work.
- Rename ingestion base and OneDrive sync classes for clearer hierarchy.
- Make OneDrive sync a concrete ingestion handler; bump ingest version to v3.0.5.
- Remove redundant bytes handler in favor of base ingestion; bump ingest version to v3.0.4.
- Centralize bytes ingestion in the base handler; bump ingest version to v3.0.3.
- Simplify OneDrive sync ingestion wiring; bump ingest version to v3.0.2.
- Ingest OneDrive FIT bytes directly without base64 payloads or temp files.
- Allow FitParser/FitAdapter to parse in-memory FIT bytes; bump ingest version to v3.0.1.
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
