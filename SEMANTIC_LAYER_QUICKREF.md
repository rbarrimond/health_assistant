# Semantic Access Layer - Quick Reference

## 🎯 Core Concept

The semantic layer answers **meaningful questions** about training, not raw database queries.

## 🔑 Key Endpoint (Use This First!)

```http
GET /api/planning/context?athlete_id=rob&days=45
```

Answers: *"Given what I've actually done, what does tomorrow look like?"*

Returns: Recent workouts, weekly rollups, last hard day, Z2 volume, intensity minutes, data flags

---

## 📋 All Endpoints

| Endpoint | Purpose | Example |
| -------- | ------- | ------- |
| `/api/planning/context` | Planning decisions | `?athlete_id=rob&days=45` |
| `/api/workouts` | List workouts | `?athlete_id=rob&since=2026-01-01&sport=Cycling` |
| `/api/workouts/{id}` | Workout detail | `/{workout_id}?athlete_id=rob` |
| `/api/rollups/weekly` | Weekly summaries | `?athlete_id=rob&weeks=16` |
| `/api/analysis/zones` | Zone distribution | `?athlete_id=rob&days=30` |
| `/api/analysis/efficiency` | Efficiency trends | `?athlete_id=rob&days=90` |

---

## 🛡️ Built-in Protections

- ✓ All queries require `athlete_id`
- ✓ Workout queries: max 200
- ✓ Days lookback: max 365
- ✓ Weeks: max 52
- ✓ Summary-first (time series on demand only)

---

## 🤖 ChatGPT Usage Patterns

### "What should I do tomorrow?"

```text
→ GET /api/planning/context?athlete_id=rob&days=45
→ Returns: Last hard day, Z2 volume, intensity load, flags
```

### "Show me my cycling workouts from January"

```text
→ GET /api/workouts?athlete_id=rob&sport=Cycling&since=2026-01-01
→ Returns: Filtered workout summaries
```

### "How is my aerobic efficiency trending?"

```text
→ GET /api/analysis/efficiency?athlete_id=rob&days=90
→ Returns: Decoupling samples and averages
```

### "Am I getting enough Z2?"

```text
→ GET /api/analysis/zones?athlete_id=rob&days=30
→ Returns: Zone percentages and totals
```

---

## 🧪 Testing

```bash
# Unit tests (27 tests)
pytest tests/test_semantic_layer.py -v

# Integration tests (17 tests)
pytest tests/test_semantic_layer_endpoints.py -v

# All semantic layer tests (44 tests)
pytest tests/test_semantic*.py -v
```

---

## 🚀 Local Development

```bash
# Start Functions host
func host start

# Test planning context
curl "http://localhost:7071/api/planning/context?athlete_id=rob&days=30"

# Test workouts list
curl "http://localhost:7071/api/workouts?athlete_id=rob&limit=10"

# Test specific workout
curl "http://localhost:7071/api/workouts/{workout_id}?athlete_id=rob"
```

---

## 📊 Response Formats

All endpoints return JSON with:

- ✓ Consistent error format: `{"error": "description"}`
- ✓ ISO 8601 dates with UTC (`2026-01-15T10:00:00Z`)
- ✓ Status codes: 200 OK, 400 Bad Request, 404 Not Found, 500 Error

---

## 🎨 Design Philosophy

> **"You don't want the system to tell you what to do.  
> You want it to tell you what is true, and why that matters."**

This layer:

- **Does**: Shape data for reasoning, answer semantic questions, protect performance
- **Does NOT**: Generate recommendations, expose raw tables, make judgments

---

## 📖 Full Documentation

- [SEMANTIC_LAYER_API.md](SEMANTIC_LAYER_API.md) - Complete API reference
- [WORKOUT_INTELLIGENCE_AGENT_VISION.md](WORKOUT_INTELLIGENCE_AGENT_VISION.md) - System architecture
- [SEMANTIC_LAYER_SUMMARY.md](SEMANTIC_LAYER_SUMMARY.md) - Implementation details
