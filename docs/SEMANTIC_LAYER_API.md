# Semantic Access Layer API

Version: 2.1.1

The Semantic Access Layer is the **Read API** that sits between the raw metrics database and the ChatGPT UI. It exposes meaningful, human-centric questions about training data rather than raw table access.

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

### 📋 Core Semantic Layer Endpoints (20)

**ChatGPT-Facing Endpoints:**

| Endpoint | Purpose | Example |
| -------- | ------- | ------- |
| `/api/health` | Health check | Returns 200 when healthy, 503 when degraded |
| `/api/agent/context` | **Agent memory context** | `?athlete_id=rob` |
| `/api/agent/preferences` | User preferences | GET/POST `?athlete_id=rob` |
| `/api/agent/observations` | Training observations | GET/POST `?athlete_id=rob` |
| `/api/planning/context` | Planning decisions | `?athlete_id=rob&days=45` |
| `/api/workouts` | List workouts | `?athlete_id=rob&since=2026-01-01&sport=Cycling` |
| `/api/workouts/{workout_id}` | Workout detail | `/{workout_id}?athlete_id=rob` |
| `/api/rollups/weekly` | Weekly summaries | `?athlete_id=rob&weeks=16` |
| `/api/analysis/zones` | Zone distribution | `?athlete_id=rob&days=30` |
| `/api/analysis/efficiency` | Efficiency trends | `?athlete_id=rob&days=90` |
| `/api/physiometrics/current` | Current metrics | `?athlete_id=rob` |
| `/api/physiometrics/history` | Body metrics trends | `?athlete_id=rob&days=90` |
| `/api/physiometrics/update` | Update a metric | POST with metric + value |
| `/api/config/reload` | Reload configuration | POST (admin) |
| `/api/config/update` | Update configuration | POST (admin) |
| `/api/config/history` | Config audit trail | `?limit=10` |
| `/api/withings/webhook` | Withings OAuth callback | POST (Withings) |

**Internal/Admin Endpoints:**

These support ingestion and infrastructure but are not part of the ChatGPT-facing semantic layer:

- `/api/process_fit` - FIT file ingestion (admin)
- `/api/onedrive/authorize` - OneDrive OAuth flow (admin)
- `/api/onedrive/callback` - OneDrive OAuth redirect (internal)
- `/api/onedrive/sync` - Manual sync trigger (admin)
- `/api/.well-known/ai-plugin.json` - ChatGPT plugin manifest
- `/api/openapi.yaml` - API specification
- `/api/logo.svg` - Plugin logo

### 🛡️ Built-in Protections

- ✓ `athlete_id` parameter (Phase 1: defaults to "rob")
- ✓ Workout queries: max 200
- ✓ Days lookback: max 365
- ✓ Weeks: max 52
- ✓ Summary-first (time series on demand only)

### 🤖 ChatGPT Usage Patterns

#### "What should I do tomorrow?"

```text
→ GET /api/agent/context?athlete_id=rob  # Load preferences & observations first
→ GET /api/planning/context?athlete_id=rob&days=45
→ Returns: Last hard day, Z2 volume, intensity load, flags
```

---

## Philosophy

This layer:

- **Shapes data for reasoning** - returns small, coherent payloads optimized for LLM consumption
- **Constrains scope** - protects against unbounded queries and performance issues
- **Encodes domain knowledge** - understands how humans think about training
- **Stays stable** - provides a consistent interface for GPT Actions

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
  "recent_workouts": [
    {
      "workout_id": "abc123...",
      "sport": "Cycling",
      "start_time_utc": "2026-01-15T10:00:00+00:00",
      "duration_sec": 3600,
      "hr_z2_sec": 3000,
      "intensity_sec": 300,
      "pwr_avg_watts": 220
    }
  ],
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

**Use cases:**

- Daily training decision making
- Assessing readiness for intensity
- Identifying fatigue or recovery needs
- Detecting data quality issues

---

## Agent Memory System

> **New in v2.0:** External memory for persistent user context, training goals, and observations.  
> **See:** [AGENT_MEMORY.md](./AGENT_MEMORY.md) for complete documentation.

### 0. Get Agent Context (Call First)

```http
GET /api/agent/context?athlete_id=rob
```

**Primary agent memory endpoint.** Call at conversation start to load user preferences, training goals, and active observations into GPT context.

**Query Parameters:**

- `athlete_id` (optional, defaults to `rob`): Athlete identifier

**Response:**

```json
{
  "athlete_id": "rob",
  "preferences": {
    "current_goal": "Build aerobic base for spring races",
    "training_phase": "base-building",
    "preferred_sports": ["cycling", "running"],
    "ftp_test_frequency_weeks": 6,
    "last_ftp_test_date": "2026-01-15"
  },
  "active_observations": [
    {
      "observation_id": "uuid",
      "category": "pattern",
      "summary": "Low decoupling trend since Jan",
      "priority": "normal",
      "status": "active"
    }
  ],
  "instruction_addendum": "User's current goal: Build aerobic base for spring races | Training phase: base-building | Active observations: Low decoupling trend since Jan",
  "retrieved_at": "2026-02-05T12:00:00+00:00"
}
```

**Use cases:**

- Load user preferences at conversation start
- Tailor advice based on current training goals
- Reference active observations and patterns
- Provide contextually aware recommendations

### Get/Update Preferences

```http
GET /api/agent/preferences?athlete_id=rob
POST /api/agent/preferences?code=<function_key>
```

Manage user training preferences and goals. POST requires function authentication.

**GET Response:**

```json
{
  "athlete_id": "rob",
  "preferences": {
    "current_goal": "Build aerobic base for spring races",
    "training_phase": "base-building",
    "preferred_sports": ["cycling", "running"],
    "ftp_test_frequency_weeks": 6,
    "last_ftp_test_date": "2026-01-15",
    "notes": "Prefer weekday morning rides"
  },
  "updated_at": "2026-02-05T12:10:00+00:00"
}
```

**POST Request:**

```json
{
  "athlete_id": "rob",
  "current_goal": "Build aerobic base for spring races",
  "training_phase": "base-building",
  "preferred_sports": ["cycling", "running"],
  "ftp_test_frequency_weeks": 6,
  "last_ftp_test_date": "2026-01-15",
  "notes": "Prefer weekday morning rides"
}
```

**POST Response:**

```json
{
  "athlete_id": "rob",
  "preferences": {
    "current_goal": "Build aerobic base for spring races",
    "training_phase": "base-building",
    "preferred_sports": ["cycling", "running"],
    "ftp_test_frequency_weeks": 6,
    "last_ftp_test_date": "2026-01-15",
    "notes": "Prefer weekday morning rides"
  },
  "updated_at": "2026-02-05T12:10:00+00:00"
}
```

### Manage Observations

```http
GET /api/agent/observations?athlete_id=rob&status=active&limit=20
POST /api/agent/observations?code=<function_key>
PATCH /api/agent/observations/{observation_id}?code=<function_key>
```

Track training patterns, flags, and insights. POST/PATCH require function authentication.

**POST Request:**

```json
{
  "athlete_id": "rob",
  "category": "fatigue",
  "summary": "Elevated resting heart rate detected",
  "details": "Resting HR 58 vs baseline 52 over 3 days",
  "workout_ids": ["abc123", "def456"],
  "priority": "high",
  "expires_days": 4
}
```

**POST Response (201):**

```json
{
  "observation_id": "uuid",
  "observation": {
    "observation_id": "uuid",
    "athlete_id": "rob",
    "category": "fatigue",
    "summary": "Elevated resting heart rate detected",
    "details": "Resting HR 58 vs baseline 52 over 3 days",
    "referenced_workout_ids": ["abc123", "def456"],
    "priority": "high",
    "status": "active",
    "created_at": "2026-02-05T12:20:00+00:00",
    "expires_at": "2026-02-09T00:00:00+00:00"
  }
}
```

**PATCH Request:**

```json
{
  "athlete_id": "rob",
  "status": "resolved"
}
```

**PATCH Response:**

```json
{
  "observation_id": "uuid",
  "status": "resolved",
  "updated_at": "2026-02-06T08:15:00+00:00"
}
```

---

## Physiometrics Management

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
    },
    {
      "effective_date": "2025-10-22",
      "updated_at_utc": "2025-10-22T07:45:12+00:00",
      "data_source": "withings",
      "weight_kg": 76.5,
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

### 9. Update Physiometrics

```http
POST /api/physiometrics/update
Content-Type: application/json
```

Update physiometric values (single metric or bulk partial update).

**Request Body (Single Metric):**

```json
{
  "athlete_id": "rob",
  "metric": "cycling_vo2max_ml_kg_min",
  "value": 52.3,
  "effective_date": "2026-01-19",
  "source": "chatgpt"
}
```

**Request Body (Bulk Update):**

```json
{
  "athlete_id": "rob",
  "metrics": {
    "weight_kg": 75.2,
    "cycling_vo2max_ml_kg_min": 52.3
  },
  "effective_date": "2026-01-19",
  "source": "chatgpt"
}
```

**Parameters:**

- `athlete_id` (required): Athlete identifier
- `metric` (required for single update): Metric name
- `value` (required for single update): New value
- `metrics` (required for bulk): Dict of metric names to values
- `effective_date` (optional): ISO date when value takes effect (defaults to today)
- `source` (optional): Data source (`chatgpt`, `manual`, `withings`) - defaults to `chatgpt`

**Response:**

```json
{
  "status": "success",
  "athlete_id": "rob",
  "metric": "cycling_vo2max_ml_kg_min",
  "value": 52.3,
  "effective_date": "2026-01-19",
  "source": "chatgpt",
  "updated_at_utc": "2026-01-19T14:32:15+00:00"
}
```

**Use cases:**

- ChatGPT updates cycling VO2Max from user conversation
- Manual entry of weight if Withings not connected
- Bulk update of FTP and LTHR after threshold test

---

### 10. Retroactive Zone Recalculation

```http
GET /api/workouts/{workout_id}/recalculated?ftp_watts=300&lthr_bpm=175
```

Get a read-only view of workout zones recalculated with different physiometric values.

**Route Parameters:**

- `workout_id` (required): Workout identifier

**Query Parameters:**

- `ftp_watts` (optional): Override FTP value for power zone calculation
- `lthr_bpm` (optional): Override LTHR value for HR zone calculation

**Response:**

```json
{
  "status": "not_implemented",
  "message": "Retroactive zone recalculation coming soon"
}
```

**Use cases:**

- Answer "How would this workout look at my current FTP?"
- Compare zone distribution before/after threshold improvements
- Analyze training load with different physiometric baselines

---

## Withings Integration

### OAuth Authorization Flow

#### Step 1: Get Authorization URL

```json
GET /api/withings/authorize?athlete_id=rob
```

**Response:**

```json
{
  "authorization_url": "https://account.withings.com/oauth2_user/authorize2?...",
  "instructions": "Open this URL in your browser to authorize Withings access",
  "athlete_id": "rob"
}
```

#### Step 2: User Authorizes in Browser

User opens the URL and authorizes access to their Withings account.

#### Step 3: Callback Handled by Azure

```http
GET /api/withings/callback?code=...&state=...
```

Withings redirects back to this endpoint with authorization code. The system:

1. Exchanges code for OAuth tokens
2. Stores tokens in `WithingsTokens` table
3. Subscribes to webhook notifications
4. Returns success HTML page

#### Step 4: Automatic Webhook Sync

When user weighs in with BodyScan or Body+ scales:

1. Withings sends webhook notification to `/api/withings/webhook`
2. Webhook queued for async processing
3. Background worker fetches measurement data
4. Weight and body composition stored in `Physiometrics` table with `source=withings`

---

### Withings Webhook (Internal)

```http
POST /api/withings/webhook
Content-Type: application/x-www-form-urlencoded

userid=12345&appli=1&startdate=1705622400&enddate=1705622500
```

This endpoint is called by Withings servers when new measurements are available.

**Processing:**

- Validates webhook payload
- Checks deduplication (avoids processing same webhook twice)
- Queues for async processing
- Returns HTTP 200 immediately (fast acknowledgment)
- Background worker fetches and stores measurement data

**Supported Measurements:**

- Weight (kg)
- Fat mass (kg)
- Muscle mass (kg)
- Bone mass (kg)
- Body fat percentage
- Visceral fat index
- Metabolic age (years)

---

## ChatGPT Integration Examples

Update Cycling VO2Max

User: "My new cycling VO2Max is 52.3"

ChatGPT calls:

```json
POST /api/physiometrics/update
{
  "athlete_id": "rob",
  "metric": "cycling_vo2max_ml_kg_min",
  "value": 52.3,
  "source": "chatgpt"
}
```

Connect Withings Account

User: "Connect my Withings scale"

ChatGPT calls:

```bash
GET /api/withings/authorize?athlete_id=rob
```

ChatGPT responds: "Please open this URL to authorize access to your Withings account: [link]"

Check Weight Trend

User: "Show my weight trend for the last 30 days"

ChatGPT calls:

```bash
GET /api/physiometrics/history?athlete_id=rob&metrics=weight_kg&days=30
```

ChatGPT responds: "Your weight has ranged from 74.8 kg to 76.2 kg over the last 30 days, with an average of 75.4 kg. You're trending downward at about 0.2 kg per week."

Update Multiple Metrics

User: "I did a threshold test today. My new FTP is 295 and LTHR is 178"

ChatGPT calls:

```json
POST /api/physiometrics/update
{
  "athlete_id": "rob",
  "metrics": {
    "power_ftp_watts": 295,
    "heart_rate_lthr_bpm": 178
  },
  "effective_date": "2026-01-19",
  "source": "chatgpt"
}
```

---

## 2. List Workouts

```http
GET /api/workouts?athlete_id=rob&since=2026-01-01&limit=50&sport=Cycling
```

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
  "sport": "Cycling",
  "start_time_utc": "2026-01-15T10:00:00+00:00",
  "duration_sec": 3600,
  "hr_avg_bpm": 145,
  "pwr_avg_watts": 220,
  "hr_z2_sec": 3000,
  "pwr_z2_sec": 2700,
  "intensity_sec": 480,
  "decoupling_pct": 2.5,
  "ef_overall": 1.52,
  "intensity_factor": 0.85,
  "tss": 65,
  "laps_count": 3,
  "laps": []
}
```

**Use cases:**

- Deep dive into specific workout
- Fetching lap summaries before requesting lap detail

**Transport note:** If the client sends `Accept-Encoding: gzip`, the response will be gzip-compressed.

---

### 3a. Get Workout Lap Detail

```http
GET /api/workouts/{workout_id}/laps/{lap_index}?athlete_id=rob
```

Retrieve lap summary and per-lap record payload for a single lap.

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
  "lap_index": 0,
  "record_count": 300,
  "start_time": "2026-01-15T10:00:00+00:00",
  "total_elapsed_time": 300,
  "total_distance": 1500.5,
  "avg_heart_rate": 145,
  "avg_power": 220,
  "records": [
    {
      "record_index": 0,
      "heart_rate": 145,
      "power": 220,
      "cadence": 90,
      "position_lat": 384217123.0,
      "position_long": -120123456.0
    }
  ]
}
```

---

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
  "rollups": [
    {
      "PartitionKey": "rob#2026",
      "RowKey": "2026-03",
      "total_duration_sec": 14400,
      "total_distance_m": 180000,
      "total_hr_z2_min": 200,
      "total_pwr_z2_min": 180,
      "total_intensity_min": 45
    }
  ]
}
```

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

## Usage with ChatGPT

The semantic layer is designed to be consumed by ChatGPT via GPT Actions. Example prompts:

**"What should I do tomorrow?"**
→ Calls `/api/planning/context` to get recent training load, last hard day, Z2 volume, flags

**"Show me my cycling workouts from January"**
→ Calls `/api/workouts?sport=Cycling&since=2026-01-01`

**"How is my aerobic efficiency trending?"**
→ Calls `/api/analysis/efficiency?days=90`

**"Am I getting enough base training?"**
→ Calls `/api/analysis/zones?days=30` to check Z2 percentage

---

## Implementation Details

### Date Handling

- All dates use **ISO 8601 format with explicit UTC offsets** (`2026-01-15T10:00:00+00:00`)
- Date ranges are **inclusive** on both ends
- Default lookback periods are conservative (30-90 days) to protect performance

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

---

## Configuration Management Endpoints

These endpoints manage athlete physiometric configuration (FTP, LTHR, HR methods, body composition).

### 11. Get Configuration History

```http
GET /api/config/history?limit=10
```

Retrieve the history of configuration changes (FTP, LTHR, zone basis).

**Query Parameters:**

- `limit` (optional): Max records to return (default 10, max 50)

**Response:**

```json
{
  "status": "success",
  "count": 2,
  "history": [
    {
      "updated_at_utc": "2026-01-20T10:30:00+00:00",
      "heart_rate": {
        "basis": "LTHR",
        "lthr_bpm": 175,
        "hr_max_bpm": 195,
        "resting_hr_bpm": 52
      },
      "power": {
        "ftp_watts": 285
      }
    }
  ]
}
```

**Use cases:**

- Audit trail for all configuration changes
- Detecting when zones were adjusted
- Correlating configuration changes with performance shifts
- Validating FTP history for retrospective metric recalculation

---

### 12. Update Configuration

```http
POST /api/config/update
```

Update physiometrics configuration (FTP, LTHR, HR/power zone basis).

**Request Body:**

```json
{
  "heart_rate": {
    "basis": "LTHR",
    "lthr_bpm": 175,
    "hr_max_bpm": 195,
    "resting_hr_bpm": 52
  },
  "power": {
    "ftp_watts": 285
  }
}
```

**Response (200 OK):**

```json
{
  "status": "success",
  "message": "Configuration saved to Azure Table Storage",
  "updated_at_utc": "2026-01-20T10:30:00+00:00",
  "heart_rate": {
    "basis": "LTHR",
    "lthr_bpm": 175,
    "hr_max_bpm": 195,
    "resting_hr_bpm": 52
  },
  "power": {
    "ftp_watts": 285
  }
}
```

**Status codes:**

- `200 OK` - Configuration updated successfully
- `400 Bad Request` - Invalid payload
- `500 Internal Server Error` - Failed to update configuration

---

### 13. Reload Configuration

```http
POST /api/config/reload
```

Force reload of athlete configuration from storage (useful after external updates or to clear cache).

**Response (200 OK):**

```json
{
  "status": "success",
  "message": "Configuration reloaded from disk",
  "heart_rate": {
    "basis": "LTHR",
    "lthr_bpm": 175,
    "hr_max_bpm": 195,
    "resting_hr_bpm": 52
  },
  "power": {
    "ftp_watts": 285
  }
}
```

**Use cases:**

- After manual database edits
- To clear in-memory cache
- Before recalculating zones for past workouts

---

## Testing

Comprehensive test coverage in `tests/test_semantic_layer.py`:

```bash
# Run semantic layer tests
pytest tests/test_semantic_layer.py -v

# Run specific test class
pytest tests/test_semantic_layer.py::TestPlanningContext -v
```

---

## Local Development

```bash
# Start Azure Functions host
func host start

# Test planning context endpoint
curl "http://localhost:7071/api/planning/context?athlete_id=rob&days=30"

# Test workouts list
curl "http://localhost:7071/api/workouts?athlete_id=rob&limit=10"

# Test zone analysis
curl "http://localhost:7071/api/analysis/zones?athlete_id=rob&days=30"
```

---

## Future Enhancements

### Phase 2 (Planned)

- Precomputed rollup aggregations for faster queries
- Comparison windows ("best 6-week block")
- Fatigue/readiness heuristics (still deterministic)

### Phase 3 (Optional)

- Multi-athlete support (same schema, different partition keys)
- Longitudinal modeling and trend detection
- Export capabilities (CSV, JSON, email summaries)

---

## Related Documentation

- [Workout Intelligence Agent Vision](./WORKOUT_INTELLIGENCE_AGENT_VISION.md) - Overall system architecture
- [Workout Schema](./WORKOUT_SCHEMA.md) - Database schema and metrics
- [Testing Guide](../tests/README.md) - Test strategy and execution
