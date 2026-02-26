# Changelog

Change history for the Health Assistant / Workout Intelligence Agent system. Entries include component changes and explicit SemVer bumps when applicable.

**Format conventions:**

- **BREAKING:** prefix denotes backward-incompatible changes
- Version bumps noted as: `[component vX.Y.Z]`
- Related changes grouped under common themes

## 2026-02-26

### Payload Source Normalization

- Force `PayloadFitModel.normalized_source_system` to always emit `HTTP`, ignoring optional caller-provided `source_system` metadata for direct payload ingests `[ingest v13.0.29, INGESTION_SCHEMA v15.0.30]`.

### Timezone Contract Clarification (Semantic vs Metadata)

- Clarify semantic-layer timezone field contract: expose both `local_tz_offset` and `timezone` in workout summaries/details, with `local_tz_offset` designated for GPT/client local-time display and `timezone` reserved for metadata context.
- Update OpenAPI schemas to document the split semantics and include `local_tz_offset` explicitly in `WorkoutSummary` for both semantic and operations specs `[openapi.yaml v3.0.1, openapi.operations.yaml v2.0.2]`.
- Align schema documentation wording across semantic and ingestion docs, including canonical schema registry correction to `CANONICAL_SCHEMA_VERSION=1.4.0` `[WORKOUT_SCHEMA v11.1.2, SEMANTIC_LAYER_API v6.0.1, INGESTION_SCHEMA v15.0.29]`.

### BaseFitModel Interface Tightening

- **BREAKING:** Move FIT source inputs (`file_bytes`, `source_metadata`) into constructor-owned private model state in `BaseFitModel`, enforcing fail-fast eager initialization semantics at construction time
- **BREAKING:** Remove `start_time_utc_precise` compatibility alias fallback from workout storage partition key derivation; `start_time_utc` is now the sole canonical partition timestamp source
- Update timezone semantics so `timezone` prefers a valid IANA name and falls back to `local_tz_offset` (UTC offset string) when IANA metadata is unavailable or invalid
- Refactor semantic/core projections to consume `local_tz_offset` directly rather than alias fallback reads from `timezone` `[ingest v13.0.28, INGESTION_SCHEMA v15.0.28]`

### FIT Semantic Streamlining

- Normalize FIT device product identity using Garmin `garmin_product` preference and emit canonical `product_id` in metadata, preventing downstream reliance on vendor-prefixed fields
- Ignore FIT epoch `activity.local_timestamp` values for timezone inference and route HealthFit filename offsets through base fallback hooks
- Emit UTC timestamps with explicit offsets (no trailing `Z`) for `start_time_utc`, `file_time_created_utc`, and `activity_timestamp_utc`
- Consolidate Apple workout type and timezone resolution via source-specific hooks in `BaseFitModel`, removing duplicate subclass overrides `[ingest v13.0.27, INGESTION_SCHEMA v15.0.27]`

### RR Intervals Multi-Value Support

- **BREAKING:** Change `CanonicalRecord.rr_interval_sec` field from `Optional[float]` (scalar) to `rr_intervals_sec: Tuple[float, ...]` (immutable tuple) to support multiple RR intervals per 1 Hz record—essential for accurate HRV representation grouped by canonical time grid per [RR_Intervals_Canonical_State_Specification](docs/devops/data_architecture/RR_Intervals_Canonical_State_Specification.md); implement order-preserving HRV grouper in `CanonicalRecordSet._build_hrv_interval_map()` supporting both timestamped (FIT spec Mode 1) and un-timestamped (Mode 2) HRV messages; update `CanonicalAnalyticsEngine._resample_to_1hz()` to concatenate RR interval tuples (not `.first()`) for multi-record resampling windows; add `@field_validator("rr_intervals_sec")` to enforce tuple type and non-negative constraints `[CANONICAL_SCHEMA v1.4.0, INGESTION_SCHEMA v15.0.26]`

### Aerobic Decoupling Sign Correction

- Fix aerobic decoupling formula to invert efficiency ratio from `((EF_second / EF_first) - 1) * 100` to `((EF_first / EF_second) - 1) * 100` to correctly produce positive values for fatigue/aerobic stress (bugfix aligns code with advertised contract) `[INGESTION_SCHEMA v15.0.25, CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT already versioned]`

## 2026-02-25

### Ingestion Documentation Alignment

- Move ingestion schema documentation under data architecture and update cross-references across docs, clarifying `ingestion_id` as the source-system identity and `workout_id` as semantic identity; document the current storage-path mismatch and planned refactor `[INGESTION_SCHEMA v15.0.24, CANONICAL_DATA_ARCHITECTURE v2.2.2]`

### Analytics Surface Clarification

- Clarify `laps.json` as the pass-through representation used for interval semantics, reserve `intervals.json` for future workout/workout_step carryover, and note Zwift/Strava behavior; add data architecture index section to docs overview `[CANONICAL_ANALYTICS_SURFACE v1.1.2]`

### Canonical Analytics Ownership

- Explicitly document `CanonicalAnalyticsEngine` as the sole read-time computation layer for derived analytics (including zones) and align canonical data architecture + workout schema phrasing with that contract `[CANONICAL_ANALYTICS_SURFACE v1.1.3, CANONICAL_DATA_ARCHITECTURE v2.2.3, WORKOUT_SCHEMA v11.1.1]`

### Semantic Layer Canonical Routing

- Route semantic-layer canonical fallback computation through `CanonicalAnalyticsEngine` to remove duplicate zone/enhanced analytics calculations outside the engine (behavior aligned with documentation; no schema changes)

### API Documentation Clarity

- Update API specifications (`openapi.yaml`, `openapi.operations.yaml`) to clarify that zones and enhanced analytics are computed at read-time from canonical substrate using deterministic `CanonicalAnalyticsEngine`
- Expand `ZoneDistribution` schema with detailed field descriptions (z1-z5 minutes, percentages, query_window structure)
- Expand `EfficiencyTrends` schema with detailed field descriptions (decoupling_pct, hr_drift_bpm, ef_overall, samples structure)
- Update API preambles to explicitly state read-time computation model and deterministic behavior

### API Schema Ownership Cleanup

- Remove unused `ZoneDistribution` and `EfficiencyTrends` schemas from `openapi.operations.yaml` (these schemas are only used by semantic endpoints in `openapi.yaml`)
- Update `api_docs/README.md` to clarify that the two OpenAPI specs are independent with minimal overlap (only `/api/health` endpoint appears in both)
- Document that schemas are maintained only in specs where they're actually used, eliminating unnecessary duplication `[openapi.operations.yaml v2.0.1]`

### FIT Date-Time Normalization Removal

- Remove superfluous FIT `date_time` normalization/coercion in `BaseFitModel` timestamp paths (start-time derivation, record timestamp handling, metadata timestamp serialization, and HealthFit FIT-message start extraction), preserving decoded timezone awareness as provided by fitdecode; add explicit consistent-awareness validation for record timestamp ordering `[ingest v13.0.26, INGESTION_SCHEMA v15.0.23]`

### Ingestion Utility Extraction

- Move numeric coercion helper from `BaseFitModel._coerce_float` into shared ingestion utility module (`TrainingAnalyticsPlatform/ingestion/value_utils.py`) and route canonical record coercion through `coerce_float`; no runtime behavior change.

### BaseFitModel Eager FIT Initialization

- Parse and index FIT data messages during `BaseFitModel` instantiation instead of lazy access-time loading, and remove lazy-loading internals (`_messages_loaded`, `_load_fit_messages`, `_ensure_message_index`) from FIT model state/flow `[ingest v13.0.25, INGESTION_SCHEMA v15.0.22]`

### Semantic FIT Validation Gate

- Enforce explicit semantic FIT validation before ingestion artifact generation via `BaseFitModel.validate_semantic_contract()` (exactly one `file_id`, `file_id.type == activity`, required `session` and `record` messages, non-negative `session.total_elapsed_time`, monotonic `record.timestamp`, and `activity.num_sessions` consistency when present) `[ingest v13.0.24, INGESTION_SCHEMA v15.0.21]`
- Require semantic identity inputs to be FIT-derived and validated before `workout_id` computation in shared ingestion flow (`FitIngestionBaseHandler._parse_and_store`) `[ingest v13.0.24]`

## 2026-02-24

### Garmin Sync Duration Type Narrowing

- Harden `GarminSyncDeduplicator._is_within_duration_tolerance` by narrowing `duration_sec` entity values before float coercion, resolving strict type-checker `Unknown | None` conversion errors without behavior changes.

### FIT Record Accessor Cleanup

- Remove redundant `BaseFitModel._get_record_value` helper and inline direct `FitDataMessage.get_value(..., fallback=None)` calls in canonical record extraction; no runtime behavior change.

### Fitdecode Import Cleanup

- Replace module-qualified `fitdecode.*` usage in FIT models with explicit symbol imports (`FitReader`, `FitDataMessage`, and processors) for cleaner typing and improved class readability; no runtime behavior change.

### BaseFitModel Serialization Hygiene

- Exclude `BaseFitModel.file_bytes` from Pydantic serialization output via field config (`exclude=True`) to prevent raw FIT payload bytes from appearing in model dumps.

### BaseFitModel Shim Organization

- Move `BaseFitModel._metadata_dict` to a dedicated bottom-of-class type-checker shim section to keep core ingestion/domain logic grouped first; no runtime behavior change.

### BaseFitModel Lazy Private State Annotations

- Refactor `BaseFitModel` FIT cache internals to explicit Pydantic `PrivateAttr` fields (`_messages`, message indexes, and core cached messages), replacing implicit mutable class defaults and manual `object.__setattr__` initialization in `__init__` `[ingest v13.0.23]`
- Fix RR interval lazy-index guard so HRV index construction now reliably triggers message lazy-load before iterating HRV frames `[ingest v13.0.23]`

### Strict FIT Sport Validation

- Treat missing FIT sport (`sport` message / session `sport`) as a catastrophic parse failure by raising `FitParsingError` (`FIT_PARSING_FAILED`) in base model semantics `[ingest v13.0.22]`
- Remove HealthFit filename-derived semantic sport fallback; semantic identity now requires FIT-native sport signals only `[ingest v13.0.22, INGESTION_SCHEMA v15.0.18]`

### Workout Name Semantic Normalization

- Remove redundant `sport_name` and `sub_sport_name` computed fields from FIT models; canonical semantics now use normalized `sport` and `sub_sport` only `[ingest v13.0.21]`
- Update constructed workout-name fallback to `"<sport>-<sub_sport>-<local_start_datetime>"` (normalized lowercase), dropping legacy `file_id.type`-driven name fallback behavior in this path `[ingest v13.0.21, INGESTION_SCHEMA v15.0.17]`

### FIT Parsing Domain Error Mapping

- Replace generic `RuntimeError` FIT parse wrapper with typed `FitParsingError` domain exception and preserve explicit exception chaining from fitdecode parse failures `[ingest v13.0.20]`
- Map malformed/unparseable FIT payload failures to explicit `FIT_PARSING_FAILED` handler responses (HTTP 422) across payload, OneDrive, and Garmin ingestion paths `[ingest v13.0.20, INGESTION_SCHEMA v15.0.16]`

## 2026-02-23

### Session UTC Start-Time Math

- Derive session-based canonical UTC start as `session.timestamp - session.total_elapsed_time`; stop treating FIT session `start_time` (local wall-clock) as UTC for semantic identity computation `[ingest v13.0.19, INGESTION_SCHEMA v15.0.15]`

### FIT Start-Time Validity Enforcement

- Enforce strict FIT-derived `start_time_utc` contract for semantic identity; remove source-specific filename local-time fallback from canonical start-time resolution `[ingest v13.0.18, INGESTION_SCHEMA v15.0.14]`
- Treat FIT files with no usable FIT-derived start timestamp as invalid for semantic `workout_id` and reject ingestion rather than fabricating UTC start time from local filename text `[ingest v13.0.18]`

### Local Timezone Offset Semantics

- Add canonical `local_tz_offset` metadata to represent local wall-clock UTC offset (for example `UTC-05:00`) while preserving UTC storage for `start_time_utc` `[ingest v13.0.17, INGESTION_SCHEMA v15.0.12, WORKOUT_SCHEMA v11.1.0]`
- Retain `timezone` as a backward-compatible alias of `local_tz_offset` in ingestion, semantic projections, and session models `[ingest v13.0.17]`
- Remove implicit unknown->`UTC` defaulting in timezone resolution; unresolved local offsets now remain unset (`null`) `[ingest v13.0.17]`
- Bump Workouts canonical schema to `1.3.0` for the new canonical metadata field `[ingest v13.0.17]`

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

### Workout Name Construction

- Improve Workout FIT message name extraction by reading `wkt_name` with `name` compatibility fallback `[ingest v13.0.8]`
- Add constructed workout-name fallback `"<Daypart> <Apple Workout Type>"` when explicit names are unavailable and Apple type can be inferred from FIT sport/sub-sport `[ingest v13.0.8]`
- Fallback to `"<sport_name>-<sub_sport_name>-<local_start_datetime>"` when Apple workout type is unavailable `[ingest v13.0.8, INGESTION_SCHEMA v15.0.5]`
- Enforce deterministic HealthFit `apple_workout_type` from filename activity token only (no FIT sport/sub-sport inference fallback for HealthFit sources) `[ingest v13.0.9]`
- Restrict `AppleWorkoutTypeResolver` to FIT `sport`/`sub_sport` mapping only; move name-token mapping to source-specific path used by `HealthFitModel` filename semantics `[ingest v13.0.10, INGESTION_SCHEMA v15.0.6]`
- Map FIT `cycling` + `virtual_cycling` (e.g., Zwift exports) to Apple `Indoor Cycle` in `AppleWorkoutTypeResolver` `[ingest v13.0.11, INGESTION_SCHEMA v15.0.7]`
- Correct virtual sub-sport handling to map FIT `virtual_activity` by sport: `cycling -> Indoor Cycle`, `running -> Indoor Run`, `walking -> Indoor Walk` `[ingest v13.0.12, INGESTION_SCHEMA v15.0.8]`
- Remove unsupported `virtual_cycling` mapping to align strictly with fitdecode profile enums `[ingest v13.0.13, INGESTION_SCHEMA v15.0.9]`
- Refactor `HealthFitModel.apple_workout_type` to resolve directly from HealthFit filename activity token inside `HealthFitModel` (source-owned semantics), removing shared name-resolver dependency from this path `[ingest v13.0.14]`
- Clarify and align HealthFit filename datetime contract: `YYYY-MM-DD-HHMMSS` is recording-device local time (not UTC), and source-specific UTC extraction converts from that local value `[ingest v13.0.15, INGESTION_SCHEMA v15.0.10]`

### Start Time, Timezone, and Partitioning Alignment

- Canonicalize `start_time_utc` to use the full deterministic fallback chain (event → session → source-specific UTC → first record) and align semantic `workout_id` generation to this canonical field `[ingest v13.0.16, INGESTION_SCHEMA v15.0.11]`
- Keep `start_time_utc_precise` as compatibility alias only; stop persisting it in new canonical workout metadata writes `[ingest v13.0.16]`
- Harden HealthFit filename timezone fallback to compare filename local time against FIT-message UTC evidence (event/session/record), avoiding circular UTC collapse from source-specific fallback paths `[ingest v13.0.16]`
- Bump Workouts canonical schema to `1.2.0` and align PartitionKey derivation with canonical start time (with legacy precise fallback support for compatibility) `[ingest v13.0.16]`

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
