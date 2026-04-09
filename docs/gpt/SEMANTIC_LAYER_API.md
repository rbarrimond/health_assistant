# Semantic Access Layer API (GPT)

Version: 7.2.1

The Semantic Access Layer is the **read + agent-memory write API** for ChatGPT Actions. It exposes meaningful, human-centric questions about training data rather than raw table access.

> **Normative contract authority:** Endpoint paths, parameters, request/response schemas, and auth requirements are defined in [`openapi.yaml`](../../api_docs/openapi.yaml).
>
> - Admin/operations endpoints: [`../devops/OPERATIONS_API.md`](../devops/OPERATIONS_API.md)
> - Storage and ingestion architecture: [`INGESTION_SCHEMA.md`](../devops/data_architecture/INGESTION_SCHEMA.md)
> - Agent-memory architecture and storage semantics: [`AGENT_MEMORY.md`](./AGENT_MEMORY.md)

**Phase 1 Note:** This system is currently deployed for single-athlete use. Most endpoints default `athlete_id` to `"rob"` when not provided. Multi-athlete architecture exists, but strict enforcement is deferred to Phase 2.

---

## Quick Reference

### 🎯 Core Concept

The semantic layer answers **meaningful questions** about training, not raw database queries.

### 🔑 Most Important Endpoint

```http
GET /api/planning/context?athlete_id=rob&days=45
```

**Question it answers:** *"Given what I've actually done, what does tomorrow look like?"*

### 📋 GPT-Facing Endpoints

| Endpoint | Purpose |
| -------- | ------- |
| `/api/health` | Health check |
| `/api/agent/context` | Agent memory context |
| `/api/agent/preferences` | Preference CRUD (list/create/update-by-id) |
| `/api/agent/observations` | Observation CRUD (list/create/update-status) |
| `/api/planning/context` | Planning decisions |
| `/api/workouts` | Workout listing |
| `/api/workouts/{workout_id}` | Workout detail (includes `metrics.session` metadata passthrough for direct inspection, without redundant raw `activity_metadata`) |
| `/api/workouts/{workout_id}/laps/{lap_index}` | Single-lap detail |
| `/api/rollups/weekly` | Weekly summaries |
| `/api/analysis/zones` | Zone distribution |
| `/api/analysis/efficiency` | Efficiency trends |
| `/api/physiometrics/current` | Current physiometrics |
| `/api/physiometrics/history` | Physiometric trends |
| `/api/training-state/current` | Current training state |
| `/api/training-state/history` | Training-state trends |

> For authoritative path and parameter definitions, see [`openapi.yaml`](../../api_docs/openapi.yaml).

**Operational usage and call ordering:** [`GPT_ACTIONS_GUIDE.md`](./GPT_ACTIONS_GUIDE.md).

---

## Scope Protections

- `athlete_id` scoping (Phase 1 default behavior: `rob`)
- Scope limits are enforced as parameter `maximum` constraints in [`openapi.yaml`](../../api_docs/openapi.yaml).
- Summary-first response philosophy (time series requested explicitly)

---

## Semantic Rules (Non-OpenAPI)

These are behavioral semantics and interpretation constraints, not transport contracts.

### Zone Time Units

- Canonical storage uses **seconds** (`hr_z2_sec`, `pwr_z2_sec`, `intensity_sec`)
- Summary views convert to **minutes** (`cumulative_z2_minutes`, `cumulative_intensity_minutes`)
- Detection thresholds:
  - `last_hard_day` > 5 minutes intensity
  - `last_long_day` > 60 minutes Z2

### Training-State Resolution

- `GET /api/training-state/current` and `GET /api/training-state/history` compute state on demand.
- Workload metrics (`cts_rolling_7d`, `cts_rolling_28d`, `ats_rolling`, `fatigue_index`) come from workouts.
- Physiometrics are resolved **as-of effective date** using source ownership rules (not latest-row wins).
- Composite `readiness_score` consumes HRV recovery input only when Intervals-derived data is present.
- `garmin_readiness_score`, `garmin_training_status`, `garmin_training_load`, `garmin_recovery_time_hours`, and Garmin load-focus percentages are Garmin-native passthroughs.

---

## Philosophy

This layer:

- **Shapes data for reasoning** — coherent payloads optimized for LLM planning
- **Constrains scope** — explicit bounds for performance and reliability
- **Encodes domain semantics** — training-language contracts, not raw-table exposure
- **Stays stable** — contract-driven integrations for GPT Actions

---

## Design Principles

- **Meaning over mechanics**: endpoints are organized around coaching decisions.
- **Bounded retrieval**: no unbounded scans through API-level defaults and maxima.
- **Stable contracts**: schema evolution should preserve GPT integration reliability.
- **Readability-first payloads**: compact structures favor deterministic assistant behavior.

---

## Implementation Notes

- **Date handling**: use ISO date/time inputs; assume UTC unless offset is explicit.
- **Error semantics**: invalid parameters return 4xx; unexpected failures return 5xx.
- **Projection strategy**: endpoint-level projection behavior is defined in [`openapi.yaml`](../../api_docs/openapi.yaml).
- **Agent memory usage**: preference/observation records are intended for persistent context grounding, not derived analytics.

For schema details and concrete payload examples, use [`openapi.yaml`](../../api_docs/openapi.yaml).
