# Workout Schema - Semantic API (Logical)

Version: 11.1.0

This document defines the **logical workout schema** exposed by the semantic API.
It avoids storage details (tables, blobs, partitions) and focuses on fields used
for reasoning and planning. Operational storage is documented in
[INGESTION_SCHEMA.md](../devops/data_architecture/INGESTION_SCHEMA.md).

Derived analytics are computed from canonical records at read time and surfaced
as calculated properties here.

---

## Workout Summary (List)

Returned by `GET /api/workouts` and embedded in planning contexts.

### Core identity & classification

|Field|Type|Required|Description|
|---|---:|:---:|---|
|workout_id|string|✅|Stable unique workout id (source-agnostic client identity)|
|athlete_id|string|✅|Athlete identifier|
|sport|string|✅|Generic sport (`cycling`, `running`, `strength_training`, etc.)|
|sub_sport|string|⛔️|FIT sub-sport (`indoor_cycling`, `gravel`, etc.)|
|apple_workout_type|string|⛔️|Apple Watch workout type if detected|
|workout_name|string|⛔️|User-facing workout name|
|is_indoor|bool|⛔️|Indoor flag if derivable|
|source_system|string|⛔️|Source system name (e.g., `HealthFit`)|

### Temporal fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|start_time_utc|datetime (ISO string)|✅|Workout start UTC|
|local_tz_offset|string|⛔️|Local wall-clock UTC offset (for example `UTC-05:00`)|
|timezone|string|⛔️|Compatibility alias of `local_tz_offset`|
|duration_sec|int|✅|Elapsed duration (seconds)|
|moving_time_sec|int|⛔️|Moving time if derivable|

### Device metadata (optional)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|device_name|string|⛔️|Device label (e.g., `garmin edge_1050`, `apple_watch_ultra`)|

---

## Workout Detail (Single)

Returned by `GET /api/workouts/{workout_id}`.
Extends the summary with derived metrics and optional lap summaries.

### Distance & elevation (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|distance_m|float|⛔️|Total distance meters|
|elevation_gain_m|float|⛔️|Total elevation gain|
|elevation_loss_m|float|⛔️|Total elevation loss|
|avg_speed_mps|float|⛔️|Average speed|
|max_speed_mps|float|⛔️|Max speed|
|calories_kcal|float|⛔️|Calories if present/estimated|

### Heart rate summary (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|hr_avg_bpm|float|⛔️|Average heart rate|
|hr_max_bpm|float|⛔️|Max heart rate|
|hr_min_bpm|float|⛔️|Min heart rate|
|hr_resting_bpm|float|⛔️|Resting HR if available (rare)|
|hr_samples_count|int|⛔️|Number of HR samples used|
|hr_missing_pct|float|⛔️|Percent of expected samples missing (0–100)|

### Power summary (cycling, derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|pwr_avg_watts|float|⛔️|Average power|
|pwr_max_watts|float|⛔️|Max power|
|pwr_normalized_watts|float|⛔️|Normalized Power (if computed)|
|pwr_variability_index|float|⛔️|VI = NP / AvgP (if NP computed)|
|pwr_samples_count|int|⛔️|Number of power samples used|
|pwr_missing_pct|float|⛔️|Percent missing|

### Cadence summary (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|cad_avg_rpm|float|⛔️|Average cadence|
|cad_max_rpm|float|⛔️|Max cadence|
|cad_samples_count|int|⛔️|Cadence samples count|

### Training load / intensity (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|trimp|float|⛔️|TRIMP if computed|
|tss|float|⛔️|Training Stress Score (requires FTP + NP)|
|intensity_factor|float|⛔️|IF = NP / FTP|
|workout_rpe|int|⛔️|Optional manual RPE if you add later|

### Power-duration anchors (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|peak_5s_watts|float|⛔️|Best 5s rolling average power|
|peak_30s_watts|float|⛔️|Best 30s rolling average power|
|peak_3min_watts|float|⛔️|Best 3min rolling average power|
|peak_5min_watts|float|⛔️|Best 5min rolling average power|
|peak_8min_watts|float|⛔️|Best 8min rolling average power|
|peak_20min_watts|float|⛔️|Best 20min rolling average power|
|peak_60min_watts|float|⛔️|Best 60min rolling average power|

### Envelope scores (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|sprint_envelope_score|float|⛔️|Composite sprint capability score|
|vo2_envelope_score|float|⛔️|Composite VO2 capability score|
|threshold_envelope_score|float|⛔️|Composite threshold endurance score|

### Variability & pacing (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|cv_power|float|⛔️|Coefficient of variation for power|
|cv_hr|float|⛔️|Coefficient of variation for heart rate|
|surge_count|int|⛔️|Number of surge events detected|
|surge_density_per_hr|float|⛔️|Surges per hour|
|pacing_evenness_score|float|⛔️|Pacing smoothness score|

### Durability & efficiency (derived)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|efficiency_factor_avg|float|⛔️|Normalized power / HR efficiency ratio|
|decoupling_pct|float|⛔️|% divergence between HR and power halves|
|durability_slope|float|⛔️|Performance decline slope over time|
|fatigue_rate_power|float|⛔️|Power fatigue rate across session|
|hr_power_lag_sec|int|⛔️|Lag between power and HR response|
|ef_first_half|float|⛔️|Efficiency factor for first half|
|ef_second_half|float|⛔️|Efficiency factor for second half|
|ef_overall|float|⛔️|Overall efficiency factor|
|hr_drift_bpm|float|⛔️|HR drift (bpm) between halves|

### Structured artifacts (derived, stored as blobs)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|intervals_json|array|⛔️|Structured interval detection artifact|
|climbs_json|array|⛔️|Structured climb detection artifact|
|power_curve_json|array|⛔️|Log-spaced power curve artifact|

---

## Zone Definitions (derived per-workout)

### HR zone definition fields

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

## Time-in-zone metrics (seconds)

### HR time-in-zone fields

|Field|Type|Required|Description|
|---|---:|:---:|---|
|hr_z1_sec|int|✅|Seconds in HR Zone 1|
|hr_z2_sec|int|✅|Seconds in HR Zone 2|
|hr_z3_sec|int|✅|Seconds in HR Zone 3|
|hr_z4_sec|int|✅|Seconds in HR Zone 4|
|hr_z5_sec|int|✅|Seconds in HR Zone 5|
|hr_zone_total_sec|int|✅|Sum of HR zone seconds (sanity check)|

### Power time-in-zone fields

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

### Convenience "hot fields" (seconds)

|Field|Type|Required|Description|
|---|---:|:---:|---|
|low_aerobic_sec|float|✅|Seconds in low aerobic (pwr_z1+pwr_z2)|
|intensity_sec|float|✅|Seconds in intensity (pwr_z4+pwr_z5+pwr_z6+pwr_z7)|

---

## Aerobic efficiency / drift / decoupling

|Field|Type|Required|Description|
|---|---:|:---:|---|
|decoupling_pct|float|⛔️|% change in efficiency between first/second halves|
|hr_drift_bpm|float|⛔️|Avg HR second half minus first half|
|ef_first_half|float|⛔️|Efficiency factor first half (AvgP / AvgHR)|
|ef_second_half|float|⛔️|Efficiency factor second half|
|ef_overall|float|⛔️|Overall EF (AvgP / AvgHR)|

---

## Notes / flags

|Field|Type|Required|Description|
|---|---:|:---:|---|
|flags|string|⛔️|Comma-separated machine flags, e.g. `missing_hr,indoor`|
|notes|string|⛔️|Short user note if captured later|
|updated_at_utc|datetime (ISO string)|⛔️|Update timestamp if recalculated|

---

## Weekly Rollups (Logical)

Returned by `GET /api/rollups/weekly`.

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
|avg_decoupling_pct|float|⛔️|Average decoupling for eligible workouts|
|hard_days_count|int|⛔️|Count of workouts with intensity >= threshold|
|long_rides_count|int|⛔️|Count of long rides (define threshold)|
|last_updated_at_utc|datetime (ISO string)|✅|Update timestamp|

---

## Field Units & Conventions

- Duration: seconds (`*_sec`) and derived minutes (`*_min`) where shown.
- Distance: meters (`distance_m`) and kilometers (`*_km`) where shown.
- Elevation: meters (`*_m`).
- Power: watts.
- Heart rate: bpm.
- Time-in-zone: seconds.
- Timestamps: ISO 8601 with explicit UTC offset (no trailing `Z`).
