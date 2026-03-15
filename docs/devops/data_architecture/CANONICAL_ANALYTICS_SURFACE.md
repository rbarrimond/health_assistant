# Canonical Analytics Surface
<!-- markdownlint-disable MD024 -->

Version: 1.1.4

> This document defines the canonical analytics contract for workout computation.
> The surface is derived deterministically from canonical.parquet streams.
>
> - Raw telemetry schema
> - Session-level aggregates
> - Power-duration anchors
> - Higher-order durability and variability metrics
> - Structured JSON artifacts
> - On-demand projections (not persisted)
>
> All stored metrics must be recomputable from the canonical substrate.

All derived analytics (including zones and enhanced analytics) are computed at
read time by `CanonicalAnalyticsEngine` from canonical.parquet. Any computations
implemented outside that engine are deviations from this contract.

------------------------------------------------------------------------

## Section I. Canonical Substrate (Parquet)

The canonical substrate represents the raw, time-series workout telemetry.
Each row corresponds to a timestamped observation.
All higher-level analytics must be computable from this stream.
Units are explicit and normalized.

Core Telemetry

- `timestamp_utc` — Absolute UTC timestamp of the sample (required).
- `elapsed_sec` — Seconds since the start of the workout (required).
- `power_watts` — Instantaneous mechanical power output in watts (nullable).
- `heart_rate_bpm` — Heart rate in beats per minute (nullable).
- `cadence_rpm` — Pedaling cadence in revolutions per minute (nullable).
- `speed_mps` — Ground speed in meters per second (nullable).
- `distance_m` — Cumulative distance traveled in meters (nullable).
- `elevation_m` — Elevation above sea level in meters (nullable).

Extended Telemetry (Nullable):

- `temperature_c` — Ambient temperature in degrees Celsius.
- `respiration_rate_brpm` — Respiratory rate in breaths per minute.
- `lr_balance_pct` — Left leg power contribution percentage (0–100).
- `rr_interval_sec` — Beat-to-beat RR interval in seconds aligned to timestamp when available (sourced from HRV messages).

Notes:

- With the exception of `timestamp_utc` and `elapsed_sec`, all substrate fields are nullable.
- Different exercise modalities (cycling, strength, commute, indoor trainer, rowing, etc.) may omit telemetry dimensions such as heart rate, speed, elevation, or power.
- Absence of any field must not invalidate ingestion or downstream analytics.
- Derived metrics must be conditionally computed only when required substrate fields are present.
- All stored metrics must remain recomputable from this substrate.
- HRV messages from FIT files must be merged deterministically into `rr_interval_sec` during ingestion when present.

------------------------------------------------------------------------

## Section II. Base Session Metrics

These metrics are scalar aggregates derived from the canonical time series.
They represent the minimal session-level summary required for downstream analysis.
All values must be reproducible from canonical.parquet.

- `duration_sec` — Total elapsed workout duration in seconds.
- `moving_time_sec` — Time in seconds during which movement was detected.
- `distance_m` — Total session distance in meters.
- `elevation_gain_m` — Total accumulated elevation gain in meters.
- `elevation_loss_m` — Total accumulated elevation loss in meters.
- `avg_speed_mps` — Average speed across moving time in meters per second.
- `max_speed_mps` — Maximum observed speed in meters per second.
- `calories_kcal` — Estimated energy expenditure in kilocalories.
- `hr_avg_bpm` — Average heart rate across the session.
- `hr_max_bpm` — Maximum heart rate recorded.
- `hr_min_bpm` — Minimum heart rate recorded.
- `hr_zone_basis` — Method used to compute heart rate zones (e.g., LTHR or Max HR).
- `hr_zone_reference_bpm` — Reference BPM value used for zone computation.
- `hr_z1_sec` — Total seconds spent in heart rate Zone 1.
- `hr_z2_sec` — Total seconds spent in heart rate Zone 2.
- `hr_z3_sec` — Total seconds spent in heart rate Zone 3.
- `hr_z4_sec` — Total seconds spent in heart rate Zone 4.
- `hr_z5_sec` — Total seconds spent in heart rate Zone 5.
- `hr_zone_total_sec` — Total time in seconds across all heart rate zones.
- Per-workout HR zone minute fields are not part of the canonical contract; minute projections are derived on demand from `*_sec` fields.
- `pwr_avg_watts` — Average power output in watts.
- `pwr_max_watts` — Maximum instantaneous power in watts.
- `pwr_normalized_watts` — Normalized power accounting for variability.
- `pwr_variability_index` — Ratio of normalized power to average power.
- `ftp_watts` — Functional Threshold Power used for session computations.
- `intensity_factor` — Ratio of normalized power to FTP.
- `tss` — Training Stress Score calculated from intensity and duration.
- `cad_avg_rpm` — Average cadence in revolutions per minute.
- `cad_max_rpm` — Maximum cadence in revolutions per minute.

------------------------------------------------------------------------

## Section III. Power-Duration Anchors

Power-duration anchors represent best-effort mean maximal power values
over fixed durations. These are deterministic rolling-window computations
over the canonical power stream.

- `peak_5s_watts` — Highest 5-second rolling average power.
- `peak_30s_watts` — Highest 30-second rolling average power.
- `peak_3min_watts` — Highest 3-minute rolling average power.
- `peak_5min_watts` — Highest 5-minute rolling average power.
- `peak_8min_watts` — Highest 8-minute rolling average power.
- `peak_20min_watts` — Highest 20-minute rolling average power.
- `peak_60min_watts` — Highest 60-minute rolling average power.

------------------------------------------------------------------------

## Section IV. Envelope Scores

Envelope scores compress power-duration capability into interpretable indices.
These scores are derived from anchor values and normalized to internal scales.
They are not vendor metrics.

- `sprint_envelope_score` — Composite sprint capability score (1–30 seconds).
- `vo2_envelope_score` — Composite VO2 max power score (3–8 minutes).
- `threshold_envelope_score` — Composite threshold endurance score (15–45 minutes).

------------------------------------------------------------------------

## Section V. Variability & Stochasticity

Variability metrics describe pacing stability and stochastic effort patterns.
These are second-order statistics derived from the power and heart rate series.

- `cv_power` — Coefficient of variation of power output.
- `cv_hr` — Coefficient of variation of heart rate.
- `surge_count` — Number of high-intensity surge events detected.
- `surge_density_per_hr` — Surge count normalized per hour of activity.
- `pacing_evenness_score` — Composite pacing smoothness metric.

------------------------------------------------------------------------

## Section VI. Aerobic Efficiency & Durability

Durability metrics measure drift and fatigue response over time.
They quantify the relationship between heart rate and power under sustained load.

- `efficiency_factor_avg` — Average ratio of normalized power to heart rate.
- `decoupling_pct` — Percentage divergence between heart rate and power halves.
- `durability_slope` — Rate of performance decline across session duration.
- `fatigue_rate_power` — Decline rate in power output under sustained effort.
- `hr_power_lag_sec` — Time lag between power changes and heart rate response.

------------------------------------------------------------------------

## Section VII. Power Zones

Zone distributions are computed from power_watts using the FTP snapshot
active at the time of analysis. Zone definitions must be explicitly versioned.

- `pwr_z1_sec` — Seconds spent in Power Zone 1 (active recovery).
- `pwr_z2_sec` — Seconds spent in Power Zone 2 (low aerobic).
- `pwr_z3_sec` — Seconds spent in Power Zone 3 (tempo).
- `pwr_z4_sec` — Seconds spent in Power Zone 4 (threshold).
- `pwr_z5_sec` — Seconds spent in Power Zone 5 (VO2).
- `pwr_z6_sec` — Seconds spent in Power Zone 6 (anaerobic).
- `pwr_z7_sec` — Seconds spent in Power Zone 7 (neuromuscular).
- `low_aerobic_sec` — Aggregate seconds in aerobic base zones.
- `intensity_sec` — Aggregate seconds above threshold intensity.

------------------------------------------------------------------------

## Section VIII. Structured Artifacts (Blob JSON)

Structured artifacts are stored separately as JSON blobs. These enable
interval-level and climb-level analytics without duplicating scalar storage.

- `laps.json` — Pass-through representation of FIT lap messages. This preserves
  semantic meaning at the client layer.
  - FIT `workout` and `workout_step` messages represent structured workouts,
    but Zwift does not emit them; it encodes steps as laps and Strava
    interprets those laps as workout steps.
  - For this reason, interval semantics are derived from laps rather than
    computed server-side.
- `intervals.json` — Reserved for future use to carry `workout` and
  `workout_step` messages when present.
- `climbs.json` — Structured climb detection artifact.
  - `duration` — Climb duration in seconds.
  - `avg_grade` — Average grade percentage during climb.
  - `avg_power` — Average power during climb.
  - `efficiency_factor` — Efficiency factor during climb.
- `power_curve.json` — Optional log-spaced duration power mapping artifact.

------------------------------------------------------------------------

## Section IX. Derived On-Demand (Not Stored)

These projections are computed lazily at query time.
They are functions of the canonical substrate and must never be persisted.
This preserves recomputability and schema sovereignty.

- `rolling_ef(t)` — Time-varying rolling efficiency factor.
- `rolling_cv(t)` — Rolling coefficient of variation.
- `rolling_power(t)` — Rolling average power function.
- `grade(t)` — Derived road grade over time.
- `drift_envelope(t)` — Time-varying cardiac drift indicator.
- `surge_flags(t)` — Boolean surge detection over time.
