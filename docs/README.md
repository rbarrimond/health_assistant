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

- **[gpt/README.md](./gpt/README.md)** — GPT documentation architecture, authority hierarchy, and routing map
- **[gpt/INSTRUCTIONS.md](./gpt/INSTRUCTIONS.md)** — Behavioral rules, reasoning constraints, and safety guidelines
- **[gpt/GPT_ACTIONS_GUIDE.md](./gpt/GPT_ACTIONS_GUIDE.md)** — Operational API usage patterns, endpoint call order
- **[gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md](./gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md)** — Philosophy, design principles, operating model
- **[gpt/AGENT_MEMORY.md](./gpt/AGENT_MEMORY.md)** — Memory system mechanics, storage contracts
- **[gpt/SEMANTIC_LAYER_API.md](./gpt/SEMANTIC_LAYER_API.md)** — Semantic interpretation and cognitive guidance for training decisions
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

- **[devops/OPERATIONS_API.md](./devops/OPERATIONS_API.md)** — Operations workflow playbook (runbook guidance)
- **[devops/DEPLOYMENT.md](./devops/DEPLOYMENT.md)** — Deployment procedures and infrastructure setup
- **[devops/MONITORING.md](./devops/MONITORING.md)** — Monitoring, logging, observability
- **[devops/CHAOS.md](./devops/CHAOS.md)** — Chaos engineering and reliability testing
- **[devops/BACKENDS.md](./devops/BACKENDS.md)** — Backend services and integrations

### API Contract Source of Truth

- **`api_docs/openapi.yaml`** — Normative GPT-facing API contract (paths, params, schemas, auth, canonical examples)
- **`api_docs/openapi.operations.yaml`** — Normative operations/admin API contract

### Development

- **[devops/data_architecture/INGESTION_SCHEMA.md](./devops/data_architecture/INGESTION_SCHEMA.md)** — Ingestion versioning and schema requirements
- **[CHANGELOG.md](./CHANGELOG.md)** — Version history and change log

### Data Architecture

- **[devops/data_architecture/CANONICAL_DATA_ARCHITECTURE.md](./devops/data_architecture/CANONICAL_DATA_ARCHITECTURE.md)** — Architecture philosophy and data flow
- **[devops/data_architecture/CANONICAL_ANALYTICS_SURFACE.md](./devops/data_architecture/CANONICAL_ANALYTICS_SURFACE.md)** — Deterministic analytics contract
- **[devops/data_architecture/CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT.md](./devops/data_architecture/CANONICAL_ANALYTICS_DETERMINISTIC_FORMULA_CONTRACT.md)** — Metric formulas and invariants
- **[devops/data_architecture/INGESTION_SCHEMA.md](./devops/data_architecture/INGESTION_SCHEMA.md)** — Ingestion contracts and version registry

---

## Quick Start

### For Custom GPT Setup

1. Upload all files from `gpt/` folder (7 core files)
2. Optionally upload files from `gpt/context/` folder (3 context files)
3. Configure ChatGPT Actions using `api_docs/openapi.yaml`

### For Developers

1. Start with [gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md](./gpt/WORKOUT_INTELLIGENCE_AGENT_VISION.md) for system design
2. Review [gpt/README.md](./gpt/README.md) for authority boundaries before editing docs
3. Use `api_docs/openapi.yaml` and `api_docs/openapi.operations.yaml` for contract updates
4. Review [gpt/SEMANTIC_LAYER_API.md](./gpt/SEMANTIC_LAYER_API.md) for semantic interpretation guidance
5. See [devops/OPERATIONS_API.md](./devops/OPERATIONS_API.md) for workflow/runbook guidance
6. Follow [devops/DEPLOYMENT.md](./devops/DEPLOYMENT.md) for getting started
7. Check module docstrings in `config/constants.py` and `TrainingAnalyticsPlatform/models/constants.py` for constants architecture

---

## Documentation Governance

- Update OpenAPI first for any API contract change.
- Keep markdown docs contract-light and cognition/operations focused.
- Do not duplicate request/response schema examples outside OpenAPI.
- If semantic behavior changes, update both OpenAPI descriptions/examples and GPT semantic guidance docs.

---

## Cross-References

All relative links within each folder remain valid. Cross-folder references use appropriate relative paths (e.g., `../devops/DEPLOYMENT.md` or `../../api_docs/openapi.yaml`).
