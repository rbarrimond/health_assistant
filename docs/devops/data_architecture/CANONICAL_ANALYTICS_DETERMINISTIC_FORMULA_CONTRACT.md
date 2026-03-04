# Canonical Analytics Surface
<!-- markdownlint-disable MD025 -->

## Deterministic Formula Contract (Appendix)

This document defines the deterministic implementation formulas for
envelope, variability, and durability metrics.

All metrics must be reproducible from canonical.parquet.

------------------------------------------------------------------------

## Assumptions

- `P(t)` = power_watts series\
- `HR(t)` = heart_rate_bpm series\
- Uniform sampling (Δt = 1s unless otherwise specified)\
- `FTP` = ftp_watts

------------------------------------------------------------------------

## Normalized Power (Coggan Definition)

``` python
p30 = rolling_mean(power_watts, window=30)
normalized_power = (mean(p30 ** 4)) ** 0.25
```

------------------------------------------------------------------------

## Variability Index

``` python
variability_index = normalized_power / avg_power
```

------------------------------------------------------------------------

## Intensity Factor

``` python
intensity_factor = normalized_power / ftp_watts
```

------------------------------------------------------------------------

## Training Stress Score

``` python
duration_hours = duration_sec / 3600
tss = duration_hours * (intensity_factor ** 2) * 100
```

------------------------------------------------------------------------

## Peak Power Anchors

``` python
peak_w_watts = rolling_mean(power_watts, window=w_seconds).max()
```

------------------------------------------------------------------------

# Envelope Scores

## Sprint Envelope

``` python
sprint_raw = 0.6 * peak_5s_watts + 0.4 * peak_30s_watts
sprint_envelope_score = sprint_raw / ftp_watts
```

## VO2 Envelope

``` python
vo2_raw = mean([peak_3min_watts, peak_5min_watts, peak_8min_watts])
vo2_envelope_score = vo2_raw / ftp_watts
```

## Threshold Envelope

``` python
threshold_raw = mean([peak_20min_watts, peak_60min_watts])
threshold_envelope_score = threshold_raw / ftp_watts
```

------------------------------------------------------------------------

# Variability Metrics

## Coefficient of Variation (Power)

``` python
cv_power = std(power_watts) / mean(power_watts)
```

## Coefficient of Variation (Heart Rate)

``` python
cv_hr = std(heart_rate_bpm) / mean(heart_rate_bpm)
```

## Surge Detection

``` python
surge_threshold = 1.2 * ftp_watts

mask = power_watts > surge_threshold

surge_count = count_segments(mask, min_duration_sec=3)

surge_density_per_hr = surge_count / (duration_sec / 3600)
```

## Pacing Evenness Score

``` python
pacing_evenness_score = 1 / variability_index
```

------------------------------------------------------------------------

# Aerobic Efficiency & Durability

## Efficiency Factor

``` python
efficiency_factor_avg = normalized_power / hr_avg_bpm
```

## Cardiac Decoupling

**Sign semantics:** Positive values indicate **efficiency decline over time** (aerobic fatigue), negative values indicate **efficiency improvement over time** (warming up or improved aerobic economy).

``` python
EF1 = NP_first_half / HR_first_half
EF2 = NP_second_half / HR_second_half

# Positive = fatigue/aerobic stress (EF1 > EF2), Negative = improvement (EF1 < EF2)
decoupling_pct = ((EF1 / EF2) - 1) * 100
```

Edge cases: `decoupling_pct` is `null`/omitted if `EF1 ≤ 0` or `EF2 ≤ 0`.

## Durability Slope

``` python
durability_slope = linear_regression_slope(elapsed_sec, power_watts)
```

## Fatigue Rate Power

``` python
P1 = mean(power_first_quartile)
P4 = mean(power_last_quartile)

fatigue_rate_power = (P4 - P1) / duration_sec
```

## HR--Power Lag

``` python
lag_sec = argmax_tau(correlation(power_t, shift(hr_t, tau)))
```

Search τ in range \[-60, +60\] seconds.
