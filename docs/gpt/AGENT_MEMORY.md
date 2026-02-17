# Agent Memory System

Version: 2.1.0

## Overview

The Agent Memory System provides lightweight external memory for the GPT Workout Intelligence Agent using Azure Table Storage. It implements **Option 3 (Hybrid)** from the design: persistent facts in Table Storage + GPT's native memory for conversational continuity.

## Behavioral Alignment

This document describes memory storage and API mechanics. Agent behavior rules live in:

- `INSTRUCTIONS.md` for reasoning and safety rules
- `GPT_ACTIONS_GUIDE.md` for operational API usage

Conversation-start checklist and call order live in `GPT_ACTIONS_GUIDE.md`.

## Architecture

```text
┌─────────────────┐
│ GPT Agent       │
│ (ChatGPT)       │
└────────┬────────┘
         │
         │ 1. GET /api/agent/context (at conversation start)
         │
┌────────▼────────────────────────────────────────┐
│ Agent Memory Handler                            │
│                                                 │
│  • Fetches user preferences                     │
│  • Fetches active observations                  │
│  • Builds instruction addendum                  │
└────────┬────────────────────────────────────────┘
         │
         │ Queries Table Storage
         │
┌────────▼─────────────────────────────────────┐
│ Azure Table Storage                          │
│                                              │
│  ┌─────────────────────┐                     │
│  │ AgentPreferences    │                     │
│  │  - Training goals   │                     │
│  │  - Training phase   │                     │
│  │  - FTP test cadence │                     │
│  └─────────────────────┘                     │
│  │  - Sport prefs      │                     │
│                                              │
│  ┌─────────────────────┐                     │
│  │ AgentObservations   │                     │
│  │  - Active patterns  │                     │
│  │  - Flags            │                     │
│  │  - Insights         │                     │
│  └─────────────────────┘                     │
└──────────────────────────────────────────────┘
```

## What Gets Stored

### User Preferences (AgentPreferences Table)

- **Current training goal** - e.g., "Build base for spring marathon"
- **Training phase** - e.g., "base-building", "build", "peak", "recovery"
- **Preferred sports** - Priority-ordered list
- **FTP test frequency** - How often to prompt for testing
- **Last FTP test date** - Track when last tested
- **Notes** - Free-form context

### Agent Observations (AgentObservations Table)

- **Category** - pattern, flag, insight
- **Summary** - Brief observation (e.g., "Consistent Z2 quality improvement")
- **Details** - Detailed context
- **Referenced workout IDs** - Related workouts
- **Priority** - low, normal, high
- **Status** - active, resolved, archived
- **Expiration** - Optional auto-expiry date

## What Does NOT Get Stored

❌ Workout metrics (stored in Workouts table)  
❌ Computed metrics (generated on-demand)  
❌ LLM interpretations (kept ephemeral)  
❌ Conversation history (handled by GPT)

## API Endpoints

### Get Complete Context (Primary)

```http
GET /api/agent/context?athlete_id=rob
```

Returns:

```json
{
  "athlete_id": "rob",
  "preferences": [
    {
      "preference_id": "pref_abc123",
      "category": "goal",
      "summary": "Build aerobic base for spring races",
      "priority": "high",
      "status": "active",
      "created_at": "2026-01-15T08:00:00+00:00"
    },
    {
      "preference_id": "pref_def456",
      "category": "training_phase",
      "summary": "base-building",
      "priority": "normal",
      "status": "active",
      "created_at": "2026-01-15T08:00:00+00:00"
    }
  ],
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

**Usage:** Call this **FIRST** at conversation start to load context (requires function key).

### Manage Preferences

Preferences are now **multi-item** with stable IDs, similar to observations. Legacy single-record preferences are automatically converted to list format for backward compatibility.

#### List Preferences (requires function key)

```http
GET /api/agent/preferences?athlete_id=rob&status=active&limit=20&code=<function_key>
```

#### Add Preference (requires function key)

```http
POST /api/agent/preferences?code=<function_key>
Content-Type: application/json

{
  "athlete_id": "rob",
  "category": "goal",
  "summary": "Build aerobic base for spring races",
  "details": "Focus on Z2 volume and consistency",
  "priority": "high"
}
```

#### Update Preference (requires function key)

```http
PATCH /api/agent/preferences/{preference_id}?code=<function_key>
Content-Type: application/json

{
  "athlete_id": "rob",
  "status": "resolved"
}
```

### Manage Observations

#### List Observations (requires function key)

```http
GET /api/agent/observations?athlete_id=rob&status=active&limit=20&code=<function_key>
```

#### Add Observation (requires function key)

```http
POST /api/agent/observations?code=<function_key>
Content-Type: application/json

{
  "athlete_id": "rob",
  "category": "pattern",
  "summary": "Strong Z2 quality improvement",
  "details": "Decoupling consistently <5% in last 6 sessions",
  "workout_ids": ["workout-123", "workout-456"],
  "priority": "normal",
  "expires_days": 30
}
```

#### Update Observation Status (requires function key)

```http
PATCH /api/agent/observations/{observation_id}?code=<function_key>
Content-Type: application/json

{
  "athlete_id": "rob",
  "status": "resolved"
}
```

## Benefits

✅ **Persistent context** - Training goals survive across sessions  
✅ **Pattern tracking** - Agent can flag observations for future reference  
✅ **Lightweight** - Minimal storage overhead  
✅ **Separation of concerns** - Memory ≠ metrics  
✅ **GPT-compatible** - Works with ChatGPT's native memory  
✅ **Deterministic** - Facts, not interpretations

For operational usage patterns, call order, and integration examples, see [GPT_ACTIONS_GUIDE.md](./GPT_ACTIONS_GUIDE.md).

## Future Enhancements (Post-MVP)

- Auto-expire observations based on `expires_at`
- Observation categories (trend, warning, achievement)
- Preference validation rules
- Bulk observation updates
- Observation search/filtering
- Training phase transitions
- Goal progress tracking

## Implementation Details

**Tables:** `AgentPreferences`, `AgentObservations`  
**Handler:** `AgentMemoryHandler` (FitParser/handlers/agent_memory_handler.py)  
**Models:** `AgentPreferences`, `AgentObservation` (FitParser/models/agent.py)  
**Storage:** Azure Table Storage (same as Workouts)
