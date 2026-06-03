# Semantic Access Layer API (GPT)

Version: 8.1.0

The Semantic Access Layer is the **read + agent-memory write API** for ChatGPT Actions. It exposes meaningful, human-centric questions about training data rather than raw table access.

> **Document role:** Semantic interpretation and cognitive direction.
>
> **Contract authority:** Endpoint paths, parameters, request/response schemas, auth requirements, and canonical examples are defined in [`openapi.yaml`](../../api_docs/openapi.yaml).
>
> - Admin/operations endpoints: [`../devops/OPERATIONS_API.md`](../devops/OPERATIONS_API.md)
> - Storage and ingestion architecture: [`INGESTION_SCHEMA.md`](../devops/data_architecture/INGESTION_SCHEMA.md)
> - Agent-memory architecture and storage semantics: [`AGENT_MEMORY.md`](./AGENT_MEMORY.md)
>
- GPT call ordering: [`GPT_ACTIONS_GUIDE.md`](./GPT_ACTIONS_GUIDE.md)

**Phase 1 Note:** This system is currently deployed for single-athlete use. Most endpoints default `athlete_id` to `"rob"` when not provided. Multi-athlete architecture exists, but strict enforcement is deferred to Phase 2.

---

## Quick Reference

### 🎯 Core Concept

The semantic layer answers **meaningful questions** about training, not raw database queries.

### 🔑 Most Important Question

"Given what I've actually done, what does tomorrow look like?"

Use planning context first for short-horizon decisions, then pull narrower endpoint slices only when deeper detail is required.

### Retrieval Strategy (Cognitive)

1. Load **agent context** and **planning context** before first user-facing guidance.
2. Prefer **summary views first** (planning, weekly rollups, zones, efficiency).
3. Use **detail views on demand** (workout detail and lap detail) only when summary payloads are insufficient.
4. Use **memory writes intentionally** (preferences/observations) for durable user constraints and persistent coaching facts.
5. Avoid endpoint over-fetching when a narrower question can be answered from already loaded context.

For endpoint-level contract details and examples, see [`openapi.yaml`](../../api_docs/openapi.yaml).

---

## Scope Protections

- `athlete_id` scoping (Phase 1 default behavior: `rob`)
- Scope limits are enforced as parameter `maximum` constraints in [`openapi.yaml`](../../api_docs/openapi.yaml).
- Summary-first response philosophy (time series requested explicitly)
- Prefer bounded windows over broad historical sweeps unless the user asks for longitudinal analysis.

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

- Training-state endpoints compute state on demand.
- Workload metrics (`cts_rolling_7d`, `cts_rolling_28d`, `ats_rolling`, `fatigue_index`) come from workouts.
- Physiometrics are resolved **as-of effective date** using source ownership rules (not latest-row wins).
- Composite `readiness_score` consumes HRV recovery input only when Intervals-derived data is present.
- `garmin_readiness_score`, `garmin_training_status`, `garmin_training_load`, `garmin_recovery_time_hours`, and Garmin load-focus percentages are Garmin-native passthroughs.

### Interpretation Guardrails

- Do not interpret one low-readiness snapshot as a trend without checking recent history.
- Do not treat absent data as negative signal; represent missingness explicitly.
- Prefer explicit uncertainty statements when signals disagree (e.g., load suggests fatigue while subjective markers are absent).

---

## Philosophy

This layer:

- **Shapes data for reasoning** — coherent payloads optimized for LLM planning
- **Constrains scope** — explicit bounds for performance and reliability
- **Encodes domain semantics** — training-language contracts, not raw-table exposure
- **Stays stable** — contract-driven integrations for GPT Actions

---

## Design Principles

- **Meaning over mechanics**: APIs are consumed as coaching decision surfaces, not raw records.
- **Bounded retrieval**: no unbounded scans through API-level defaults and maxima.
- **Stable contracts**: schema evolution should preserve GPT integration reliability.
- **Readability-first payloads**: compact structures favor deterministic assistant behavior.

---

## Implementation Notes

- **Date handling**: use ISO date/time inputs; assume UTC unless offset is explicit.
- **Error semantics**: invalid parameters return 4xx; unexpected failures return 5xx.
- **Projection strategy**: endpoint-level projection behavior is defined in [`openapi.yaml`](../../api_docs/openapi.yaml).
- **Agent memory usage**: preference/observation records are intended for persistent context grounding, not derived analytics.

## Out of Scope For This Document

- endpoint path inventories
- method/parameter contract details
- request/response payload examples

Those remain canonical in [`openapi.yaml`](../../api_docs/openapi.yaml).

For schema details and concrete payload examples, use [`openapi.yaml`](../../api_docs/openapi.yaml).
