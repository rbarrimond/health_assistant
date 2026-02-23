# Documentation Overview

This directory contains all documentation for the Health Assistant / Workout Intelligence Agent system.

## File Organization

Documentation is organized by audience:

- **`gpt/`** — GPT Knowledge (upload to Custom GPT)
- **`gpt/context/`** — Domain-specific context (optional upload)
- **`devops/`** — Developer & operations reference (do not upload to GPT)

---

## GPT Knowledge (Upload to Custom GPT)

Core agent behavior and API contracts for ChatGPT:

- **[gpt/INSTRUCTIONS.md](./gpt/INSTRUCTIONS.md)** — Behavioral rules, reasoning constraints, and safety guidelines
- **[gpt/GPT_ACTIONS_GUIDE.md](./gpt/GPT_ACTIONS_GUIDE.md)** — Operational API usage patterns, endpoint call order
- **[gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md](./gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md)** — Philosophy, design principles, operating model
- **[gpt/AGENT_MEMORY.md](./gpt/AGENT_MEMORY.md)** — Memory system mechanics, storage contracts
- **[gpt/SEMANTIC_LAYER_API.md](./gpt/SEMANTIC_LAYER_API.md)** — GPT-facing endpoint inventory (mirrors `openapi.yaml`)
- **[gpt/WORKOUT_SCHEMA.md](./gpt/WORKOUT_SCHEMA.md)** — Workout data model and field definitions

---

## Domain Context (Optional GPT Upload)

Athlete-specific and training-specific knowledge:

- **[gpt/context/ROB_CONTEXT.md](./gpt/context/ROB_CONTEXT.md)** — Athlete profile, training history
- **[gpt/context/CYCLING_CONTEXT.md](./gpt/context/CYCLING_CONTEXT.md)** — Cycling training concepts
- **[gpt/context/MOVESMETHOD_CONTEXT.md](./gpt/context/MOVESMETHOD_CONTEXT.md)** — Moves Method philosophy

---

## Developer & Operations Reference

**Do not upload to Custom GPT. For developers only.**

### Operations & Infrastructure

- **[devops/OPERATIONS_API.md](./devops/OPERATIONS_API.md)** — Admin/write endpoints (mirrors `openapi.operations.yaml`)
- **[devops/DEPLOYMENT.md](./devops/DEPLOYMENT.md)** — Deployment procedures and infrastructure setup
- **[devops/MONITORING.md](./devops/MONITORING.md)** — Monitoring, logging, observability
- **[devops/CHAOS.md](./devops/CHAOS.md)** — Chaos engineering and reliability testing
- **[devops/BACKENDS.md](./devops/BACKENDS.md)** — Backend services and integrations

### Development

- **[devops/INGESTION_SCHEMA.md](./devops/INGESTION_SCHEMA.md)** — Ingestion versioning and schema requirements
- **[CHANGELOG.md](./CHANGELOG.md)** — Version history and change log

---

## Quick Start

### For Custom GPT Setup

1. Upload all files from `gpt/` folder (6 core files)
2. Optionally upload files from `gpt/context/` folder (3 context files)
3. Configure ChatGPT Actions using `api_docs/openapi.yaml`

### For Developers

1. Start with [gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md](./gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md) for system design
2. Review [gpt/SEMANTIC_LAYER_API.md](./gpt/SEMANTIC_LAYER_API.md) for GPT-facing API reference
3. See [devops/OPERATIONS_API.md](./devops/OPERATIONS_API.md) for admin endpoints
4. Follow [devops/DEPLOYMENT.md](./devops/DEPLOYMENT.md) for getting started
5. Check module docstrings in `config/constants.py` and `TrainingAnalyticsPlatform/models/constants.py` for constants architecture

---

## Cross-References

All relative links within each folder remain valid. Cross-folder references use appropriate relative paths (e.g., `../devops/DEPLOYMENT.md` or `../../api_docs/openapi.yaml`).
