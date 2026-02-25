# Canonical Data Architecture
<!-- markdownlint-disable MD024 -->

Version: 2.2.2

=====================================================================

## Section I. Philosophy

This architecture enforces strict separation between:

1. Deterministic telemetry (physics)
2. Structural metadata
3. Semantic enrichment

### Core Principles

- Canonical Parquet stream is the single source of metric truth
- All derived metrics are deterministic projections
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
- rr_interval_sec (nullable)

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

These fields capture the academic/model source and reference basis used for
zone computation and are immutable once the workout is ingested.

=====================================================================

## Section IV. Derived Projections (Lazy Computation)

This section separates pass-through fields from deterministic projections.

Pass-through fields (not computed):

- laps.json (pass-through artifact sourced from FIT lap messages)

Derived fields (computed from canonical.parquet):

- Normalized Power (NP)
- Intensity Factor (IF)
- Training Stress Score (TSS)
- Power Curve scalars and power_curve_json artifact
- Durability
- Decoupling
- Efficiency Factor
- Surge Detection
- climbs_json artifact

Derived outputs remain deterministic projections over the canonical substrate.
No scalar duplication unless required for query optimization.

=====================================================================

## Section V. Wellness Domain

Sources:

- Intervals (HRV, RHR, sleep)
- Withings (weight, body composition)

Storage:
Azure Table (daily index)

PartitionKey = athlete_id
RowKey = YYYY-MM-DD

Derived Metrics:

- Rolling HRV
- Readiness Score
- Autonomic Stress Index

Design Notes:

- Sparse tolerant
- Nullable physiometrics supported
- Independent from workout ingestion

=====================================================================

## Section VI. Garmin Training State Domain

Read-only polling via python-garminconnect.

Daily snapshot includes:

- FTP
- VO2Max
- Max HR
- LTHR
- Load
- Readiness

Storage:
PartitionKey = athlete_id
RowKey = YYYY-MM-DD

Rules:

- Historical snapshots frozen
- Vendor model outputs isolated from canonical metrics

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

## Section VIII. Data Flow Architecture

FIT Source
  → Parse
    → raw_fit.json.gz
    → fit_analysis.json
    → canonical.parquet
    → laps.json
    → metadata.json
    → Insert Workout Table Row

Wellness APIs
  → Normalize
  → Azure Table upsert

Garmin Training State
  → Poll
  → Snapshot
  → Azure Table

Semantic Layer
  → Compute projections lazily from canonical stream

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
