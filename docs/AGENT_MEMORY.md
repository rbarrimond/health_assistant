# Agent Memory System

Version: 1.0.2

## Overview

The Agent Memory System provides lightweight external memory for the GPT Workout Intelligence Agent using Azure Table Storage. It implements **Option 3 (Hybrid)** from the design: persistent facts in Table Storage + GPT's native memory for conversational continuity.

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

**Usage:** Call this **FIRST** at conversation start to load context.

### Manage Preferences

#### Get Preferences

```http
GET /api/agent/preferences?athlete_id=rob
```

#### Update Preferences (requires function key)

```http
POST /api/agent/preferences?code=<function_key>
Content-Type: application/json

{
  "athlete_id": "rob",
  "current_goal": "Build aerobic base for spring races",
  "training_phase": "base-building",
  "preferred_sports": ["cycling", "running"],
  "ftp_test_frequency_weeks": 6
}
```

### Manage Observations

#### List Observations

```http
GET /api/agent/observations?athlete_id=rob&status=active&limit=20
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

## Usage Pattern

### 1. Conversation Start

```text
Agent calls: GET /api/agent/context
→ Loads user preferences and active observations into context
→ Uses instruction_addendum to inform responses
```

### 2. During Conversation

- Agent uses preferences to tailor advice
- Agent references active observations
- Agent relies on GPT's native memory for conversation flow

### 3. Update Preferences (Manual or Agent-Triggered)

```text
User says: "My goal is to build base for spring marathon"
→ Agent or system calls: POST /api/agent/preferences
→ Update stored for future sessions
```

### 4. Add Observations (Manual or Agent-Triggered)

```text
Agent notices pattern: "User has consistent low decoupling"
→ System calls: POST /api/agent/observations
→ Flagged for future reference
```

## Benefits

✅ **Persistent context** - Training goals survive across sessions  
✅ **Pattern tracking** - Agent can flag observations for future reference  
✅ **Lightweight** - Minimal storage overhead  
✅ **Separation of concerns** - Memory ≠ metrics  
✅ **GPT-compatible** - Works with ChatGPT's native memory  
✅ **Deterministic** - Facts, not interpretations

## Example Flow

```text
User: "What should I do today?"

Agent:
1. GET /api/agent/context
   → Loads: goal="build base", phase="base-building", obs="low decoupling"
   
2. GET /api/planning/context?days=45
   → Gets workout data
   
3. Synthesizes response:
   "Based on your goal (building aerobic base) and recent low decoupling,
   suggest Z2 ride focusing on steady output..."
```

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
**Models:** `AgentPreferences`, `AgentObservation` (FitParser/models.py)  
**Storage:** Azure Table Storage (same as Workouts)
