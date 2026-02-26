# RR Intervals --- Canonical State Specification

Version: 1.0.0

## Executive Summary

This document defines the required end state for how RR intervals are
represented and aligned within the CanonicalRecord substrate. RR
intervals must be stored as immutable tuples (`Tuple[float, ...]`)
grouped by 1 Hz record timestamps. Placement must honor FIT standard
semantics: when HRV messages include a timestamp field, that timestamp
is authoritative; when they do not, anchoring must be deterministically
derived from record timestamps. The resulting projection must preserve
order, count, and determinism while maintaining sub-second beat
resolution within a 1 Hz canonical time grid.

------------------------------------------------------------------------

## 1. CanonicalRecord Field Definition

`CanonicalRecord` must contain:

``` python
rr_intervals_sec: Tuple[float, ...]
```

### Field Requirements

- Type: `Tuple[float, ...]`
- Default: `()`
- Never `None`
- Never `list`
- Immutable
- Order-preserving
- Duplicate-preserving

------------------------------------------------------------------------

## 2. Time Semantics

CanonicalRecord timestamps define a 1 Hz canonical time grid.

For each record timestamp `T`, the record represents:

```plaintext
[T, T + 1 second)
```

`rr_intervals_sec` for a record at timestamp `T` must contain:

> All RR intervals whose reconstructed beat timestamps fall within that
> time window.

No RR interval may belong to more than one record.

No RR interval may fall outside all records.

------------------------------------------------------------------------

## 3. FIT Compliance

The projection must honor FIT standard behavior:

### If HRV message includes a timestamp field

- That timestamp is authoritative.
- RR placement must be derived from that timestamp.

### If HRV message does not include a timestamp field

- RR placement must be deterministically derived from record
    timestamps in stream order.
- The anchor must be the record immediately preceding the first HRV
    message.

The system must support both modes.

------------------------------------------------------------------------

## 4. Determinism

Given identical FIT input:

- The resulting `rr_intervals_sec` tuples must be identical.
- No randomness.
- No order instability.
- No dependency on message batching behavior.

------------------------------------------------------------------------

## 5. Preservation Invariants

The following must always hold:

1. **Count preservation**

```plaintext
Total RR intervals in CanonicalRecord == Total RR intervals in FIT
```

1. **Order preservation** Flattening all `rr_intervals_sec` tuples in
    timestamp order must reproduce the original RR stream order exactly.

2. **No duplication**

3. **No dropped intervals**

------------------------------------------------------------------------

## 6. Projection Model

CanonicalRecord is a 1 Hz physiological projection.

It must:

- Preserve sub-second beat resolution via grouping.
- Not interpolate.
- Not synthesize beats.
- Not smooth RR intervals.
- Not encode FIT batching artifacts.

------------------------------------------------------------------------

## 7. Alignment Requirement

When HRV lacks a timestamp field:

RR-derived instantaneous HR, when bucketed to 1 Hz, must align with
record-domain `heart_rate_bpm` within expected tolerance (\~1--2 bpm
MAE).

This confirms correct temporal anchoring.

------------------------------------------------------------------------

## 8. Conceptual Model

CanonicalRecord becomes:

```plaintext
1 Hz record timestamp + ordered tuple of sub-second RR intervals
```

It is a time-grid projection of irregular beat events.
