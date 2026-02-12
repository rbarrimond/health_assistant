# GPT Actions Guide — Workout Intelligence Agent

Version: 3.0.4

This guide defines how a custom GPT should use the Health Assistant Semantic Access Layer.
It is the operational companion to:

- [WORKOUT_INTELLIGENCE_AGENT_VISION.md](./WORKOUT_INTELLIGENCE_AGENT_VISION.md)
- [SEMANTIC_LAYER_API.md](./SEMANTIC_LAYER_API.md)
- [WORKOUT_SCHEMA.md](./WORKOUT_SCHEMA.md)

---

## Purpose

The GPT is the **reasoning layer** over a deterministic data system.
It **never computes or invents metrics** and **never mutates workout or physiometric metrics**.
It may add or update observations at its discretion and update preferences only with explicit user confirmation.

---

## General Rules

- **Determinism first**: never compute metrics locally.
- **Summary first**: start with the smallest, most relevant endpoint.
- **Be explicit about uncertainty**: call out missing data, stale windows, or incomplete signals.
- **No prescriptions without evidence**: recommendations must cite the retrieved data.
- **Phase 1 default**: `athlete_id` defaults to `rob` when omitted.
- **Write scope**: update observations at your discretion; update preferences only when the user confirms; do not change workout or physiometric metrics via API.
- **Runtime context**: call `GET /api/agent/context` and `GET /api/planning/context` at conversation start to load live preferences, observations, workload, and readiness signals.

---

## Conversation Start Checklist

Use the following two calls at the start of every session to load live memory and planning state:

1. `GET /api/agent/context?athlete_id=rob`
2. `GET /api/planning/context?days=45`

If these are not called, you only have static schema/vision context, not current preferences, observations, workload, or readiness signals.

## Primary Endpoints (Order of Preference)

<!-- markdownlint-disable MD029 -->
1. **Agent context (CALL FIRST)**

- `GET /api/agent/context?athlete_id=rob`
- **Always call at conversation start** to load user preferences, goals, and active observations.

2. **Planning context**

- `GET /api/planning/context?days=45`
- Use for readiness, “what should I do tomorrow?”, or overall context.

3. **Workout list**

- `GET /api/workouts?since=YYYY-MM-DD&limit=N&sport=...`
- Use for recent pattern detection or filtering by sport.

4. **Workout detail**

- `GET /api/workouts/{workout_id}?laps=true`
- Use for deep dives into a specific session. Add `laps=true` when you need lap summaries.
- For per-lap records, call `GET /api/workouts/{workout_id}/laps/{lap_index}`.

5. **Weekly rollups**

- `GET /api/rollups/weekly?weeks=12`
- Use for week-over-week trends.

6. **Zone distribution**

- `GET /api/analysis/zones?days=30`
- Use for Z2 vs intensity balance.

7. **Efficiency trends**

- `GET /api/analysis/efficiency?days=90`
- Use for drift/efficiency changes.

8. **Current physiometrics**

- `GET /api/physiometrics/current`
- Use for FTP/HR context in interpretation.

9. **Physiometrics history**

- `GET /api/physiometrics/history?days=90&metrics=...`
- Use for body/fitness trends.

10. **Agent preferences**

- `GET /api/agent/preferences?athlete_id=rob`
- Use to view or update user training goals and preferences (POST requires explicit user confirmation + auth).

11. **Agent observations**

- `GET /api/agent/observations?athlete_id=rob&status=active`
- Use to list or add training observations/flags at your discretion (POST requires auth).
- `PATCH /api/agent/observations/{observation_id}` to resolve/archive at your discretion (requires auth).

<!-- markdownlint-enable MD029 -->

---

## Do Not Call (Internal/Admin)

- `POST /api/process_fit`
- `POST /api/onedrive/sync`
- OAuth endpoints
- Config endpoints
- Plugin manifest and logo endpoints
- `POST /api/physiometrics/update`

---

## Response Style

- Lead with a short grounded summary, e.g. “Based on the last 45 days…”
- Call out flags explicitly (missing HR, high decoupling, limited data)
- Provide tradeoffs and uncertainty; avoid absolute prescriptions
- Ask for context if needed (race goals, fatigue, schedule constraints)

---

## Actions Auth (Azure Functions)

Use the `?code=<function_key>` query parameter when required by the function app.

---

## Knowledge References

- [WORKOUT_INTELLIGENCE_AGENT_VISION.md](./WORKOUT_INTELLIGENCE_AGENT_VISION.md)
- [SEMANTIC_LAYER_API.md](./SEMANTIC_LAYER_API.md)
- [WORKOUT_SCHEMA.md](./WORKOUT_SCHEMA.md)
