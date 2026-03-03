# Canonical Metadata Schema (metadata.json)

**Version**: 2.3.0  
**Effective**: 2026-03-02  
**Status**: Active

---

## Overview

This document specifies the structure of **metadata.json** blobs stored in Azure Blob Storage for each workout ingestion. The metadata.json file is the **authoritative source of truth** for all workout properties beyond the queryable subset stored in the Workouts table.

**Storage Path**: `{container}/{athlete_id}/{workout_id}/metadata.json`

**Semantic Zones**: The metadata structure is partitioned into semantic zones representing different aspects of the workout:

1. **Identity** — FIT semantic fields required for workout identity
2. **Capabilities** — Data availability flags
3. **Provenance** — Ingestion tracking and versioning
4. **Session** — Aggregated session statistics
5. **File Metadata** — FIT file properties
6. **Activity Metadata** — Activity and timing information
7. **Enrichment** — Manual and derived classification
8. **LLM Analysis** — AI/LLM inference results (reserved, not yet implemented)

---

## Schema Definition

```json
{
  "metadata_schema_version": "2.3.0",
  "identity": {
    "start_time_utc": "ISO8601 timestamp",
    "sport": "string (cycling, running, swimming, etc.)",
    "sub_sport": "string (road, mountain, indoor_cycling, etc.)",
    "duration_sec": "integer, total duration in seconds",
    "distance_m": "number, distance in meters",
    "device_name": "string filename-derived source/device token when available for HealthFit (e.g., 'Robert's Apple Watch 7')",
    "device_manufacturer": "string canonicalized for query semantics (e.g., 'Apple', 'garmin')",
    "device_model": "string canonical model name (e.g., 'Apple Watch Ultra 3 49mm', 'Edge 1040')"
  },
  "capabilities": {
    "has_power": "boolean, whether power data is present in canonical records",
    "has_hr": "boolean, whether heart rate data is present in canonical records",
    "has_gps": "boolean, whether GPS position data is present in canonical records"
  },
  "provenance": {
    "ingestion_version": "string (SemVer of ingestion code that processed this file)",
    "ingestion_id": "string (unique ingestion identifier for idempotency)",
    "ingestion_timestamp_utc": "ISO8601 timestamp when ingestion completed",
    "environment": "enum: 'indoor' | 'outdoor' | null",
    "source_device_name": "string, filename-derived source device token when available (e.g., `Robert's Apple Watch Ultra 3`)"
  },
  "session": {
    "avg_speed_mps": "number, average speed in meters/second",
    "max_speed_mps": "number, maximum speed in meters/second",
    "calories_kcal": "number, estimated calories burned",
    "elevation_gain_m": "number, total elevation gain in meters",
    "elevation_loss_m": "number, total elevation loss in meters",
    "moving_time_sec": "integer, time in motion (excluding stops)"
  },
  "file_metadata": {
    "file_time_created_utc": "ISO8601 timestamp from FIT file_id.time_created",
    "file_manufacturer": "string canonicalized for semantic consistency (e.g., Apple for HealthFit Apple Watch exports)",
    "file_manufacturer_raw": "string raw FIT manufacturer enum name/value (e.g., 'development')",
    "file_manufacturer_code": "integer raw FIT manufacturer code when available (e.g., 255)",
    "file_product": "string (product code or name from FIT file)",
    "file_serial_number": "string (device serial number from FIT file)"
  },
  "activity_metadata": {
    "local_tz_offset": "string (e.g., 'UTC-05:00', 'America/New_York'), computed from device, activity, and session messages",
    "Note": "Redundant timestamp fields (activity_timestamp_utc, activity_local_time) removed in v2.0.0—use session.start_time_utc instead"
  },
  "enrichment": {
    "apple_workout_type": "string (e.g., 'Indoor Cycle'), from Apple Watch workout classification",
    "workout_name": "string, user-assigned or inferred workout name",
    "virtual_platform": "string or null (e.g., 'Zwift', 'TrainerRoad', 'Garmin')",
    "commute_flag": "boolean or null, whether workout was commuting",
    "race_flag": "boolean or null, whether workout was racing/event",
    "structured_flag": "boolean or null, whether workout was structured/coached"
  },
  "llm_analysis": {
    "version": "string (version of LLM analysis model)",
    "timestamp_utc": "ISO8601 timestamp when analysis was performed",
    "goals_inference": {
      "description": "Inferred training goals from power distribution, pace, or other signals",
      "confidence": "number 0-1"
    },
    "intensity_classification": {
      "description": "Classification of workout intensity (recovery, endurance, tempo, threshold, VO2max, anaerobic, sprint)",
      "confidence": "number 0-1"
    },
    "performance_summary": {
      "description": "Summary of performance metrics relevant to inferred goals"
    }
  }
}
```

---

## Field Categories

### Identity Zone

**Purpose**: Canonical FIT semantic fields required for workout identity and filtering.

- **start_time_utc**: Activity start time in UTC. Immutable, immutable. Primary sort key together with sport.
- **sport**: Primary activity type from FIT session message. Immutable.
- **sub_sport**: Secondary activity classification. Immutable.
- **duration_sec**: Total workout duration. Immutable.
- **distance_m**: Total distance if GPS/speed available. May be null for indoor activities without distance data.
- **device_name**: For HealthFit ingests, the source/device token preserved exactly as-is from filename segment 4. Contains original spaces (e.g., `Robert's Apple Watch 7`), hyphens, and apostrophes. Not normalized or mutated by ingestion.
- **device_manufacturer**: Canonical manufacturer label used for semantic queries and Workouts projection.
- **device_model**: Canonical device model label used for semantic queries and Workouts projection (Apple Watch internal IDs are mapped to friendly names when known).

### Capabilities Zone

**Purpose**: Data availability flags enabling query-time filtering without scanning canonical records.

- **has_power**: True if any power values present in canonical records. Enables filtering workouts with power data.
- **has_hr**: True if any heart rate values present in canonical records.
- **has_gps**: True if any position records present in canonical records.

Computed at ingestion time by scanning canonical.parquet; immutable thereafter.

### Provenance Zone

**Purpose**: Ingestion tracking and versioning for reproducibility and debugging.

- **ingestion_version**: SemVer of ingestion code (e.g., "1.5.0"). Enables tracking which ingestion rules applied.
- **ingestion_id**: Unique identifier for this ingestion (hash of file contents). Immutable.
- **ingestion_timestamp_utc**: When ingestion completed. Immutable.
- **environment**: Extracted from FIT message or inferred. Clarifies indoor vs. outdoor context.
- **source_device_name**: Full filename-derived HealthFit source/device token retained for provenance.

All fields immutable after ingestion.

### Session Zone

**Purpose**: Aggregated statistics from FIT session message.

- All derived from FIT session message or computed from records.
- May be recomputed during analysis but represent session-level aggregates.

### File Metadata Zone

**Purpose**: FIT file-level identity/provenance information for device tracking and debugging.

- `file_manufacturer` stores canonical manufacturer semantics used for consistency with identity/workouts fields.
- `file_manufacturer_raw` and `file_manufacturer_code` preserve raw FIT provenance for audit/debug.
- Extracted from FIT file_id message.
- Immutable.
- May be null if FIT file lacks these fields.

### Activity Metadata Zone

**Purpose**: Activity-level timing and location information.

- Extracted from FIT activity and file_id messages.
- Provides context for downstream analytics (e.g., time-of-day, local timezone).

### Enrichment Zone

**Purpose**: Manual and derived classification not present in FIT file.

- **apple_workout_type**: Classification from Apple HealthKit API (only present if source is Apple Watch).
- **workout_name**: User-assigned name or inferred label. For HealthFit, canonical inference uses `<day part> <apple workout type>`.
- **virtual_platform**: Software platform used (Zwift, TrainerRoad, etc.), inferred or explicit.
- **{commute,race,structured}_flag**: Contextual flags. Nullable to distinguish "not set" from "false".

Mutable — may be updated by enrichment pipeline.

### LLM Analysis Zone

**Purpose**: Reserved for future AI/LLM inference results.

**Status**: NOT YET IMPLEMENTED. Structure is placeholder for future use.

**When implemented**, this zone will contain:

- **version**: Track which LLM model and prompt template was used
- **timestamp_utc**: When analysis was performed
- **goals_inference**: What training goals the LLM inferred from the data
- **intensity_classification**: Structured intensity categorization
- **performance_summary**: LLM-generated narrative summary or structured performance assessment

**Note**: This zone should NEVER be populated by services other than the designated LLM analysis pipeline. Other services must read it only.

---

## Versioning

**current_version**: 2.3.0

**Migration from 2.2.0 → 2.3.0**:

- Added `identity.device_name` for HealthFit ingests using the filename `<source/device name>` token.
- Clarified filename contract preservation semantics for source/device identity capture.

**Migration from 2.1.0 → 2.2.0**:

- Added `provenance.source_device_name` to preserve HealthFit filename source-device identity token independently from FIT-derived device identity fields.
- HealthFit `enrichment.workout_name` inference contract now uses constructed naming `<day part> <apple workout type>`.

**Migration from 2.0.0 → 2.1.0**:

- Identity zone contract clarified to canonical query fields: `device_manufacturer`, `device_model`.
- Added immutable FIT provenance fields in `file_metadata`: `file_manufacturer_raw`, `file_manufacturer_code`.
- Canonical `file_manufacturer` now represents normalized semantic manufacturer values.

**Backward Compatibility**:

- No automatic migration. Workouts ingested under schema 1.5.0 retain old metadata.
- Queries must handle both schema versions during transition period.

---

## Immutability Contract

**Immutable after ingestion**:

- Identity zone (entire)
- Capabilities zone (entire)
- Provenance zone (entire)
- File Metadata zone (entire)
- Activity Metadata zone (entire)

**Mutable**:

- Enrichment zone (individual flags may be updated by enrichment pipeline)
- LLM Analysis zone (updated only by designated analysis service)

---

## Storage and Access

**Blob Encoding**: UTF-8 JSON, JSON-serializable types only

**Blob Path**: `workouts/{athlete_id}/{workout_id}/metadata.json`

**Lifecycle**:

- Created during ingestion
- May be updated by enrichment pipeline (mutable zones)
- Queried by analytics/reporting but not modified by them

**Related Artifacts**:

- `canonical.parquet` — Canonical substrate records (Section I in ingestion schema)
- `laps.json` — Lap messages from FIT file

---

## Field Nullability Guidelines

**Required (never null)**:

- `identity.start_time_utc`, `identity.sport`
- `provenance.ingestion_version`, `provenance.ingestion_id`, `provenance.ingestion_timestamp_utc`

**Nullable (may be null)**:

- `capabilities.*` (if data availability cannot be determined)
- `session.*` (if workout lacks that metric type)
- `file_metadata.*` (if FIT file lacks these fields)
- `activity_metadata.*` (if FIT file lacks these fields)
- `enrichment.*` (if not yet classified)
- `llm_analysis` (not yet implemented)

---

## Example metadata.json

```json
{
  "metadata_schema_version": "2.3.0",
  "identity": {
    "start_time_utc": "2025-12-04T01:45:18+00:00",
    "sport": "cycling",
    "sub_sport": "indoor_cycling",
    "duration_sec": 3604,
    "distance_m": 26.11965,
    "device_name": "Robert's Apple Watch 7",
    "device_manufacturer": "Apple",
    "device_model": "Apple Watch Ultra 3 49mm"
  },
  "capabilities": {
    "has_power": true,
    "has_hr": false,
    "has_gps": false
  },
  "provenance": {
    "ingestion_version": "1.5.0",
    "ingestion_id": "onedrive:2DE1CE6A0066F643!s6dfff5239a4a4809a9d16722f8381323",
    "ingestion_timestamp_utc": "2025-12-04T01:50:00+00:00",
    "environment": "indoor",
    "source_device_name": "Robert's-Apple-Watch-7"
  },
  "session": {
    "avg_speed_mps": 26.0892,
    "max_speed_mps": 26.3016,
    "calories_kcal": 464,
    "elevation_gain_m": null,
    "elevation_loss_m": null,
    "moving_time_sec": 3604
  },
  "file_metadata": {
    "file_time_created_utc": "2025-12-04T01:45:18+00:00",
    "file_manufacturer": "Apple",
    "file_manufacturer_raw": "development",
    "file_manufacturer_code": 255,
    "file_product": "Watch7,12",
    "file_serial_number": "27753"
  },
  "activity_metadata": {
    "local_tz_offset": "America/New_York"
  },
  "enrichment": {
    "apple_workout_type": "Indoor Cycle",
    "workout_name": "Indoor Cycling",
    "virtual_platform": null,
    "commute_flag": null,
    "race_flag": false,
    "structured_flag": null
  },
  "llm_analysis": null
}
```

---

## References

- [CANONICAL_DATA_ARCHITECTURE.md](CANONICAL_DATA_ARCHITECTURE.md) — Workouts table structure and identity model
- [INGESTION_SCHEMA.md](INGESTION_SCHEMA.md) — FIT ingestion contract and message requirements
