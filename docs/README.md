# Documentation Overview

This directory contains all documentation for the Health Assistant / Workout Intelligence Agent system.

## File Organization

These files are organized in a **flat structure** to support Custom GPT configurations, which require all knowledge files in a single directory.

---

## Agent Behavior & Operations

Core files defining how the agent thinks and operates:

- **[INSTRUCTIONS.md](./INSTRUCTIONS.md)** — Behavioral rules, reasoning constraints, and safety guidelines for the agent
- **[GPT_ACTIONS_GUIDE.md](./GPT_ACTIONS_GUIDE.md)** — Operational API usage patterns, endpoint call order, and integration examples
- **[WORKOUT_INTELLIGENCE_AGENT_VISION.md](./WORKOUT_INTELLIGENCE_AGENT_VISION.md)** — High-level philosophy, design principles, and operating model
- **[AGENT_MEMORY.md](./AGENT_MEMORY.md)** — Memory system mechanics, storage contracts, and API payloads

---

## API Contracts & Schemas

Technical reference for API endpoints and data models:

- **[SEMANTIC_LAYER_API.md](./SEMANTIC_LAYER_API.md)** — Complete endpoint inventory with request/response contracts
- **[WORKOUT_SCHEMA.md](./WORKOUT_SCHEMA.md)** — Workout data model and field definitions
- **[INGESTION_SCHEMA.md](./INGESTION_SCHEMA.md)** — Ingestion versioning and schema requirements

---

## Domain Knowledge

Athlete-specific and training-specific context:

- **[ROB_CONTEXT.md](./ROB_CONTEXT.md)** — Athlete profile, training history, and personal context
- **[CYCLING_CONTEXT.md](./CYCLING_CONTEXT.md)** — Cycling-specific training concepts and terminology
- **[MOVESMETHOD_CONTEXT.md](./MOVESMETHOD_CONTEXT.md)** — Moves Method training philosophy and framework

---

## Operations & Infrastructure

Deployment, monitoring, and backend services:

- **[DEPLOYMENT.md](./DEPLOYMENT.md)** — Deployment procedures and infrastructure setup
- **[MONITORING.md](./MONITORING.md)** — Monitoring, logging, and observability
- **[CHAOS.md](./CHAOS.md)** — Chaos engineering and reliability testing
- **[BACKENDS.md](./BACKENDS.md)** — Backend services and integrations

---

## Audit Trail

- **[CHANGELOG.md](./CHANGELOG.md)** — Version history and change log for all documentation and code

---

## Usage Notes

### For Custom GPTs

All files can be uploaded to the "Knowledge" section of a Custom GPT. The agent will use:

1. **INSTRUCTIONS.md** — for behavioral constraints
2. **GPT_ACTIONS_GUIDE.md** — for API usage patterns
3. **SEMANTIC_LAYER_API.md** — for endpoint contracts
4. Domain files as needed for context

### For Developers

Start with:

- **WORKOUT_INTELLIGENCE_AGENT_VISION.md** for the high-level design
- **SEMANTIC_LAYER_API.md** for API reference
- **DEPLOYMENT.md** for getting started

### Cross-References

Files reference each other using relative links (e.g., `[INSTRUCTIONS.md](./INSTRUCTIONS.md)`). All references remain valid within the flat structure.
