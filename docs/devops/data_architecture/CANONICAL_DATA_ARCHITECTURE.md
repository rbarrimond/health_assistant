# Canonical Data Architecture
<!-- markdownlint-disable MD024 -->

Version: 2.2.4

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

Persistence contract:

- Ingestion persists source-derived canonical record streams to `canonical.parquet` without using 1 Hz cadence as an acceptance gate.
- Semantic read paths (API metrics hydration, weekly rollup assembly) perform strict validation first and may retry with `resample=True` to tolerate sparse gaps; fallback emits distortion telemetry and thresholded warnings.

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

---------------------------------------------------------------------

### Timezone Resolution Contract

Timezone semantics are deterministic and shared across ingestion, projection, and
historical remediation paths.

Resolution order:

1. Derive `local_tz_offset` from FIT **session** local-vs-UTC timing
  (`session.start_time` vs `session.timestamp - session.total_elapsed_time`).
2. If session timing fields are missing/invalid, use fallback offset signals
  (device/activity/source metadata) to preserve ingestion resilience.
3. Resolve `timezone` from the derived offset using existing timezone rules.
4. **Zwift cloud exception**: for explicit Zwift/virtual workouts at `UTC+00:00`,
  use athlete home timezone because source-local wall-clock context is hidden.

Invariants:

- `local_tz_offset` is always the offset context for the workout.
- `timezone` is canonical timezone context (IANA when resolvable, offset fallback).
- Non-Zwift `UTC+00:00` workouts must not be coerced to athlete home timezone.

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

---------------------------------------------------------------------

### Workout Detail Read Contract (`GET /api/workouts/{workout_id}`)

The single-workout detail read path is canonical-required.

Read-time source boundaries:

- Identity and lookup: Workouts table row
- Metrics payload (`WorkoutMetricsModel`): derived from `canonical.parquet`
- Lap payload (`laps`): sourced from `laps.json` when requested

Failure semantics:

- If canonical records are missing, unreadable, empty, or fail canonical validation,
  the API returns an explicit server error rather than emitting a partial metrics model.
- This preserves deterministic recomputability and prevents mixed-provenance metric payloads.

=====================================================================

## Section V. Wellness Domain: Direct Ingestion (v3.0.0)

### Architecture Paradigm

**Direct Ingestion Model**: `Fetch → Validate → Upsert` (no blob storage)

All wellness data flows directly from source APIs to the canonical `Physiometrics` table. No intermediate blob storage is used for physiometrics. This approach prioritizes operational simplicity and eliminates storage overhead for sparse, low-volume wellness measurements.

**Single Canonical Table**: `Physiometrics` (Azure Table Storage)

**On-Demand Projection**: `TrainingState` computed fresh on request (no table)

### PhysiometricsSnapshot v3.0.0: Simplified Schema

**Table**: `Physiometrics`

```text
PartitionKey: {athlete_id}|{YYYY-MM}
RowKey: DD
```

This partitioning strategy enables efficient range queries for monthly rollups while maintaining daily granularity at the row level.

**Schema**: Canonical 25-field model with metric-by-metric source precedence

```python
# Metadata (4 fields)
athlete_id: str                # Athlete identifier
effective_date: str            # YYYY-MM-DD (local athlete timezone)
data_sources: str              # CSV of contributing sources (e.g., "withings,intervals,garmin")
canonical_version: str         # Schema version (default: "3.0.0")
last_updated_utc: datetime     # Timestamp of last upsert

# Body composition (Withings exclusive) - 5 fields
weight_kg: Optional[float]              # Body weight
fat_mass_kg: Optional[float]            # Fat mass
muscle_mass_kg: Optional[float]         # Muscle mass
bone_mass_kg: Optional[float]           # Bone mass
body_fat_pct: Optional[float]           # Body fat percentage

# Recovery metrics (Intervals exclusive) - 3 fields
hrv_ln_rmssd: Optional[float]           # HRV (natural log of RMSSD)
sleep_duration_sec: Optional[float]     # Sleep duration in seconds
resting_hr_bpm: Optional[float]         # Resting heart rate (Intervals only; Garmin ignored)

# Activity (Intervals exclusive) - 1 field
steps: Optional[int]                    # Daily step count (Intervals only; Garmin ignored)

# Nutrition (Intervals exclusive) - 4 fields
calories_kcal: Optional[float]          # Daily calorie intake
carbs_g: Optional[float]                # Carbohydrate intake
protein_g: Optional[float]              # Protein intake
fat_g: Optional[float]                  # Fat intake

# Performance baselines (Garmin primary; manual/chatgpt fallback for gaps) - 4 fields
ftp_watts: Optional[float]                     # Functional threshold power
cycling_vo2max_ml_kg_min: Optional[float]      # Cycling VO2Max estimate
hr_lthr_bpm: Optional[float]                   # Lactate threshold heart rate
hr_max_bpm: Optional[float]                    # Maximum heart rate

# Training state (Garmin exclusive) - 3 fields
training_load: Optional[float]          # Garmin cumulative training load
recovery_time_minutes: Optional[int]    # Garmin recovery time estimate
readiness_score: Optional[float]        # Garmin readiness score (0-100)

# Extended training metrics (Garmin exclusive) - 5 fields
training_effect_aerobic: Optional[float]        # Aerobic training effect (0-5)
training_effect_anaerobic: Optional[float]      # Anaerobic training effect (0-5)
training_stress_score: Optional[float]          # Training stress score
training_stress_balance: Optional[float]        # Training stress balance
atp_probability: Optional[float]                # ATP/energy availability (0-100)
```

**Total**: 25 metric fields + 4 metadata fields = 29 fields

### Source Precedence: Metric Ownership with Explicit Fallbacks

Most fields use single-source ownership. A small set of training baseline metrics uses explicit fallback to preserve user-provided training configuration when Garmin values are unavailable.

| Field Group | Exclusive Owner | Rationale |
| ----------- | --------------- | --------- |
| **Body composition** (5) | Withings | Medical-grade scale; most accurate |
| **Recovery metrics** (3) | Intervals | Primary HRV/sleep tracking source; Garmin resting HR less reliable |
| **Activity** (1) | Intervals | Garmin step count less accurate |
| **Nutrition** (4) | Intervals | Explicit nutrition logging |
| **Performance baselines** (4) | Garmin (primary), then chatgpt/manual for FTP/LTHR/HRmax only | Preserve config-originated baseline values when Garmin baseline fields are missing |
| **Training state** (3) | Garmin | Proprietary training load algorithms |
| **Extended training** (5) | Garmin | Proprietary recovery/readiness models |

**Key Rules**:

- **Intervals resting HR is Intervals-only** (no Garmin/manual/chatgpt fallback)
- **Intervals steps take precedence** over Garmin (Garmin values ignored)
- **Withings body composition exclusive** (Intervals weight/body fat ignored)
- **FTP/LTHR/HRmax use limited fallback**: `garmin -> chatgpt -> manual`

### Ingestion Pathways: Direct Fetch Pattern

#### 1. Withings Measurements

**Trigger**: Webhook POST from Withings API → HTTP 200 ACK immediately

**Flow**:

```text
1. Withings API POST → /api/withings/webhook
2. Extract athlete_id, measurement date from payload
3. Validate webhook signature (security)
4. Check WebhookDeduplication table (idempotency)
5. Fetch measurement details via WithingsClient.get_measurement()
6. Convert to PhysiometricsSnapshot via WithingsPhysiometricsAdapter
7. Upsert to Physiometrics table (atomic)
8. Record in WebhookDeduplication table
9. Return HTTP 200```

**Adapter**: `WithingsPhysiometricsAdapter.map_to_canonical()`
- Sets: `weight_kg`, `fat_mass_kg`, `muscle_mass_kg`, `bone_mass_kg`, `body_fat_pct`
- All other fields: `None` (respects exclusive ownership)

**Idempotency**: Upsert by `(athlete_id, effective_date, source)` ensures safe retries without cross-source overwrites

#### 2. Garmin Training State

**Trigger**: Daily timer (3 AM UTC) or manual sync endpoint `/api/garmin/physiometrics/sync`

**Flow**:
```text
1. Timer/HTTP trigger → GarminPhysiometricsHandler.sync_daily()
2. Fetch training state via GarminConnectClient.get_training_state(date)
3. Validate response structure
4. Convert to PhysiometricsSnapshot via GarminTrainingStateAdapter
5. Upsert to Physiometrics table (atomic)
6. Return summary (dates processed, records upserted)
```

**Adapter**: `GarminTrainingStateAdapter.map_to_canonical()`

- Sets: `ftp_watts`, `cycling_vo2max_ml_kg_min`, `hr_lthr_bpm`, `hr_max_bpm`, `training_load`, `recovery_time_minutes`, `readiness_score`, `training_effect_aerobic`, `training_effect_anaerobic`, `training_stress_score`, `training_stress_balance`, `atp_probability`
- **Explicitly ignores**: `resting_hr_bpm`, `steps` (Intervals exclusive)
- All other fields: `None`

**Idempotency**: Upsert by `(athlete_id, effective_date, source)` ensures safe retries without cross-source overwrites

#### 3. Intervals.icu Wellness

**Trigger**: Daily timer or manual sync endpoint `/api/intervals/physiometrics/sync`

**Flow**:

```text
1. Timer/HTTP trigger → IntervalsPhysiometricsHandler.sync_daily()
2. Fetch wellness records via IntervalsClient.get_wellness(date_range)
3. Validate response structure (check required fields)
4. Convert to PhysiometricsSnapshot via IntervalsPhysiometricsAdapter
5. Upsert to Physiometrics table (atomic)
6. Return summary (dates processed, records upserted)
```

**Adapter**: `IntervalsPhysiometricsAdapter.map_to_canonical()`

- Sets: `hrv_ln_rmssd`, `sleep_duration_sec`, `resting_hr_bpm`, `steps`, `calories_kcal`, `carbs_g`, `protein_g`, `fat_g`
- **Explicitly ignores**: `weight_kg`, `body_fat_pct` (Withings exclusive)
- All other fields: `None`

**Idempotency**: Upsert by `(athlete_id, effective_date, source)` ensures safe retries without cross-source overwrites

### Consolidation: Multi-Source Merge (Nightly)

**Handler**: `PhysiometricsConsolidationHandler`

**Trigger**: Nightly timer (4 AM UTC) or manual endpoint `/api/physiometrics/consolidate`

**Algorithm**:

```text
1. Query Physiometrics table for last 7 days (catch late arrivals)
2. Group by (athlete_id, effective_date)
3. For each group with multiple source rows:
   a. Apply exclusive ownership rules (SourcePrecedenceResolver)
   b. Merge fields from all sources into single canonical snapshot
   c. Set data_sources = CSV of contributing sources
   d. Upsert consolidated row to Physiometrics table
4. Emit audit log of consolidation decisions
```

**Idempotency**: Safe to re-run any day; consolidation is deterministic over immutable source snapshots

### Physiometrics Storage Identity

- `PartitionKey = athlete_id`
- `RowKey = YYYY-MM-DD|source`
- `effective_date` remains the athlete-local date used for time-window queries
- `data_source` records the canonical source identifier (`withings`, `garmin`, `intervals`, `manual`, `chatgpt`)

This storage identity is intentionally source-qualified. Daily rows from different sources must coexist; using `effective_date` alone is a storage bug because it destroys provenance and breaks metric-precedence consolidation.

**SourcePrecedenceResolver.METRIC_SOURCES**:

```python
{
    "weight_kg": ["withings"],
    "fat_mass_kg": ["withings"],
    "muscle_mass_kg": ["withings"],
    "bone_mass_kg": ["withings"],
    "body_fat_pct": ["withings"],
    
    "hrv_ln_rmssd": ["intervals"],
    "sleep_duration_sec": ["intervals"],
    "resting_hr_bpm": ["intervals"],  # Intervals only
    
    "steps": ["intervals"],  # Garmin ignored
    
    "calories_kcal": ["intervals"],
    "carbs_g": ["intervals"],
    "protein_g": ["intervals"],
    "fat_g": ["intervals"],
    
    "ftp_watts": ["garmin", "chatgpt", "manual"],
    "cycling_vo2max_ml_kg_min": ["garmin"],
    "hr_lthr_bpm": ["garmin", "chatgpt", "manual"],
    "hr_max_bpm": ["garmin", "chatgpt", "manual"],
    
    "training_load": ["garmin"],
    "recovery_time_minutes": ["garmin"],
    "readiness_score": ["garmin"],
    
    "training_effect_aerobic": ["garmin"],
    "training_effect_anaerobic": ["garmin"],
    "training_stress_score": ["garmin"],
    "training_stress_balance": ["garmin"],
    "atp_probability": ["garmin"],
}
```

### Replay Capability

To replay historic ingestion (when schema changes or bugs are fixed):

1. **Mark existing rows for reprocessing**: Update `canonical_version` to trigger adapter logic
2. **Re-fetch from sources**: Call sync endpoints with `lookback_days` parameter
3. **Re-consolidate**: Run `PhysiometricsConsolidationHandler` for affected dates

**Limitations**: No blob archive exists for physiometrics. Replay depends on source API availability and retention policies.

### Error Handling & Recovery

| Scenario | Action | Recovery |
| -------- | ------ | -------- |
| Source API fetch failure | Retry 3x with exponential backoff | Defer to next scheduled run |
| Adapter validation failure | Log error + skip record | Continue processing remaining records |
| Table upsert failure | Retry 3x with exponential backoff | Record in application logs |
| Consolidation job failure | Log + defer | Idempotent; safe to re-run next day |
| Webhook dedup collision | Skip processing (already handled) | No action needed |

### Schema Versioning

- **Canonical Version**: `canonical_version` field tracks schema evolution (SemVer)
- **Current Version**: `3.0.0` (simplified MVP with 25 fields)
- **Breaking Changes**: Require major version bump + migration script
- **Additive Changes**: Minor version bump (backward compatible)
- **Bug Fixes**: Patch version bump

**Version History**:

- `3.0.0`: Simplified schema (25 fields); removed visceral_fat, metabolic_age, subjective wellness, sport_info, extended body metrics, menstrual tracking, raw JSON blobs, nested structures
- `2.5.0`: Extended body composition + subjective wellness + sport_info
- `2.0.0`: Base canonical schema with HRV/sleep/readiness

=====================================================================

## Section VI. Training State Domain: On-Demand Projection

**IMPORTANT**: TrainingState is **NOT stored** in a table. It is computed on-demand for each API request.

### Architectural Decision

**TrainingState is a pure projection** computed from:

1. **Workouts table** (TSS history for rolling 7-day and 28-day windows)
2. **Physiometrics table** (HRV, readiness, Garmin training state)

**No TrainingState table exists**. All metrics are computed fresh on each request using Pandas/NumPy for rolling aggregations.

### TrainingStateSnapshot Model

**Purpose**: Read-only projection exposed via API

**Schema**:

```python
athlete_id: str                           # Athlete identifier
effective_date: str                       # YYYY-MM-DD (target date)

# Rolling training stress (computed from Workouts)
cts_rolling_7d: Optional[float]           # Chronic training stress (7-day avg)
cts_rolling_28d: Optional[float]          # Chronic training stress (28-day avg)
ats_rolling: Optional[float]              # Acute training stress (7-day)
fatigue_index: Optional[float]            # ATS/CTS ratio (higher = more fatigued)

# Readiness and recovery (from Physiometrics)
readiness_score: Optional[float]          # Composite readiness (0-100)
garmin_readiness_score: Optional[float]   # Garmin native readiness
mood: Optional[int]                       # User-reported mood (1-5)
soreness: Optional[int]                   # User-reported soreness (1-5)

# Recovery prediction (computed)
pred_recovery_days: Optional[int]         # Predicted days to full recovery

# Provenance
data_sources: str                         # "workouts,physiometrics"
canonical_version: str                    # "3.0.0"
computed_at_utc: datetime                 # When projection was computed
```

### On-Demand Computation

**SemanticLayer Methods**:

```python
def compute_current_training_state(athlete_id: str) -> Dict:
    """Compute current training state (today's date)."""
    # 1. Query Workouts table for last 28 days
    # 2. Calculate rolling TSS (7-day, 28-day)
    # 3. Compute CTS (28-day avg), ATS (7-day avg), fatigue_index (ATS/CTS)
    # 4. Query latest Physiometrics for HRV and readiness
    # 5. Compute composite readiness (if Garmin readiness not available)
    # 6. Return TrainingStateSnapshot (in-memory)

def compute_training_state_history(athlete_id: str, days: int = 45) -> Dict:
    """Compute training state for each day in date range."""
    # 1. For each date in range:
    #    a. Query Workouts for rolling 28-day window ending on that date
    #    b. Compute CTS/ATS/fatigue_index at that point in time
    #    c. Query Physiometrics for that date
    # 2. Return list of TrainingStateSnapshot objects (all in-memory)
```

**Performance**: Azure Table queries are fast; Pandas rolling aggregation is efficient. Acceptable latency for read-only API (<500ms for 45-day history).

### API Endpoints

**Current Training State**:

```http
GET /api/training-state/current?athlete_id=rob

Response:
{
  "athlete_id": "rob",
  "effective_date": "2026-03-05",
  "cts_rolling_7d": 42.5,
  "cts_rolling_28d": 38.2,
  "ats_rolling": 42.5,
  "fatigue_index": 1.11,
  "readiness_score": 75.0,
  "garmin_readiness_score": 72.0,
  "data_sources": "workouts,physiometrics",
  "canonical_version": "3.0.0",
  "computed_at_utc": "2026-03-05T14:30:00Z"
}
```

**Training State History**:

```http
GET /api/training-state/history?athlete_id=rob&days=45

Response:
{
  "athlete_id": "rob",
  "query_window": {
    "start_date": "2026-01-19",
    "end_date": "2026-03-05",
    "days": 45
  },
  "count": 45,
  "data_points": [
    {
      "effective_date": "2026-01-19",
      "cts_rolling_7d": 38.2,
      "cts_rolling_28d": 35.1,
      "ats_rolling": 38.2,
      "fatigue_index": 1.09,
      "readiness_score": 72.0,
      "garmin_readiness_score": 70.0
    },
    // ... 44 more daily snapshots
  ],
  "computed_at_utc": "2026-03-05T14:30:00Z"
}
```

### Computation Rules

**Chronic Training Stress (CTS)**:

- 7-day CTS = Sum(TSS last 7 days) / 7
- 28-day CTS = Sum(TSS last 28 days) / 28

**Acute Training Stress (ATS)**:

- ATS = 7-day CTS (acute load is short-term average)

**Fatigue Index**:

- Fatigue Index = ATS / CTS (28-day)
- Values < 1.0: Fresh (acute load below chronic baseline)
- Values > 1.2: Fatigued (acute load elevated)

**Composite Readiness**:

- If Garmin readiness available: Use Garmin value
- Otherwise: Weighted average of HRV (normalized) + inverse fatigue index
- HRV normalization: ln_rmssd 2.5-4.5 → 0-100 scale
- Fatigue normalization: fatigue_index 0.5-2.0 → 100-0 scale (inverted)

### Immutability & Recomputability

**TrainingState is deterministic**:

- Same Workouts + Physiometrics data → Same TrainingState output
- No side effects; read-only computation
- Safe to compute multiple times; results identical

**No storage overhead**:

- No TrainingState table to maintain
- No nightly consolidation job needed
- No versioning or migration complexity
- Compute cost negligible (Pandas efficient)

**Trade-offs**:

- **Pros**: Simpler architecture, no stale data, always fresh
- **Cons**: Compute cost per request (acceptable for low traffic)

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
