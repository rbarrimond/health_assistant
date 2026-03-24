# Changelog

Change history for the Health Assistant / Workout Intelligence Agent system. Entries include component changes and explicit SemVer bumps when applicable.

**Format conventions:**

- **BREAKING:** prefix denotes backward-incompatible changes
- Version bumps noted as: `[component vX.Y.Z]`
- Related changes grouped under common themes

## 2026-03-23

### Garmin Force Re-Ingestion Semantics Alignment [application v3.10.0, ingestion v15.6.0, operations API v4.5.0]

- **Changed (force contract)**: `POST /api/garmin/sync` with `force=true` now bypasses both activity-id prefilter skipping and unchanged-content skip gating during FIT ingestion, ensuring forced activities continue through parse/store.
- **Changed (persisted semantics)**: successful forced reprocessing now writes a fresh `ingested_at_utc` in `IngestionState` because ingestion no longer short-circuits on unchanged-content when force is enabled.
- **Updated (operations contract docs)**: `api_docs/openapi.operations.yaml` updated to describe force behavior as bypassing both activity-id prefilter and unchanged-content skip checks.
- **Updated (backend docs)**: `docs/devops/BACKENDS.md` now documents forced skip-bypass behavior and `ingested_at_utc` refresh semantics for successful forced re-ingestion.

### Canonical Metadata Schema Version Emission Alignment [application v3.9.7, ingestion v15.5.1]

- **Fixed**: canonical `metadata.json` now explicitly emits top-level `metadata_schema_version` from canonical schema constant (`2.4.0`) in `build_canonical_metadata()`.
- **Changed**: split schema constants into `CANONICAL_METADATA_SCHEMA_VERSION` (canonical metadata blob contract) and `METADATA_MESSAGES_SCHEMA_VERSION` (raw FIT metadata-messages artifact) to remove ambiguity.
- **Preserved**: canonical enrichment payload semantics are unchanged; this patch aligns runtime metadata version signaling with documented contract.

### Canonical Garmin Workout Enrichment Promotion [application v3.9.6, ingestion v15.5.0]

- **Added**: Garmin list-derived activity-scoped enrichment promotion into canonical metadata `enrichment` zone for training load/effect, VO2max, cycling cadence, running cadence, left-balance, respiration, and temperature fields when present in Garmin activity-list payloads.
- **Added**: explicit provenance markers in enrichment for promoted Garmin list fields: `garmin_enrichment_source="activity_list"` and `garmin_enrichment_scope="activity"`.
- **Preserved**: physiometrics ownership boundaries for daily training state/load focus remain unchanged (no overlap introduced with workout ingestion metadata).
- **Preserved**: FIT ingestion, duplicate detection, and source filtration workflow are unchanged.

### Garmin Pre-Download Manufacturer Pre-Filter [application v3.9.5, ingestion v15.4.0]

- **Added**: pre-download manufacturer pre-filter in `GarminSyncIngestionHandler.handle()` — if the cached Garmin list `source_manufacturer_code` is non-None and not in `GARMIN_API_ALLOWED_MANUFACTURERS`, the activity is rejected and recorded as `filtered` before the FIT file download is attempted, saving unnecessary bandwidth and parsing work.
- **Scope**: only activates when the cached code is confidently resolved (non-None); activities with an absent or unresolvable manufacturer fall through to the existing post-parse FIT-based filter, preserving the existing behavior for those cases.

### Garmin Manufacturer Equivalence Validation [application v3.9.4]

- **Added**: shared manufacturer normalization helper so Garmin list payloads and FIT `file_id.manufacturer` resolve through the same canonical code-mapping path.
- **Added**: Garmin activity contract now exposes cached list-side `manufacturer`, normalized `source_manufacturer_code`, and `deviceId` for downstream validation and future prefilter work.
- **Added**: non-blocking Garmin ingestion validation that logs mismatches between cached list manufacturer code and FIT manufacturer code while preserving FIT-derived allowlist enforcement.
- **Added**: storage audit script `scripts/validate_garmin_manufacturer_equivalence.py` to measure normalized-code equivalence over indexed Garmin activities already ingested.
- **Fixed**: stale Zwift documentation references updated from manufacturer code `263` to the actual allowlisted FIT code `260`.

### Garmin Normalization Drift Warnings [application v3.9.3]

- **Added**: non-fatal normalization drift reporting methods in `GarminActivityContract` for missing required core fields, unknown activity types, and unmapped interesting payload fields.
- **Changed**: Garmin sync ingestion now emits structured warning logs for normalization drift while continuing ingestion (no fail-fast behavior introduced).
- **Added**: regression coverage for drift-reporting helpers to preserve constitutional observability guarantees.
- **Preserved**: ingestion idempotency, FIT retrieval/parsing workflow, and workout persistence semantics remain unchanged.

### Garmin Typed Activity Normalization Contract [application v3.9.2]

- **Added**: typed Garmin activity-list normalization contract in `TrainingAnalyticsPlatform/integrations/garmin_activity_contract.py` with explicit core/common/type-specific alias tiers.
- **Changed**: Garmin sync ingestion handler now resolves source metadata through the shared typed contract rather than embedded ad-hoc alias maps.
- **Added**: type-specific optional metadata extraction for observed polymorphic activity families (e.g., walking steps/cadence, cycling power metrics, strength total reps) as additive source metadata.
- **Preserved**: ingestion idempotency key behavior and workout persistence semantics remain unchanged.

### Garmin List Payload Alias Normalization [application v3.9.1]

- **Changed**: Garmin sync source metadata extraction now resolves known list payload aliases for core fields (activity id/name/type, UTC/local start time, duration, distance) to tolerate observed schema polymorphism across activity types.
- **Added**: source metadata now captures optional list-derived activity metrics when available (`source_average_hr_bpm`, `source_max_hr_bpm`, `source_calories`) without affecting ingestion idempotency keys.
- **Changed**: near-duplicate detection parsing now uses normalized start-time and duration aliases, improving duplicate checks when Garmin list payloads expose alternate field names.
- **Scope**: this release hardens ingestion metadata parsing only; FIT download, parsing, and workout storage semantics remain unchanged.

## 2026-03-22

### Garmin Activity Index Contract (Phase 1) [application v3.9.0]

- **Added**: dedicated managed Azure Table `GarminActivityIndex` for persisted Garmin activity-list index rows.
- **Added**: canonical persisted entity contract for exact Garmin list payload storage with required control fields: `activity_id`, `source_start_time_utc`, `last_listed_at_utc`, `payload_schema_version`.
- **Added**: explicit key strategy for athlete/time-range queries: `PartitionKey=athlete_id`, `RowKey=YYYYMMDDTHHMMSSZ|activity_id`.
- **Added**: configuration knobs `GARMIN_ACTIVITY_INDEX_ROLLING_WINDOW_DAYS` (default `3`) and `GARMIN_ACTIVITY_INDEX_FRESHNESS_HOURS` (default `24`) to prepare cache-first orchestration.
- **Scope**: Phase 1 is contract + schema only; no intentional Garmin sync candidate-selection behavior change yet.

### Garmin Activity Index Storage Layer (Phase 2) [application v3.9.0]

- **Added**: dedicated `GarminActivityIndexStorage` module with typed operations for index row upsert, lookback-window payload queries, latest indexed timestamp lookup, and indexed day-coverage inspection.
- **Changed**: `StorageCoordinator` now exposes `garmin_activity_index` to provide a first-class access path for Garmin index operations.
- **Scope**: cache-first sync orchestration behavior remains unchanged in Phase 2; this phase is storage-layer wiring only.

### Garmin Cache-First Candidate Selection (Phase 3) [application v3.9.0]

- **Changed**: Garmin sync candidate selection now uses a cache-first merge of (a) bounded rolling list-window results and (b) indexed lookback payloads from `GarminActivityIndex`.
- **Added**: one-time bootstrap fallback for cache gaps in older lookback windows (expanded list call for uncovered range, then persisted index refresh).
- **Added**: resilient fallback path to direct Garmin list calls when index reads fail, preserving sync continuity.
- **Preserved**: ingestion idempotency and prefilter-by-activity-id semantics remain unchanged.

### Pre-Sync Operational Safety + Metadata (Phase 4) [application v3.9.0]

- **Added**: Garmin-specific execution metadata passthrough in pre-sync source results (`list_window_days_used`, `list_calls_made`, `cache_hit_count`, `cache_miss_days`).
- **Changed**: deferred retry gating for Garmin pre-sync now evaluates only outbound Garmin failure signals (rate limiting/auth/list-call failures), avoiding defer decisions tied to non-outbound internal cache operations.
- **Preserved**: weekly pre-sync fail-fast and planning pre-sync best-available semantics.

### Garmin Library Stewardship Preflight [application v3.8.2]

- **Changed**: upgraded minimum Garmin dependency from `garminconnect>=0.2.38` to `garminconnect>=0.2.40` in both `pyproject.toml` and `requirements.txt`.
- **Rationale**: aligns with project library-stewardship policy before cache-first activity index work, ensuring we rely on current upstream auth/token handling behavior rather than local reimplementation.
- **Validated**: Garmin-focused regression suites pass after the dependency-floor update (`test_garmin_client.py`, `test_garmin_sync_handler.py`, `test_garmin_physiometrics_sync_handler.py`, `test_garmin_training_state_adapter.py`).

## 2026-03-21

### Garmin Rate-Limit Conservatism Tightening [application v3.8.1]

- **Changed**: Garmin auth cooldown default increased from `900` seconds to `3600` seconds after auth-level throttling to better align with observed 429 block durations.
- **Changed**: pre-sync retry sleep now uses equal-jitter exponential backoff rather than deterministic exponential delays, reducing synchronized retries across instances.
- **Added**: Garmin activity sync now supports `GARMIN_ACTIVITY_REQUEST_DELAY_SEC` (default `1.0`) to pace successful per-activity FIT ingestions during large backfills.

### Garmin Auth Consolidation — Single Entry Point [application v3.8.0]

- **Added**: `GarminConnectClient.authenticate(stored_token)` — a single method that encapsulates the token-restore-then-fallback-login pattern, mirroring the `init_api()` pattern from the garminconnect library's own example. Tries `restore_from_tokens(stored_token)` first; if that raises `GarminConnectError` (or no token is provided), falls back to a full credential-based `login()`.
- **Changed**: `GarminPhysiometricsSyncHandler._authenticate_client()` now calls `self.client.authenticate(stored_token)` rather than duplicating restore/fallback logic inline.
- **Changed**: `GarminSyncHandler.sync()` auth block replaced with a single `self._client.authenticate(stored_token)` call.
- **Removed (internal)**: the duplicated restore→fallback pattern that existed independently in both handlers.
- **Tests**: four new unit tests for `authenticate()` in `test_garmin_client.py` covering restore success, restore failure fallback, no-token path, and login error propagation. Handler tests updated to assert at the `authenticate()` boundary.

## 2026-03-20

### Error Handling Course Correction (Non-Breaking) [application v3.7.0]

- **Changed (non-destructive)**: Garmin physiometrics sync error payload now includes explicit `recoverable` classification in structured error details to improve client retry behavior.
  - `recoverable=true`: transient failures suitable for retry (upstream service degradation, rate limits)
  - `recoverable=false`: non-retryable failures (authentication/configuration/internal)
- **SemVer correction**: prior major-version framing was churn and has been corrected to a minor version bump.
- **Operational semantics**: HTTP `207` still represents partial completion with errors; HTTP `200` represents clean completion.

### Workout Lookback Input Contract Hardening [application v3.6.1]

- **Changed (Garmin + OneDrive workout sync request handling)**: explicit `lookback_days=0` (or `days=0` for OneDrive) is now preserved and no longer treated as missing.
- **Changed (defaulting behavior)**: config/environment defaults are now applied only when lookback is absent (`null`/missing), not when the caller explicitly sends `0`.
- **Changed (validation behavior)**: negative lookback values now return HTTP `400` with `lookback_days must be a non-negative integer`.

### Physiometrics Lookback Offset Semantics [application v3.6.0]

- **Changed (Garmin + Intervals physiometrics sync)**: `lookback_days` now uses offset semantics to remove ambiguous same-day overlap in routine backfills.
- **Semantics**:
  - `lookback_days=0` syncs **today** only.
  - `lookback_days=1` syncs **yesterday** only.
  - `lookback_days=N` (N > 0) syncs exactly N completed days ending yesterday.
- **Validation**: physiometrics sync handlers now reject negative `lookback_days` values with HTTP 400.

### Operational Error Response Context Enrichment [application v3.5.0, operations API v4.4.0]

- **Changed (operational error contract)**: operational HTTP endpoints now add structured troubleshooting context to JSON error responses without changing success payloads.
- **Added (error metadata)**: JSON error responses now include additive fields such as `error_code`, `correlation_id`, `operation`, and source/provider or domain identifiers like `athlete_id` and `resource_id` when available.
- **Added (partial failure detail)**: operational partial-success responses that already expose an `errors` array now also emit `error_details` with per-error contextual metadata for faster diagnosis.
- **Updated (operations spec)**: `api_docs/openapi.operations.yaml` now documents the enriched operational error response fields and partial-failure detail records.

## 2026-03-19

### Async Queue Encoding + Operation Result Serialization Fixes [application v3.4.5]

- **Fixed (Azure Queue compatibility)**: async ingestion and deferred retry queue adapters now configure explicit `TextBase64EncodePolicy`/`TextBase64DecodePolicy` when enqueuing messages to Azure Queue Storage.
- **Impact**: queue-triggered Functions now receive/decode payloads correctly instead of failing pre-invocation and rapidly poisoning messages.
- **Fixed (Azure Table compatibility)**: async ingestion operation `mark_status()` now serializes `result` payloads to JSON strings before Table updates.
- **Impact**: successful async worker results no longer fail with `Type not supported when sending data to the service: <class 'dict'>`, eliminating retry loops and poison fallback caused by Table serialization errors.

### Garmin Async Queue Terminal Config Failure Classification [application v3.4.4]

- **Fixed (retry classification correctness)**: `GarminSyncConfig.from_env()` now raises typed `ConfigError` (instead of `ValueError`) when Garmin credentials are missing.
- **Impact**: async ingestion executor now classifies missing Garmin credentials as terminal configuration failure, marks operation `failed`, and acknowledges the message without repeated host retries/poison churn.

### Async Ingestion Hybrid Retry Classification [application v3.4.3]

- **Changed (worker retry policy)**: `AsyncIngestionOperationExecutor` now classifies failures into terminal vs retryable categories.
- **Changed (terminal handling)**: deterministic domain/data failures are persisted as `failed` and acknowledged without host-level rethrow.
- **Unchanged (transient handling)**: storage/external/transient failures still rethrow after failure persistence, preserving Azure Queue retry and poison-queue fallback behavior.

### Async Operation ETag Capture Fix [application v3.4.2]

- **Fixed (correctness)**: `AsyncIngestionOperationState.from_entity()` now reads ETag from `entity.metadata["etag"]` (Azure Data Tables SDK metadata location) instead of entity payload keys.
- **Impact**: `mark_status()` optimistic concurrency now uses persisted ETag values as designed when an ETag is present.

### Async Operation Table Serialization Compatibility Fix [application v3.4.1]

- **Fixed (storage compatibility)**: `AsyncIngestionOperationState.to_entity()` now serializes `context` and `result` as JSON strings so Azure Table entity writes remain scalar-compatible.
- **Fixed (read compatibility)**: `AsyncIngestionOperationState.from_entity()` now deserializes JSON payload strings back to dictionaries and safely falls back to `{}` on malformed/non-object values.
- **Schema note**: `AsyncIngestionOperations` column names are unchanged (`context`, `result`), but persisted values are now canonical JSON-encoded object payloads.

### Async Ingestion Operation Lifecycle Persistence + Status API [application v3.4.0, operations API v4.3.0]

- **Added (typed contracts)**: `TrainingAnalyticsPlatform/models/async_operation.py` introduces strict Pydantic contracts for persisted async ingestion operation state.
- **Added (state storage)**: `TrainingAnalyticsPlatform/storage/async_ingestion_operation_storage.py` adds `AsyncIngestionOperations` table operations for lifecycle state transitions.
- **Added (schema surface)**: `AsyncIngestionOperations` is now a managed application-owned Azure Table created by storage bootstrap.
- **Changed (async producer state)**: OneDrive and Garmin async producers now persist queued operation state with mode/source/lookback/context metadata and operation id.
- **Changed (worker lifecycle state)**: async ingestion queue worker now records `processing` and terminal `succeeded`/`failed` statuses with result/error payload.
- **Added (operations endpoint)**: `GET /api/async/operations/status` returns operation state by `athlete_id` + `operation_id`.

### Deferred Retry Queue Foundation for Timeout-Risk Pre-Sync [application v3.3.1, ingestion v15.3.0]

- **Added (typed contracts)**: `TrainingAnalyticsPlatform/models/retry.py` introduces strict Pydantic contracts for deferred retry queue payloads and persisted deferral state.
- **Added (queue adapter)**: `TrainingAnalyticsPlatform/integrations/deferred_retry_queue.py` encapsulates Azure Queue enqueue/decode behavior for deferred work items.
- **Added (state storage)**: `TrainingAnalyticsPlatform/storage/retry_deferral_storage.py` adds `RateLimitDeferrals` table operations with ETag-aware status update support.
- **Added (orchestration)**: `TrainingAnalyticsPlatform/handlers/deferred_retry_coordinator.py` implements timeout-risk policy decisioning (`Retry-After` vs request budget/safety margin), queue scheduling, and state persistence.
- **Changed (shared pre-sync execution)**: `TrainingAnalyticsPlatform/handlers/presync_core.py` now supports deferral metadata (`deferred`, `safe_to_retry_at_utc`, `deferred_operation_id`) and no longer forces inline retries when timeout-risk deferral is selected.
- **Changed (DI wiring)**: `FunctionAppDependencies` now provides deferred retry queue/coordinator services and injects coordinator into weekly/planning pre-sync handlers.
- **Added (schema surface)**: `RateLimitDeferrals` is now a managed application-owned Azure Table created by storage bootstrap.
- **Added (config)**: `DEFERRED_RETRY_ENABLED`, `DEFERRED_RETRY_HTTP_REQUEST_BUDGET_SEC`, `DEFERRED_RETRY_SAFETY_MARGIN_SEC`, and `DEFERRED_RETRY_SCHEMA_VERSION` environment variables.

### Planning Context Lazy Hydration + Force Rollup Cleanup [application v3.3.0, operations API v4.2.0]

- **Added (handler)**: `PlanningContextPreSyncHandler` — best-available JIT sync across all 4 sources (OneDrive workouts, Garmin activities, Garmin physiometrics, Intervals physiometrics) before planning context reads. Uses request-driven `days` parameter as lookback window. Individual source failures produce a warning log and are recorded but do not abort remaining sources or the HTTP response.
- **Changed (endpoint behavior)**: `GET /api/planning/context` now performs read-repair lazy hydration before returning results. All sources are idempotent; already-present data is never re-ingested. First call after a data gap may have higher latency.
- **Changed (ops endpoint)**: `POST /api/operations/rollups/weekly/compute` (`force_weekly_rollups`) is now a pure compute trigger — `pre_sync` request field, 424 response, and pre-sync execution removed. Weekly pre-sync continues to run on the timer.
- **Updated (operations contract)**: `openapi.operations.yaml` — removed 424 response, `pre_sync` request field, `pre_sync` response field, and 3 `ForceWeeklyRollupsPreSync*` schemas from `forceWeeklyRollups`.
- **Updated (semantic contract)**: `openapi.yaml` — `/api/planning/context` description now explicitly documents read-repair behaviour, idempotency guarantee, and first-call latency note.
- **Added (config)**: `PLANNING_PRESYNC_RETRY_MAX_ATTEMPTS` (default: 3) and `PLANNING_PRESYNC_RETRY_BASE_DELAY_SEC` (default: 1.0) environment variables.

## 2026-03-18

### Garmin Polling Optimization + Force Override Controls [application v3.2.0, operations API v4.1.0]

- **Changed (ingestion behavior)**: Garmin activity sync now prefilters by `activityId` against `IngestionState` before FIT download.
  - Existing terminal states (`ingested`, `skipped`, `skipped_duplicate`, `filtered`) are skipped without downloading FIT payloads.
  - Skip telemetry now includes `skipped_by_id` and per-item status `skipped_seen_id`.
- **Changed (control-plane override)**: `/api/garmin/sync` now accepts `force` to bypass activity-id prefiltering and reprocess listed activities.
- **Changed (library stewardship)**: Garmin activity listing switched to `garminconnect` date-range API (`get_activities_by_date`) instead of local `start=0, limit=100` plus client-side date filtering.
- **Changed (ingestion behavior)**: Garmin physiometrics sync now prefetches existing dates from `Physiometrics` and skips already-stored days when `force=false`.
- **Changed (control-plane override)**: `/api/garmin/physiometrics/sync` now accepts `force` to bypass stored-date skipping and re-fetch all days in range.
- **Changed (response contract)**: Garmin physiometrics sync responses now include `records_skipped`.
- **Updated (operations contract)**: `api_docs/openapi.operations.yaml` advanced to `4.1.0` and now documents Garmin `force` request flags and new response fields (`found`, `force`, `skipped_by_id`, `records_skipped`).
- **Updated (backend docs)**: `docs/devops/BACKENDS.md` updated for Garmin prefilter semantics, force controls, and updated examples.

## 2026-03-17

### Physiometrics Current Response Normalization [application v3.1.1, semantic API v7.1.1, operations API v4.0.1]

- **Changed (response contract)**: `GET /api/physiometrics/current` now emits canonical metrics in stable domain sections that are always present (null-safe):
  - `heart_rate`, `power`, `vo2max`, `body_composition`, `recovery`, `activity`, `nutrition`, `training_state`
- **Changed (client reliability)**: canonical fields are no longer conditionally omitted from response payloads; clients can rely on structural presence without probing for missing keys.
- **Changed (semantic layer fix)**: metric resolution now uses latest non-null value per source (respecting source precedence) instead of only the newest row per source, preventing sparse latest rows from blanking otherwise available canonical metrics.
- **Changed (metadata)**: `source_effective_dates` continues to reflect newest row per contributing source for freshness visibility.
- **Documentation alignment**: OpenAPI and GPT API docs updated to reflect sectioned canonical response and optional legacy top-level extras.

### Garmin Training Status and Load Focus Integration [application v3.1.0, API v7.1.0, models v4.2.0/v5.1.0]

- **Added (schema)**: New Garmin-exclusive fields in `PhysiometricsSnapshot` (`v4.2.0`):
  - `training_status_label`: Garmin raw `trainingStatusFeedbackPhrase` token (e.g., `PRODUCTIVE_3`, `MAINTAINING_2`, `UNPRODUCTIVE_5`, `PEAKING_1`, `DETRAINING`)
    - The trailing suffix (for example `_2`) is vendor-provided feedback variant detail from Garmin and is preserved verbatim.
  - `load_focus_low_aerobic_pct`, `load_focus_high_aerobic_pct`, `load_focus_anaerobic_pct`: Distribution percentages from Garmin Connect's Load Focus metric (week view)
- **Added (schema)**: New Garmin pass-through fields in `TrainingStateSnapshot` (`v5.1.0`):
  - `garmin_training_status`: Passthrough of `training_status_label` from latest physiometrics
  - `garmin_training_load`: Garmin's native 7-day training load (distinct from our computed CTS)
  - `garmin_recovery_time_hours`: Garmin estimated recovery time, converted from minutes to hours
  - `garmin_load_focus_low_aerobic_pct`, `garmin_load_focus_high_aerobic_pct`, `garmin_load_focus_anaerobic_pct`: Passthroughs from physiometrics
- **Changed (adapter)**: `GarminTrainingStateAdapter._extract_training_context()` now extracts `mostRecentTrainingLoadBalance` (previously claimed in v14.4.2 CHANGELOG but never implemented).
- **Changed (adapter)**: `GarminTrainingStateAdapter._do_parse()` now extracts training status label from `latestTrainingStatusData.trainingStatusFeedbackPhrase` and load focus percentages from `mostRecentTrainingLoadBalance.metricsTrainingLoadBalanceDTOMap` monthly load fields.
- **Changed (sync + adapter)**: Garmin physiometrics sync now fetches `get_training_readiness` and `get_morning_training_readiness` payloads and passes them into adapter mapping.
  - `readiness_score` now prefers Garmin readiness endpoint values (morning first, then daily readiness payload) with summary fallback.
  - `recovery_time_minutes` now accepts readiness-payload recovery duration fields (minutes/hours normalized to minutes) with existing training-status fallback.
  - Readiness endpoint failures are non-fatal for daily physiometrics sync; ingestion continues with fallback mappings.
- **Changed (semantic layer)**: `SemanticLayer._compute_training_state_for_date()` now extracts and threads new Garmin fields; `_build_training_state_snapshot()` converts `recovery_time_minutes` to `recovery_time_hours` and populates all new pass-through fields.
- **Changed (precedence)**: `SourcePrecedenceResolver.METRIC_SOURCES` now registers all four new fields as Garmin-exclusive sources.
- **Changed (consolidation)**: `PhysiometricsConsolidationHandler.CONSOLIDATED_VERSION` advanced to `v4.2.0`; `TrainingStateConsolidationHandler` inherits v5.1.0 semantics.
- **Updated (sync handler)**: `GarminPhysiometricsSyncHandler._log_storage_metric_presence()` now logs presence of new fields for observability.
- **Updated (API spec)**: `openapi.yaml` advanced to `7.1.0`; new `TrainingStateSnapshot` fields documented with ranges and descriptions.
- **Fixed (adapter)**: Resolved CHANGELOG v14.4.2 claim that `mostRecentTrainingLoadBalance` was implemented but was never extracted; now fully extracted and parsed via multi-path fallback.
- **Unchanged (ownership)**: All new fields are Garmin-exclusive passthrough; no multi-source consolidation applied.

## 2026-03-16

### **BREAKING:** `readiness_score` Semantic Separation and Canonical Training-State Path [application v3.0.0]

- **BREAKING (persisted semantics)**: `readiness_score` in `TrainingStateSnapshot` now exclusively represents the composite HRV + load score. Previously it returned the Garmin native readiness as an override when present (`composite or garmin_readiness`). Consumers relying on `readiness_score` as "best available readiness including Garmin" must now read `garmin_readiness_score` for the Garmin value.
- **Changed (model)**: `_compute_composite_readiness` no longer accepts or applies `garmin_readiness`. Garmin passthrough is written only to `garmin_readiness_score`.
- **Changed (null semantics)**: `readiness_score` is `null` when `hrv_ln_rmssd` is absent **or** `fatigue_index` is absent or zero (zero load is not credible data for a score). Previously, zero `fatigue_index` clamped to `100.0` via the inverse-fatigue formula.
- **Changed (versioning)**: `TrainingStateSnapshot.canonical_version` advanced from `4.0.0` to `5.0.0`.
- **Changed (canonical path)**: `TrainingStateConsolidationHandler.compute_day()` now delegates entirely to `SemanticLayer._compute_training_state_for_date()`, removing a duplicate and divergent implementation.
- **Changed (TSS fallback)**: `SemanticLayer._compute_rolling_tss()` now falls back to `CanonicalAnalyticsEngine` when `tss` is absent from the `Workouts` table projection, via `_resolve_workout_tss()`. Previously sparse rows silently contributed zero TSS, causing underestimated load.
- **Updated (API spec)**: `openapi.yaml` advanced to `7.0.0`; `readiness_score` and `garmin_readiness_score` descriptions updated to reflect separation.
- **Updated (docs)**: `WELLNESS_INGESTION_IMPLEMENTATION.md` composite readiness pseudocode replaced with the exact formula and a worked example.

### Garmin Physiometrics Running VO2Max Formalization + Blob-First Sync Parity [application v2.1.0]

- **Changed (schema)**: promoted `running_vo2max_ml_kg_min` into canonical Garmin physiometrics semantics alongside `cycling_vo2max_ml_kg_min`.
- **Changed (versioning)**: `PhysiometricsSnapshot` canonical version advanced from `4.0.0` to `4.1.0` for the additive persisted-semantics change.
- **Changed (Garmin adapter)**: Garmin physiometrics mapping now preserves running VO2Max end-to-end instead of parsing and silently dropping it.
- **Changed (sync orchestration)**: Garmin physiometrics sync now archives per-day raw payloads to `external-sources`, records `SourceIngestionState` transitions, preserves `ext_json`, and returns `207 Multi-Status` when day-level failures occur.
- **Unchanged (ownership)**: `resting_hr_bpm` remains Intervals-exclusive; Garmin resting HR continues to be intentionally ignored.

### **BREAKING:** Canonical Wellness Field Realignment (SDNN/SpO2 Promotion + Intervals Body Fallback) [application v2.0.0]

- **Changed (schema)**: promoted `hrv_sdnn_ms` and `spo2_pct` into canonical Physiometrics semantics.
- **Changed (source precedence)**: `weight_kg` and `body_fat_pct` now use `withings -> intervals` fallback precedence.
- **Changed (schema rollback)**: removed Intervals load-context fields from canonical semantics: `intervals_ctl`, `intervals_atl`, `intervals_ramp_rate`, `intervals_ctl_load`, `intervals_atl_load`.
- **Changed (adapter mapping)**: Intervals adapter now maps `hrvSDNN`, `spO2`, `weight`, and `bodyFat` into canonical fields under the precedence contract.
- **Changed (versioning)**: canonical snapshot version advanced to `4.0.0` to reflect persisted semantic and precedence contract changes.
- **Documentation authority alignment**: canonical architecture now explicitly documents the promoted fields and revised fallback ownership model.

### Intervals Blob-First Wellness Ingestion and Partial-Failure Semantics [application v1.1.0]

- **Changed**: Intervals sync now persists each fetch call payload to blob storage in `external-sources` container before canonical processing, improving replayability and forensic debugging.
- **Changed**: Intervals sync now records source ingestion state transitions (`fetched` → `processed`/`failed`) for archived raw payload blobs.
- **Changed**: Intervals sync now returns `207 Multi-Status` when at least one record fails processing while others succeed or are persisted with warnings.
- **Schema change (Physiometrics persisted semantics)**: added Intervals load-context columns: `intervals_ctl`, `intervals_atl`, `intervals_ramp_rate`, `intervals_ctl_load`, `intervals_atl_load`.
- **Adapter contract change**: Intervals load-context fields are now treated as valid wellness content for semantic validation (no longer rejected as empty when core recovery/nutrition/activity metrics are absent).
- **Non-scalar preservation**: Intervals `sportInfo` is persisted as JSON (`sport_info_json`) and full per-record source payload remains available via archived blob envelopes.

### Session Inference Removal and HealthFit Timezone Metadata Hardening [ingest v15.2.0]

- **BREAKING (semantic)**: `session.start_time` is no longer used as timezone offset evidence anywhere in the resolution chain. `session.start_time` is a local wall-clock context value, not a UTC offset source.
- **Generic offset fallback order** (Base/Payload models) is now: `activity.local_timestamp` vs `activity.timestamp` → `device_settings.utc_offset` → subclass source-specific evidence.
- **HealthFit**: model now overrides `_explicit_timezone_metadata_keys()` to return `()`, ensuring stale persisted timezone hints (e.g. `Europe/London`) in source metadata cannot override the filename-derived offset.
- **Garmin and HealthFit short-circuit unchanged**: both models return their authoritative source offset before reaching the base chain.
- **`timezone` property**: `session_offset` parameter is now passed as `None`; session timing no longer participates in canonical timezone resolution.
- **Test updated**: `test_session_utc_math_for_start_time_only` now asserts `local_tz_offset is None` when no activity/filename/device evidence is present, confirming session start_time is not treated as offset evidence.
- **Persisted metadata impact**: workouts where `local_tz_offset` was previously derived from session timing may now emit a different (corrected) offset. HealthFit workouts with stale explicit metadata timezone keys will now emit the filename-derived offset.

## 2026-03-15

### Zwift Detection and Timezone Override Narrowing [ingest v15.1.9]

- **Changed**: Zwift classification is now based on FIT manufacturer identity (`zwift`) rather than broad activity-name/device/sub-sport heuristics.
- **Timezone contract**: Zwift remains a timezone-only edge-case override; when athlete home timezone is configured, `activity_metadata.timezone` uses that value.
- **Fallback contract**: when athlete home timezone is unavailable for Zwift workouts, timezone now falls back to the resolved `local_tz_offset` (UTC offset string).
- **Offset stability**: `local_tz_offset` derivation is unchanged and remains source-specific (HealthFit filename, Garmin API local-vs-UTC, or FIT/device fallback).
- **Supersedes v15.1.8 wording**: prior language about broad Zwift/virtual signal detection has been narrowed to manufacturer-based detection to reduce churn.

### Zwift Timezone Simplification to Athlete Home Timezone [ingest v15.1.8]

- **Changed**: Zwift workout timezone resolution now uses athlete home timezone directly when Zwift/virtual signals are present.
- **Simplified precedence**: Zwift athlete-home override is now applied before explicit source timezone hints in canonical timezone resolution.
- **Detection update**: Zwift detection no longer requires `UTC+00:00`; it relies on Zwift/virtual workout signals.
- **Persisted metadata impact**: affected Zwift ingests may emit athlete-home IANA timezone values in `activity_metadata.timezone` even when `local_tz_offset` is non-UTC.

### Source-Specific Timezone Resolution Hardening for HealthFit and Garmin [ingest v15.1.7]

- **Changed**: local timezone resolution now uses source-specific authoritative evidence before generic FIT/device fallback logic.
- **HealthFit contract restored**: filename-local recording time is now authoritative for UTC offset derivation when present, rather than being demoted beneath generic FIT session/activity/device signals.
- **Garmin contract hardened**: Garmin API `source_start_time_local` vs `source_start_time_utc` is now treated as authoritative local-time evidence when available, preventing malformed indoor FIT/device timestamps from overriding API truth.
- **OO design correction**: source-specific timezone resolution is now implemented via model overrides in the FIT model hierarchy instead of forcing all sources through one flattened fallback order.
- **Persisted metadata impact**: affected HealthFit and Garmin ingests may now emit corrected `activity_metadata.local_tz_offset` and `activity_metadata.timezone` values; metadata schema shape is unchanged.

### FIT Timezone Fallback Correction for Malformed Garmin Indoor Sessions [ingest v15.1.6]

- **Fixed**: malformed FIT session messages where `session.start_time == session.timestamp` no longer produce duration-derived phantom timezone offsets such as `UTC+01:15` or `UTC+00:45`.
- **Fallback correction**: when session timing is invalid, `local_tz_offset` now prefers activity/timestamp-correlation-derived local time over `device_settings.utc_offset`, because affected Garmin indoor files can report `utc_offset=0` while activity local timestamps clearly indicate the effective local timezone.
- **Persisted metadata impact**: some ingests will now emit corrected `activity_metadata.local_tz_offset` and downstream `activity_metadata.timezone` values for affected files; metadata schema shape is unchanged.
- **Regression coverage**: added tests covering malformed session start/end equality and the `activity=-05:00` vs `device utc_offset=0` precedence case.

### OneDrive Delta Sync Reset Control Endpoint

- **Added**: `POST /api/onedrive/sync/reset` to explicitly clear OneDrive delta cursor state.
- **Reset scopes**:
  - `{"athlete_id": "..."}` resets one athlete token row.
  - `{"all": true}` resets all athlete OneDrive token rows.
- **Behavior**: reset preserves OAuth credentials and clears delta-state fields so the next sync reseeds from Graph delta start.
- **Safety**: ingestion idempotency semantics are unchanged; reseed may re-list prior files but unchanged files remain skip-eligible.

### Canonical Session-First Timezone Resolver Alignment [ingest v13.0.34]

- **Changed**: timezone resolution now uses one shared canonical resolver across ingestion and historical backfill paths.
- **Canonical rule**: `local_tz_offset` is derived from FIT session local-vs-UTC timing first; fallback signals are used only when session fields are missing/invalid.
- **Zwift edge-case hardening**: athlete home timezone override now applies only to explicit Zwift/virtual `UTC+00:00` workouts.
- **Parity fix**: ingestion and backfill now share the same Zwift detection and timezone precedence to prevent diverging outcomes.

### Timezone Propagation Fix Across Ingestion and Model Surfaces [ingest v13.0.33]

- **Fixed**: canonical timezone (`activity_metadata.timezone`) is now propagated from FIT model timezone resolution into model/session/projection surfaces instead of being overwritten with `local_tz_offset`.
- **Behavior contract restored**: `timezone` now prefers IANA timezone names and falls back to UTC offset only when IANA resolution is unavailable.
- **Model alignment**:
  - `WorkoutMetricsModel._build_session(...)` now uses `metadata.timezone` first, then `local_tz_offset` fallback.
  - Semantic projection defaults now preserve `activity_metadata.timezone` when present.
- **Metadata alignment**: `BaseFitModel._build_canonical_activity_metadata()` now emits both `local_tz_offset` and `timezone`.
- **Schema/docs alignment**: canonical metadata schema examples now reflect separate `local_tz_offset` and `timezone` fields.
- **Operational utility**: added `scripts/backfill_workout_timezone.py` for historical correction with dry-run/apply modes and idempotent updates across Workouts rows and metadata blobs.
- **Zwift edge-case handling**: timezone backfill now treats Zwift virtual workouts (`UTC+00:00`) as no-local-timezone sessions and uses athlete home timezone when configured.

### WorkoutProjection Automatic Flag-Driven Canonical Hydration for Missing Dependent Fields [semantic API v6.1.0]

- **Added**: automatic capability-flag-driven hydration in `SemanticLayer.build_workout_projection(...)` for missing dependent projection fields from canonical parquet via `CanonicalAnalyticsEngine`.
- **Hydration scope**: missing-only fill for capability-dependent fields gated by projection flags (`has_hr` → `hr_avg_bpm/hr_max_bpm`, `has_power` → `pwr_avg_watts/pwr_max_watts/pwr_normalized_watts`) plus cadence peaks (`cad_avg_rpm`, `cad_max_rpm`) when absent.
- **Precedence contract**: metadata-first; canonical hydration never overwrites values already present from `Workouts` table or `metadata.json`.
- **Hydration gating**: canonical reads are skipped when both `has_hr` and `has_power` are false, or when capability-dependent fields are already populated.
- **Error behavior**: canonical load/validation failures degrade gracefully to metadata-only projection output.
- **Code updates**:
  - `TrainingAnalyticsPlatform/analytics/semantic_layer.py`: added automatic flag-driven hydration path and canonical loader/hydrator helpers for projection.
  - `TrainingAnalyticsPlatform/models/core.py`: updated `WorkoutProjection` docstring to describe automatic flag-driven hydration semantics.
  - `tests/test_semantic_layer.py`: added coverage for fill-missing, metadata precedence, capability-gated skip path, and graceful fallback.

## 2026-03-14

### Workout Detail Canonical-Required Read Contract Hardening [semantic API v6.0.0]

- **Changed**: `GET /api/workouts/{workout_id}` now enforces canonical-required metrics hydration and no longer returns degraded/partial metrics when canonical hydration fails.
- **Why**: Aligns runtime behavior with the canonical analytics contract and prevents mixed-provenance response shaping.
- **Error contract**: Clients now receive a business-level `500` message (`Workout detail is temporarily unavailable`) rather than storage/canonical implementation details.
- **Contract/docs updates**:
  - `api_docs/openapi.yaml`: workout detail operation documents generic internal error behavior for failures.
  - `docs/gpt/SEMANTIC_LAYER_API.md`: workout detail section documents generic `500` internal failure semantics.
  - `docs/devops/data_architecture/CANONICAL_DATA_ARCHITECTURE.md`: added explicit workout detail read contract.
- **Versioning note**: Semantic API version remains `6.0.0` because response schema and documented status-code surface are unchanged; this is behavior hardening to match the existing canonical contract.

### BREAKING: Typed Lap Response Contracts + Nested Lap Detail Shape [semantic API v6.0.0]

- **Changed**: Lap responses now use explicit typed models instead of untyped flat dict payloads.
- **Why**: Enforces stable schema guarantees for ChatGPT consumers and removes ambiguous lap response surfaces.
- **Code updates**:
  - `TrainingAnalyticsPlatform/models/core.py`: introduced `LapSummaryResponse` and `WorkoutLapDetailResponse`; `WorkoutDetailResponse.laps` now typed as `List[LapSummaryResponse]`.
  - `TrainingAnalyticsPlatform/analytics/semantic_layer.py`: lap summarization now builds typed `LapSummaryResponse`; lap detail now returns `{workout_id, athlete_id, lap: ...}` from `WorkoutLapDetailResponse`.
- **Contract/docs updates**:
  - `api_docs/openapi.yaml`: added `LapSummary` schema; `WorkoutDetail.laps[]` now references `LapSummary`; `WorkoutLapDetail` now nests lap payload under `lap`.
  - `docs/gpt/SEMANTIC_LAYER_API.md`: updated lap detail description/examples to typed nested lap shape.

### HR Zone Total Seconds Edge-Clamp Fix [canonical_schema v2.0.3]

- **Fixed**: `hr_zone_total_sec` no longer drops out-of-range heart-rate samples during zone classification.
- **Why**: Previous in-range filtering could produce unexpectedly low or zero zone totals when samples fell below the configured floor or above the configured ceiling.
- **Code updates**:
  - `TrainingAnalyticsPlatform/models/core.py`: `_compute_hr_zones_from_series()` now edge-clamps HR samples to zone bounds before binning.
  - `tests/test_canonical_validation.py`: added regression coverage proving below-floor samples count in Z1, above-ceiling samples count in Z5, and totals remain consistent.
- **Contract/docs updates**:
  - `CANONICAL_SCHEMA_VERSION` bumped to `2.0.3` in `TrainingAnalyticsPlatform/storage/table_storage.py`.
  - `docs/devops/data_architecture/INGESTION_SCHEMA.md` updated to `2.0.3`.
  - `docs/devops/data_architecture/CANONICAL_ANALYTICS_SURFACE.md` now explicitly documents edge-clamped HR zone classification semantics.

### HR Zone Seconds-Only Contract Alignment [canonical_schema v2.0.2]

- **Changed**: Removed non-canonical per-workout HR minute fields (`hr_z1_min`..`hr_z5_min`) from the metrics model surface.
- **Why**: HR zones now mirror power zones with a single canonical unit (`*_sec`). Minute values are derived at query/aggregation boundaries.
- **Code updates**:
  - `TrainingAnalyticsPlatform/models/metrics/zones.py`: removed `HRZonesModel` minute fields.
  - `TrainingAnalyticsPlatform/models/core.py`: removed dead `metrics.get("hr_z*_min")` mappings in `_build_hr_zones()`.
  - `TrainingAnalyticsPlatform/analytics/semantic_layer.py`: clarified `_sum_zone_time()` docstring examples to seconds-based fields.
- **Contract/docs updates**:
  - `CANONICAL_SCHEMA_VERSION` bumped to `2.0.2` in `TrainingAnalyticsPlatform/storage/table_storage.py`.
  - `docs/devops/data_architecture/INGESTION_SCHEMA.md` updated with `2.0.2` and canonical source-path correction.
  - `docs/devops/data_architecture/CANONICAL_ANALYTICS_SURFACE.md` explicitly documents seconds-only per-workout zone contract.
  - `docs/gpt/WORKOUT_SCHEMA.md` clarifies that minute zone values are derived reporting projections.

### BREAKING: Weekly Rollup Per-Week Outcome Visibility + Sync-Style Status Envelope [operations API v4.0.0]

**Changed**: Weekly rollup APIs now return sync-style top-level status metadata and detailed per-week outcomes instead of only coarse aggregate athlete arrays.

**Why**: Prior responses (for example only `succeeded/skipped/failed` athlete lists) obscured mixed outcomes and made troubleshooting difficult when one week failed while others succeeded/skipped.

**Changes**:

- **`TrainingAnalyticsPlatform/analytics/semantic_layer.py`**: `compute_and_persist_previous_week_rollups()` now returns top-level `status`/`message` and detailed `results[]` with per-athlete + per-week status, messages, and stable error details. Legacy top-level compatibility fields (`requested_athletes`, `requested_weeks`, `succeeded`, `skipped`, `failed`) are removed from the compute response.
- **`TrainingAnalyticsPlatform/handlers/query_handler.py`**: `query_weekly_rollups()` now returns top-level `status`/`message` and per-requested-week `results[]` while preserving strict `rollups[]` item schema.
- **`api_docs/openapi.operations.yaml`**: expanded `ForceWeeklyRollupsResponse` schema with `status`, `message`, and `results[]` detail models.
- **`api_docs/openapi.yaml`**: expanded `WeeklyRollups` response envelope with top-level `status`, `message`, and `results[]`.
- **`docs/gpt/SEMANTIC_LAYER_API.md`**: weekly rollups response examples and semantics updated for the new envelope.

**Semantic API SemVer**: `openapi.yaml` v`5.1.0` → v`5.2.0` (backward-compatible weekly rollup response envelope expansion).

### Fix: Signed `hr_drift_bpm` Support in Durability Model

**Fixed**: `DurabilityMetricsModel.hr_drift_bpm` no longer enforces non-negative-only values.

**Root cause**: Weekly rollup hydration could produce small negative drift values (for example `-0.4`) from canonical analytics, but the durability model required `hr_drift_bpm >= 0`, causing `ValidationError` and aborting weekly rollup persistence.

**Changes**:

- **`TrainingAnalyticsPlatform/models/metrics/performance.py`**: removed `ge=0` constraint from `hr_drift_bpm` so signed drift values are accepted.
- **`tests/test_semantic_layer.py`**: added regression coverage for signed drift acceptance and mixed per-week rollup outcomes.

### Fix: Garmin Sync Control-Plane Lookback Field Alignment

**Fixed**: `/api/garmin/sync` request parsing expected `days` even though the operations OpenAPI and the Postman control-plane request shape use `lookback_days`.

**Root cause**: Garmin activity sync diverged from the other sync-style endpoints and from the published operations contract. Requests sending `lookback_days` silently fell back to the default environment lookback instead of using the caller-supplied value.

**Changes**:

- **`TrainingAnalyticsPlatform/handlers/garmin_sync_handler.py`**: changed `GarminSyncRequest.lookback_days` parsing to read `lookback_days` from the request body or query params.
- **`tests/test_garmin_sync_handler.py`**: added request parsing coverage for valid, missing, and invalid `lookback_days` values.
- **`tests/test_function_app_extras.py`**: added endpoint-level tests proving `/api/garmin/sync` forwards `lookback_days` from body and query params.
- **`docs/devops/BACKENDS.md`**: updated Garmin manual sync examples to use `lookback_days`.

### Fix: Clamp Missing Percentage Boundaries for Rollup Model Validation [application v1.0.3]

**Fixed**: `CanonicalAnalyticsEngine` could compute slight negative `hr_missing_pct` / `pwr_missing_pct` values (for example `-0.1`) under off-by-one duration/sample boundary conditions, causing `SampleMetricsModel` validation failures and aborting weekly rollup persistence.

**Root cause**: missing-percentage formulas use `(1 - samples / duration_sec) * 100`. When `samples_count` exceeded computed `duration_sec` by one sample due to boundary semantics, the raw percentage became slightly negative and violated schema constraints (`ge=0`).

**Production impact**: Weekly rollup model build raised Pydantic `ValidationError`, which propagated as `StorageError` (`Failed to build WorkoutMetricsModel for weekly rollup`) and failed athlete weekly rollup persistence.

**Changes**:

- **`TrainingAnalyticsPlatform/models/core.py`**: added canonical missing-percentage boundary helper and updated `hr_missing_pct` / `pwr_missing_pct` to clamp computed values to `[0, 100]` before returning.
- **`tests/test_canonical_validation.py`**: added regression tests for off-by-one sample/duration mismatch clamping and invalid-input `None` semantics.
- **`tests/test_semantic_layer.py`**: added weekly rollup hydration regression test proving `_build_rollup_metrics_model` succeeds for off-by-one mismatch cases and emits bounded missing percentages.
- **`docs/gpt/WORKOUT_SCHEMA.md`**: clarified that missing-percentage fields are bounded to `0–100` before validation.

**Application SemVer**: `pyproject.toml` v`1.0.2` → v`1.0.3`.

### Fix: Signed HR–Power Lag Schema Constraint [application v1.0.2]

**Fixed**: `DurabilityMetricsModel.hr_power_lag_sec` incorrectly enforced `ge=0`, causing Pydantic `ValidationError` for valid negative lag values produced by the cross-correlation algorithm.

**Root cause**: Formula contract ([`CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT.md`]) specifies τ ∈ [-60, +60] as the signed search range. Negative lag values are semantically valid (HR leads power). The `ge=0` constraint was never in the contract — it was incorrectly applied during initial model construction.

**Production impact**: Athletes whose most-recent workout produced a negative `hr_power_lag_sec` (e.g., `-27`) had their entire weekly rollup aborted. The `ValidationError` propagated as `StorageError`, landing the athlete in the `failed` list and returning HTTP 207.

**Changes**:

- **`TrainingAnalyticsPlatform/models/metrics/performance.py`**: replaced `Field(None, ge=0)` with `Field(None, ge=-60, le=60)` on `hr_power_lag_sec`, aligning the schema constraint to the formula contract search range. Updated field docstring with signed semantics.
- **`TrainingAnalyticsPlatform/models/core.py`**: added docstrings to `hr_power_lag_sec` property and `_hr_power_lag_sec()` helper documenting signed output range and confirming no `abs()` suppression is applied.
- **`docs/devops/data_architecture/CANONICAL_ANALYTICS_SURFACE.md`**: updated `hr_power_lag_sec` description to state signed semantics, search range, and null condition.
- **`docs/gpt/WORKOUT_SCHEMA.md`**: updated field description to include signed range and directionality.
- **`tests/test_canonical_validation.py`**: added 7 regression tests covering negative/zero/positive/None lag at the `DurabilityMetricsModel` level, engine output range, and no-raise contract.
- **`tests/test_semantic_layer.py`**: added `TestHrPowerLagSignSemantics` class with 3 rollup-path regression tests.

**Application SemVer**: `pyproject.toml` v`1.0.1` → v`1.0.2`.

### Ingestion Source-First Rollback [ingestion v15.1.4]

**Changed**: ingestion no longer hard-rejects non-1 Hz canonical streams at persistence time; source workouts are persisted as-ingested.

**Changes**:

- **Write-path rollback**: removed ingestion-time hard failure in `StorageInfrastructure.upload_parquet_blob()` for non-1 Hz canonical cadence.
- **Metadata resilience**: canonical distance derivation during metadata build now uses `resample=True` and no longer blocks ingestion on sparse-gap cadence irregularities.
- **Contract alignment**: strict-first validation with optional resampling remains in semantic/read paths (API/rollup hydration), not as an ingestion acceptance gate.

**Ingestion SemVer**: `INGEST_VERSION` v`15.1.3` → v`15.1.4`.

### Canonical Read-Time Sparse-Gap Tolerance for Semantic API/Rollups [application v1.0.1]

**Changed**: Semantic-layer canonical hydration now applies strict 1 Hz validation first, then retries with `resample=True` on canonical sampling validation failures.

**Changes**:

- **Strict-first fallback path**: semantic canonical metric hydration now retries with resampling when strict validation fails instead of immediately downgrading to basic sample stats.
- **Weekly rollup resilience**: weekly rollup model building now retries with `resample=True` for non-1 Hz canonical streams before surfacing failure.
- **Distortion observability**: fallback logs now include sparse-gap distortion telemetry (`gap_count`, `max_gap_sec`, `inserted_missing_bins`, `distortion_pct`).
- **Thresholded warnings**: distortion warnings are emitted only when `distortion_pct` exceeds `CANONICAL_DISTORTION_WARN_PCT` (default `5.0`).

**Notes**:

- Ingestion write-path remains strict 1 Hz validated; this change adds tolerance at read-time analytics hydration surfaces.
- No canonical telemetry schema changes.

**Application SemVer**: `pyproject.toml` v`1.0.0` → v`1.0.1`.

### Canonical Parquet Write-Time 1 Hz Validation [ingestion v15.1.3]

**Fixed**: ingestion now rejects canonical parquet payloads that do not already satisfy the 1 Hz canonical sampling contract.

**Changes**:

- **Write-path validation**: `StorageInfrastructure.upload_parquet_blob()` now validates canonical DataFrames against the existing `CanonicalAnalyticsEngine` 1 Hz contract before persisting `canonical.parquet`.
- **Failure timing**: non-1 Hz canonical telemetry now fails during ingestion instead of being written successfully and failing later during weekly-rollup rehydration.
- **Regression coverage**: storage tests now verify that valid 1 Hz canonical streams persist and non-1 Hz streams are rejected before blob upload.

**Ingestion SemVer**: `INGEST_VERSION` v`15.1.2` → v`15.1.3`.

## 2026-03-13

### **BREAKING:** Physiometrics Storage Identity Correction [application v1.0.0]

**Fixed**: `Physiometrics` storage no longer uses `effective_date` alone as row identity. Same-day source snapshots were overwriting each other, which corrupted multi-source daily state.

**Changes**:

- **Storage key correction**: `Physiometrics.RowKey` now uses `YYYY-MM-DD|source` instead of `YYYY-MM-DD`.
- **Source isolation**: Withings, Garmin, Intervals, and config-originated writes (`manual`, `chatgpt`) now persist as distinct same-day rows.
- **Config read correction**: `get_physiometrics()` and config history now read the latest config-originated row instead of whichever source wrote most recently.
- **History timestamp fix**: config history responses now use `updated_at_utc` from the stored entity rather than incorrectly treating `RowKey` as an update timestamp.

**Operational consequence**:

- Existing same-day physiometrics rows written under the old schema are considered corrupted because overwritten source snapshots cannot be recovered from table state alone.
- Reconstitute affected data by rerunning source syncs / replay flows for the desired date window after deploying this change.

**Breaking Changes**:

| Surface | Old | New | Migration |
| --- | --- | --- | --- |
| `Physiometrics.RowKey` | `YYYY-MM-DD` | `YYYY-MM-DD\|source` | Clear/reconstitute physiometrics data by replaying source syncs |
| Config history timestamp | Derived from `RowKey` | Reads stored `updated_at_utc` | No client action beyond consuming the corrected field |

**Application SemVer**: `pyproject.toml` v`0.1.0` → v`1.0.0`.

### WeeklyRollups Storage Key Compatibility Fix + Semantic API v5.1.0

**Fixed**: Weekly rollup persistence now uses an Azure Table-compatible partition key delimiter and preserves backward read compatibility for legacy rows.

**Changes**:

- **Storage write fix**: `WeeklyRollups` upserts now write `PartitionKey` as `athlete_id|YYYY`.
- **Read compatibility**: weekly rollup reads query both `athlete_id|YYYY` (preferred) and legacy `athlete_id#YYYY` partitions.
- **Payload hardening**: unsupported nested values and non-finite numeric values are filtered from weekly rollup entity writes.
- **Schema alignment**: weekly rollup strict schema now includes `athlete_home_timezone`, `week_start_local`, and `week_end_local`.

**Semantic API SemVer**: `openapi.yaml` v`5.0.0` → v`5.1.0` (backward-compatible optional field additions).

## 2026-03-12

### Weekly Rollup Persistence Timer + Local-Week Semantics

**Changed**: Added a Monday timer that computes and persists weekly rollups for the previous completed week.

**Changes**:

#### Semantic Layer [semantic_layer.py] (weekly rollup persistence)

- **New**: `compute_and_persist_previous_week_rollup()` for deterministic previous-week rollup generation and storage.
- **New**: Athlete-home-timezone local week windowing helper methods for weekly inclusion logic.
- **Behavior**: Weekly rollup grouping now supports athlete local-week semantics for persisted rows.

#### Function App [function_app.py]

- **New timer**: `weekly_rollup_timer` scheduled every Monday at 05:00 UTC.
- **Behavior**: Computes previous completed week and upserts weekly rollup row for default athlete when athlete timezone is configured.

#### Storage Semantics [WeeklyRollups]

- **New persisted fields**: `athlete_home_timezone`, `week_start_local`, `week_end_local`.
- **Compatibility**: Existing UTC fields remain present (`week_start_utc`, `week_end_utc`).

**Ingestion SemVer**: Persisted storage semantics changed for `WeeklyRollups` row shape (new weekly timezone/window context fields).

### Config Update Envelope Expansion (`/api/config/update`)

**Changed**: Expanded `POST /api/config/update` to support effective-date writes and extensible metadata while keeping backward compatibility.

**Changes**:

- **New request field**: `as_of` (`YYYY-MM-DD`) for effective-date persistence in Physiometrics.
- **New request section**: `athlete_info` (including `home_timezone` as canonical operational timezone).
- **New request section**: `gear` (extensible athlete equipment metadata).
- **Behavior**: Weekly rollup timezone resolution now prefers active `AgentPreferences` (`category=athlete_home_timezone`), then `athlete_info.home_timezone`, then legacy `athlete_timezone`, then env/config fallback.
- **Compatibility**: Existing `heart_rate` + `power` payloads remain valid.

**Storage Semantics**:

- Extended config sections are preserved via extensibility payload storage (`ext_json`) to avoid lossy round-trips.

**Ingestion SemVer**: No ingestion parser/record schema changes; this is an operational config contract and timezone resolution precedence update.

## 2026-03-11

### **BREAKING:** Semantic API v5.0.0 - Weekly Rollups Strict Schema Enforcement

**Changed**: `GET /api/rollups/weekly` now returns strict-schema rollup items and no longer passes through legacy or unmodeled fields from `WeeklyRollups` table entities.

**Motivation**: Stored weekly rollup entities may contain historical fields from older data shapes. Returning raw entities leaked undocumented keys to API consumers and created contract drift versus `WORKOUT_SCHEMA.md` and OpenAPI.

**Changes**:

#### Semantic Layer [semantic_layer.py] (v5.0.0)

- **Updated**: `_get_weekly_rollups()` now normalizes table entities to documented `WeeklyRollups` fields only.
- **Updated**: Malformed rows missing required weekly rollup fields are skipped with structured warning logs.

#### OpenAPI [openapi.yaml] (v5.0.0)

- **Version bump**: v4.0.0 -> v5.0.0 (breaking change)
- **Updated schema**: `WeeklyRollups` and nested rollup item now explicitly disallow additional properties.
- **Updated schema**: Required rollup fields are explicitly declared in schema.

#### Semantic Docs [SEMANTIC_LAYER_API.md] (v5.0.0)

- **Updated**: Weekly rollups response section now states strict-schema behavior (legacy/unmodeled keys excluded).

**Breaking Changes**:

| Endpoint | v4.x (Old) | v5.0.0 (New) | Migration |
| --- | --- | --- | --- |
| `GET /api/rollups/weekly` | Could include extra legacy/unmodeled keys from storage entities | Returns only documented `WeeklyRollups` fields | Remove dependency on undocumented keys; use only schema-defined fields |

**Ingestion SemVer**: No ingestion schema or persisted storage semantics changes in this update (query-time response shaping only).

## 2026-03-05

### **BREAKING:** Semantic API v4.0.0 - Typed Deep-Dive Workout Metrics Response

**New Feature**: `GET /api/workouts/{workout_id}` now returns a typed deep-dive response with nested `metrics: WorkoutMetricsModel`.

**Motivation**: The deep-dive endpoint previously returned a large flat payload shape that diverged from the domain model architecture. `WorkoutMetricsModel` already existed as the authoritative compositional analytics model but was not used as the API contract. This change aligns endpoint response semantics with the OO model surface.

**Changes**:

#### Models [core.py] (v4.0.0)

- **New**: `WorkoutDetailResponse` in `TrainingAnalyticsPlatform/models/core.py`
  - Top-level identity: `workout_id`, `athlete_id`, `source_system`
  - Nested metrics: `metrics` (`WorkoutMetricsModel`)
  - Optional deep-dive additions: `laps`, `laps_count`, `lap_errors`, `developer_fields_summary`, `developer_fields_error`
- **New**: `WorkoutMetricsModel.from_canonical_metrics()` helper to map canonical analytics output into compositional typed model families.

#### Semantic Layer [semantic_layer.py] (v4.0.0)

- **Updated**: `get_workout_detail()` now emits `WorkoutDetailResponse` (serialized dict) instead of a flat `WorkoutSummary`-shaped payload.
- **Updated**: Metadata payload handling now guards for non-dict values before model mapping.
- **Updated**: Lap fallback errors are surfaced in `lap_errors`.

#### OpenAPI [openapi.yaml] (v4.0.0)

- **Version bump**: v3.2.0 -> v4.0.0 (breaking change)
- **Updated schema**: `WorkoutDetail` now defined as typed envelope with nested `WorkoutMetricsModel`
- **New schema**: `WorkoutMetricsModel` component for deep-dive response payload

**Breaking Changes**:

| Endpoint | v3.2.0 (Old) | v4.0.0 (New) | Migration |
| --- | --- | --- | --- |
| `GET /api/workouts/{workout_id}` | Flat payload with direct metric keys (`hr_avg_bpm`, `tss`, `decoupling_pct`, ...) | Typed envelope with nested `metrics` families (`metrics.samples.hr_avg_bpm`, `metrics.training_load.tss`, `metrics.durability.decoupling_pct`, ...) | Update clients to read metric fields from `metrics.*` paths. Keep top-level identity/lap/developer fields unchanged semantics-wise. |

**Backward Compatibility**:

- `GET /api/workouts` and `GET /api/planning/context` remain on `WorkoutProjection` (no response-shape changes)
- Deep-dive consumers must migrate field access from flat keys to nested `metrics.*`

**Ingestion SemVer**: No ingestion schema or persisted semantics changes in this update (API-contract-only major bump).

### **BREAKING:** Semantic API v3.2.0 - Workout Projections for Efficient Planning Context

**New Feature**: Introduced lightweight `WorkoutProjection` model for efficient batch queries.

**Motivation**: Planning context and workout list operations previously returned full `WorkoutSummary` objects (80+ flattened fields including all HR zones, power zones, efficiency metrics). This required full metric computation on every query and resulted in large payloads (~500 fields per workout, ~100-150 when flattened). `WorkoutProjection` optimizes for the common case: batch planning pulls where clients need identity + summary + data flags without deep analysis.

**Changes**:

#### Models [core.py]

- **New**: `WorkoutProjection` typed model in `TrainingAnalyticsPlatform/models/core.py`
  - Identity: workout_id, sport, device, timestamps
  - Session summary: duration, distance, elevation, calories
  - Data availability flags: has_power, has_hr, has_gps
  - Sport peaks if available: hr_avg/max_bpm, pwr_avg/max_watts, pwr_normalized_watts, cad_avg/max_rpm
  - Status/enrichment flags: is_indoor, race_flag, commute_flag
  - Provenance: ingestion_version, ingestion_timestamp_utc
  - Built directly from Workouts table + metadata.json (no computation)

#### Semantic Layer [semantic_layer.py]

- **New**: `build_workout_projection(entity, ingestion_id)` — Builder method to construct projections from table entities
- **New**: `_get_workout_projections_in_range()` — Query method returning `WorkoutProjection[]` (efficient batch alternative to `_get_workouts_in_range`)
- **Updated**: `get_planning_context()` — Now returns `recent_workouts` as `WorkoutProjection[]`; maintains full workouts internally for analysis (last_hard_day, etc.)
- **Updated**: `get_workouts()` — Now returns projections for list responses (clients drill down via `/api/workouts/{workout_id}` for full metrics)

#### OpenAPI [openapi.yaml]

- **Version bump**: v3.1.0 → v3.2.0 (breaking change)
- **New schema**: `WorkoutProjection` (documented as optimized for batch queries)
- **Updated schema**: `WorkoutSummary` marked `deprecated: true` (backward reference only)
- **Updated response types**:
  - `/api/workouts`: `WorkoutsList.workouts` items now `WorkoutProjection` (was `WorkoutSummary`)
  - `/api/planning/context`: `recent_workouts` now `WorkoutProjection[]` (was generic `object[]`)
- **Updated descriptions**: Documented new response format and migration path ("For full metrics, query `/api/workouts/{workout_id}`")

**Breaking Changes**:

| Endpoint | v3.1.0 (Old) | v3.2.0 (New) | Migration |
| --- | --- | --- | --- |
| `GET /api/workouts?limit=50` | `WorkoutSummary[]` (80+ fields) | `WorkoutProjection[]` (30 fields) | Clients using zone fields (hr_z2_sec, etc.) must call `/api/workouts/{workout_id}` to get full `WorkoutDetail` |
| `GET /api/planning/context` | `recent_workouts`: `WorkoutSummary[]` | `recent_workouts`: `WorkoutProjection[]` | Same as above |
| `GET /api/workouts/{workout_id}` | `WorkoutDetail` (full metrics) | `WorkoutDetail` (full metrics) | **No change** — still returns all zones, efficiency, duration curves |

**Benefits**:

- **Payload reduction**: ~40-50% smaller responses (30 direct fields vs 80+ computed)
- **Computation savings**: No metric computation for list/planning queries (avoid CanonicalAnalyticsEngine overhead)
- **Batch efficiency**: Planning context can load 10-50 workouts without metric computation
- **Preserved drill-down**: Full metrics still available via `/api/workouts/{workout_id}`

**Backward Compatibility**:

- Old clients expecting `WorkoutSummary` in list responses will see incompatible schema
- Recommended: Update consumers to handle `WorkoutProjection` and fetch full details on demand
- `WorkoutSummary` schema preserved in OpenAPI for reference but deprecated

**Ingestion SemVer**: [models/core.py v1.0.0] — `WorkoutProjection` is new, non-breaking for ingestion pipeline

## 2026-03-06

### Ingestion Provenance Version Fallback Fix [ingestion v15.1.2]

#### Fixed: Hardcoded Provenance `ingestion_version` Default

**Issue**: Ingestion provenance metadata used a hardcoded fallback value (`"1.0.0"`) when `source_info.ingestion_version` was absent.

**Fix** (`ingestion_base_handler.py`): Use `INGEST_VERSION` constant as the default provenance version source.

- Before: `source_info.get("ingestion_version", "1.0.0")`
- After: `source_info.get("ingestion_version", INGEST_VERSION)`

**Impact**: New ingestions now persist the correct ingestion code version in `provenance.ingestion_version` instead of an unrelated static value.

**SemVer Bump**: Ingestion `v15.1.1` -> `v15.1.2` (patch behavioral fix for persisted provenance version value).

### Storage & Endpoint Fixes + ID Separation [ingestion v15.1.1]

#### Fixed: Resting HR Storage Mapping Bug

**Issue**: Physiometrics snapshot flat key `resting_hr_bpm` (from Intervals adapter) was not being read by storage layer. Storage layer attempted to read nested `heart_rate.resting_hr_bpm` (legacy pattern), which was absent in Intervals flow, causing all resting HR values to default to 60.

**Fix** (`physiometrics_storage.py:94`): Implemented three-tier fallback:

1. Check flat key `resting_hr_bpm` (Intervals path — primary)
2. Fall back to nested `heart_rate.resting_hr_bpm` (legacy compatibility)
3. Default to 60 if both absent

**Impact**: Intervals ingestion now correctly persists actual resting HR values instead of forcing 60.

#### Fixed: Intervals Endpoint + Handler ID Separation (Critical)

**Issue**: Intervals sync endpoint and handler used one `athlete_id` for two distinct purposes:

1. Intervals API URL identity (e.g., `i508584` — Intervals backend account ID)
2. Storage partition identity (e.g., `rob` — local canonical athlete)

This coupling prevented fetching data from one Intervals account (e.g., `i508584`) while storing under a canonical athlete partition (e.g., `rob`). Additionally, physiometrics from different sources (Intervals, Garmin) for the same athlete were fragmented across multiple partitions instead of being co-located.

**Fix** (`function_app.py:909–990` + `intervals_sync_handler.py:34–73`): Split identities explicitly; unify partition key by canonical athlete.

**Endpoint resolution** (`function_app.py`):

- `intervals_athlete_id`: body → query params → `INTERVALS_ATHLETE_ID` env (required for API fetch, returns 400 if absent)
- `athlete_id`: body → query params → `DEFAULT_ATHLETE_ID` env → default `"rob"` (canonical athlete for storage partition)

**Handler signature** (`intervals_sync_handler.py`):

- Changed `handle(athlete_id, lookback_days)` → `handle(intervals_athlete_id, athlete_id, lookback_days)`
- Uses `intervals_athlete_id` only for `client.get_athlete_wellness(...)` API call
- Uses `athlete_id` only for storage PartitionKey and canonical snapshot mapping
- Validates `intervals_athlete_id` required; `athlete_id` has default fallback
- **All physiometrics for the same canonical athlete (`athlete_id`) are now co-located in one table partition**, regardless of source (Intervals, Garmin, etc.)

**Storage Impact**: Partition key is canonical `athlete_id`. Example:

- Fetch from Intervals account `i508584`, store under canonical athlete `rob`:
  - PartitionKey: `rob` (not `i508584`)
  - RowKey: `effective_date`
- All Intervals + Garmin + other source data for athlete `rob` accumulates in same partition

**Migration Note**: Existing Intervals physiometrics stored under partition `i508584` (from before split) remain as-is. New Intervals syncs use canonical partition `athlete_id`.

Example request:

```http
POST /api/intervals/sync?intervals_athlete_id=i508584&athlete_id=rob&lookback_days=7
```

→ Fetches using `i508584` from Intervals backend API  
→ Stores with PartitionKey=`rob` in Physiometrics table (canonical athlete partition)  
→ All data for athlete `rob` now co-located regardless of source

#### Enhanced: Intervals Handler Diagnostics

**Feature** (`intervals_sync_handler.py:165`): Added field-presence diagnostics before validation in `_store_single_measurement()`.

Structured logging now includes boolean flags for each parsed metric:

- `has_hrv` — hrv_ln_rmssd present in source
- `has_readiness` — readiness_score present in source
- `has_nutrition` — nutrition fields (carbs/protein/fat) present in source
- `has_resting_hr` — resting_hr_bpm present in source

**Purpose**: Distinguish upstream sparse payloads (source doesn't provide field) from storage layer drops (field present but not persisted).

#### Added: Test Coverage

**Endpoint tests** (`test_function_app_extras.py`): 6 new tests for split ID behavior:

- `test_intervals_sync_requires_intervals_athlete_id` — verify API ID is required
- `test_intervals_sync_intervals_athlete_id_from_body` — body precedence for fetch ID
- `test_intervals_sync_intervals_athlete_id_from_query_param` — query param fallback for fetch ID
- `test_intervals_sync_intervals_athlete_id_from_env` — env fallback for fetch ID
- `test_intervals_sync_athlete_id_defaults_to_default_athlete_id` — storage ID default
- `test_intervals_sync_lookback_days_from_query_param` — lookback_days parameter

**Handler tests** (`test_intervals_sync_handler.py`): Updated to assert split IDs:

- Handler receives both `intervals_athlete_id` and `athlete_id` as separate parameters
- `client.get_athlete_wellness()` called with `intervals_athlete_id` (fetch identity)
- `store_physiometrics()` called with `athlete_id` (storage partition identity)

**Storage tests** (`test_table_storage_physiometrics.py`): 4 persistence assertions:

- `test_store_physiometrics_resting_hr_from_flat_key`
- `test_store_physiometrics_resting_hr_defaults_to_60_when_absent`
- `test_store_physiometrics_nutrition_macros_persisted`

**SemVer Bump**: Ingestion v15.1.0 → v15.1.1 (patch bug fix to storage mapping + handler ID separation semantics).

### **BREAKING:** Configuration Precedence Reversed - PhysiometricsSnapshot Primary

**Issue**: Configuration system prioritized environment variables over frequently-updated PhysiometricsSnapshot data from Azure Table Storage.

**Old (Wrong) Precedence**:

1. Environment variables (highest priority) ❌
2. physiometrics.json or Table Storage
3. Hard defaults

**New (Correct) Precedence** [`platform/config.py`]:

1. **PhysiometricsSnapshot from Table Storage** (primary - updated frequently) ✅
2. Environment variables (fallback - only if physiometrics missing)
3. Hard defaults (only if both above missing)

**Changes** (`TrainingAnalyticsPlatform/platform/config.py`):

- `hr_config()`: Loads physiometrics heart_rate block FIRST, then checks env vars as fallback
- `power_config()`: Loads physiometrics power block FIRST, then checks `DEFAULT_FTP` env var as fallback
- `_resolve_lthr_bpm()` and `_resolve_hr_max_bpm()`: Check physiometrics values FIRST before env var
- Simplified method signatures: Removed `env_basis` parameter from helpers; check physiometrics data structure directly

**Updated Documentation** [`config/README.md`]:

- "Configuration Precedence" section now accurate: Table Storage → Env Vars → Defaults
- Added emphasis: "Frequently updated with current athlete metrics (LTHR, FTP, etc.)" for Table Storage tier

**Test Updates** (`tests/test_config.py`):

- Renamed: `test_hr_config_env_override_*` → `test_hr_config_env_fallback_*`
- Added: `test_hr_config_physiometrics_overrides_env_basis` — verifies physiometrics takes priority
- Added: `test_hr_config_physiometrics_overrides_env_resting_hr` — verifies physiometrics takes priority
- Added: `test_power_config_physiometrics_overrides_env` — verifies physiometrics takes priority
- All 31 config tests pass ✅

**Impact**: Workouts now use current athlete physiometrics (LTHR, FTP, HR zones) from Table Storage exclusively. Environment variables serve only as fallback for unset values or local development.

## 2026-03-06-earlier

### **BREAKING:** PhysiometricsSnapshot v3.0.0 - Simplified Schema [canonical v3.0.0, ingest v15.0.0]

Major schema simplification establishing canonical as facts-only layer with exclusive source ownership and direct ingestion.

#### Schema Simplification: 30 Fields (down from 40+)

**Retained Essential Fields (25 metric fields + 4 metadata + 1 data_sources = 30 total)**:

- **Body composition (Withings exclusive)**: `weight_kg`, `fat_mass_kg`, `muscle_mass_kg`, `bone_mass_kg`, `body_fat_pct` (5 fields)
- **Recovery metrics (Intervals exclusive)**: `hrv_ln_rmssd`, `sleep_duration_sec`, `resting_hr_bpm` (3 fields)
- **Activity (Intervals exclusive)**: `steps` (1 field)
- **Nutrition (Intervals exclusive)**: `calories_kcal`, `carbs_g`, `protein_g`, `fat_g` (4 fields)
- **Performance baselines (Garmin exclusive)**: `ftp_watts`, `cycling_vo2max_ml_kg_min`, `hr_lthr_bpm`, `hr_max_bpm` (4 fields)
- **Training state (Garmin exclusive)**: `training_load`, `recovery_time_minutes`, `readiness_score` (3 fields)
- **Extended training (Garmin exclusive)**: `training_effect_aerobic`, `training_effect_anaerobic`, `training_stress_score`, `training_stress_balance`, `atp_probability` (5 fields)
- **Metadata**: `athlete_id`, `effective_date`, `data_sources`, `canonical_version`, `last_updated_utc` (5 fields)

**Removed Fields (15+ fields eliminated)**:

- Body composition: `visceral_fat_index`, `metabolic_age_years` (marginal utility)
- Recovery: `hrv_sdnn_ms` (RMSSD sufficient), `running_vo2max_ml_kg_min` (cycling primary use case)
- Training: `lactate_threshold_hr_bpm` (deprecated in favor of `hr_lthr_bpm`)
- Subjective wellness: `subjective_soreness`, `subjective_fatigue`, `subjective_stress`, `subjective_mood`, `subjective_motivation`, `subjective_injury` (6 fields - inconsistent manual entry)
- Extended body metrics: `body_abdomen_cm`, `spo2_pct`, `systolic_bp`, `diastolic_bp`, `vo2max_ml_kg_min` (5 fields - not core training metrics)
- Menstrual tracking: `menstrual_phase`, `menstrual_phase_predicted` (2 fields - out of scope for MVP)
- Sport-specific: `sport_info_json` (redundant with Workouts table sport metadata)
- Raw preservation: `raw_intervals_icu_json`, `ext_json`, `full_config_json` (3 fields - blob-first pattern abandoned)
- Nested structures: `heart_rate` dict (resting/lthr/max), `power` dict (FTP) - flattened to scalar fields

#### Exclusive Source Ownership (No Fallbacks)

**Breaking change**: Each field now owned by **exactly one source**. Fallback chains eliminated for deterministic consolidation.

**Source Precedence Table**:

- **Withings exclusive**: All 5 body composition fields
- **Intervals exclusive**: All 8 recovery/nutrition/activity fields (resting HR, steps)
- **Garmin exclusive**: All 12 performance/training fields

**Adapter changes**:

- `GarminTrainingStateAdapter`: **Explicitly ignores** `resting_hr_bpm` and `steps` (Intervals exclusive)
- `IntervalsPhysiometricsAdapter`: **Explicitly ignores** `weight_kg` and `body_fat_pct` (Withings exclusive)
- `SourcePrecedenceResolver.METRIC_SOURCES`: Updated to single-source arrays (no fallbacks)

#### Direct Ingestion Pattern (Blob-First Removed)

**Breaking change**: Abandoned blob-first reproducible ingestion pattern.

**Old flow**: `Fetch → Blob → SourceIngestionState → Processor → Canonical`  
**New flow**: `Fetch → Validate → Upsert` (direct to Physiometrics table)

**Removed components**:

- `SourceIngestionState` table (blob processing tracker)
- `external-sources` blob container (raw API responses)
- Withings/Garmin/Intervals processor jobs
- Replay-from-blob capability

**Rationale**: Wellness data is sparse and low-volume; blob storage overhead not justified. Source APIs remain queryable for historic replay.

#### Storage Schema Flattened

**Breaking change**: Removed nested dictionary structures from `to_storage_dict()`.

**Old structure**:

```python
"heart_rate": {"resting_bpm": 52, "lthr_bpm": 165, "max_bpm": 195}
"power": {"ftp_watts": 285}
```

**New structure**:

```python
"resting_hr_bpm": 52
"hr_lthr_bpm": 165
"hr_max_bpm": 195
"ftp_watts": 285
```

**Impact**: Simpler queries; no nested JSON parsing required.

#### TrainingState: On-Demand Projection (Table Removed)

**Breaking change**: `TrainingState` table **deleted**. TrainingState now computed on-demand for each API request.

**Removed**:

- `TrainingState` Azure Table Storage table
- `TrainingStateConsolidationHandler` nightly job
- `TrainingStateSnapshot` persistence logic

**New architecture**:

- `SemanticLayer.compute_current_training_state()`: Fresh computation from Workouts + Physiometrics
- `SemanticLayer.compute_training_state_history()`: Daily projections for date range
- API endpoints compute on request: `GET /api/training-state/current`, `GET /api/training-state/history`

**Computation**:

- Rolling TSS (7-day, 28-day windows) from Workouts table
- CTS (chronic training stress) = TSS_28d / 28
- ATS (acute training stress) = TSS_7d / 7
- Fatigue index = ATS / CTS
- Composite readiness from HRV + Garmin readiness

**Performance**: Pandas/NumPy aggregation efficient; <500ms for 45-day history.

#### Versioning & Migration

- **Major version bump**: `canonical_version` `2.6.0` → `3.0.0`
- **Ingest version bump**: `INGEST_VERSION` `v14.4.2` → `v15.0.0`
- **Migration**: Breaking schema changes require replay from source APIs (no blob archive available)
- **Backward compatibility**: None - v2.x code cannot read v3.0.0 schema

#### Documentation Updates

- **Section V**: Rewritten to document direct ingestion, 30-field schema, exclusive ownership
- **Section VI**: Rewritten to emphasize TrainingState as projection (not table)
- **Storage diagrams**: Updated to remove blob containers and TrainingState table

#### Testing

- **Updated**: 11 tests in `test_physiometrics_model.py` to v3.0.0 schema
- **Removed assertions**: Deleted fields (visceral_fat, nested structures, subjective wellness, sport_info, raw JSON)
- **Added tests**: Training state and extended training metrics validation
- **Test results**: 11/11 passing

#### Rationale

This major version represents architectural discipline: canonical captures **raw facts only**, not derived analytics or speculative nice-to-have metrics. TrainingState projection enforces immutability (compute from immutable sources) and eliminates materialization complexity. Schema reduced to essential training intelligence fields with clear source responsibility boundaries.

---

## 2026-03-05 (Pre-v3.0.0)

### Physiometrics Source Precedence Alignment [semantic layer, canonical v2.6.0]

- **Policy alignment**: Consolidated physiometrics precedence now explicitly enforces source ownership by metric:
  - Intervals.icu dominant for wellness/recovery fields (HRV, sleep, subjective metrics).
  - Garmin dominant for training metrics, FTP, VO2Max, readiness, and training load fields.
  - Withings dominant for weight/body composition fields (weight, fat mass, muscle mass, BMI-derived).
- **Endpoint behavior change**: `GET /api/physiometrics/current` now consolidates the latest row per source (Intervals/Garmin/Withings) applying metric-level precedence rules instead of returning a single-source snapshot. Metadata fields added:
  - `data_sources` (CSV): list of sources contributing to current snapshot
  - `source_effective_dates` (dict): per-source date tracking for data freshness visibility
- **Fix**: Consolidation now supports both `data_source` and `data_sources` source identity fields when resolving ownership.
- **Fix**: Consolidation now resolves canonical-vs-storage aliases for physiometrics fields (e.g., `ftp_watts`/`power_ftp_watts`, `resting_hr_bpm`/`heart_rate_resting_bpm`).
- **Fix**: Circular import resolved in semantic layer; extracted precedence constants locally to eliminate handlers package dependency for current endpoint.
- **Tests**: Added 8 comprehensive tests in `test_physiometrics_current_consolidated.py` covering:
  - Multi-source consolidation with per-source row fetching and latest-per-source tracking
  - Metric-level precedence (Intervals wellness vs Garmin training vs Withings body comp)
  - Timestamp-based tiebreaker when effective_date is identical across sources
  - Storage alias field resolution
- **Docs**: Updated semantic API and canonical architecture docs to reflect consolidated-vs-raw physiometrics read semantics; added explicit precedence matrix.

### Garmin Training Status Payload Mapping Fix [ingest v14.4.2]

- **Fix**: Updated Garmin physiometrics adapter to parse current Garmin Connect `get_training_status()` payload shape (`mostRecentVO2Max`, `mostRecentTrainingLoadBalance`, `mostRecentTrainingStatus.latestTrainingStatusData`) instead of only legacy flat keys.
- **Impact**: Garmin training metrics now populate queryable Physiometrics columns during sync when values are present in the source payload.
- **Versioning**:
  - `INGEST_VERSION` bumped `v14.4.1` -> `v14.4.2`

### FIT Field Decoding Fix [ingest v14.4.1]

- **Fix**: Normalize FIT `left_right_balance` field by extracting 7-bit percentage from raw uint8 byte. FIT spec encodes percentage in bits 0-6 with bit 7 as a right-side flag; fitdecode returns raw byte without masking. Apply `& 0x7F` mask during canonical record construction to ensure values conform to documented 0-100 constraint. Fixes validation errors on activities with biased left_right_balance values (e.g., raw byte 184 → 56% contribution). Structured logging records decode normalization for traceability.

## 2026-03-04

### Garmin Physiometrics Expansion [canonical v2.5.0, ingest v14.4.0]

- **Feature**: Added Garmin physiometrics sync path that ingests both daily summary and training status.
- **New endpoint**: `POST /api/garmin/physiometrics/sync`
- **New timer**: Garmin physiometrics sync runs daily at 3:30 AM UTC.
- **Garmin client additions**:
  - `get_user_summary(date)` for daily summary metrics
  - `get_training_status(date)` for training effect/recovery metrics
- **Canonical physiometrics additions** (queryable):
  - `running_vo2max_ml_kg_min`
  - `training_load`
  - `training_effect_aerobic`
  - `training_effect_anaerobic`
  - `training_stress_score`
  - `training_stress_balance`
  - `atp_probability`
  - `recovery_time_minutes`
  - `lactate_threshold_hr_bpm`
- **LTHR behavior change**:
  - `hr_lthr_bpm` now prefers Garmin-reported lactate threshold HR when available.
  - Falls back to `85%` of max HR only when training status does not provide LTHR.
- **Storage changes**: Added direct columns for the new queryable Garmin training fields while preserving full source payloads in `ext_json`.
- **Versioning**:
  - `PhysiometricsSnapshot.canonical_version` bumped `2.4.0` → `2.5.0`
  - `INGEST_VERSION` bumped `v14.3.11` → `v14.4.0`

### Sleep Duration Field Refactor [canonical v2.4.0, ingest v14.3.11] **BREAKING**

- **Schema change**: Renamed `sleep_duration_min` → `sleep_duration_sec` to store sleep in seconds (no conversion)
- **Rationale**: Preserve raw Intervals API value (`sleepSecs`) without transformation, aligning with zero-loss ingestion principles
- **Breaking changes**:
  - Field name: `PhysiometricsSnapshot.sleep_duration_min` → `PhysiometricsSnapshot.sleep_duration_sec`
  - Storage column: `sleep_duration_min` → `sleep_duration_sec`
  - Unit: minutes → seconds (multiply previous values by 60)
- **Adapter changes**:
  - Removed seconds-to-minutes conversion in `IntervalsPhysiometricsAdapter._do_parse()`
  - Now stores `sleepSecs` directly from Intervals API response
- **Storage layer**: Updated column mappings and field references across all storage/adapter/handler code
- **Versioning**:
  - `PhysiometricsSnapshot.canonical_version` bumped `2.3.0` → `2.4.0` (MAJOR component: breaking field change)
  - `INGEST_VERSION` bumped `v14.3.10` → `v14.3.11`
- **Migration**: Active development branch; no data migration required (can overwrite existing records)

### Intervals Blob Contract Cleanup [canonical v2.3.0, ingest v14.3.10]

- **Storage contract update**:
  - Persist unmodified source payload in `raw_intervals_icu_json`
  - Persist canonical extended metrics in `ext_json`
  - Keep queryable scalar columns for filtering/analytics
- **De-duplication**:
  - Removed recursive duplication pattern that embedded source blobs inside `full_config_json`
  - New writes no longer depend on `full_config_json`; legacy reads remain compatible
- **Model/adapter changes**:
  - `PhysiometricsSnapshot` now uses `raw_intervals_icu_json` + `ext_json`
  - Intervals adapter populates both blobs while preserving canonical scalar mappings
  - Withings/Garmin adapters keep these blobs as `None`
- **Versioning**:
  - `PhysiometricsSnapshot.canonical_version` bumped `2.2.0` → `2.3.0`
  - `INGEST_VERSION` bumped `v14.3.9` → `v14.3.10`

### Zero-Loss Intervals Ingestion + Minimal Canonical Boundary [canonical v2.2.0, ingest v14.3.9]

- **Feature**: Preserve full Intervals daily payload while maintaining minimal queryable canonical metrics
- **Canonical additions**:
  - `hrv_sdnn_ms`, `spo2_pct`, `systolic_bp`, `diastolic_bp`, `vo2max_ml_kg_min`
  - `menstrual_phase`, `menstrual_phase_predicted`
  - `source_updated_at_utc`
- **Raw catch-all preservation**:
  - `source_payload_json`: full source day payload, serialized JSON
  - `source_field_index_json`: sorted array of source field names present in payload
- **Intervals mapping expansion**:
  - Body composition pass-through from Intervals (`weight`, `bodyFat`) is now ingested as optional canonical values
  - Existing extended fields retained (subjective, nutrition, activity, sport_info)
- **Storage contract**:
  - Added corresponding queryable columns in `Physiometrics` table for optional canonical metrics
  - Added source payload columns to preserve zero-loss semantics
  - Fallback reconstruction updated to include raw/source fields when `full_config_json` is unavailable
- **Architecture policy**:
  - Source precedence remains **post-ingestion** (semantic/read layer), not ingest-time
  - Supports null-tolerant edge cases where one source is missing and another has data
- **Versioning**:
  - `PhysiometricsSnapshot.canonical_version` default updated `2.1.0` → `2.2.0`
  - `INGEST_VERSION` updated `v14.3.6` → `v14.3.9`

### Extended Wellness Field Ingestion [canonical v2.1.0, ingest v14.3.8]

- **Feature**: Extended PhysiometricsSnapshot model to capture 15 additional wellness fields from Intervals.icu API
- **New field categories**:
  - **Subjective wellness** (0-10 scales): soreness, fatigue, stress, mood, motivation, injury
  - **Nutrition** (macros): calories_kcal, carbs_g, protein_g, fat_g
  - **Activity metrics**: steps (daily step count)
  - **Body composition**: abdomen_cm (waist circumference)
  - **Sport-specific data**: sport_info (nested array with type, load, CTL per sport)
- **Storage strategy**:
  - Dual persistence: Individual queryable columns (e.g., `subjective_soreness`, `nutrition_calories_kcal`) + full_config_json blob
  - Nested sport_info array serialized to `sport_info_json` string column (JSON format)
  - Azure Table Storage: 40 active columns (well under 252 limit)
- **Implementation changes**:
  - `PhysiometricsSnapshot` model: Added 15 Optional fields with Pydantic validation (ge=0, le=10 for subjective scales)
  - `to_storage_dict()`: Extended with new field mappings and JSON serialization for sport_info
  - `IntervalsPhysiometricsAdapter`: Extended `_do_parse()` to extract 20 fields (up from 5), updated `map_to_canonical()` with new parameters
  - `physiometrics_storage.py`: Added 15 storage column mappings for queryable persistence
- **Testing**: Comprehensive test coverage added
  - Model tests: `test_to_storage_dict_includes_extended_wellness_fields()`, `test_to_storage_dict_handles_null_extended_fields()`, `test_to_storage_dict_sport_info_empty_list()`
  - Adapter tests: `test_adapter_maps_extended_wellness_fields()`, `test_adapter_handles_missing_extended_fields()`, `test_adapter_handles_partial_extended_fields()`, `test_adapter_sport_info_empty_list()`
- **Backward compatibility**: All new fields Optional (None-safe), no breaking changes to existing code
- **Version**: canonical_version bumped from "2.0.0" → "2.1.0" (SemVer MINOR for additive non-breaking extension)
- **API alignment**: Extracts fields from Intervals GET /api/v1/athlete/{id}/wellness endpoint (46 total fields available, 20 now captured)

### Intervals Wellness API Contract Alignment [ingest v14.3.7, integrations v1.1.0]

- **Fix**: Align Intervals client to documented wellness API contract
- **Auth update**: Use HTTP Basic API key auth (`API_KEY` username + API key password) instead of bearer API-key header
- **Endpoint update**: Migrate to `/api/v1/athlete/{id}/wellness` with `oldest`/`newest` query params
- **Schema mapping update**:
  - `id` (or legacy `date`) → `effective_date`
  - `restingHR` (or legacy `rhr`) → `resting_hr_bpm`
  - `sleepSecs` (or legacy `sleep`) → `sleep_duration_sec` (preserved in seconds)
  - `hrv` and `readiness` preserved
- **Compatibility**: Keep client aliases for existing HRV/readiness helper methods via wellness endpoint
- **Tests/docs**: Update Intervals client and sync handler tests plus wellness/architecture docs for updated contract
- No persisted schema changes; ingestion parsing semantics updated

## 2026-03-03

### Intervals.icu Physiometrics Integration [integrations v1.0.0]

- **Feature**: New Intervals.icu integration client for daily physiometrics syncing
- **Components added**:
  - `TrainingAnalyticsPlatform/integrations/intervals_client.py`: API client with bearer token auth
  - `TrainingAnalyticsPlatform/handlers/intervals_sync_handler.py`: Handler for physiometrics ingestion
  - Function endpoints: `POST /api/intervals/sync` (on-demand) + timer trigger (2 AM UTC daily)
  - Tests: `tests/test_intervals_client.py`, `tests/test_intervals_sync_handler.py`
- **Data flow**:
  - Fetches HRV (ln(RMSSD)), resting HR, sleep duration, readiness scores from Intervals.icu API
  - Maps through existing `IntervalsPhysiometricsAdapter` to `PhysiometricsSnapshot`
  - Stores to `Physiometrics` table via `StorageCoordinator`
- **Configuration**:
  - `INTERVALS_API_KEY`: stored in Azure Key Vault (managed identity access)
  - `INTERVALS_SYNC_LOOKBACK_DAYS`: configurable lookback (default 30 days)
- **Error handling**:
  - Graceful handling of auth failures (401), not found (404), rate limits (429)
  - Partial success tolerance: invalid measurements logged but don't block batch
  - All failures via `ExternalServiceError` (inherits from `HealthAssistantError`)
- **Infrastructure**: Terraform resources for Key Vault secret (`intervals-api-key`) and Function App env var reference
- No breaking changes; backward compatible with existing physiometrics storage

### Aerobic Decoupling Semantics Clarification [canonical_schema v2.0.1]

- **Enhancement**: Clarify explicit sign convention for aerobic decoupling across all contracts
- **Semantics contract** (affects persisted field interpretation):
  - **Positive**: efficiency decline over time (aerobic fatigue/stress)
  - **Negative**: efficiency improvement over time (warming up or aerobic economy gains)
  - Formula: `decoupling_pct = ((EF_first / EF_second) - 1) * 100`
- **Contract updates**:
  - `CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT.md`: Add semantics section with examples
  - `WORKOUT_SCHEMA.md`: Clarify description as "positive = efficiency decline/fatigue, negative = improvement"
  - `README.md`: Add explicit sign meaning to aerobic efficiency section
  - `openapi.yaml`: Refine decoupling_pct description
- **Test coverage**: Comprehensive sign-semantics tests in `test_semantic_layer.py`:
  - Positive decoupling triggers "high decoupling" flag only when > 5%
  - Negative decoupling (improvement) does not trigger alert
  - Mixed workouts preserve sign in aggregations and API responses
  - Boundary cases validated
- Canonical schema version bumps (patch) to reflect persisted field semantics clarification

### HealthFit Robust Filename Parsing with Spelling Tolerance [ingest v14.3.6]

- **Enhancement**: Tolerate both Apple Watch canonical and FIT-aligned activity type spellings in HealthFit filenames
- HealthFit exports from OneDrive may use either:
  - **Apple Watch canonical**: `"Indoor Cycle"`, `"Outdoor Walk"`, `"Trail Run"` (as defined in HealthKit framework)
  - **FIT-aligned spellings**: `"Indoor Cycling"`, `"Outdoor Walking"`, `"Trail Running"` (aligned with FIT sport types)
- **Solution**: Normalized lookup table (`NORMALIZED_ACTIVITY_TO_CANONICAL`) handles both forms:
  - Normalizes all activity types to hyphenated-lowercase form as key (e.g., `"indoor-cycle"`, `"indoor-cycling"`)
  - Maps both `"indoor-cycle"` and `"indoor-cycling"` aliases to canonical `"Indoor Cycle"`
  - Enables consistent parsing regardless of HealthFit/OneDrive spelling convention
- **Hyphenation robustness**: Combined with existing space/hyphen tolerance, filenames now parse correctly for both:
  - `2026-01-04-163358-Indoor-Cycle-RunGap.fit` (canonical with hyphens)
  - `2026-01-04-163358-Indoor-Cycling-RunGap.fit` (FIT-aligned with hyphens)
  - `2026-01-04-163358-Indoor Cycle-RunGap.fit` (canonical with spaces)
  - `2026-01-04-163358-Indoor Cycling-RunGap.fit` (FIT-aligned with spaces)
- **Device name extraction**: Parsing is now independent of FIT message available—uses normalized lookup to identify activity token boundary, then extracts trailing device name robustly
- No breaking changes; existing "Cycle"/"Walk"/"Run" forms continue to work
- Resolves issues with "Other" single-word activities and ambiguous FIT signals where filename fallback is insufficient

### OneDrive Apple Watch Allowlist + Ingested-Terminal Short-Circuit [ingest v14.3.5]

- **Fix**: Tighten HealthFit/OneDrive filtration to **allowlist Apple Watch only**
- OneDrive ingestion now rejects any non-watch source (`device_source_type != "apple_watch"`), including Garmin/unknown devices that previously slipped through
- Apple Watch detection is explicit (`device_name` or `device_model` containing `"watch"`), not inverse-HealthKit logic
- HealthKit-synced detection remains in place (`device_name` iPhone sentinel and `device_model` iPhone model pattern)
- **Ingestion terminal-state update**: unchanged files now short-circuit only when prior status is `ingested`
- Removed redundant `status="skipped"` writes for already-ingested unchanged files; system now emits debug logs and returns skipped response without mutating `IngestionState`
- Preserves `filtered` and `failed` state recording behavior
- Removed confirmed orphan helpers in `fit_models.py` (`_parse_utc_offset_minutes`, `_build_canonical_session_metadata`) and corrected apple workout fallback docstring drift

### Enhanced HealthKit Filtration Using Device Model [ingest v14.3.4]

- **Enhancement**: Improved HealthKit-synced workout detection to catch workouts synced via third-party apps (RunGap, Zwift, Intervals.icu)
- Add `device_model` property to `BaseFitModel`: extracts FIT file_id product name (e.g., `"iPhone17,1"`, `"Watch7,12"`)
- Enhanced `FitDevice.is_healthkit_synced()` to check both `device_name` AND `device_model` for iPhone indicators
- Pattern detection: Regex `r"iphone\d+,\d+"` matches Apple internal model identifiers (e.g., iPhone17,1, iPhone14,2)
- **Scenario addressed**: RunGap/Zwift sync workout to HealthKit → HealthFit exports with `device_model="iPhone17,1"` but `device_name="RunGap"` or app name
- Previous filtration only checked `device_name="iPhone"` sentinel, missed synced workouts with app name but iPhone product ID
- OneDrive path now filters: `device_name` containing "iphone" OR `device_model` matching iPhone model pattern
- HTTP/payload path: No filtration (unchanged behavior, accepts all devices)
- Defense in depth: Catches HealthKit-synced workouts via both human-readable device name and internal product identifier
- No breaking changes; expands filtration coverage without changing persisted schema

## 2026-03-02

### HealthFit OneDrive Filename Corruption Recovery [ingest v14.3.3]

- **Enhancement**: Recover device name from OneDrive-corrupted HealthFit filenames
- OneDrive inconsistently converts spaces to hyphens in filenames: `"Functional Strength Training"` becomes `"Functional-Strength-Training"`
- **Solution**: Use FIT sport/sub_sport metadata as authoritative source for activity type, then reverse-parse corrupted filename to extract device name
- New `HealthFitModel.device_name` property extracts device name using FIT-derived activity type as anchor
- Denormalization restores known patterns: `Apple-Watch` → `Apple Watch`, `Apple-Watch-Ultra` → `Apple Watch Ultra`
- Handles `.fit` and `.fit.gz` suffixes correctly
- Non-canonical device names (e.g., with model numbers) accepted as-is; e.g., `"Robert's Apple Watch-7"` (model number hyphens preserved)
- No breaking changes; existing filename parsing preserved for canonical (non-corrupted) files
- Enables successful ingestion of HealthFit files from OneDrive despite filename corruption

### HealthFit Canonical Pattern Enforcement [ingest v14.3.2]

- **BREAKING FIX**: Replace hybrid regex/boundary-detection approach (v14.3.1) with strict canonical pattern enforcement
- Canonical HealthFit filename format: `YYYY-MM-DD-HHMMSS-{ActivityType}-{DeviceName}.fit[.gz]`
- Activity types use SPACES only, NO HYPHENS: `"Indoor Cycling"`, `"Functional Strength Training"` (NOT `"Indoor-Cycling"`)
- First hyphen after HHMMSS is ALWAYS the activity/device separator
- Device names preserved exactly as-is from filename: spaces, hyphens, apostrophes all intact
- Regex pattern: `r'^(\d{4}-\d{2}-\d{2})-(\d{6})-([^-]+)-(.+)\.fit(?:\.gz)?$'`
  - Group 1: Date (YYYY-MM-DD, device-local)
  - Group 2: Time (HHMMSS, device-local)
  - Group 3: Activity type (no hyphens allowed)
  - Group 4: Device name (everything to .fit stem, preserved exactly)
- Eliminates complex boundary-detection logic that was corrupting device tokens
- No breaking changes to canonical metadata schema or API contracts

### HealthFit Parsing Simplification [ingest v14.3.1] - DEPRECATED

- ~~Consolidate using hybrid regex/boundary-detection approach~~ (incorrectly allowed hyphens in activity type and corrupted device names)
- ~~Regex captures date, time, and remaining content; boundary detection using Apple workout types~~ (caused hyphen injection)
- ~~Normalizes activity types (converts legacy hyphenated format to spaced format)~~ (failed to enforce canonical format)
- Superseded by v14.3.2 canonical pattern enforcement

### HealthFit Raw Filename Contract + Identity Device Name [ingest v14.3.0]

- Preserve raw OneDrive filename (`item.name`) in `source_file_name` end-to-end; preprocessing logical filename is now stored separately as `source_logical_file_name`
- Fix HealthFit filename parsing for hyphenated source/device names so values like `Robert's-Apple-Watch-7` are preserved in full (no tail-segment truncation)
- Add `identity.device_name` sourced from HealthFit filename `<source/device name>` token while retaining `identity.device_manufacturer` and `identity.device_model` from FIT identity fields
- Keep `provenance.source_device_name` aligned with the full filename-derived source/device token
- Update canonical metadata schema documentation to 2.3.0 and ingestion schema registry to v15.0.36

### HealthFit Workout Naming + Source Device Provenance [ingest v14.2.0]

- Change HealthFit workout-name semantics to constructed naming: `<day part> <apple workout type>` (for example, `Morning Indoor Cycle`) instead of direct filename activity label passthrough
- Preserve full filename source-device token in canonical metadata under `provenance.source_device_name` (for example, `Robert's Apple Watch Ultra 3`)
- Keep device identity semantics separate: `identity.device_manufacturer` and `identity.device_model` continue to represent FIT-derived recording device identity
- Merge (not overwrite) pre-populated provenance fields in ingestion handler so source-derived provenance survives ingestion-context enrichment
- Update canonical metadata schema documentation to 2.2.0 and ingestion schema registry to v15.0.35

### HealthFit Apple Manufacturer Normalization [ingest v14.1.1]

- Normalize Apple-origin HealthFit FIT manufacturer values to canonical `Apple` in identity fields used by Workouts projection and metadata identity zone
- Preserve raw FIT manufacturer provenance in metadata file fields via `file_manufacturer_raw` and `file_manufacturer_code` (e.g., `development`, `255`)
- Normalize Apple Watch internal product identifiers (e.g., `Watch7,12` and `Watch 7,12`) to friendly model names when known
- Correct Apple manufacturer-code branching in product-name resolution (Apple code `255`, not `32`)
- Fix Apple device model extraction when FIT files provide `file_id.product_name` (e.g., `Watch17,2`) but omit `file_id.product`, preventing null `device_model` in Workouts
- Update canonical metadata schema documentation to 2.1.0 and ingestion schema registry to v15.0.34

### Workouts Table Schema Enforcement [ingest v14.0.0 - BREAKING]

- **BREAKING:** Remove `metrics: Dict[str, Any]` field from `WorkoutEntity` class in `storage_infrastructure.py`
- **BREAKING:** Delete `_flatten_structured_metadata()` method from `WorkoutStorage` class - no longer flattens semantic zones into table
- **BREAKING:** Enforce schema constraint `extra="forbid"` on `WorkoutEntity` for strict queryable-only validation
- **Rationale:** Eliminate artifact conflation violation where session metrics, provenance, and enrichment data were being stored in Workouts table (should remain in metadata.json blob or IngestionState table)
- **Impact summary:**
  - Workouts table now stores exactly 19 queryable fields (identity + capabilities + device + pointers)
  - Session metrics, enrichment, provenance, activity metadata now exclusively reside in metadata.json blob or IngestionState table
  - Enforces documented separation of concerns: metadata.json (faithful FIT artifact) | Workouts table (queryable identity) | IngestionState table (provenance)
  - Major version bump signals backward-incompatible schema change
- **Data safety:** Non-breaking for data persistence - metadata.json blob contains all required fields; this change enforces logical separation only
- **Code changes:**
  - `constants.py`: INGEST_VERSION bumped v13.0.32 → v14.0.0
  - `storage_infrastructure.py`: Removed metrics field, metrics collection logic from `from_table_entity()`, metrics expansion from `to_entity()`
  - `workout_storage.py`: Deleted `_flatten_structured_metadata()` method (15 lines), removed flattening call from ingestion flow
  - `semantic_layer.py`: Updated `_entity_to_workout_dict()` to load metadata.json blob for session/enrichment zones instead of reading from removed metrics field
- **Tests:** 11 new schema enforcement tests verify extra="forbid" validation; semantic layer tests updated to mock metadata blob loading; all 481 tests passing
- **Documentation:** Code now enforces documented architecture principle of artifact separation

## 2026-03-01

### Storage Architecture Cleanup [code cleanup - no version bump]

- Remove orphaned `WorkoutTableStorage` class (~1200 lines dead code) from `table_storage.py` following v2.0.0 storage refactor to `StorageCoordinator` architecture
- Update `IngestionContext.storage` type annotation from forward reference `"WorkoutTableStorage"` to `Any` (accepts any storage object with `get_ingestion_state` method)
- Migrate `backfill_ingestion_state.py` utility script from deprecated `WorkoutTableStorage` to new `StorageCoordinator` API
- Remove misleading test assertions passing removed schema fields (`source_system`, `normalized_source_system`, `source_item_id`) in `test_table_storage_workouts.py`
- Add `TestWorkoutEntitySchemaValidation` class with 4 validation tests enforcing `extra="forbid"` schema constraint on removed fields
- Fix test fixture: add missing `ingestion_id` field to `test_get_workout_detail_found` mock entity (resolves Pydantic `min_length=1` validation error)
- Update documentation across 5 files:
  - `INGESTION_SCHEMA.md`: Clarify provenance field storage split (Workouts vs IngestionState)
  - `WORKOUT_SCHEMA.md`: Remove inaccurate `source_system` from public API schema
  - `BACKENDS.md`: Update code examples from `WorkoutTableStorage()` to `StorageCoordinator()`
- Tests: 470 passing (was 465 + 4 new validation tests + 1 fixed), 3 pre-existing failures unrelated to cleanup (fit_models.py recursion bugs)
- No ingestion logic, parsing, or stored schema changes — pure dead code elimination and documentation accuracy improvements

### Schema Cleanup - Phase 3: Activity Metadata Tightening [ingest v13.0.32]

- **BREAKING:** Remove redundant timestamp fields from `activity_metadata` zone: `activity_timestamp_utc` and `activity_local_time`
- Keep only `local_tz_offset` in activity metadata (computed centrally via `FitFile.local_tz_offset` property)
- Rationale: Timestamp fields duplicated session-level `start_time_utc`; timezone offset computed once at FitFile level
- Update `_build_canonical_activity_metadata()` to extract timezone offset ONLY
- Update CANONICAL_METADATA_SCHEMA.md with new activity_metadata structure
- Tests: 465+ passing (device extraction validated, activity metadata cleanup complete)

## 2026-02-28

### Timezone Selection - Major City Priority

- Improve `iana_from_offset()` timezone selection to prefer major metropolitan areas over smaller cities when multiple DST-aware zones match the same offset
- Add priority-ordered major city list: `America/New_York` now preferred over `America/Detroit` or `America/Montreal` for UTC-05:00
- Fix DST detection to use actual workout timestamp year instead of hardcoded 2024 for accurate timezone classification
- Add `_select_major_city()` helper function with population/usage-based priority ordering for 40+ major cities worldwide
- Update timezone selection algorithm: (1) athlete preference, (2) DST-aware zones, (3) major city priority, (4) path depth, (5) alphabetical
- Resolves issue where `UTC-05:00` converted to `America/Atikokan` (static offset) or `America/Detroit` (not expected) instead of `America/New_York` (expected major city)
- No schema version bump (behavior refinement within 1.5.0 semantic contract) `[timezone_utils]`

## 2026-02-27

### Automatic IANA Timezone Resolution

- Add automatic conversion of UTC offset strings to IANA timezone names in `BaseFitModel.timezone` property using stdlib `zoneinfo` module
- Implement `iana_from_offset()` in `timezone_utils` to map UTC offsets to canonical IANA timezones using `available_timezones()` lookup at workout timestamp
- Add `athlete_timezone` configuration field to physiometrics.json and Config class (env var: `ATHLETE_TIMEZONE`) for disambiguation of ambiguous offsets like UTC-05:00 (New York vs Toronto vs Bogotá)
- Add Zwift workout detection: indoor workouts at UTC+00:00 now resolve to athlete's physical timezone instead of cloud service offset
- Update `BaseFitModel.timezone` with 4-step priority chain: (1) device explicit IANA metadata, (2) Zwift override, (3) offset→IANA conversion with athlete hint, (4) offset string fallback
- Timezone field now exports America/New_York instead of UTC-05:00 for workout metadata `[CANONICAL_SCHEMA_VERSION 1.5.0]`

### Manufacturer Code Extraction Robustness

- Fix `_extract_code_and_name()` in `BaseFitModel` to handle string manufacturer values returned by fitdecode (previously only handled int/enum objects)
- Add reverse lookup fallback to resolve string manufacturer names to numeric codes via `MANUFACTURER_NAME_TO_CODE` when code extraction fails
- Improve diagnostic logging to surface manufacturer extraction failures with `ingestion_id` and `file_sha256` for troubleshooting `[ingest v13.0.31 (bug fix - no version bump)]`
- Add comprehensive unit tests covering all input type combinations (None, int, string, enum objects) with full coverage of reverse lookup paths
- Diagnoses root cause of Garmin API workouts failing with `manufacturer_code None not in allowlist` — enables investigation of why FIT files lack manufacturer data

## 2026-02-26

### Apple Watch Internal Identifier Mapping

- Add `APPLE_WATCH_INTERNAL_IDS` dictionary mapping Apple Watch internal device identifiers (e.g., "Watch7,12") to marketing names for all models from Series 0 through Series 11, Ultra 1-3, and SE 1-3
- Add `get_apple_watch_model()` helper function for lookup of marketing names from internal IDs found in FIT file_id.product_name fields
- Source: [adamawolf/3048717](https://gist.github.com/adamawolf/3048717) and [TheiphoneWiki Models](https://www.theiphonewiki.com/wiki/Models) `[code_mappings]`

### Payload Source Normalization

- Force `PayloadFitModel.normalized_source_system` to always emit `HTTP`, ignoring optional caller-provided `source_system` metadata for direct payload ingests `[ingest v13.0.29, INGESTION_SCHEMA v15.0.30]`.

### Device Filtration Fast-Fail

- Add fast-fail device filtration with explicit `filtered` ingestion state, rejecting HealthKit-synced workouts on OneDrive ingestion and enforcing Garmin/Zwift manufacturer allowlist for Garmin API sync (payload ingestion remains unfiltered) `[ingest v13.0.31, INGESTION_SCHEMA v15.0.32]`.

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
- Allow HealthFit Apple workout type to fall back to FIT sport/sub_sport inference when filename token is missing or unrecognized, with warning logs to flag potential export anomalies `[ingest v13.0.30, INGESTION_SCHEMA v15.0.31]`

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
