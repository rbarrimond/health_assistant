# Changelog

Change history for the Health Assistant / Workout Intelligence Agent system. Entries include component changes and explicit SemVer bumps when applicable.

**Format conventions:**

- **BREAKING:** prefix denotes backward-incompatible changes
- Version bumps noted as: `[component vX.Y.Z]`
- Related changes grouped under common themes

## 2026-03-05

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
