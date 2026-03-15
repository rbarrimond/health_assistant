# Semantic Access Layer API (GPT)

Version: 6.0.0

The Semantic Access Layer is the **read + agent-memory write API** for ChatGPT Actions. It exposes meaningful, human-centric questions about training data rather than raw table access.

> **Note:** This document mirrors [`openapi.yaml`](../../api_docs/openapi.yaml). For admin/operations endpoints, see [`../devops/OPERATIONS_API.md`](../devops/OPERATIONS_API.md).
> Storage and ingestion details live in [`INGESTION_SCHEMA.md`](../devops/data_architecture/INGESTION_SCHEMA.md).
>
> **Phase 1 Note:** This system is currently deployed for single-athlete use. Most endpoints default `athlete_id` to `"rob"` when not provided. The multi-athlete architecture is implemented but enforcement is deferred to Phase 2.

---

## Quick Reference

### 🎯 Core Concept

The semantic layer answers **meaningful questions** about training, not raw database queries.

### 🔑 Most Important Endpoint

```http
GET /api/planning/context?athlete_id=rob&days=45
```

**Answers:** *"Given what I've actually done, what does tomorrow look like?"*

**Returns:** Recent workouts, weekly rollups, last hard day, Z2 volume, intensity minutes, data flags

### 📋 GPT-Facing Endpoints

| Endpoint | Purpose | Example |
| -------- | ------- | ------- |
| `/api/health` | Health check | Returns 200 when healthy, 503 when degraded |
| `/api/agent/context` | **Agent memory context** | `?athlete_id=rob` |
| `/api/agent/preferences` | User preferences | GET/POST `?athlete_id=rob` |
| `/api/agent/observations` | Training observations | GET/POST/PATCH |
| `/api/planning/context` | Planning decisions | `?athlete_id=rob&days=45` |
| `/api/workouts` | List workouts | `?athlete_id=rob&since=2026-01-01` |
| `/api/workouts/{workout_id}` | Workout detail | `/{workout_id}?athlete_id=rob&laps=true` |
| `/api/workouts/{workout_id}/laps/{lap_index}` | Lap detail | Typed single-lap summary |
| `/api/rollups/weekly` | Weekly summaries | `?athlete_id=rob&weeks=16` |
| `/api/analysis/zones` | Zone distribution | `?athlete_id=rob&days=30` |
| `/api/analysis/efficiency` | Efficiency trends | `?athlete_id=rob&days=90` |
| `/api/physiometrics/current` | Current metrics | `?athlete_id=rob` |
| `/api/physiometrics/history` | Body metrics trends | `?athlete_id=rob&days=90` |
| `/api/training-state/current` | Current training state | `?athlete_id=rob` |
| `/api/training-state/history` | Training state trends | `?athlete_id=rob&days=90` |

**Operational usage:** See [GPT_ACTIONS_GUIDE.md](./GPT_ACTIONS_GUIDE.md) for call order and integration examples.

### 🛡️ Built-in Protections

- ✓ `athlete_id` parameter (Phase 1: defaults to "rob")
- ✓ Workout queries: max 200
- ✓ Days lookback: max 365
- ✓ Weeks: max 52
- ✓ Summary-first (time series on demand only)

---

## Philosophy

This layer:

- **Shapes data for reasoning** - returns small, coherent payloads optimized for LLM consumption
- **Constrains scope** - protects against unbounded queries and performance issues
- **Encodes domain knowledge** - understands how humans think about training
- **Stays stable** - provides a consistent interface for GPT Actions

---

## Core Endpoints

### 1. Planning Context (Most Important)

```http
GET /api/planning/context?athlete_id=rob&days=45
```

**The single most important endpoint.** Answers: *"Given what I've actually done, what does tomorrow look like?"*

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `days` (optional): Number of days to look back (default 45, max 365)

**Response:**

```json
{
  "athlete_id": "rob",
  "query_window": {
    "start_date": "2025-12-01T00:00:00+00:00",
    "end_date": "2026-01-15T00:00:00+00:00",
    "days": 45
  },
  "recent_workouts": [...],
  "weekly_rollups": [...],
  "summary": {
    "last_hard_day": "2026-01-15T10:00:00+00:00",
    "last_long_day": "2026-01-13T08:00:00+00:00",
    "cumulative_z2_minutes": 450,
    "cumulative_intensity_minutes": 85,
    "total_workouts": 12
  },
  "notable_flags": [
    "2 workout(s) missing heart rate data",
    "1 workout(s) with high decoupling (>5%)"
  ]
}
```

**Zone Time Units:**

- Zone times are stored in **seconds** (canonical storage unit: `hr_z2_sec`, `pwr_z2_sec`, `intensity_sec`)
- Summary aggregates are converted to **minutes** for display (`cumulative_z2_minutes`, `cumulative_intensity_minutes`)
- Detection thresholds: last_hard_day (>5 min intensity), last_long_day (>60 min Z2)

**Use cases:**

- Daily training decision making
- Assessing readiness for intensity
- Identifying fatigue or recovery needs
- Detecting data quality issues

---

## Agent Memory System

> **New in v2.0:** External memory for persistent user context, training goals, and observations.  
> **See:** [AGENT_MEMORY.md](./AGENT_MEMORY.md) for complete documentation.

This section describes how memory data is stored and retrieved. Full API mechanics and payloads live in [AGENT_MEMORY.md](./AGENT_MEMORY.md). Operational call order lives in [GPT_ACTIONS_GUIDE.md](./GPT_ACTIONS_GUIDE.md).

### 1a. Get Agent Context

```http
GET /api/agent/context?athlete_id=rob&code=<function_key>
```

Retrieve preferences and active observations for conversation start.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `code` (required): Function key for authentication

**Response:**

Weekly rollup items are strict-schema payloads: responses include only documented `WeeklyRollups` fields and do not pass through legacy or unmodeled storage keys.

```json
{
  "athlete_id": "rob",
  "preferences": [
    {
      "preference_id": "pref_abc123",
      "category": "goal",
      "summary": "Build Z2 base",
      "priority": "high",
      "status": "active",
      "created_at": "2026-01-15T08:00:00+00:00"
    }
  ],
  "active_observations": [
    {
      "observation_id": "obs_123",
      "category": "fatigue",
      "summary": "Slept poorly this week",
      "priority": "normal",
      "status": "active",
      "created_at": "2026-02-10T08:00:00+00:00"
    }
  ],
  "instruction_addendum": "User's current goal: Build Z2 base",
  "retrieved_at": "2026-02-12T12:05:00+00:00"
}
```

**Use cases:**

- Load memory at conversation start
- Detect constraints before planning

---

### 1b. List Agent Preferences

```http
GET /api/agent/preferences?athlete_id=rob&status=active&limit=20&code=<function_key>
```

List user preferences with filtering.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `status` (optional, defaults to `active`): Preference status filter
- `limit` (optional): Max preferences to return
- `code` (required): Function key for authentication

**Response:**

```json
{
  "athlete_id": "rob",
  "count": 2,
  "preferences": [
    {
      "preference_id": "pref_abc123",
      "category": "goal",
      "summary": "Build Z2 base",
      "priority": "high",
      "status": "active",
      "created_at": "2026-01-15T08:00:00+00:00"
    },
    {
      "preference_id": "pref_def456",
      "category": "training_phase",
      "summary": "base",
      "priority": "normal",
      "status": "active",
      "created_at": "2026-01-15T08:00:00+00:00"
    }
  ]
}
```

**Use cases:**

- Confirm active preferences before advice
- Audit user context

---

### 1c. Add Agent Preference

```http
POST /api/agent/preferences
```

Create a new preference item.

**Request Body:**

```json
{
  "athlete_id": "rob",
  "category": "goal",
  "summary": "Build Z2 base",
  "details": "Focus on aerobic endurance for spring races",
  "priority": "high"
}
```

**Response:**

```json
{
  "preference_id": "pref_abc123",
  "preference": {
    "preference_id": "pref_abc123",
    "athlete_id": "rob",
    "category": "goal",
    "summary": "Build Z2 base",
    "details": "Focus on aerobic endurance for spring races",
    "priority": "high",
    "status": "active",
    "created_at": "2026-02-12T12:06:00+00:00"
  }
}
```

**Use cases:**

- Persist new goals or constraints
- Sync updates from user conversation

---

### 1d. Update Agent Preference

```http
PATCH /api/agent/preferences/{preference_id}
```

Update a preference (status, summary, details, etc.).

**Route Parameters:**

- `preference_id` (required): Preference identifier

**Request Body:**

```json
{
  "athlete_id": "rob",
  "status": "resolved"
}
```

**Response:**

```json
{
  "preference_id": "pref_abc123",
  "preference": {
    "preference_id": "pref_abc123",
    "status": "resolved",
    "updated_at": "2026-02-12T12:07:00+00:00"
  }
}
```

**Use cases:**

- Archive resolved goals
- Update preference details

---

### 1e. List Agent Observations

```http
GET /api/agent/observations?athlete_id=rob&status=active&limit=50&code=<function_key>
```

List observations with optional filtering.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `status` (optional): Observation status filter
- `limit` (optional): Max observations to return
- `code` (required): Function key for authentication

**Response:**

```json
{
  "athlete_id": "rob",
  "count": 1,
  "observations": [
    {
      "observation_id": "obs_123",
      "category": "fatigue",
      "summary": "Slept poorly this week",
      "priority": "normal",
      "status": "active",
      "created_at": "2026-02-10T08:00:00+00:00"
    }
  ]
}
```

**Use cases:**

- See active constraints
- Audit memory items

---

### 1f. Add Agent Observation

```http
POST /api/agent/observations?athlete_id=rob
```

Create a new observation (e.g., soreness, schedule constraints).

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier

**Request Body:**

```json
{
  "athlete_id": "rob",
  "category": "soreness",
  "summary": "Right knee is tender after intervals",
  "priority": "normal",
  "expires_days": 7
}
```

**Response:**

```json
{
  "observation_id": "obs_456",
  "observation": {
    "observation_id": "obs_456",
    "athlete_id": "rob",
    "category": "soreness",
    "summary": "Right knee is tender after intervals",
    "priority": "normal",
    "status": "active",
    "created_at": "2026-02-12T10:30:00+00:00"
  }
}
```

**Use cases:**

- Capture new constraints mid-cycle
- Record recovery or readiness notes

### 1g. Update Agent Observation

```http
PATCH /api/agent/observations/{observation_id}
```

Update observation status (e.g., `active`, `resolved`, `archived`).

**Route Parameters:**

- `observation_id` (required): Observation identifier

**Request Body:**

```json
{
  "athlete_id": "rob",
  "status": "resolved"
}
```

**Response:**

```json
{
  "observation_id": "obs_456",
  "status": "resolved",
  "updated_at": "2026-02-12T10:35:00+00:00"
}
```

**Use cases:**

- Mark observations as resolved
- Archive old observations

---

## Workout Endpoints

### 2. List Workouts

```http
GET /api/workouts?athlete_id=rob&since=2026-01-01&limit=50&sport=Cycling
```

Get workout summaries with optional filtering.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `since` (optional): ISO date to filter workouts after
- `limit` (optional): Max workouts to return (default 50, max 200)
- `sport` (optional): Filter by sport type

**Note:** `device_name` reflects the file-creator device (e.g., Edge 1050, Apple Watch), not peripheral sensors.

**Response:**

```json
{
  "athlete_id": "rob",
  "count": 15,
  "workouts": [
    {
      "workout_id": "abc123",
      "sport": "Cycling",
      "start_time_utc": "2026-01-15T10:00:00+00:00",
      "duration_sec": 3600,
      "distance_m": 45000,
      "hr_avg_bpm": 145,
      "pwr_avg_watts": 220
    }
  ]
}
```

**Use cases:**

- Recent activity overview
- Sport-specific analysis
- Training log queries

---

### 3. Get Workout Detail

```http
GET /api/workouts/{workout_id}?athlete_id=rob&laps=true
```

Retrieve full workout data with optional lap summaries.

**Route Parameters:**

- `workout_id` (required): Unique workout identifier

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `laps` (optional, default `false`): Include lap summary data

**Response:**

```json
{
  "workout_id": "abc123",
  "athlete_id": "rob",
  "source_system": "onedrive",
  "metrics": {
    "session": {
      "sport": "Cycling",
      "start_time_utc": "2026-01-15T10:00:00+00:00",
      "duration_sec": 3600
    },
    "samples": {
      "hr_avg_bpm": 145,
      "pwr_avg_watts": 220,
      "cad_avg_rpm": 86
    },
    "zones_hr": {
      "hr_z2_sec": 3000
    },
    "zones_power": {
      "pwr_z2_sec": 2700,
      "intensity_sec": 480
    },
    "training_load": {
      "intensity_factor": 0.85,
      "tss": 65
    },
    "durability": {
      "decoupling_pct": 2.5,
      "ef_overall": 1.52
    }
  },
  "laps_count": 3,
  "laps": []
}
```

**Use cases:**

- Deep dive into specific workout
- Fetching lap summaries before requesting lap detail

**Transport note:** If the client sends `Accept-Encoding: gzip`, the response will be gzip-compressed.

**Error semantics:**

- `404` when the workout is not found for the athlete
- `500` when internal processing fails

---

### 3a. Get Workout Lap Detail

```http
GET /api/workouts/{workout_id}/laps/{lap_index}?athlete_id=rob
```

Retrieve typed lap summary payload for a single lap.

**Route Parameters:**

- `workout_id` (required): Unique workout identifier
- `lap_index` (required): Zero-based lap index

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`)

**Response:**

```json
{
  "workout_id": "abc123",
  "athlete_id": "rob",
  "lap": {
    "lap_index": 0,
    "message_index": 0,
    "start_time": "2026-01-15T10:00:00+00:00",
    "end_time": "2026-01-15T10:05:00+00:00",
    "total_elapsed_time": 300,
    "total_timer_time": 296,
    "total_distance": 1500.5,
    "avg_heart_rate": 145,
    "avg_power": 220,
    "extra_fields": {
      "dev_form_power": {
        "value": 12.5,
        "units": "%"
      }
    }
  }
}
```

---

## Analysis Endpoints

### 4. Weekly Rollups

```http
GET /api/rollups/weekly?athlete_id=rob&weeks=16
```

Get aggregated weekly training data.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `weeks` (optional): Number of weeks to retrieve (default 16, max 52)

**Response:**

```json
{
  "athlete_id": "rob",
  "weeks": 16,
  "count": 16,
  "status": "success",
  "message": "Weekly rollups available for requested window",
  "results": [
    {
      "weeks_ago": 1,
      "status": "success",
      "message": "Weekly rollup available",
      "week_start_utc": "2026-01-13T00:00:00+00:00",
      "week_end_utc": "2026-01-19T23:59:59+00:00"
    },
    {
      "weeks_ago": 16,
      "status": "skipped",
      "message": "No weekly rollup available for requested week"
    }
  ],
  "rollups": [
    {
      "week_start_utc": "2026-01-13T00:00:00+00:00",
      "week_end_utc": "2026-01-19T23:59:59+00:00",
      "workouts_count": 6,
      "total_duration_min": 240.0,
      "total_distance_km": 180.0,
      "total_elev_m": 900.0,
      "total_hr_z2_min": 200.0,
      "total_pwr_z2_min": 180.0,
      "total_low_aerobic_min": 160.0,
      "total_intensity_min": 45.0,
      "avg_decoupling_pct": 3.2,
      "hard_days_count": 2,
      "long_rides_count": 1,
      "last_updated_at_utc": "2026-01-19T23:59:59+00:00"
    }
  ]
}
```

**Response status semantics:**

- `success` - rollups available for all requested week slots
- `partial` - rollups available for part of requested week slots
- `skipped` - no rollups available for requested week slots

**Use cases:**

- Training volume trends
- Week-over-week comparison
- Load management

---

### 5. Zone Distribution

```http
GET /api/analysis/zones?athlete_id=rob&days=30
```

Analyze time-in-zone distribution for training balance assessment.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `days` (optional): Number of days to analyze (default 30, max 365)

**Response:**

```json
{
  "athlete_id": "rob",
  "query_window": {
    "start_date": "2025-12-16T00:00:00+00:00",
    "end_date": "2026-01-15T00:00:00+00:00",
    "days": 30
  },
  "total_minutes": 600,
  "zones": {
    "z1": 50,
    "z2": 400,
    "z3": 80,
    "z4": 50,
    "z5": 20
  },
  "percentages": {
    "z1": 8.3,
    "z2": 66.7,
    "z3": 13.3,
    "z4": 8.3,
    "z5": 3.3
  }
}
```

**Use cases:**

- Assessing training polarization
- Checking Z2 base building
- Identifying intensity imbalance

---

### 6. Efficiency Trends

```http
GET /api/analysis/efficiency?athlete_id=rob&days=90
```

Track aerobic efficiency and power-HR decoupling over time.

**Query Parameters:**

- `athlete_id` (required): Athlete identifier
- `days` (optional): Number of days to analyze (default 90, max 365)

**Response:**

```json
{
  "athlete_id": "rob",
  "query_window": {
    "start_date": "2025-10-17T00:00:00+00:00",
    "end_date": "2026-01-15T00:00:00+00:00",
    "days": 90
  },
  "samples": [
    {
      "date": "2026-01-15T10:00:00+00:00",
      "sport": "Cycling",
      "decoupling_pct": 2.5,
      "ef_overall": 1.52,
      "hr_drift_bpm": 3.2
    }
  ],
  "summary": {
    "total_samples": 15,
    "avg_decoupling": 3.2
  }
}
```

**Use cases:**

- Tracking aerobic fitness improvements
- Identifying fatigue or overtraining
- Assessing workout quality

---

## Physiometrics Endpoints

### 7. Get Current Physiometrics

```http
GET /api/physiometrics/current?athlete_id=rob
```

Retrieve current physiometric values for an athlete (weight, FTP, LTHR, cycling VO2Max, body composition).

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier

**Response:**

```json
{
  "athlete_id": "rob",
  "heart_rate": {
    "basis": "HRmax",
    "lthr_bpm": 175,
    "hr_max_bpm": 195,
    "resting_hr_bpm": 52
  },
  "power": {
    "ftp_watts": 285
  },
  "weight_kg": 75.2,
  "fat_mass_kg": 12.5,
  "muscle_mass_kg": 38.2,
  "bone_mass_kg": 3.1,
  "body_fat_pct": 16.6,
  "visceral_fat_index": 8,
  "metabolic_age_years": 32,
  "cycling_vo2max_ml_kg_min": 52.3,
  "effective_date": "2026-01-19",
  "data_source": "withings"
}
```

**Use cases:**

- Display current athlete profile
- Show training zones based on current FTP/LTHR
- Track body composition changes

---

### 8. Get Physiometrics History

```http
GET /api/physiometrics/history?athlete_id=rob&metrics=weight_kg,cycling_vo2max_ml_kg_min&days=90
```

Retrieve time-series physiometric data for trend analysis.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier
- `days` (optional): Number of days to look back (default 90, max 365)
- `metrics` (optional): Comma-separated list of metrics (default: all)
  - Available metrics: `weight_kg`, `fat_mass_kg`, `muscle_mass_kg`, `bone_mass_kg`, `body_fat_pct`, `visceral_fat_index`, `metabolic_age_years`, `cycling_vo2max_ml_kg_min`, `heart_rate_lthr_bpm`, `heart_rate_hr_max_bpm`, `power_ftp_watts`

**Response:**

```json
{
  "athlete_id": "rob",
  "query_window": {
    "start_date": "2025-10-21",
    "end_date": "2026-01-19",
    "days": 90
  },
  "count": 85,
  "data_points": [
    {
      "effective_date": "2025-10-21",
      "updated_at_utc": "2025-10-21T08:15:32+00:00",
      "data_source": "withings",
      "weight_kg": 76.8,
      "cycling_vo2max_ml_kg_min": 51.2
    }
  ]
}
```

**Use cases:**

- Weight trend charting
- FTP progression tracking
- Body composition analysis over time
- VO2Max improvement tracking

---

## Physiometrics API Walkthrough

### Data Sources and Precedence

Physiometrics are stored as source snapshots and merged by metric precedence for consolidated reads.

- Intervals.icu dominates wellness/recovery metrics.
- Garmin dominates training metrics, FTP, and VO2Max metrics.
- Withings dominates weight and body composition metrics.
- `resting_hr_bpm` is Intervals-only (no Garmin/manual/chatgpt fallback).
- `ftp_watts`, `hr_lthr_bpm`, and `hr_max_bpm` use explicit fallback: `garmin -> chatgpt -> manual`.

### Current Physiometrics (Read)

`GET /api/physiometrics/current` returns a consolidated daily snapshot using source precedence rules, with normalized metric fields plus metadata (`effective_date`, `data_sources`). Use this for profile displays, training-zone context, and chat summaries.

### Physiometrics History (Read)

`GET /api/physiometrics/history` returns source-row history over a bounded date window from stored Physiometrics entities. If `metrics` is provided, only those fields plus metadata are returned per data point; otherwise the full snapshot is returned. Use this for trends and charts.

---

## Design Principles

### ✅ What This Layer Does

- Returns **small, bounded payloads** suitable for LLM reasoning
- Answers **semantic questions** humans actually ask
- Protects against **unbounded queries** and performance issues
- Provides **summary-first** data with detail on demand
- Encodes **training domain knowledge** in its structure

### ❌ What This Layer Does NOT Do

- Expose raw database tables directly
- Return unlimited time series by default
- Make training recommendations or judgments
- Store transient interpretations
- Depend on specific UI assumptions

---

## Implementation Details

### Date Handling

- All dates use **ISO 8601 format with explicit UTC offsets** (`2026-01-15T10:00:00+00:00`)
- Date ranges are **inclusive** on both ends
- Default lookback periods are conservative (30-90 days) to protect performance

### Timezone Fields

- `local_tz_offset` is the semantic/API field for client-side local-time display to humans.
- `timezone` is metadata context for provenance and prefers IANA timezone names when available.
- When IANA timezone data is unavailable, `timezone` falls back to the UTC offset string.

### Query Constraints

- Most endpoints accept `athlete_id` for data isolation (Phase 1 defaults to `rob` when omitted)
- Maximum limits prevent unbounded queries:
  - Workouts: max 200
  - Days: max 365
  - Weeks: max 52
- Queries span multiple month partitions automatically

### Performance Optimizations

- Summary-only queries exclude time series data by default
- Partition key strategy enables efficient month-based queries
- Result sets sorted by date (newest first) for relevance

### Error Handling

All endpoints return consistent error responses:

```json
{
  "error": "Error description"
}
```

**Status codes:**

- `200 OK` - Success
- `400 Bad Request` - Invalid parameters
- `404 Not Found` - Resource doesn't exist
- `500 Internal Server Error` - Server-side failure
