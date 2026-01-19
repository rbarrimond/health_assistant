# Semantic Access Layer API

The Semantic Access Layer is the **Read API** that sits between the raw metrics database and the ChatGPT UI. It exposes meaningful, human-centric questions about training data rather than raw table access.

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

- `athlete_id` (required): Athlete identifier
- `days` (optional): Number of days to look back (default 45, max 365)

**Response:**

```json
{
  "athlete_id": "rob",
  "query_window": {
    "start_date": "2025-12-01T00:00:00Z",
    "end_date": "2026-01-15T00:00:00Z",
    "days": 45
  },
  "recent_workouts": [
    {
      "workout_id": "abc123...",
      "sport": "Cycling",
      "start_time_utc": "2026-01-15T10:00:00Z",
      "duration_sec": 3600,
      "z2_minutes": 50,
      "z4_minutes": 5,
      "pwr_avg_watts": 220
    }
  ],
  "weekly_rollups": [...],
  "summary": {
    "last_hard_day": "2026-01-15T10:00:00Z",
    "last_long_day": "2026-01-13T08:00:00Z",
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

### 2. List Workouts

```http
GET /api/workouts?athlete_id=rob&since=2026-01-01&limit=50&sport=Cycling
```

Query workouts with flexible filters.

**Query Parameters:**

- `athlete_id` (required): Athlete identifier
- `since` (optional): ISO date string - start of range
- `until` (optional): ISO date string - end of range (default: now)
- `limit` (optional): Max workouts to return (default 50, max 200)
- `sport` (optional): Filter by sport type (e.g., "Cycling", "Running")

**Response:**

```json
{
  "athlete_id": "rob",
  "count": 15,
  "workouts": [
    {
      "workout_id": "abc123",
      "sport": "Cycling",
      "start_time_utc": "2026-01-15T10:00:00Z",
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
GET /api/workouts/{workout_id}?athlete_id=rob
```

Retrieve full workout data including time series records.

**Route Parameters:**

- `workout_id` (required): Unique workout identifier

**Query Parameters:**

- `athlete_id` (required): Athlete identifier

**Response:**

```json
{
  "workout_id": "abc123",
  "athlete_id": "rob",
  "sport": "Cycling",
  "start_time_utc": "2026-01-15T10:00:00Z",
  "duration_sec": 3600,
  "hr_avg_bpm": 145,
  "pwr_avg_watts": 220,
  "z2_minutes": 50,
  "pwr_hr_decoupling_pct": 2.5,
  "records": [
    {
      "heart_rate": 145,
      "power": 220,
      "cadence": 90
    }
  ]
}
```

**Use cases:**

- Deep dive into specific workout
- Examining time series data
- Analyzing workout quality

---

### 4. Weekly Rollups

```http
GET /api/rollups/weekly?athlete_id=rob&weeks=16
```

Get aggregated weekly training data.

**Query Parameters:**

- `athlete_id` (required): Athlete identifier
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
      "z2_minutes": 200,
      "intensity_minutes": 45
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

- `athlete_id` (required): Athlete identifier
- `days` (optional): Number of days to analyze (default 30, max 365)

**Response:**

```json
{
  "athlete_id": "rob",
  "query_window": {
    "start_date": "2025-12-16T00:00:00Z",
    "end_date": "2026-01-15T00:00:00Z",
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
    "start_date": "2025-10-17T00:00:00Z",
    "end_date": "2026-01-15T00:00:00Z",
    "days": 90
  },
  "samples": [
    {
      "date": "2026-01-15T10:00:00Z",
      "sport": "Cycling",
      "decoupling_pct": 2.5,
      "avg_efficiency": 1.52
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

- All dates use **ISO 8601 format with UTC timezone** (`2026-01-15T10:00:00Z`)
- Date ranges are **inclusive** on both ends
- Default lookback periods are conservative (30-90 days) to protect performance

### Query Constraints

- All endpoints require `athlete_id` for data isolation
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

- [Workout Intelligence Agent Vision](../WORKOUT_INTELLIGENCE_AGENT_VISION.md) - Overall system architecture
- [Workout Schema](../WORKOUT_SCHEMA.md) - Database schema and metrics
- [Testing Guide](../tests/TESTING.md) - Test strategy and execution
