# Agent Memory System

Version: 2.1.1

> **Document role:** Memory architecture and behavioral storage guidance.
> Endpoint contracts (paths, parameters, payload schemas, auth) are normative in [`openapi.yaml`](../../api_docs/openapi.yaml).

## Overview

The Agent Memory System provides lightweight external memory for the GPT Workout Intelligence Agent using Azure Table Storage. It implements a hybrid approach: persistent facts in Table Storage + GPT native conversation memory.

## Behavioral Alignment

This document covers memory storage semantics. Behavior authority lives in:

- [`INSTRUCTIONS.md`](./INSTRUCTIONS.md) for reasoning and safety rules
- [`GPT_ACTIONS_GUIDE.md`](./GPT_ACTIONS_GUIDE.md) for operational call order

## Architecture

```text
┌─────────────────┐
│ GPT Agent       │
│ (ChatGPT)       │
└────────┬────────┘
         │
         │ 1. GET /api/agent/context (conversation start)
         │
┌────────▼────────────────────────────────────────┐
│ Agent Memory Handler                            │
│                                                 │
│  • Retrieves active preference items            │
│  • Retrieves active observations                │
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
│  │  - Preference items │                     │
│  │  - Stable IDs       │                     │
│  └─────────────────────┘                     │
│                                              │
│  ┌─────────────────────┐                     │
│  │ AgentObservations   │                     │
│  │  - Pattern/flag     │                     │
│  │  - Status lifecycle │                     │
│  │  - Optional expiry  │                     │
│  └─────────────────────┘                     │
└──────────────────────────────────────────────┘
```

## What Gets Stored

### Preference Items (AgentPreferences table)

- `category`: semantic grouping (goal, schedule, timezone, constraints)
- `summary`: compact preference statement
- `details`: optional extended context
- `priority`: low / normal / high
- `status`: active / resolved / archived
- stable identifiers and timestamps for lifecycle tracking

### Observations (AgentObservations table)

- category, summary, details
- optional workout references
- priority and status lifecycle
- optional expiration to prevent stale context accumulation

## What Does NOT Get Stored

❌ Raw workout metrics (stored in workout domain storage)
❌ Computed analytics (derived on demand)
❌ LLM interpretations as persistent truth
❌ Full conversation transcripts

## Design Intent

- **Persistent context, not persistent reasoning**
- **Lifecycle-aware records** (status transitions and archival)
- **Separation of concerns** between memory facts and analytics data
- **Deterministic retrieval** for conversation grounding

## API Contract Source

For endpoint details and payload contracts, use [`openapi.yaml`](../../api_docs/openapi.yaml):

- `/api/agent/context`
- `/api/agent/preferences` and `/api/agent/preferences/{preference_id}`
- `/api/agent/observations` and `/api/agent/observations/{observation_id}`

## Future Enhancements

- TTL policies for low-priority observations
- Preference conflict detection (active contradictory goals)
- Better deduplication and merge hints for repeated observations
- Optional source attribution fields for externally injected memory
