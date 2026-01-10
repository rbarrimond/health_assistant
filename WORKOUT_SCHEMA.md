# Workout Metrics Schema (v1) — Azure Table Storage

This schema is designed to support:

- ad hoc queries (last 45 days, last 12 weeks, etc.)
- trend analysis (Z2 volume, intensity balance, drift/decoupling trends)
- workout planning context payloads
- clean Power BI usage (columnar fields, minimal JSON)

It assumes:

- **OneDrive** holds the raw `.fit` files (`/Apps/HealthFit/*.fit`)
- **Python ingestion** parses FIT and writes **deterministic metrics**
- **Azure Table Storage** stores the metric entities

---

## Tables

1. `Workouts` — **one entity per workout** (primary fact table)
2. `WeeklyRollups` — **one entity per week** (optional but recommended)
3. `IngestionState` — **idempotency + operational tracking** (recommended)

---

## 1) Workouts Table

### Keying strategy (recommended)

- `PartitionKey`: `athlete_id#YYYY-MM` (e.g., `rob#2026-01`)
- `RowKey`: `YYYYMMDDTHHMMSSZ#workout_id` (e.g., `20260107T231500Z#b6d2c0a1e9b4`)

Why:

- month partitions keep queries bounded and cheap
- RowKey is sortable by time within partition
- stable workout_id supports direct lookup

### Core identity fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|PartitionKey|string|✅|`athlete_id#YYYY-MM`|
|RowKey|string|✅|`start_time_utc_compact#workout_id`|
|workout_id|string|✅|Stable unique id (see **workout_id generation**)|
|athlete_id|string|✅|Short stable identifier for the athlete (e.g., `rob`)|
|source_system|string|✅|`HealthFit` (or `Garmin`, `Strava`, etc. if expanded later)|
|source_file_name|string|✅|File name from OneDrive (e.g., `2026-01-07-...fit`)|
|source_file_path|string|✅|OneDrive path (e.g., `/Apps/HealthFit/...`)|
|source_drive_id|string|⛔️|OneDrive `driveId` (recommended if using Graph)|
|source_item_id|string|⛔️|OneDrive `itemId` (recommended if using Graph)|
|source_etag|string|⛔️|OneDrive ETag/version marker|
|file_size_bytes|int|⛔️|Size of FIT file|
|file_sha256|string|⛔️|Optional integrity hash for idempotency + validation|

#### workout_id generation (deterministic)

Preferred order:

1. `source_item_id` (if using Graph): `sha1(source_item_id)`
2. `sha1(file_sha256)`
3. `sha1(source_file_path + source_file_name + start_time_utc)`

> Goal: stable across reprocessing; changes only if the underlying file truly changes.

---

### Temporal & classification fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|start_time_utc|datetime (ISO string)|✅|Workout start time UTC, e.g. `2026-01-07T23:15:00Z`|
|end_time_utc|datetime (ISO string)|⛔️|Derived end time UTC|
|timezone|string|⛔️|Source timezone if available (`America/New_York`)|
|duration_sec|int|✅|Total elapsed duration (seconds)|
|moving_time_sec|int|⛔️|Moving time if derivable (cycling often equals duration)|
|sport|string|✅|`cycling`, `running`, `strength_training`, etc.|
|sub_sport|string|⛔️|`indoor_cycling`, `gravel`, etc. if available|
|workout_name|string|⛔️|Workout title (HealthFit/Strava/Garmin name)|
|device_name|string|⛔️|Device model if present|
|is_indoor|bool|⛔️|Indoor flag if derivable|
|has_gps|bool|⛔️|Whether GPS track exists|

---

### Distance / elevation / energy

|Field|Type|Required|Description|
|---|---:|:---:|---|
|distance_m|float|⛔️|Total distance (meters)|
|elevation_gain_m|float|⛔️|Total ascent (meters)|
|elevation_loss_m|float|⛔️|Total descent (meters)|
|avg_speed_mps|float|⛔️|Average speed|
|max_speed_mps|float|⛔️|Max speed|
|calories_kcal|float|⛔️|Calories if present/estimated|

---

### Heart rate summary

|Field|Type|Required|Description|
|---|---:|:---:|---|
|hr_avg_bpm|float|⛔️|Average heart rate|
|hr_max_bpm|float|⛔️|Max heart rate|
|hr_resting_bpm|float|⛔️|Resting HR if available in file (rare)|
|hr_samples_count|int|⛔️|Number of HR samples used for metrics|
|hr_missing_pct|float|⛔️|Percent of expected samples missing (0–100)|

---

### Power summary (cycling)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|pwr_avg_watts|float|⛔️|Average power|
|pwr_max_watts|float|⛔️|Max power|
|pwr_normalized_watts|float|⛔️|Normalized Power (if computed)|
|pwr_variability_index|float|⛔️|VI = NP / AvgP (if NP computed)|
|pwr_samples_count|int|⛔️|Number of power samples used|
|pwr_missing_pct|float|⛔️|Percent missing|

---

### Cadence summary

|Field|Type|Required|Description|
|---|---:|:---:|---|
|cad_avg_rpm|float|⛔️|Average cadence|
|cad_max_rpm|float|⛔️|Max cadence|
|cad_samples_count|int|⛔️|Cadence samples count|

---

### Training load / intensity (optional but useful)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|trimp|float|⛔️|TRIMP if you choose to compute it|
|tss|float|⛔️|Training Stress Score (requires FTP + NP)|
|intensity_factor|float|⛔️|IF = NP / FTP|
|workout_rpe|int|⛔️|Optional manual RPE if you add later|

---

## Zone Definitions (stored per-workout for interpretability)

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

### Convenience “hot fields” (recommended)

These are derived from the zone fields but are worth storing for fast queries.

|Field|Type|Required|Description|
|---|---:|:---:|---|
|hr_z2_min|float|✅|`hr_z2_sec / 60`|
|pwr_z2_min|float|✅|`pwr_z2_sec / 60`|
|intensity_min|float|✅|e.g., `pwr_z4+z5+z6+z7` minutes (define explicitly)|
|low_aerobic_min|float|✅|e.g., `pwr_z1+z2` minutes (define explicitly)|

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
|ingest_version|string|✅|Version string of ingestion code (e.g., `v1.0.3`)|
|ingested_at_utc|datetime (ISO string)|✅|Ingestion timestamp|
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
|last_error|string|⛔️|Last error message (truncated)|
|workout_id|string|⛔️|Link to Workouts entity|
|retry_count|int|✅|Retry count|

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
- Datetimes: ISO 8601 UTC strings (e.g., `2026-01-07T23:15:00Z`)

---

## Notes on Fit Parsing & Zone Computation

- Time-in-zone should be computed from per-sample records using stored zone boundaries.
- Store FTP used for the workout (power zones) to keep historical interpretability.
- If HR or power samples are missing, set `*_samples_count` and `*_missing_pct` accordingly.
- Only compute decoupling/EF when there’s sufficient continuous data (define minimum duration, e.g., 30 minutes).

---
