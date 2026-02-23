# Ingestion Schema

Version: 14.0.0

This document defines the current ingestion payloads, FIT model architecture, and IngestionState table schema.
It is intentionally explicit to avoid ambiguity between ingestion metadata and workout metrics.

For historical changes, see [CHANGELOG.md](../CHANGELOG.md).

## Scope

- **Ingestion payloads** accepted by the ingestion entrypoints.
- **IngestionState** table schema (idempotency + provenance + operational tracking).
- **Workouts** provenance policy (what stays vs what moves to IngestionState).

Ingestion writes canonical parquet payloads (records) and stores
metadata + blob pointers in the Workouts table. Derived metrics are
computed on read, with additional canonical artifacts persisted for
archival and semantic use.

This document does **not** define the workout metrics schema. See WORKOUT_SCHEMA.md for that.

---

## FIT Parsing Architecture (Current)

FIT parsing uses a hierarchical Pydantic model architecture with factory-based instantiation.

### Model Classes

**BaseFitModel** (abstract Pydantic model)

- Encapsulates FIT file parsing via fitdecode
- Provides message indexing and caching
- Implements all artifact builders (build_canonical_records, build_canonical_metadata, build_raw_fit, build_fit_analysis, build_metadata_messages, build_laps_json)
- Computes `semantic_workout_id` as `@property` from start_time_utc_precise + normalized sport

**OneDriveFitModel** (abstract subclass of BaseFitModel)

- Handles OneDrive-sourced FIT files
- Parses HealthFit filename pattern (YYYY-MM-DD-HHMMSS-{ActivityType}-{Source}.fit[.gz])
- Extracts metadata from filename structure

**Concrete Model Classes:**

- **HealthFitModel**: Apple Watch FITs exported via HealthFit app
- **GarminFitModel**: FIT files from Garmin Connect API sync
- **PayloadFitModel**: Generic fallback for other sources

### Factory Function

`create_fit_model(source_metadata: Dict, file_bytes: bytes) -> BaseFitModel`

Inspects `source_metadata` to select appropriate model class and instantiate it:

- OneDrive source + .fit file → HealthFitModel
- Garmin API → GarminFitModel
- Other → PayloadFitModel

**Key Design:**

- No automatic file loading; callers read file_bytes before instantiation
- `file_bytes` is required parameter
- All source provenance consolidates into single `source_metadata` dict

### Handlers Usage Pattern

Handlers call `create_fit_model()` directly (no FitParser facade):

```python
# 1. Prepare source metadata
source_info = {
    "source_system": "Garmin",
    "source_item_id": activity_id,
    # ... additional provenance fields
}

# 2. Read file bytes (handler responsibility)
file_bytes = file.read_bytes()  # or download_fit_bytes()

# 3. Create model
model = create_fit_model(source_metadata=source_info, file_bytes=file_bytes)

# 4. Extract artifacts
metadata = model.build_canonical_metadata()
records = model.build_canonical_records()
raw_fit = model.build_raw_fit(return_dict=True, return_json=False)
metadata_msgs = model.build_metadata_messages()
laps = model.build_laps_json()
analysis = model.build_fit_analysis()

# 5. Get semantic dedup key
semantic_workout_id = model.semantic_workout_id  # Property on model
```

### Semantic Workout ID

Computed as `@property` on BaseFitModel:

```python
semantic_workout_id = SHA1("{start_time_utc_precise}#{normalized_sport}")
```

Where:

- `start_time_utc_precise` is the model's computed_field (best available UTC time)
- `normalized_sport` is the FIT sport field normalized to lowercase

Used as secondary dedup check across sources.

---

## Operational Storage Layout

This section captures the storage-level details that are intentionally hidden
from the semantic API.

### Azure Table Storage

1. `Workouts` — metadata + parquet pointers

    - `PartitionKey`: `athlete_id|YYYY-MM`
    - `RowKey`: `YYYYMMDDTHHMMSS0000|workout_id_prefix`

1. `WeeklyRollups` — aggregated weekly metrics

    - `PartitionKey`: `athlete_id#YYYY`
    - `RowKey`: `YYYY-WW`

1. `IngestionState` — idempotency + provenance

    - `PartitionKey`: `athlete_id`
    - `RowKey`: `ingestion_id`

1. `Physiometrics` — body + fitness metrics (FTP, weight, LTHR)
1. `AgentPreferences` — user training preferences
1. `AgentObservations` — training observations

### Azure Blob Storage

- `workouts` — canonical artifacts and telemetry
  - `{ingestion_id}/canonical.parquet`
  - `{ingestion_id}/raw_fit.json.gz`
  - `{ingestion_id}/fit_analysis.json`
  - `{ingestion_id}/metadata.json`
  - `{ingestion_id}/laps.json`

---

## Ingestion Payload (process_fit / payload ingest)

### Required fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| athlete_id | string | Yes | Athlete identifier. |
| source_file_name | string | Yes | Original filename (e.g., `2026-01-07-...fit`). |
| file_content_b64 | string | Yes | Base64-encoded FIT file content. |

### Optional fields (source provenance)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| source_system | string | No | Source system name (e.g., `HealthFit`, `Local`). |
| source_file_path | string | No | Full source path, if known. |
| source_item_id | string | No | Stable source item ID (e.g., OneDrive item ID). |
| source_drive_id | string | No | Drive ID (OneDrive). |
| source_etag | string | No | OneDrive eTag (version token). |
| source_ctag | string | No | OneDrive cTag (content version token). |
| source_quickxor_hash | string | No | OneDrive quickXor hash for content. |
| source_modified_at_utc | string | No | Source last-modified timestamp (ISO 8601 UTC). |
| file_size_bytes | int | No | Size of FIT file in bytes. |
| file_sha256 | string | No | SHA-256 hash of file content. |

### Notes

- `source_item_id` and `file_sha256` are the preferred inputs for idempotency and
  `ingestion_id` creation.
- If `file_sha256` is not supplied for direct uploads, ingestion computes it from the file.
- `workout_name` is inferred from FIT messages with the following priority:
  1. Activity message name field
  2. Session message session_name field
  3. Constructed from sport and subsport names (e.g., "Cycling-Indoor Cycling")
  4. Activity ID from source system (e.g., Garmin activity ID)
  5. Filename stem (fallback)
- `workout_id` is the stable client-facing identifier and should be **treated as immutable once created**.
- `ingestion_id` is deterministic per-source and is used for idempotency and blob storage paths.

---

## IngestionState Table

This table is the authoritative store for ingestion provenance and idempotency.
It is intentionally separate from Workouts to keep workout entities small and stable.

### Keys

- PartitionKey: `athlete_id`
- RowKey: `ingestion_id`

### Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| status | string | Yes | `ingested`, `failed`, `skipped`. |
| first_seen_at_utc | string | Yes | ISO 8601 UTC timestamp when first observed. |
| last_attempt_at_utc | string | Yes | ISO 8601 UTC timestamp for latest attempt. |
| retry_count | int | Yes | Retry count (increments only on failures). |
| workout_id | string | No | Stable workout ID linked to Workouts table. |
| ingestion_id | string | No | Deterministic source-scoped ingestion identifier. |
| stable_workout_id | string | No | Stable client-facing workout identifier. |
| source_file_name | string | No | Original source filename (e.g., `2026-01-07-...fit`). |
| source_drive_id | string | No | Source drive ID (OneDrive). |
| source_etag | string | No | OneDrive eTag (version token). |
| source_ctag | string | No | OneDrive cTag (content version token). |
| source_quickxor_hash | string | No | OneDrive quickXor hash for content. |
| source_modified_at_utc | string | No | OneDrive last modified timestamp (ISO 8601 UTC). |
| file_sha256 | string | No | SHA-256 hash of file content. |
| ingest_version | string | Yes | Ingestion code version (e.g., `v3.0.8`). |
| ingested_at_utc | string | No | ISO 8601 UTC timestamp when status becomes `ingested`. |
| error_message | string | No | Last error message (truncated). |

### Idempotency rules

- A file is considered **unchanged** when any of the following match previous state:
  `source_ctag`, `source_quickxor_hash`, `file_sha256`, `source_etag`, or
  `source_modified_at_utc` (in that order of preference).
- Unchanged files with a prior status of `ingested` or `skipped` are skipped.
- Skipped ingestions preserve prior provenance values.
- `stable_workout_id` should be reused from existing ingestion state if present.

---

## Workouts Provenance Policy

Workouts should only store minimal provenance and canonical parquet pointers.

### Allowed provenance fields in Workouts

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| source_system | string | Yes | Source system name (e.g., `HealthFit`). |
| normalized_source_system | string | No | Normalized source classification (`HealthFit` for Apple Watch FITs, otherwise `Garmin`). |
| source_item_id | string | No | Stable source item ID (OneDrive item ID). |
| ingestion_id | string | No | Deterministic source-scoped ingestion identifier. |
| semantic_workout_id | string | No | Semantic workout identifier based on start time + sport. |
| canonical_schema_version | string | Yes | Canonical telemetry schema version. |
| canonical_records_blob | string | Yes | Blob path to canonical records parquet. |
| records_count | int | No | Count of canonical records. |
| laps_count | int | No | Count of laps in laps.json. |

All other provenance fields belong in **IngestionState**.

### FIT Analysis Artifact

`{workout_id}/fit_analysis.json` stores deterministic FIT structure analysis output. Current schema includes:

- `analysis_version`
- `message_inventory`
- `classification_evidence`
- `developer_fields_summary`
- `anomalies`
- `summary_flags`

### Metadata Artifact

`{workout_id}/metadata.json` stores deterministic metadata + LLM enrichment placeholders. Current schema includes:

- `metadata_schema_version`
- `extracted_at_utc`
- `raw_fit_messages`
- `llm_enrichment`

### Laps Artifact

`{workout_id}/laps.json` stores uncompressed lap messages. Current schema includes:

- `schema_version`
- `extracted_at_utc`
- `laps`

---

## Timezone Inference (FIT)

When FIT files do not provide an explicit timezone name or device UTC offset,
timezone inference uses local vs UTC timestamps in the FIT messages. The
priority order is:

1. Activity `local_time` (or `local_timestamp`) vs Activity `timestamp`.
2. Session `start_time` (local) vs Session `timestamp - total_elapsed_time`.

This keeps FIT timestamps UTC by spec while recovering a local offset for
workout display and grouping.

---

## Timestamp Formatting

All stored timestamps use ISO 8601 with an explicit UTC offset
(e.g., `2026-02-10T04:00:33.206177+00:00`) and must not use a trailing `Z`.

---

## workout_id Determinism

The `workout_id` is computed deterministically using the best available inputs
in this order:

1. `source_item_id`
2. `file_sha256`
3. `source_file_path` + `source_file_name` + `start_time_utc`

Once a `workout_id` has been assigned to a file, it is treated as immutable
and should be reused for reprocessing via IngestionState lookup.

---

## Data Hygiene (Deferred)

Duplicate resolution for recordings that share the same `start_time_utc`
is deferred to a later data hygiene pass. The ingestion pipeline does not
currently enforce a single winner for these cases.

---

## Enhanced raw_fit.json

The `build_raw_fit()` method uses `fitdecode.cmd.fitjson.RecordJSONEncoder` to provide
full-fidelity JSON serialization including:

- Raw field values (alongside rendered values)
- Definition numbers (def_num)
- Frame headers (frame_type, header_size, protocol_version)
- Chunk positions (chunk_data_offset, chunk_data_size)

This ensures complete round-trip preservation of FIT binary semantics.
Legacy ingestion stored lap summaries in `WorkoutLaps` and per-lap record
payloads as JSON blobs in `lap-records`. Current ingestion stores laps only
in `laps.json` and does not materialize canonical laps parquet.
