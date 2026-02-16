# Workout Metrics Schema — Azure Table Storage

Version: 7.0.0

This schema is designed to support:

- a canonical substrate stored as parquet (Section I)
- semantic layer queries without changing the API surface
- workout planning context payloads

It assumes:

- **OneDrive Personal** holds the raw `.fit` files (`/Apps/Apps/HealthFit/*.fit`)
- **Python ingestion** parses FIT and writes canonical parquet + metadata
- **Azure Table Storage** stores workout metadata + parquet pointers

---

## Tables

1. `Workouts` — **one entity per workout** (metadata + parquet pointers)
2. `WeeklyRollups` — **one entity per week** (optional but recommended)
3. `IngestionState` — **idempotency + operational tracking** (recommended)
4. `Physiometrics` — **body and fitness metrics** (FTP, weight, LTHR, etc.)
5. `AgentPreferences` — **user training preferences and goals** (agent memory)
6. `AgentObservations` — **training patterns and observations** (agent memory)

> **Note:** `WorkoutLaps` and `lap-records` are legacy stores. Laps now live in parquet.

> **Note:** Tables 5-6 are part of the Agent Memory System. See [AGENT_MEMORY.md](./AGENT_MEMORY.md) for details.

---

## Canonical Substrate (Parquet)

Canonical records are stored as parquet in Azure Blob Storage and represent the
lowest-level substrate for derived metrics.

**Container:** `canonical-substrate`

**Blob name:** `{workout_id}/canonical-records.parquet`

### Section I Fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|timestamp_utc|datetime (ISO string)|✅|Record timestamp UTC|
|elapsed_sec|float|⛔️|Elapsed seconds since workout start|
|power_watts|float|⛔️|Instantaneous power|
|heart_rate_bpm|float|⛔️|Instantaneous heart rate|
|cadence_rpm|float|⛔️|Instantaneous cadence|
|speed_mps|float|⛔️|Instantaneous speed|
|distance_m|float|⛔️|Cumulative distance|
|elevation_m|float|⛔️|Instantaneous elevation|

### Canonical Laps (Parquet)

**Container:** `canonical-laps`

**Blob name:** `{workout_id}/canonical-laps.parquet`

|Field|Type|Required|Description|
|---|---:|:---:|---|
|lap_index|int|✅|Lap sequence index|
|start_time_utc|datetime (ISO string)|⛔️|Lap start UTC|
|elapsed_sec|float|⛔️|Lap elapsed seconds|
|moving_time_sec|float|⛔️|Lap moving time seconds|
|distance_m|float|⛔️|Lap distance meters|
|calories_kcal|float|⛔️|Lap calories|
|avg_heart_rate_bpm|float|⛔️|Average HR|
|max_heart_rate_bpm|float|⛔️|Max HR|
|avg_power_watts|float|⛔️|Average power|
|max_power_watts|float|⛔️|Max power|
|avg_cadence_rpm|float|⛔️|Average cadence|
|max_cadence_rpm|float|⛔️|Max cadence|

## 1) Workouts Table

### Keying strategy (recommended)

- `PartitionKey`: `athlete_id|YYYY-MM` (e.g., `rob|2026-01`)
- `RowKey`: `YYYYMMDDTHHMMSS0000|workout_id_prefix` (e.g., `20260107T2315000000|b6d2c0a1e9b4`)

Why:

- month partitions keep queries bounded and cheap
- RowKey is sortable by time within partition
- stable workout_id supports direct lookup
- RowKey stores the first 12 characters of `workout_id` to keep keys short

### Core identity fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|PartitionKey|string|✅|`athlete_id\|YYYY-MM`|
|RowKey|string|✅|`start_time_utc_compact\|workout_id_prefix`|
|workout_id|string|✅|Stable unique id (see **workout_id generation**)|
|athlete_id|string|✅|Short stable identifier for the athlete (e.g., `rob`)|
|source_system|string|✅|`HealthFit` (or `Garmin`, `Strava`, etc. if expanded later)|
|source_item_id|string|⛔️|Source item ID (if available)|

#### workout_id generation (deterministic)

Preferred order:

1. `source_item_id` (if available): `sha1(source_item_id)`
2. `sha1(file_sha256)`
3. `sha1(source_file_path + source_file_name + start_time_utc)`

> Goal: stable across reprocessing; changes only if the underlying file truly changes.

---

### Temporal & classification fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|start_time_utc|datetime (ISO string)|✅|Workout start time UTC, e.g. `2026-01-07T23:15:00+00:00`|
|timezone|string|⛔️|Source timezone if available (UTC offset like `UTC-05:00`)|
|duration_sec|int|✅|Total elapsed duration (seconds)|
|moving_time_sec|int|⛔️|Moving time if derivable (cycling often equals duration)|
|sport|string|✅|Generic FIT sport (`cycling`, `running`, `strength_training`, etc.)|
|sub_sport|string|⛔️|Generic FIT sub-sport (`indoor_cycling`, `gravel`, `strength_training`, etc.) if available|
|apple_workout_type|string|⛔️|Apple Watch workout type (`Functional Strength Training`, `Indoor Cycle`, etc.) if detected|
|workout_name|string|⛔️|Workout title (HealthFit/Strava/Garmin name)|
|device_name|string|⛔️|Device model if present|
|is_indoor|bool|⛔️|Indoor flag if derivable|

### Canonical parquet pointers

|Field|Type|Required|Description|
|---|---:|:---:|---|
|canonical_records_blob|string|✅|Blob path for canonical records parquet|
|canonical_laps_blob|string|⛔️|Blob path for canonical laps parquet|
|records_count|int|⛔️|Number of canonical records|
|laps_count|int|⛔️|Number of canonical laps|

### FIT metadata (File / Device / Activity)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|file_time_created_utc|datetime (ISO string)|⛔️|FIT file creation time|
|file_manufacturer|string|⛔️|FIT file manufacturer name|
|file_product|string|⛔️|FIT file product identifier|
|file_serial_number|string|⛔️|FIT file serial number|
|activity_timestamp_utc|datetime (ISO string)|⛔️|Activity timestamp UTC|
|activity_local_time|datetime (ISO string)|⛔️|Activity local timestamp (local timezone, no UTC conversion)|

---

## 2) WorkoutLaps Table (Legacy)

Legacy lap summaries and record blobs. New ingestion uses canonical laps parquet.

### Keying strategy

- `PartitionKey`: `workout_id`
- `RowKey`: zero-padded lap index (e.g., `0000`, `0001`)

### Core fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|PartitionKey|string|✅|`workout_id`|
|RowKey|string|✅|Zero-padded lap index|
|workout_id|string|✅|Workout id|
|athlete_id|string|✅|Athlete identifier|
|lap_index|int|✅|Lap sequence index|
|record_count|int|✅|Number of records in lap blob|
|blob_name|string|⛔️|Blob name for lap record payload|

### Lap summary fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|start_time|datetime|⛔️|Lap start time UTC|
|total_elapsed_time|float|⛔️|Lap elapsed time (sec)|
|total_timer_time|float|⛔️|Lap moving time (sec)|
|total_distance|float|⛔️|Lap distance (meters)|
|total_calories|float|⛔️|Lap calories|
|avg_heart_rate|float|⛔️|Average HR|
|max_heart_rate|float|⛔️|Max HR|
|avg_power|float|⛔️|Average power|
|max_power|float|⛔️|Max power|
|avg_cadence|float|⛔️|Average cadence|
|max_cadence|float|⛔️|Max cadence|

### Lap record blobs

- Container: `lap-records`
- Blob name: `{workout_id}/lap-XXXX.json`
- Payload: array of records with minimal fields and `record_index`
- Record fields: `record_index`, `heart_rate`, `power`, `cadence`, `position_lat`, `position_long`

---

### Distance / elevation / energy (derived)

These fields are computed from canonical records and are **not stored** in the
Workouts table.

|Field|Type|Required|Description|
|---|---:|:---:|---|
|distance_m|float|⛔️|Total distance (meters)|
|elevation_gain_m|float|⛔️|Total ascent (meters)|
|elevation_loss_m|float|⛔️|Total descent (meters)|
|avg_speed_mps|float|⛔️|Average speed|
|max_speed_mps|float|⛔️|Max speed|
|calories_kcal|float|⛔️|Calories if present/estimated|

---

### Heart rate summary (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|hr_avg_bpm|float|⛔️|Average heart rate|
|hr_max_bpm|float|⛔️|Max heart rate|
|hr_resting_bpm|float|⛔️|Resting HR if available in file (rare)|
|hr_samples_count|int|⛔️|Number of HR samples used for metrics|
|hr_missing_pct|float|⛔️|Percent of expected samples missing (0–100)|

---

### Power summary (cycling, derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|pwr_avg_watts|float|⛔️|Average power|
|pwr_max_watts|float|⛔️|Max power|
|pwr_normalized_watts|float|⛔️|Normalized Power (if computed)|
|pwr_variability_index|float|⛔️|VI = NP / AvgP (if NP computed)|
|pwr_samples_count|int|⛔️|Number of power samples used|
|pwr_missing_pct|float|⛔️|Percent missing|

---

### Cadence summary (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|cad_avg_rpm|float|⛔️|Average cadence|
|cad_max_rpm|float|⛔️|Max cadence|
|cad_samples_count|int|⛔️|Cadence samples count|

---

### Training load / intensity (derived, optional but useful)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|trimp|float|⛔️|TRIMP if you choose to compute it|
|tss|float|⛔️|Training Stress Score (requires FTP + NP)|
|intensity_factor|float|⛔️|IF = NP / FTP|
|workout_rpe|int|⛔️|Optional manual RPE if you add later|

---

## Zone Definitions (derived per-workout for interpretability)

### HR zone definition fields

Store enough to interpret time-in-zone historically even if settings change later.

|Field|Type|Required|Description|
|---|---:|:---:|---|
|hr_zone_model|string|✅|e.g., `garmin_5`, `custom_5`, `coggan_hr_5`|
|hr_zone_basis|string|✅|`HRmax`, `LTHR`, or `HRR`|
|hr_zone_reference_bpm|float|⛔️|HRmax or LTHR value used (if known)|
|hr_z1_low_bpm|float|⛔️|Lower bound for Z1 (inclusive)|
|hr_z1_high_bpm|float|⛔️|Upper bound for Z1 (inclusive)|
|hr_z2_low_bpm|float|⛔️|...|
|hr_z2_high_bpm|float|⛔️|...|
|hr_z3_low_bpm|float|⛔️|...|
|hr_z3_high_bpm|float|⛔️|...|
|hr_z4_low_bpm|float|⛔️|...|
|hr_z4_high_bpm|float|⛔️|...|
|hr_z5_low_bpm|float|⛔️|...|
|hr_z5_high_bpm|float|⛔️|...|

> If you’re strict about 5 HR zones, keep it fixed. If you may change zone count later, store JSON instead. For Power BI friendliness, fixed columns win.

### Power zone definition fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|pwr_zone_model|string|✅|e.g., `coggan_7`|
|ftp_watts|float|✅|FTP used to classify this workout|
|pwr_z1_low_w|float|⛔️|Lower bound Z1 (inclusive)|
|pwr_z1_high_w|float|⛔️|Upper bound Z1|
|pwr_z2_low_w|float|⛔️|...|
|pwr_z2_high_w|float|⛔️|...|
|pwr_z3_low_w|float|⛔️|...|
|pwr_z3_high_w|float|⛔️|...|
|pwr_z4_low_w|float|⛔️|...|
|pwr_z4_high_w|float|⛔️|...|
|pwr_z5_low_w|float|⛔️|...|
|pwr_z5_high_w|float|⛔️|...|
|pwr_z6_low_w|float|⛔️|...|
|pwr_z6_high_w|float|⛔️|...|
|pwr_z7_low_w|float|⛔️|...|
|pwr_z7_high_w|float|⛔️|...|

---

## Time-in-zone metrics (the important part)

### HR time-in-zone fields (seconds)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|hr_z1_sec|int|✅|Seconds in HR Zone 1|
|hr_z2_sec|int|✅|Seconds in HR Zone 2|
|hr_z3_sec|int|✅|Seconds in HR Zone 3|
|hr_z4_sec|int|✅|Seconds in HR Zone 4|
|hr_z5_sec|int|✅|Seconds in HR Zone 5|
|hr_zone_total_sec|int|✅|Sum of HR zone seconds (sanity check)|

### Power time-in-zone fields (seconds)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|pwr_z1_sec|int|✅|Seconds in Power Zone 1|
|pwr_z2_sec|int|✅|Seconds in Power Zone 2|
|pwr_z3_sec|int|✅|Seconds in Power Zone 3|
|pwr_z4_sec|int|✅|Seconds in Power Zone 4|
|pwr_z5_sec|int|✅|Seconds in Power Zone 5|
|pwr_z6_sec|int|✅|Seconds in Power Zone 6|
|pwr_z7_sec|int|✅|Seconds in Power Zone 7|
|pwr_zone_total_sec|int|✅|Sum of power zone seconds|

### Convenience “hot fields” (seconds only)

All stored metrics use seconds to avoid mixing units. If minutes are needed,
derive them at read time.

|Field|Type|Required|Description|
|---|---:|:---:|---|
|low_aerobic_sec|float|✅|Seconds in low aerobic (pwr_z1+pwr_z2)|
|intensity_sec|float|✅|Seconds in intensity (pwr_z4+pwr_z5+pwr_z6+pwr_z7)|

> Define intensity/low-aerobic once and keep it consistent.

---

## Aerobic efficiency / drift / decoupling (recommended)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|decoupling_pct|float|⛔️|% change in efficiency between first/second halves (cycling: HR vs power). Often computed from Pw:HR ratio drift|
|hr_drift_bpm|float|⛔️|Avg HR second half minus first half|
|ef_first_half|float|⛔️|Efficiency factor first half (e.g., AvgP / AvgHR)|
|ef_second_half|float|⛔️|Efficiency factor second half|
|ef_overall|float|⛔️|Overall EF (AvgP / AvgHR)|

> These enable the “Z2 quality” conversation without re-reading FIT.

---

## Notes / flags (optional but valuable)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|flags|string|⛔️|Comma-separated machine flags, e.g. `missing_hr,indoor,short_warmup`|
|notes|string|⛔️|Short user note if you capture later|
|updated_at_utc|datetime (ISO string)|⛔️|Update timestamp if reprocessed|

---

## 2) WeeklyRollups Table (optional but recommended)

Precomputing rollups makes API calls fast and avoids scanning many partitions for trend charts.

### WeeklyRollups Keys

- `PartitionKey`: `athlete_id#YYYY` (e.g., `rob#2026`)
- `RowKey`: `YYYY-WW` (ISO week, e.g., `2026-02`)

### Fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|week_start_utc|datetime (ISO string)|✅|Start of week (UTC)|
|week_end_utc|datetime (ISO string)|✅|End of week (UTC)|
|workouts_count|int|✅|Count of workouts|
|total_duration_min|float|✅|Total duration minutes|
|total_distance_km|float|⛔️|Total distance|
|total_elev_m|float|⛔️|Total elevation gain|
|total_hr_z2_min|float|✅|Sum HR Z2 minutes|
|total_pwr_z2_min|float|✅|Sum power Z2 minutes|
|total_low_aerobic_min|float|✅|Sum low aerobic minutes|
|total_intensity_min|float|✅|Sum intensity minutes|
|avg_decoupling_pct|float|⛔️|Average decoupling for eligible Z2 workouts|
|hard_days_count|int|⛔️|Count of workouts with intensity >= threshold|
|long_rides_count|int|⛔️|Count of long rides (define threshold)|
|last_updated_at_utc|datetime (ISO string)|✅|Update timestamp|

---

## 3) IngestionState Table (recommended)

Tracks what was ingested, avoids duplicates, and preserves errors for troubleshooting.

### IngestionState Keys

- `PartitionKey`: `athlete_id`
- `RowKey`: `source_item_id` OR `file_sha256` OR `workout_id`

### IngestionState Fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|status|string|✅|`ingested`, `failed`, `skipped`|
|first_seen_at_utc|datetime|✅|First time file observed|
|last_attempt_at_utc|datetime|✅|Last ingestion attempt|
|error_message|string|⛔️|Last error message (truncated)|
|workout_id|string|⛔️|Link to Workouts entity|
|retry_count|int|✅|Retry count|
|source_file_name|string|⛔️|Original source filename (e.g., `2026-01-07-...fit`)|
|source_drive_id|string|⛔️|Source drive ID (if available)|
|source_etag|string|⛔️|Last seen OneDrive etag for the file|
|source_ctag|string|⛔️|Last seen OneDrive ctag for the file|
|source_quickxor_hash|string|⛔️|Last seen OneDrive quickXor hash for the file|
|source_modified_at_utc|datetime|⛔️|Last modified timestamp from OneDrive|
|file_sha256|string|⛔️|Last seen file hash for the file|
|ingest_version|string|✅|Version string of ingestion code (e.g., `v2.0.0`)|
|ingested_at_utc|datetime (ISO string)|⛔️|Timestamp when status becomes `ingested`|

---

## API Contract Alignment (for Custom GPT Actions later)

### Recommended endpoints (v1)

1. `GET /api/workouts?since=YYYY-MM-DD&limit=N` - returns list of Workouts summary fields (no time-series)
2. `GET /api/workouts/{workout_id}` - returns full Workouts entity
3. `GET /api/rollups/weekly?weeks=12` - returns WeeklyRollups list
4. `GET /api/planning/context?days=45` - returns recent workouts, weekly rollups, "last hard day", "last long day", Z2 volume, intensity volume, and any flags (missing HR, etc.)

Auth for Azure Functions:

- `?code=<function_key>` query parameter

---

## Field Units & Conventions

- Duration: seconds (`*_sec`) at storage; include derived minutes (`*_min`) for convenience
- Distance: meters (`distance_m`)
- Elevation: meters (`elevation_gain_m`)
- Power: watts
- HR: bpm
- Times in zones: seconds
- Datetimes: ISO 8601 UTC offsets (e.g., `2026-01-07T23:15:00+00:00`)

---

## Notes on Fit Parsing & Zone Computation

- Time-in-zone should be computed from per-sample records using stored zone boundaries.
- Store FTP used for the workout (power zones) to keep historical interpretability.
- If HR or power samples are missing, set `*_samples_count` and `*_missing_pct` accordingly.
- Only compute decoupling/EF when there’s sufficient continuous data (define minimum duration, e.g., 30 minutes).

---
