# Ingestion Schema

Version: 7.0.0

This document defines the ingestion payloads and the IngestionState table schema.
It is intentionally explicit to avoid ambiguity between ingestion metadata and workout metrics.

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
    - `RowKey`: `source_item_id` OR `file_sha256` OR `workout_id`

1. `Physiometrics` — body + fitness metrics (FTP, weight, LTHR)
1. `AgentPreferences` — user training preferences
1. `AgentObservations` — training observations

### Azure Blob Storage

- `workouts` — canonical artifacts and telemetry
  - `{workout_id}/canonical.parquet`
  - `{workout_id}/raw_fit.json.gz`
  - `{workout_id}/fit_analysis.json`
  - `{workout_id}/metadata.json`
  - `{workout_id}/laps.json`

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
  `workout_id` creation.
- If `file_sha256` is not supplied for direct uploads, ingestion computes it from the file.
- `workout_name` is inferred from FIT messages with the following priority:
  1. Activity message name field
  2. Session message session_name field
  3. Constructed from sport and subsport names (e.g., "Cycling-Indoor Cycling")
  4. Activity ID from source system (e.g., Garmin activity ID)
  5. Filename stem (fallback)
- `workout_id` is deterministic and should be **treated as immutable once created**.

---

## IngestionState Table

This table is the authoritative store for ingestion provenance and idempotency.
It is intentionally separate from Workouts to keep workout entities small and stable.

### Keys

- PartitionKey: `athlete_id`
- RowKey: `source_item_id` OR `file_sha256` OR `workout_id`

### Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| status | string | Yes | `ingested`, `failed`, `skipped`. |
| first_seen_at_utc | string | Yes | ISO 8601 UTC timestamp when first observed. |
| last_attempt_at_utc | string | Yes | ISO 8601 UTC timestamp for latest attempt. |
| retry_count | int | Yes | Retry count (increments only on failures). |
| workout_id | string | No | Workout ID linked to Workouts table. |
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
- `workout_id` should be reused from existing ingestion state if present.

---

## Workouts Provenance Policy

Workouts should only store minimal provenance and canonical parquet pointers.

### Allowed provenance fields in Workouts

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| source_system | string | Yes | Source system name (e.g., `HealthFit`). |
| normalized_source_system | string | No | Normalized source classification (`HealthFit` for Apple Watch FITs, otherwise `Garmin`). |
| source_item_id | string | No | Stable source item ID (OneDrive item ID). |
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

## Lap Record Storage (Legacy)

Legacy ingestion stored lap summaries in `WorkoutLaps` and per-lap record
payloads as JSON blobs in `lap-records`. Current ingestion stores laps only
in `laps.json` and does not materialize canonical laps parquet.
