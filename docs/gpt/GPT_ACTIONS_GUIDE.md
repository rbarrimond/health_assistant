# GPT Actions Guide — Workout Intelligence Agent

Version: 4.2.0

> **Document role:** Operational procedure only. This file defines API call ordering and usage flow.
> Behavior, safety, and interpretation authority live in the **Custom GPT Control Layer Instructions**.
>
> **Contract authority:** Exact endpoint paths, methods, parameters, auth, and payload examples are normative in the **configured Custom GPT Actions schema**.

This guide defines how a custom GPT should use the Health Assistant Semantic Access Layer.
It is the operational companion to:

- `WORKOUT_INTELLIGENCE_AGENT_VISION.md`
- `SEMANTIC_LAYER_API.md`
- `WORKOUT_SCHEMA.md`

## Knowledge Base Constraints

- The Custom GPT knowledge base is a flat uploaded document set.
- Repo-relative links are not reliable at runtime.
- Cross-references should use uploaded document names.

## Behavioral Rules

Behavioral rules and reasoning constraints are governed by the **Custom GPT Control Layer Instructions**. Use this guide for operational API usage and endpoint ordering.

---

## Conversation Start Checklist

Before the first natural-language response in every session, the agent must automatically make the following two calls to load live memory and planning state:

1. `GET /api/agent/context?athlete_id=rob`
2. `GET /api/planning/context?days=45`

If these are not called, you only have static schema/vision context, not current preferences, observations, workload, or readiness signals. The first user-facing response must wait until both calls complete.

## ChatGPT Integration Examples

These examples are sequencing illustrations only. For exact request shapes and canonical examples, use the configured Custom GPT Actions schema.

"What should I do tomorrow?"

```text
-> GET /api/agent/context?athlete_id=rob
-> GET /api/planning/context?athlete_id=rob&days=45
-> Returns: Last hard day, Z2 volume, intensity load, flags
```

Check Weight Trend

User: "Show my weight trend for the last 30 days"

ChatGPT calls:

```http
GET /api/physiometrics/history?athlete_id=rob&metrics=weight_kg&days=30
```

ChatGPT responds: "Here are your weight entries from the last 30 days (most recent first). If you'd like, I can summarize the trend from the returned data."

Check Current Physiometrics

User: "What are my current FTP and LTHR?"

ChatGPT calls:

```http
GET /api/physiometrics/current?athlete_id=rob
```

ChatGPT responds: "Your current FTP is 295 W and LTHR is 178 bpm (per the latest physiometrics)."

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
- Use for deep dives into a specific session when list projections are insufficient.
- Add `laps=true` when you need lap summaries.
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

## Actions Auth (Azure Functions)

Auth is defined in the configured Custom GPT Actions schema under `securitySchemes.FunctionKey`. Pass `?code=<function_key>` as a query parameter on every request.
