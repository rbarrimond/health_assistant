# Ingestion Schema

Version: 15.0.24

This document defines the current ingestion payloads, FIT model architecture, and IngestionState table schema.
It is intentionally explicit to avoid ambiguity between ingestion metadata and workout metrics.

For historical changes, see [CHANGELOG.md](../../CHANGELOG.md).

## Scope

- **Ingestion payloads** accepted by the ingestion entrypoints.
- **IngestionState** table schema (idempotency + provenance + operational tracking).
- **Workouts** provenance policy (what stays vs what moves to IngestionState).

Ingestion writes canonical parquet payloads (records) and stores metadata + blob pointers in the Workouts table.
Derived metrics are computed on read, with additional canonical artifacts persisted for archival and semantic use.

This document does **not** define the workout metrics schema. See [WORKOUT_SCHEMA.md](../../gpt/WORKOUT_SCHEMA.md) for that.

## Identity Model (Ingestion vs Workout)

- `ingestion_id` is the source-system identity used for idempotency and storage paths.
  - OneDrive: OneDrive item ID.
  - Garmin API: Garmin activity ID.
  - HTTP payload: SHA-256 digest of decoded FIT bytes.
- `workout_id` is the semantic identity derived from FIT timestamps and sport.
- Artifact blob paths are keyed by `ingestion_id`.

Implementation note: current storage paths use `workout_id` for blob prefixes. This is a known mismatch and will be refactored to align with the intended `ingestion_id`-keyed storage contract.

## Canonical Schema Source of Truth

Canonical schema documentation is centralized in this document.

### Canonical telemetry field schema

- Canonical record field definitions are modeled by `CanonicalRecord` in `TrainingAnalyticsPlatform/models/substrate.py`.
- `BaseFitModel.build_canonical_records()` must emit records conforming to that schema.
- Canonical records are serialized to `{ingestion_id}/canonical.parquet`.

### Canonical schema version

- `canonical_schema_version` persisted in Workouts is sourced from `CANONICAL_SCHEMA_VERSION` in `TrainingAnalyticsPlatform/storage/table_storage.py`.
- The value is attached during ingestion in `FitIngestionBaseHandler._parse_and_store()`.

Current canonical schema version: `1.3.0`.

### Change management contract

- Any canonical telemetry field add/remove/rename/type change requires:
  1. Bumping `CANONICAL_SCHEMA_VERSION`
  2. Updating this document
  3. Recording the change in `docs/CHANGELOG.md`
- Non-breaking documentation clarifications in this file still require incrementing the document version at the top of this file.

### Version registry (authoritative)

All ingestion-related schema/code version constants must be documented here.

| Version | Current value | Code source | Purpose |
| --- | --- | --- | --- |
| `INGEST_VERSION` | `v13.0.26` | `TrainingAnalyticsPlatform/ingestion/constants.py` | Ingestion code version persisted to `IngestionState.ingest_version`. |
| `CANONICAL_SCHEMA_VERSION` | `1.3.0` | `TrainingAnalyticsPlatform/storage/table_storage.py` | Canonical parquet schema version persisted to `Workouts.canonical_schema_version`. |
| `METADATA_SCHEMA_VERSION` | `1.0.0` | `TrainingAnalyticsPlatform/ingestion/constants.py` | Version emitted in `metadata.json` as `metadata_schema_version`. |
| `LAPS_SCHEMA_VERSION` | `1.0.0` | `TrainingAnalyticsPlatform/ingestion/constants.py` | Version emitted in `laps.json` as `schema_version`. |
| `FIT_ANALYSIS_VERSION` | `v1.0.0` | `TrainingAnalyticsPlatform/ingestion/constants.py` | Version emitted in `fit_analysis.json` as `analysis_version`. |

---

## FIT Parsing Architecture (Current)

FIT parsing uses a hierarchical Pydantic model architecture with factory-based instantiation.

### Model Classes

**BaseFitModel** (abstract Pydantic model)

- Encapsulates FIT file parsing via fitdecode
- Provides message indexing and caching
- Parses/indexes FIT messages eagerly during model instantiation (no lazy message loading)
- Implements all artifact builders (build_canonical_records, build_canonical_metadata, build_raw_fit, build_fit_analysis, build_metadata_messages, build_laps_json)
- Computes semantic workout identity from start_time_utc + normalized sport

**OneDriveFitModel** (abstract subclass of BaseFitModel)

- Handles OneDrive-sourced FIT files
- Extracts metadata from filename structure

**Concrete Model Classes:**

- **HealthFitModel**: Apple Watch FITs exported via HealthFit app
  - Parses HealthFit filename pattern (YYYY-MM-DD-HHMMSS-{ActivityType}-{Source}.fit[.gz])
  - Treats HealthFit filename `YYYY-MM-DD-HHMMSS` timestamp as recording-device local time (not UTC)
- **GarminFitModel**: FIT files from Garmin Connect API sync
- **PayloadFitModel**: Generic fallback for other sources

### Factory Function

`create_fit_model(source_metadata: Dict, file_bytes: bytes) -> BaseFitModel`

Inspects `source_metadata` to select appropriate model class and instantiate it:

- OneDrive source + .fit file → HealthFitModel
- Garmin API → GarminFitModel
- HTTP → PayloadFitModel

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

# 5. Compute workout_id from semantic identity
workout_id = model.semantic_workout_id
```

### Semantic Workout Identity

Computed as `model.semantic_workout_id` on BaseFitModel:

```python
workout_id = SHA1("{start_time_utc}#{normalized_sport}")
```

Where:

- `start_time_utc` is the model's computed_field (best available UTC time)
- `normalized_sport` is normalized in this priority order:
  1. Sport message `sport` field
  2. Session `sport` field

FIT sport validity contract:

- FIT files must contain a valid sport in either sport or session messages.
- Missing sport is treated as a fatal FIT parsing failure (`FIT_PARSING_FAILED`).
- There is no source-specific filename fallback for semantic sport.

`start_time_utc` resolves in this order:

1. Event start `timestamp`
2. Session-derived UTC start: `session.timestamp - session.total_elapsed_time`
3. First record `timestamp`

Canonical start-time validity contract:

- `start_time_utc` must come from FIT message timestamps only.
- Session `start_time` is local wall-clock context and must not be treated as UTC.
- HealthFit filename local wall-clock timestamps must not be used to fabricate `start_time_utc`.
- FIT files with no usable FIT-derived start timestamp are invalid for semantic identity and must be rejected.

Timezone offset contract:

- `start_time_utc` remains UTC and is never converted to local wall-clock time in storage.
- `local_tz_offset` stores the local wall-clock UTC offset string when derivable (for example `UTC-05:00`).
- `timezone` is retained as a compatibility alias of `local_tz_offset`.
- Unknown local offsets must remain unset (`null`) and must not be defaulted to `UTC`.

`workout_id` is required for successful ingestion and is derived from semantic identity.
If semantic ID cannot be computed, ingestion must fail.

---

---

## FIT Semantic Contract (Required Messages)

The ingestion layer enforces a strict FIT semantic contract. FIT parsing is not best-effort and does not attempt to fabricate missing semantics.

This section documents the required `file_id` and `session` messages and their purpose.

### file_id Message (Required)

The `file_id` message defines the file-level identity and type.

Required fields:

- `type` — must equal `activity`

Optional identity fields (normalized by BaseFitModel):

- `manufacturer`
- `product` or `garmin_product`
- `serial_number`
- `time_created`

Device-specific fields must be normalized inside `BaseFitModel` into a single canonical device identity representation. Downstream systems must not branch on raw FIT field names such as `garmin_product`.

Purpose:

- Declares the FIT file category (activity vs workout vs other types).
- Establishes device provenance.
- Anchors the semantic interpretation of the entire file.

Contract:

- Files where `file_id.type != activity` must be rejected.
- Missing `file_id` is a fatal parsing failure (`FIT_PARSING_FAILED`).
- Ingestion must not infer file type from context or filename.

Rationale:

`file_id` is the root semantic declaration. Without it, the file cannot be safely interpreted as an activity.

Device identity normalization contract:

- If `manufacturer == garmin`, prefer `garmin_product` when present; otherwise use `product`.
- Downstream systems must consume a single normalized `product_id` and must not reference vendor-prefixed FIT fields directly.
- FIT protocol field names are transport-layer concerns and must not leak past `BaseFitModel`.

---

### session Message (Required for Activity Files)

An activity FIT file must contain at least one `session` message.

Required semantic fields:

- `sport`
- `total_elapsed_time`
- `total_timer_time`
- `timestamp`

Purpose:

- Defines the sport classification.
- Provides activity-level summary metrics.
- Defines the temporal envelope for associated records.
- Enables deterministic semantic identity derivation.

Contract:

- Missing `session` is a fatal parsing failure (`FIT_PARSING_FAILED`).
- Multiple sessions are allowed by FIT, but current ingestion expects exactly one session unless explicitly expanded to support multi-session activities.
- Sport must be derived from FIT messages only (sport message preferred, session fallback allowed).
- Ingestion must not infer sport from filenames or external metadata.

Prohibited behaviors:

- Do not fabricate a session from record timestamps.
- Do not compute synthetic totals to replace missing session fields.
- Do not infer sport from laps or filename tokens.

Rationale:

`record` messages are stateless telemetry. Without `session`, records cannot be interpreted as a coherent activity. The `session` message is the semantic anchor for sport, duration, and identity.

---

### activity Message (Closure Summary)

If present, the `activity` message must be validated but is not currently required.

Expected fields:

- `num_sessions`
- `total_timer_time`
- `timestamp`

Validation rules (if present):

- `num_sessions` must equal the number of parsed session messages.
- `total_timer_time` should approximately equal the sum of session timer times.

The `activity` message acts as a file-level closure summary. It must not override session-level truth.

---

### Invariant Summary

For `file_id.type == activity`, ingestion requires:

1. Exactly one `file_id`.
2. At least one `session`.
3. At least one `record`.
4. Valid sport classification from FIT messages.

Violations result in HTTP 422 and domain error `FIT_PARSING_FAILED`.

There are no semantic fallbacks.

---

### Anti-Patterns (Explicitly Forbidden)

The following behaviors are prohibited because they violate FIT semantics and corrupt deterministic identity:

1. **Synthetic Session Reconstruction**
   - Do not fabricate a `session` from first/last record timestamps.
   - Do not compute synthetic `total_elapsed_time` or `total_timer_time` when missing.

2. **Sport Inference from Non-FIT Sources**
   - Do not infer sport from filenames, directory paths, or external metadata.
   - Do not infer sport from lap names.

3. **Record-Derived Activity Identity**
   - Do not derive semantic identity from record-only inspection if session is missing.
   - Do not fallback to first record timestamp when session exists but is malformed.

4. **Silent Field Repair**
   - Do not silently coerce missing required FIT fields to default values.
   - Do not replace missing timezone offsets with `UTC`.

If a required semantic invariant is violated, ingestion must fail deterministically.

---

### Validation Checklist (BaseFitModel.validate_semantic_contract)

Before any artifact builders execute, the model must pass structural validation.

Minimum validation contract for `file_id.type == activity`:

1. Exactly one `file_id` message.
2. `file_id.type == activity`.
3. At least one `session` message.
4. At least one `record` message.
5. Valid sport classification from FIT `sport` or `session.sport`.
6. Valid UTC timestamp derivable from FIT messages.

Additional structural integrity checks:

- Record timestamps must be monotonic (non-decreasing).
- Session `total_elapsed_time` must be non-negative.
- If `activity` message exists, `num_sessions` must equal parsed session count.

Validation must occur prior to:

- Canonical record construction
- Semantic workout ID computation
- Artifact generation

Failure must raise domain error `FIT_PARSING_FAILED` and result in HTTP 422.

---

### Record-to-Session Assignment Rules

`record` messages are global time-series telemetry. They do not inherently belong to a session.

Session assignment must follow deterministic timestamp boundaries:

1. Sort sessions by `timestamp - total_elapsed_time` (derived session start UTC).
2. Define session time window as:
   - `session_start_utc = session.timestamp - session.total_elapsed_time`
   - `session_end_utc = session.timestamp`
3. Assign each record to the session whose time window contains the record timestamp.

Prohibited:

- Do not assign records to sessions based on lap grouping alone.
- Do not infer session membership from sport changes in record messages.
- Do not assume a single session unless validated.

If a record falls outside all session windows, ingestion must fail.

---

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
1. `AgentObservations` — client GPT's training observations

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

- `ingestion_id` is the source-system identity. Use OneDrive item ID or Garmin activity ID
  when available; for direct HTTP uploads, use the SHA-256 digest of decoded FIT bytes.
- If `file_sha256` is not supplied for direct uploads, ingestion computes it from the file.
- OneDrive ingestion requires `source_item_id`; missing ID is treated as a hard failure.
- FIT payloads that cannot be parsed (malformed or incompatible bytes) must fail with typed domain error `FIT_PARSING_FAILED` and HTTP 422.
- `workout_name` is inferred with the following priority:
  1. Workout FIT message name (`wkt_name`, with `name` compatibility fallback)
  2. External source metadata activity name (e.g., Garmin API `source_activity_name`)
  3. Source-specific subclass lookup (HealthFit filename activity type)
  4. Constructed fallback:
  - `"<Daypart> <Apple Workout Type>"` when Apple workout type can be derived from FIT sport/sub-sport
  - otherwise `"<sport>-<sub_sport>-<local_start_datetime>"` using normalized lowercase FIT sport fields
- Apple workout typing contract:
  - `AppleWorkoutTypeResolver` maps only FIT `sport` + `sub_sport`
    - includes virtual mappings by sport: `("cycling", "virtual_activity") -> "Indoor Cycle"`, `("running", "virtual_activity") -> "Indoor Run"`, `("walking", "virtual_activity") -> "Indoor Walk"`
  - `HealthFitModel` resolves Apple workout type from HealthFit filename activity token via source-specific logic
- `workout_id` is the stable client-facing identifier and should be **treated as immutable once created**.
- `workout_id` is computed from semantic identity and has **no fallback**.
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
| source_file_name | string | No | Original source filename (e.g., `2026-01-07-...fit`). |
| source_drive_id | string | No | Source drive ID (OneDrive). |
| source_etag | string | No | OneDrive eTag (version token). |
| source_ctag | string | No | OneDrive cTag (content version token). |
| source_quickxor_hash | string | No | OneDrive quickXor hash for content. |
| source_modified_at_utc | string | No | OneDrive last modified timestamp (ISO 8601 UTC). |
| file_sha256 | string | No | SHA-256 hash of file content. |
| ingest_version | string | Yes | Ingestion code version (current: `v13.0.26`). |
| ingested_at_utc | string | No | ISO 8601 UTC timestamp when status becomes `ingested`. |
| error_message | string | No | Last error message (truncated). |

### Idempotency rules

- A file is considered **unchanged** when any of the following match previous state:
  `source_ctag`, `source_quickxor_hash`, `file_sha256`, `source_etag`, or
  `source_modified_at_utc` (in that order of preference).
- Unchanged files with a prior status of `ingested` or `skipped` are skipped.
- Skipped ingestions preserve prior provenance values.

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
| canonical_schema_version | string | Yes | Canonical telemetry schema version. |
| canonical_records_blob | string | Yes | Blob path to canonical records parquet. |
| records_count | int | No | Count of canonical records. |
| laps_count | int | No | Count of laps in laps.json. |

All other provenance fields belong in **IngestionState**.

### FIT Analysis Artifact

`{ingestion_id}/fit_analysis.json` stores deterministic FIT structure analysis output. Current schema includes:

Current `analysis_version`: `v1.0.0`.

- `analysis_version`
- `message_inventory`
- `classification_evidence`
- `developer_fields_summary`
- `anomalies`
- `summary_flags`

### Metadata Artifact

`{ingestion_id}/metadata.json` stores deterministic metadata + LLM enrichment placeholders. Current schema includes:

Current `metadata_schema_version`: `1.0.0`.

- `metadata_schema_version`
- `extracted_at_utc`
- `raw_fit_messages`
- `llm_enrichment`

### Laps Artifact

`{ingestion_id}/laps.json` stores uncompressed lap messages. Current schema includes:

Current laps `schema_version`: `1.0.0`.

- `schema_version`
- `extracted_at_utc`
- `laps`

---

## Timezone Inference (FIT)

When FIT files do not provide an explicit timezone name or device UTC offset,
timezone inference uses local vs UTC timestamps in the FIT messages. The
priority order is:

1. Activity `local_timestamp` vs Activity `timestamp`, only when `local_timestamp` is not equal to FIT epoch (1989-12-31T00:00:00).
2. Session `start_time` (local wall-clock context) vs Session `timestamp - total_elapsed_time`.

This keeps FIT timestamps UTC by spec while recovering a local offset fora
workout display and grouping.

FIT epoch handling rule:

- `local_timestamp` equal to FIT epoch (`1989-12-31T00:00:00`) represents an unset value and must be treated as null.
- Epoch-equivalent values must not be used to derive timezone offsets.

`Workouts.timezone` stores this recovered offset as `UTC±HH:MM` and should be
used together with `start_time_utc` by clients when rendering local start time.

---

### Timestamp Trust Model (Copilot Guardrail)

To prevent accidental semantic corruption, the following timestamp trust rules are mandatory:

1. `session.timestamp` is canonical UTC and must never be localized or mutated.
2. `event.timestamp` values are canonical UTC and must never be localized or mutated.
3. `record.timestamp` values are canonical UTC and must never be localized or mutated.
4. `session.start_time` values are canonical UTC and must never be localized or mutated.
5. `activity.local_timestamp` is a FIT `date_time` field representing device local wall-clock context. It must NOT be treated as authoritative UTC. If it equals FIT epoch (`1989-12-31T00:00:00`), it represents an unset value and must be ignored for timezone inference.

Prohibited behaviors:

- Do not automatically convert UTC timestamps to local time during parsing.
- Do not overwrite stored UTC timestamps with localized values.
- Do not apply `local_tz_offset` to mutate stored timestamps.
- Do not assume `activity.local_timestamp` is UTC.

All timestamps persisted in storage remain UTC. Local wall-clock context is represented only via `local_tz_offset`.

Any automatic timestamp localization during parsing is a semantic violation.

---

---

## Timestamp Formatting

All stored timestamps use ISO 8601 with an explicit UTC offset
(e.g., `2026-02-10T04:00:33.206177+00:00`) and must not use a trailing `Z`.

---

## workout_id Determinism

The `workout_id` is computed deterministically as semantic identity:

1. `start_time_utc`
2. normalized FIT sport code/name

Formula:

`SHA1("{start_time_utc}#{normalized_sport}")`

There is no fallback. If semantic identity cannot be computed, ingestion fails.

## ingestion_id Determinism

`ingestion_id` is computed by concrete source handlers using source-specific context:

1. OneDrive: `source_item_id` (required; no fallback)
2. Garmin API: `source_item_id` (activity ID)
3. HTTP payload: `file_sha256` of decoded FIT bytes

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
