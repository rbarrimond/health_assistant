# Changelog

Change history for the Health Assistant / Workout Intelligence Agent system. Entries include component changes and explicit SemVer bumps when applicable.

**Format conventions:**

- **BREAKING:** prefix denotes backward-incompatible changes
- Version bumps noted as: `[component vX.Y.Z]`
- Related changes grouped under common themes

## 2026-02-23

### Observability & Telemetry

- Add structured JSON logging bootstrap for Azure Functions with env-driven `LOG_LEVEL` / `LOG_FORMAT` configuration
- Add endpoint lifecycle structured events (`endpoint.success`, `endpoint.bad_request`, `endpoint.not_found`, `endpoint.error`) with `operation_id` and `correlation_id`
- Propagate correlation headers on HTTP responses using `traceparent` + `x-correlation-id` fallback behavior
- Add structured timer trigger events for OneDrive sync lifecycle (`timer.past_due`, `timer.success`, `timer.warning`, `timer.error`, `timer.completed`)

### Ingestion Identity Simplification

- **BREAKING:** Remove `IngestionIdentityPolicy`; concrete ingestion handlers now compute `ingestion_id` from source context (`source_item_id` then `file_sha256`) `[ingest v13.0.0]`
- **BREAKING:** Enforce semantic-only `workout_id` with no fallback; ingestion fails when semantic identity cannot be computed `[INGESTION_SCHEMA v15.0.0, ingest v13.0.0]`
- Use `ingestion_id` as the only ingestion state key source in shared idempotency context
- Treat missing OneDrive `source_item_id` as catastrophic (no `file_sha256` fallback) `[INGESTION_SCHEMA v15.0.1, ingest v13.0.1]`
- Raise typed ingestion identity exceptions for ID resolution/calculation failures `[ingest v13.0.2]`
- Map typed ID failures to explicit ingestion handler `error_code` responses (`INGESTION_ID_RESOLUTION_FAILED`, `WORKOUT_ID_CALCULATION_FAILED`) `[ingest v13.0.3]`
- Centralize typed exception-to-response serialization in exception classes for consistent OOP handler contracts `[ingest v13.0.4]`

### Semantic Workout ID Fallback Hardening

- Fix semantic `workout_id` calculation to prefer Session `sport` with File ID `type` as fallback, avoiding false failures when `file_id` is missing `[ingest v13.0.5, INGESTION_SCHEMA v15.0.2]`
- Add precise start-time fallback to Session `timestamp` when Session `start_time` is unavailable, preserving deterministic semantic ID generation `[ingest v13.0.5]`
- Add HealthFit semantic sport fallback from filename activity token for OneDrive files missing FIT sport fields, reducing `WORKOUT_ID_CALCULATION_FAILED` on historical exports `[ingest v13.0.6, INGESTION_SCHEMA v15.0.3]`

### Two-ID Identity Model

- **BREAKING:** Enforce two-ID ingestion identity model: only `ingestion_id` (source-scoped idempotency key) and `workout_id` (semantic stable identity) are persisted for ingestion identity `[ingest v13.0.7, INGESTION_SCHEMA v15.0.4]`
- Remove persisted `stable_workout_id` and separate `semantic_workout_id` storage fields from Workouts/IngestionState entity contracts; semantic identity now exists only as the computation that produces `workout_id` `[ingest v13.0.7]`

## 2026-02-22

### Ingestion Schema & Instructions

- Move changelog to docs/ and generalize scope; update cross-references `[INGESTION_SCHEMA v13.0.1]`
- Streamline copilot instructions to numbered outline with doc authority and non-recursive edit guardrail
- Add OOP/OOAD preference to architectural discipline guidance

### Ingestion Identity

- **BREAKING:** Split stable workout identity from ingestion idempotency; add ingestion_id storage and keep workout_id as stable client identifier `[INGESTION_SCHEMA v14.0.0, ingest v12.0.0, WORKOUT_SCHEMA v11.0.0]`

### Type Safety

- Add precise type overloads for `build_raw_fit()` to narrow return types based on flags

## 2026-02-21

### Semantic Workout IDs & Start Time Resolution

- Add precise start time resolution (event → session → filename → record) and semantic workout IDs derived from start_time_utc_precise + sport
- Persist semantic_workout_id in Workouts and include start_time_utc_precise in canonical metadata `[ingest v11.1.0, schema 11.1.0]`

### FIT Field Schema Enforcement

- Enforce FIT field schema list by removing non-listed lookups (drops `enhanced_speed`, `enhanced_altitude`, `respiration_rate`)
- Remove `indoor` and `time_zone` lookups; stop using file_id `number` for activity IDs `[ingest v10.0.10]`
- Remove fallback to non-existent `timezone_offset` in device settings (FIT profile only defines `utc_offset`) `[ingest v10.0.9]`

### Workout Name Extraction

- Simplify workout name extraction to use only reliable sources: API-provided names and FIT metadata (sport-subsport-activityID)
- Remove unused fallback methods (`_get_activity_workout_name()`, `_get_session_workout_name()`, `_get_filename_stem_workout_name()`) `[ingest v10.0.8]`
- Prioritize Garmin Connect API `activityName` in workout name extraction `[ingest v10.0.7]`

### HRV Processing

- Restore HRV RR interval indexing from HRV messages (type 78) using `time` field with millisecond-to-seconds conversion `[ingest v10.0.11]`
- Fix HRV RR interval processing for Garmin: remove fallback to non-existent `rr_interval` field, add `fallback=None` to `get_value()` calls, improve Garmin HRV documentation `[ingest v10.0.6]`

## 2026-02-20

### Canonical Data Architecture Refactor

- **BREAKING:** Remove `parse()` method and metric computation (~536 lines) from FitParser to enforce "Canonical Parquet as single source of truth"
- FitParser now pure artifact extractor; all metrics computed in `CanonicalAnalyticsEngine.from_dataframe()` at read time
- Enables recomputability without re-ingestion `[ingest v9.0.0]`
- **BREAKING:** Remove canonical laps parquet and `canonical_laps_blob` from Workouts; laps now in `laps.json` only `[ingest v10.0.0, schema 7.0.0]`
- **BREAKING:** Remove FitAdapter and legacy workout models; load FIT via fitdecode directly `[ingest v8.0.0, schema 6.0.0]`
- Remove WorkoutLaps table storage and legacy per-lap record blobs

### FIT Parsing Optimizations

- Add message-type index in FitParser for faster metadata/lap/timezone lookups
- Remove `fit_message_utils` wrapper; call fitdecode directly
- Remove FitParser message/field wrappers; use fitdecode `get_value()`/`get_raw_value()` directly `[ingest v9.0.2]`
- Stop slicing per-lap record payloads; laps.json remains pure lap-message artifact

### Canonical Telemetry & Metadata

- Populate extended canonical telemetry (temperature, respiration, left/right balance); RR interval from HRV messages only `[ingest v10.0.2]`
- Restore Apple workout type extraction in canonical session metadata `[ingest v10.0.3]`
- Use FIT file_id "number" for activity ID with safe field access `[ingest v10.0.4]`
- Standardize FIT field access on `get_value()` and `local_timestamp` for activity local time `[ingest v10.0.5]`
- Add versioned constants for ingestion artifacts; store laps.json uncompressed `[ingest v7.2.0, schema 5.2.0]`

### Activity Name Extraction

- Enhance FIT activity name extraction with priority-based resolution: activity message → sport-subsport → activity ID → filename
- Add `source_activity_name` parameter for API names; persist in IngestionState `[ingest v7.1.0]`

### Garmin Ingestion Fixes

- Fix Garmin FIT file ingestion with proper ZIP/gzip format detection and extraction
- Refactor `download_activity_fit()` into helper methods for testability `[ingest v7.0.1]`
- Add Garmin near-duplicate detection by start-time/duration window
- Compute FIT SHA-256 before idempotency checks

### Source Classification & Developer Fields

- Add normalized source classification (`normalized_source_system`) using device/manufacturer heuristics
- Add FIT structural analyzer with deterministic output (`fit_analysis.json` v1.0.0)
- Add optional developer-field summary via `developer_fields=true` query param

## 2026-02-19

### FIT Protocol Mappings

- Add FIT protocol manufacturer and product code mappings from fitdecode SDK v21.171 (330+ manufacturer codes, Garmin/Favero/Apple models) `[schema 5.1.0]`
- Update `config/README.md` for application-level constants documentation

## 2026-02-18

### FIT Parser Migration & Storage Consolidation

- Migrate FIT ingestion to fitdecode with compatibility shim
- Consolidate blob storage into `workouts` container with canonical artifact writes (raw FIT, metadata, laps, analysis)
- Add `canonical_schema_version` to Workouts `[ingest v6.0.0, schema 5.0.0]`

## 2026-02-17

### Canonical Analytics & Model Refactor

- Fold canonical analytics into `WorkoutMetricsModel` with compositional submodels (training load, power-duration anchors, envelope scores, variability, durability)
- Add `WorkoutMetricsModel.from_canonical()` classmethod with in-memory caching
- Rename `CanonicalWorkoutMetrics` to `CanonicalAnalyticsEngine` (clarity) `[WORKOUT_SCHEMA v10.0.0]`
- Split monolithic `FitParser/models.py` (2311 lines) into multi-file package: `core.py`, `constants.py`, `substrate.py`, `legacy.py`, `agent.py`, `metrics/*` `[ingest v4.1.1, schema 4.1.1]`
- Fix semantic layer tests with correct mock usage

## 2026-02-15

### Ingestion Idempotency

- Treat unchanged skipped ingestions as terminal; preserve `ingested_at_utc` `[ingest v3.1.1, schema 3.1.1]`

## 2026-02-16

### Canonical Analytics Surface Expansion

- Expand Canonical Analytics Surface with core vs extended telemetry, nullability guidance, HRV RR-interval notes `[v1.1.0]`
- Extend CanonicalRecord with extended telemetry; preserve sparse RR intervals during 1 Hz resampling
- Add canonical FIT parquet substrate + lap parquet storage `[ingest v4.0.0, WORKOUT_SCHEMA v7.0.0]`
- Store activity local timestamps without UTC conversion; rename to `activity_local_time`

### Schema Cleanup & Separation

- Remove redundant metadata fields (`file_type`, `event_count`, `event_types`, `end_time_utc`)
- Split logical workout schema from operational storage; move storage layout to ingestion schema `[WORKOUT_SCHEMA v8.0.0, schema 4.1.0, SEMANTIC_LAYER_API v5.0.0, GPT OpenAPI v2.1.0]`
- Trim workout device fields to `device_name` only `[WORKOUT_SCHEMA v9.0.0, SEMANTIC_LAYER_API v6.0.0, GPT OpenAPI v3.0.0]`

### CanonicalWorkoutMetrics Evolution

- Refactor to own canonical DataFrame instead of record list
- Add power curve helper and `power_curve_watts` computed field
- Expand to full Canonical Analytics Surface with 1 Hz resampling, Coggan normalized power, anchor/envelope/variability/durability
- Standardize FTP naming to `ftp_watts`
- Rewrite to compute directly from DataFrame with vectorized pandas (remove metric-routing lookups)
- Remove unused legacy helper methods
- Add explicit `resample=True` flag for automatic resampling

## 2026-02-14

### Documentation Reorganization & API Cleanup

- **BREAKING:** Reorganize docs into gpt/ and devops/ folders; split SEMANTIC_LAYER_API into GPT (v3.0.0) and OPERATIONS_API (v1.0.0) to mirror openapi split
- Add docs/README.md with file organization overview
- Secure agent memory read endpoints with function key requirement
- **BREAKING:** Refactor agent preferences to multi-item list with stable IDs and PATCH updates `[OpenAPI v2.0.0, SEMANTIC_LAYER_API v4.0.0, AGENT_MEMORY v2.0.0]`

### GPT Actions & Instructions

- Align GPT Actions guide with read-only scope; remove physiometrics update examples `[GPT Actions v3.5.0-3.7.0]`
- Tighten guide to require initial context calls before natural-language response
- Deduplicate behavioral rules into INSTRUCTIONS
- Clarify observation discretion vs preference confirmation `[INSTRUCTIONS v4.1.4]`

### API Endpoints

- Document operations-spec endpoints (healthcheck, agent memory, Withings auth/callback) `[OPERATIONS_API v1.1.0]`
- Add healthcheck and agent write endpoints to GPT-facing OpenAPI
- Validate `lap_index` route param before int cast

## 2026-02-10

### OpenAPI & Testing

- Split OpenAPI spec into semantic (read) and operations (admin/write) for ChatGPT 30-operation limit
- Skip dependency warmup during pytest; keep integration tests opt-in via env flags

### Storage & Timestamps

- Store lap summaries in WorkoutLaps table with per-lap record blobs `[ingest v3.1.0]`
- Standardize stored timestamps on ISO 8601 UTC offsets (no trailing Z)
- Prefer activity local time vs UTC for FIT timezone inference `[ingest v3.0.8]`

## 2026-02-09

### Ingestion Handler Refactor

- **BREAKING:** Refactor FIT ingestion handlers under abstract base; remove FitUploadHandler `[ingest v3.0.0]`
- Move OneDrive sync orchestration into `OneDriveSyncHandler`; consolidate bytes ingestion `[ingest v3.0.1-v3.0.5]`
- Ingest OneDrive FIT bytes directly without base64 payloads or temp files
- Allow FitParser to parse in-memory bytes

### Timezone & Deployment

- Normalize FIT timestamps to UTC; infer timezone offsets `[ingest v3.0.6]`
- Include config package in Azure Functions deployments

## 2026-02-08

### Schema & API Alignment

- Fix OpenAPI nullability schema; refactor ingestion state preservation
- Align workout list endpoint filters with semantic layer `[ingest v2.3.1]`
- Expand OpenAPI workout fields; document plugin/asset endpoints

### Workout Metadata & Idempotency

- Remove file provenance from Workouts; keep source filename/drive ID in IngestionState
- Resolve workout names from FIT session_name; resolve Apple workout types from workout_name
- Reuse existing workout_id from ingestion state `[ingest v2.3.0]`
- Prefer file SHA over OneDrive etag for unchanged detection
- Store OneDrive cTag/quickXor/modified timestamp in IngestionState; guard sync idempotency checks `[ingest v2.2.4-v2.2.7]`

## 2026-02-07

### Ingestion State Separation

- **BREAKING:** Move ingestion metadata (`ingest_version`, `ingested_at_utc`) from Workouts to IngestionState `[ingest v2.0.0]`
- Remove ingestion timestamps from semantic workout payloads
- Add backfill script for IngestionState metadata

### Schema Simplification & Timezone Handling

- Exclude Azure Table system metadata from Workouts metrics
- Stop storing minute-based zone fields; derive from seconds at read time
- Store low aerobic/intensity metrics in seconds only
- Respect FIT timezone names or device UTC offsets

### Development & Idempotency

- Add optional runtime chaos injection via `sitecustomize` for local testing
- Skip ingestion when OneDrive etag/file hash unchanged; record `skipped` status `[ingest v2.2.2]`
