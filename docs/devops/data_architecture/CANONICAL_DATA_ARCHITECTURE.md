# Canonical Data Architecture
<!-- markdownlint-disable MD024 -->

Version: 2.2.3

=====================================================================

## Section I. Philosophy

This architecture enforces strict separation between:

1. Deterministic telemetry (physics)
2. Structural metadata
3. Semantic enrichment

### Core Principles

- Canonical Parquet stream is the single source of metric truth
- All derived metrics are deterministic projections
- CanonicalAnalyticsEngine is the sole computation layer for derived analytics at read time
- AI analysis is advisory and never mutates canonical data
- Raw FIT JSON is preserved for full archival integrity
- Vendor platforms may be ingestion sources or publication sinks, but never canonical authorities
- Architecture optimized for recomputability and sovereignty

=====================================================================

## Section II. Workout Ingestion Artifacts

At ingestion, each workout produces five immutable blobs and one Workout Table row.

---------------------------------------------------------------------

### 1. Raw FIT Archive (Immutable)

Path:
/workouts/{ingestion_id}/raw_fit.json.gz

Purpose:

- Full structural preservation
- Schema evolution insurance
- Vendor forensic capability
- Re-decodable indefinitely

This file is never modified after ingestion.

---------------------------------------------------------------------

### 2. AI Structural Analysis (Advisory)

Path:
/workouts/{ingestion_id}/fit_analysis.json

Purpose:

- Classify unknown FIT fields
- Detect device quirks
- Detect summary vs record discrepancies
- Recommend canonical promotion candidates
- Provide semantic enrichment guidance

Rules:

- Cannot modify canonical.parquet
- Versioned independently
- Treated as enrichment metadata only

---------------------------------------------------------------------

### 3. Canonical Record Stream (Authoritative)

Path:
/workouts/{ingestion_id}/canonical.parquet

Derived strictly from FIT `Record` messages.

Canonical fields include:

- timestamp_utc
- elapsed_sec
- power_watts (nullable)
- heart_rate_bpm (nullable)
- cadence_rpm (nullable)
- speed_mps (nullable)
- distance_m (nullable)
- elevation_m (nullable)
- temperature_c (nullable)
- respiration_rate_brpm (nullable)
- lr_balance_pct (nullable)
- rr_intervals_sec (immutable tuple of floats, default empty)

This file is the authoritative substrate for all metrics.

---------------------------------------------------------------------

### 4. Lap Messages (Contextual)

Path:
/workouts/{ingestion_id}/laps.json

Purpose:

- Preserve vendor segmentation
- Structured workout definitions
- Manual lap markers

Laps preserve FIT message semantics for client interpretation. `intervals_json`
is not used in the current architecture. A future iteration may populate
`intervals_json` from FIT `workout` and `workout_step` messages when present.

Laps are never flattened into canonical telemetry.

---------------------------------------------------------------------

### 5. Metadata Messages

Path:
/workouts/{ingestion_id}/metadata.json

Contains structured FIT messages:

- file_id
- file_creator
- device_info
- sport
- sub-sport
- activity
- session
- event

Provides fast metadata access without decompressing `raw_fit.json.gz`.

=====================================================================

## Section III. Workout Table

One Azure Table row per workout.

PartitionKey = athlete_id
RowKey = workout_id

Operational Note:
The Workouts table implementation may use an ingestion-optimized keying
scheme (athlete_id|YYYY-MM + timestamp prefix). Logical identifiers remain
workout_id and athlete_id as specified here.

Identity Model:

- `ingestion_id` is the source-system identity used for idempotency and storage paths.
- `workout_id` is the semantic identity derived from FIT timestamps and sport.

Implementation note: current storage paths use `workout_id` for blob prefixes. This is a known mismatch and will be refactored to align with the intended `ingestion_id`-keyed storage contract.

---------------------------------------------------------------------

### Required Deterministic Fields

- workout_id
- athlete_id
- start_time_utc
- sport
- sub_sport
- device_source
- gear_id
- duration_sec
- distance_m
- has_power
- has_hr
- has_gps

Computed deterministically from canonical.parquet and metadata.

---------------------------------------------------------------------

### Optional Enrichment Fields

- environment (indoor | outdoor)
- virtual_platform (Zwift | Garmin | Other) - based on recording device
- commute_flag
- race_flag
- structured_flag
- analysis_version

These may be AI-assisted but never override deterministic telemetry.

---------------------------------------------------------------------

### Versioning Fields

- ingestion_version
- canonical_schema_version
- analysis_model_version

---------------------------------------------------------------------

### Immutable Zone Provenance Fields

- hr_zone_model
- hr_zone_basis
- hr_zone_reference_bpm
- pwr_zone_model
- ftp_watts

These fields capture the model source and reference basis used to compute zones
at read time. When persisted, they must remain immutable for the workout.

=====================================================================

## Section IV. Derived Projections (Lazy Computation)

This section separates pass-through fields from deterministic projections.

Pass-through fields (not computed):

- laps.json (pass-through artifact sourced from FIT lap messages)

Derived fields (computed from canonical.parquet):

- Normalized Power (NP)
- Intensity Factor (IF)
- Training Stress Score (TSS)
- HR and power zone distributions
- Power Curve scalars and power_curve_json artifact
- Durability
- Decoupling
- Efficiency Factor
- Surge Detection
- climbs_json artifact

Derived outputs remain deterministic projections over the canonical substrate.
No scalar duplication unless required for query optimization.

=====================================================================

## Section V. Wellness Domain: Blob-First Reproducible Ingestion

### Storage Strategy: Three-Container Model

| Container | Purpose | Data | Lifecycle |
| --- | --- | --- | --- |
| `workouts` | FIT workout artifacts | canonical.parquet, raw_fit.json.gz, laps.json, metadata.json | Immutable; keep indefinitely (archive after 1 year) |
| `external-sources` | External API/vendor raw responses | Withings measurements, Garmin training state, Intervals HRV/RHR/sleep | Reproducible; archive after 90 days |
| `backups` | Table backup snapshots | Daily exported Workouts/Physiometrics/TrainingState tables | Auto-cool after 30 days; delete after 90 days |

### Physiometrics Ingestion: Source → Blob → Canonical

Two canonical aggregates (separate tables and blob storage):

#### 1. PhysiometricsSnapshot

**Table**: `Physiometrics` (Azure Table Storage)

```text
PartitionKey: athlete_id
RowKey: YYYY-MM-DD (effective_date, local athlete timezone)

Schema (current + planned):
  • effective_date: str  (YYYY-MM-DD, RowKey component for idempotent upsert)
  • updated_at_utc: datetime  (timestamp of last upsert; audit trail)
  • measured_at_utc: Optional[datetime]  (timestamp of measurement collection)
  • data_source: str  (primary source for this snapshot; e.g., "intervals", "withings", "garmin")
  • data_sources: Optional[str]  (CSV of all contributing sources for consolidated days)
  • canonical_version: str  (e.g., "2.0.0"; tracks schema evolution)
  
  • weight_kg: Optional[float]
  • fat_mass_kg: Optional[float]
  • muscle_mass_kg: Optional[float]
  • bone_mass_kg: Optional[float]
  • body_fat_pct: Optional[float]
  • visceral_fat_index: Optional[float]
  • metabolic_age_years: Optional[int]
  
  • heart_rate_basis: str  (e.g., "LTHR", "HRmax")
  • heart_rate_lthr_bpm: Optional[float]
  • heart_rate_hr_max_bpm: Optional[float]
  • heart_rate_resting_bpm: Optional[float]
  
  • hrv_ln_rmssd: Optional[float]  (log-normalized RMSSD from Intervals)
  • hrv_sdnn_ms: Optional[float]  (HRV SDNN from Intervals)
  • sleep_duration_min: Optional[float]  (from Intervals)
  • readiness_score: Optional[float]  (0-100 composite from Garmin or Intervals)
  
  • power_ftp_watts: Optional[float]
  • cycling_vo2max_ml_kg_min: Optional[float]
  • load: Optional[float]  (training load from Garmin; planned)
  
  • subjective_soreness: Optional[float]  (0-10 scale; subjective wellness)
  • subjective_fatigue: Optional[float]  (0-10 scale; subjective wellness)
  • subjective_stress: Optional[float]  (0-10 scale; subjective wellness)
  • subjective_mood: Optional[float]  (0-10 scale; subjective wellness)
  • subjective_motivation: Optional[float]  (0-10 scale; subjective wellness)
  • subjective_injury: Optional[float]  (0-10 scale; subjective wellness)
  
  • nutrition_calories_kcal: Optional[float]  (daily caloric intake)
  • nutrition_carbs_g: Optional[float]  (carbohydrate intake in grams)
  • nutrition_protein_g: Optional[float]  (protein intake in grams)
  • nutrition_fat_g: Optional[float]  (fat intake in grams)
  
  • activity_steps: Optional[int]  (daily step count)
  
  • body_abdomen_cm: Optional[float]  (waist circumference in centimeters)
  • spo2_pct: Optional[float]  (blood oxygen saturation percentage)
  • systolic_bp: Optional[float]  (systolic blood pressure)
  • diastolic_bp: Optional[float]  (diastolic blood pressure)
  • vo2max_ml_kg_min: Optional[float]  (VO2max)
  • menstrual_phase: Optional[str]  (source-reported menstrual phase)
  • menstrual_phase_predicted: Optional[str]  (source-predicted menstrual phase)
  
  • sport_info_json: Optional[str]  (JSON-serialized array of sport-specific metrics; e.g., [{"type": "Ride", "load": 120.5, "ctl": 85.2}])
  • source_updated_at_utc: Optional[str]  (source-side updated timestamp, ISO 8601)
  • ext_json: Optional[str]  (JSON serialization of canonical extended physiometrics fields)
  • raw_intervals_icu_json: Optional[str]  (JSON serialization of full, unmodified Intervals source day payload)
  
  • full_config_json: Optional[str]  (legacy compatibility field for older rows; new writes use `ext_json` + scalar columns + `raw_intervals_icu_json`)
```

**Idempotency**: Upsert per `(athlete_id, effective_date)` ensures that multiple snapshots for the same day from the same source merge deterministically. The `full_config_json` field preserves the complete input payload for auditability and schema evolution tolerance.

#### 2. TrainingStateSnapshot

**Table**: `TrainingState` (Azure Table Storage)

```text
PartitionKey: athlete_id
RowKey: YYYY-MM-DD (effective_date)

Schema:
  • cts_rolling_7d: Optional[float]  (Chronic Training Stress, last 7 days)
  • cts_rolling_28d: Optional[float]  (last 28 days)
  • ats_rolling: Optional[float]  (Acute Training Stress)
  • fatigue_index: Optional[float]  (ATS/CTS ratio)
  
  • readiness_score: Optional[float]  (composite: HRV + load + HR)
  • garmin_readiness_score: Optional[float]  (pass-through from Garmin)
  • mood: Optional[int]  (user-reported 1-5)
  • soreness: Optional[int]  (user-reported 1-5)
  
  • pred_recovery_days: Optional[int]
  
  • data_sources: CSV (e.g., "workouts,physiometrics,garmin")
  • canonical_version: str  (e.g., "2.0.0")
  • last_updated_utc: datetime
```

**Idempotency**: Upsert per `(athlete_id, effective_date)`. Computed nightly from immutable `Workouts` + `Physiometrics` tables.

### Ingestion Pathways: Blob-First Pattern

#### Withings Measurements

**Trigger**: Webhook POST → HTTP 200 ACK immediately (async processing)

**Blob Storage**:

```text
Container: external-sources
Path: physiometrics/{athlete_id}/withings/webhooks/{webhook_enddate_unix}.json
Content: Raw Withings API measurement response (JSON)
```

**Deduplication**: Track in `WebhookDeduplication` table by `(athlete_id, withings_userid, enddate_unix)`.

**Processor**: `WithingsPhysiometricsProcessor`

1. Query `SourceIngestionState` for blobs with `status: fetched` and `source: withings`.
2. Download blob → deserialize JSON.
3. Validate semantic contract (required fields: weight_kg, timestamp).
4. Map to `PhysiometricsSnapshot` (extract effective_date from measurement timestamp).
5. Upsert to `Physiometrics` table.
6. Update `SourceIngestionState` to `status: processed`.

#### Garmin Training State

**Trigger**: Daily timer (3 AM UTC) or manual sync endpoint

**Blob Storage**:

```text
Container: external-sources
Path: physiometrics/{athlete_id}/garmin/daily/{YYYY-MM-DD}.json
Content: Raw Garmin Connect API training state response (JSON)
```

**Processor**: `GarminTrainingStateProcessor`

1. Query `SourceIngestionState` for blobs with `status: fetched` and `source: garmin_training_state`.
2. Download blob → deserialize JSON.
3. Validate semantic contract (required fields: ftp, vo2max, lthr, load, readiness).
4. Map to `PhysiometricsSnapshot` (Garmin-sourced fields).
5. Upsert to `Physiometrics` table.
6. Update `SourceIngestionState` to `status: processed`.

#### Intervals.icu Wellness

**Trigger**: Daily timer or manual sync endpoint

**Blob Storage**:

```text
Container: external-sources
Path: physiometrics/{athlete_id}/intervals/daily/{YYYY-MM-DD}.json
Content: Raw Intervals API wellness response (HRV, restingHR, sleepSecs, readiness; JSON)
```

**Processor**: `IntervalsPhysiometricsProcessor`

1. Query `SourceIngestionState` for blobs with `status: fetched` and `source: intervals`.
2. Download blob → deserialize JSON.
3. Validate semantic contract (HRV ln(RMSSD), resting HR, sleep duration).
4. Map to `PhysiometricsSnapshot` (Intervals-sourced fields).
5. Upsert to `Physiometrics` table.
6. Update `SourceIngestionState` to `status: processed`.

### SourceIngestionState Tracking

**Table**: `SourceIngestionState`

```text
PartitionKey: athlete_id
RowKey: {source}_{blob_key_suffix}  (e.g., "withings_20260303_1234567890", "garmin_20260303")

Schema:
  • source: str  ("withings", "garmin", "intervals")
  • blob_path: str  (full path in external-sources container)
  • status: str  ("fetched" | "processed" | "failed")
  • canonical_version: str  (version of processor that processed blob)
  • processed_at_utc: datetime  (when processor completed)
  • error: str  (if status: failed; truncated if > 1024 chars)
  • retry_count: int  (incremented on failure; reset on success)
  • last_attempt_at_utc: datetime
```

**Rules**:

- On blob upload, insert row with `status: fetched`.
- Processor marks `status: processed` after canonical table upsert succeeds.
- On processor failure, record error + increment retry_count.
- Idempotency: Processor checks `is_processed()` before re-processing same (source, effective_date).

### Consolidation: Multi-Source Merge (Nightly)

**PhysiometricsConsolidationHandler** (runs after all source processors complete):

1. Query `Physiometrics` table for all rows with `effective_date` in past 7 days (catch late arrivals).
2. For each `(athlete_id, effective_date)` group, apply source precedence rules:
   - **Body mass**: Prefer Withings; fallback to Intervals.
   - **Body composition**: Withings only.
   - **HRV/RHR/Sleep**: Intervals preferred; backfill from Garmin if available.
   - **Training state (FTP, VO2, LTHR)**: Garmin primary; Intervals if available.
   - **Readiness**: Garmin preferred; compute composite if unavailable.
3. Optionally write consolidated snapshot to separate row (or keep per-source at API layer).
4. Emit audit log of merge decisions + sources used.

**Idempotency**: Safe to re-run any day; merges are deterministic over immutable source snapshots.

### Replay Capability

To replay historic ingestion:

1. **Replay Withings**: Query all `physiometrics/{athlete_id}/withings/webhooks/*.json` blobs; trigger `WithingsPhysiometricsProcessor` on each → overwrites `Physiometrics` rows (upsert idempotent).
2. **Replay Garmin**: Query all `physiometrics/{athlete_id}/garmin/daily/*.json` blobs; trigger `GarminTrainingStateProcessor` on each → overwrites rows.
3. **Replay Intervals**: Query all `physiometrics/{athlete_id}/intervals/daily/*.json` blobs; trigger `IntervalsPhysiometricsProcessor` on each → overwrites rows.
4. **Replay Consolidation**: Re-run `PhysiometricsConsolidationHandler` (idempotent; computes from canonical tables).
5. **Replay Training State**: Re-run `TrainingStateConsolidationHandler` (computes from immutable `Workouts` + `Physiometrics`).

**Audit Trail**: Each canonical row persists `canonical_version` + `last_updated_utc` + `data_sources`. Replay updates `last_updated_utc` but version remains (unless schema changed).

### Error Handling & Recovery

| Scenario | Action | Recovery |
| --- | --- | --- |
| Blob fetch failure | Retry 3x with exponential backoff | Defer to next scheduled run |
| Processor validation failure | Record in `SourceIngestionState` with error | Manual intervention or auto-retry next run |
| Table upsert failure | Retry 3x; on failure, record in `SourceIngestionState` | Manual intervention |
| Consolidation job failure | Log + defer | Idempotent; safe to re-run next day |
| Webhook dedup collision | Skip re-upload (check dedup table first) | Already processed; no action needed |

### Schema Versioning

- **Source Schema Version**: Tracks raw API response format (e.g., "withings_v1" if API changes).
- **Canonical Version**: Tracks processor output schema (e.g., "2.0.0").
- If source API schema changes → new source version; old blobs can be re-processed by versioned processor.
- Changelog entry for version bumps; SemVer on breaking changes.

=====================================================================

## Section VI. Training State Domain: Derived Consolidation

See Section V above (TrainingStateSnapshot integrated into state schema).

**Consolidation Job** (`TrainingStateConsolidationHandler`):

1. Query `Workouts` table for `effective_date` in past 28 days.
2. Sum TSS; compute rolling CTS (28-day) and ATS (7-day).
3. Query latest `Physiometrics` snapshot for HRV and Garmin readiness.
4. Compute composite readiness score (if not provided by Garmin).
5. Upsert `TrainingState` table.

**Immutability**: Training State is purely derived from immutable canonical data; safe to recompute any time.

**Rules**:

- Historical snapshots frozen.
- Vendor model outputs (Garmin readiness, load) isolated from derived metrics.
- Computation is deterministic and idempotent.

=====================================================================

## Section VII. Gear Domain

Gear Table:
PartitionKey = athlete_id
RowKey = gear_id (UUID)

Fields:

- gear_name
- gear_type
- is_ebike
- has_power_meter
- attributes

Relationships:

- Workout references gear_id
- Vendor gear IDs optional
- Supports equipment-based analytics

=====================================================================

## Section VIII. Data Flow Architecture (Blob-First Reproducible)

```text
WORKOUT INGESTION:
  FIT Source (OneDrive / Garmin Connect / Direct Upload)
    → Fetch + Store raw FIT binary
    → Parse + Validate (BaseFitModel)
    → Store blobs in workouts container:
       - raw_fit.json.gz (immutable archive)
       - fit_analysis.json (advisory)
       - canonical.parquet (authoritative telemetry)
       - laps.json (contextual)
       - metadata.json (structural)
    → Insert Workouts table row
    → Record IngestionState (terminal marker)
    → Semantic layer computes lazily (NP, IF, TSS, zones, etc.)

WELLNESS INGESTION (Blob-First Reproducible):
  
  [1] Withings Measurements
    → Webhook POST → HTTP 200 ACK immediately
    → Async: Fetch via WithingsClient + Store blob
       external-sources/physiometrics/{athlete_id}/withings/webhooks/{timestamp}.json
    → Record SourceIngestionState: "fetched"
    → WithingsPhysiometricsProcessor runs (timer or on-demand):
       • Download blob → deserialize JSON
       • Validate semantic contract
       • Map to PhysiometricsSnapshot via WithingsAdapterBase
       • Upsert Physiometrics table
       • Mark SourceIngestionState: "processed"
  
  [2] Garmin Training State
    → Timer (3 AM UTC) or on-demand sync
    → Fetch via GarminConnectClient + Store blob
       external-sources/physiometrics/{athlete_id}/garmin/daily/{YYYY-MM-DD}.json
    → Record SourceIngestionState: "fetched"
    → GarminTrainingStateProcessor runs:
       • Download blob → deserialize JSON
       • Validate semantic contract
       • Map to PhysiometricsSnapshot via GarminAdapterBase
       • Upsert Physiometrics table
       • Mark SourceIngestionState: "processed"
  
  [3] Intervals.icu
    → Timer or on-demand sync
    → Fetch wellness records + Store blob
       external-sources/physiometrics/{athlete_id}/intervals/daily/{YYYY-MM-DD}.json
    → Record SourceIngestionState: "fetched"
    → IntervalsPhysiometricsProcessor runs:
       • Download blob → deserialize JSON
       • Validate semantic contract
       • Map to PhysiometricsSnapshot via IntervalsAdapterBase
       • Upsert Physiometrics table
       • Mark SourceIngestionState: "processed"
  
CONSOLIDATION (Nightly):
  
  PhysiometricsConsolidationHandler:
    → Query Physiometrics table for all sources on effective_date (catch late arrivals)
    → Apply source precedence rules
    → Optionally: Write consolidated snapshot (or merge at read-time via API projection)
    → Emit audit log of merge decisions
  
  TrainingStateConsolidationHandler:
    → Compute rolling TSS from Workouts (last 7 & 28 days)
    → Fetch latest Physiometrics snapshot (HRV, readiness)
    → Compute fatigue index, composite readiness
    → Upsert TrainingState table

SEMANTIC LAYER:
  → Read Workouts canonical.parquet (lazy; stream to CanonicalAnalyticsEngine)
  → Compute derived metrics: NP, IF, TSS, power curves, HR zones, climbs, etc.
  → Read PhysiometricsSnapshot + TrainingStateSnapshot for context
  → Expose query APIs: current_physio(), history(), athlete_state(), etc.
```

### Determinism & Reproducibility

- **Canonical Parquet** (Workouts): Single source of metric truth; recomputable from raw FIT.
- **Physiometrics Blobs** (external-sources): Immutable snapshots of vendor API responses; replayed to regenerate table rows.
- **TrainingState**: Pure computation over canonicalized Workouts + Physiometrics; deterministic and replayable.
- **SourceIngestionState**: Audit trail of processor runs; enables forensic replay and version tracking.

### Replay Safety

All ingestion is idempotent and replayable:

- Upsert semantics ensure overwrites are safe.
- Blob storage preserves original API responses indefinitely.
- Schema versioning allows processors to evolve without breaking historical data.
- No production side effects from re-processing; all writes are to canonical tables (append-safe and overwrite-safe).

=====================================================================

## Section IX. Governance

- Canonical parquet is immutable
- Raw FIT (as compressed JSON) archive guarantees long-term sovereignty
- AI analysis is advisory and versioned
- No recomputation depends on vendor-derived scalars
- Zone provenance is immutable per workout and must include:
  hr_zone_model, hr_zone_basis, hr_zone_reference_bpm, pwr_zone_model, ftp_watts
- System optimized for deterministic reproducibility

=====================================================================

## Section X. Deterministic Contract Integration

This architecture explicitly integrates with:

- CANONICAL_ANALYTICS_SURFACE.md
- CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT.md

Rules:

- All derived metrics MUST conform to the deterministic formula contract.
- Canonical parquet schema changes require schema version bump.
- Formula contract changes require minor version bump.
- Breaking storage or ingestion changes require major version bump.
- AI enrichment layers must not alter deterministic outputs.

Terminology Crosswalk:

- `intervals_json` (analytics/API surface) = pass-through representation of
  ingest lap artifact (`laps.json`)
- `climbs_json` and `power_curve_json` = deterministic computed artifacts from
  canonical telemetry

Forward Compatibility:

- If future lap resampling or lap normalization is introduced, it must be
  version-gated and documented as an explicit behavior change.

Versioning Policy:

- MAJOR: Storage model or canonical schema changes
- MINOR: Additional deterministic metrics or enrichment layers
- PATCH: Documentation or clarification updates only

=====================================================================

## Section XI. Schema Evolution Policy

Canonical schema evolution must follow:

1. Backward compatibility where possible
2. Nullable-first column additions
3. Raw FIT archive retained to allow reprocessing
4. Analysis model versioning independent of canonical schema

No telemetry field may be removed without a MAJOR version increment.

=====================================================================
