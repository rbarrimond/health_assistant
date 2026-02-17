# Phase 1 -- Canonical System Architecture (v1)
<!-- markdownlint-disable MD024 -->
------------------------------------------------------------------------

## Section I. System Overview

- **Canonical Telemetry Storage**: Parquet workout streams
    (device-native FIT parsed)
- **Minimal Workout Metadata Table** referencing parquet blobs
- **Wellness Table** (daily physiological state)
- **GarminTrainingState Table** (vendor model snapshots)
- **Gear Table** (canonical gear artifact)
- **Blob Storage** for `canonical.parquet` and optional
    `metadata.json`
- **Semantic Layer** computes all derived metrics from canonical
    streams

------------------------------------------------------------------------

## Section II. Workout Domain

### Sources

- Apple Watch FIT (OneDrive)
- Garmin Edge / Zwift FIT (Garmin Connect)

### Canonical Output

- Normalized `parquet` stream

### Derived Projections

- Normalized Power (NP)
- Intensity Factor (IF)
- Training Stress Score (TSS)
- Power Curve
- Durability
- Decoupling

### Workout Table Fields

- `workout_id`
- `date`
- `sport`
- `device_source`
- `gear_id`
- `parquet_path`

------------------------------------------------------------------------

## Section III. Wellness Domain

### Sources

- Intervals (HRV, RHR, sleep)
- Withings (weight, body composition)

### Storage

- Daily indexed Azure Table
  - `PartitionKey = athlete_id`
  - `RowKey = YYYY-MM-DD`

### Derived Metrics

- Rolling HRV
- Readiness Score
- Autonomic Stress Index

### Design Notes

- Sparse tolerant
- Nullable physiometrics supported

------------------------------------------------------------------------

## Section IV. Garmin Training State Domain

- Read-only polling via `python-garminconnect`
- Daily snapshot model state:
  - VO2Max
  - LTHR
  - Load
  - Readiness

### Storage

- `PartitionKey = athlete_id`
- `RowKey = YYYY-MM-DD`

### Rules

- Historical snapshots frozen (no retroactive overwrite)
- Vendor-model outputs isolated from canonical metrics

------------------------------------------------------------------------

## Section V. Gear Domain

### Gear Table

- `PartitionKey = athlete_id`
- `RowKey = gear_id (UUID)`

### Fields

- `gear_name`
- `gear_type`
- `is_ebike`
- `has_power_meter`
- `attributes`

### Relationships

- Workout references `gear_id`
- Vendor gear mapping fields optional (Strava/Garmin IDs)
- Supports analytical segmentation by equipment

------------------------------------------------------------------------

## Section VI. Data Flow Architecture

- Garmin → FIT download → Parse → `canonical.parquet`
- Apple Watch → FIT (OneDrive) → Parse → `canonical.parquet`
- Wellness APIs → Normalize → Azure Table upsert
- Garmin State → Poll → Snapshot → Azure Table
- Semantic Layer → Compute projections lazily from canonical stream

------------------------------------------------------------------------

## Section VII. Governance Principles

- Parquet stream is the **single source of workout truth**
- All metrics are **deterministic projections**
- No duplicated scalar storage unless for query optimization
- Vendor platforms are sinks, not authorities
- Architecture designed for sovereignty and recomputability
