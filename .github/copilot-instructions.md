# Copilot Instructions — Workout Intelligence Agent

These instructions govern how Copilot should analyze and edit code in this repository, which implements a workout intelligence agent that processes workout and physiometric data. The scope is limited to code analysis and edits related to the core data processing, modeling, and versioning logic. The instructions are designed to ensure that all code changes are consistent with the project's documentation and architectural principles, and that they maintain the integrity of the data models and processing pipelines. For queries beyond this scope, revert to default Copilot behavior.

## 1. Canonical Semantics

- The `docs/` directory is the authoritative specification for data models, invariants, pipeline stages, storage schema, and versioning policy.
- Use [docs/README.md](../docs/README.md) to locate the right source of truth.
- If code behavior contradicts documentation, surface the inconsistency explicitly.

## 2. Documentation-First Analysis

- Start with relevant files in `docs/` before analyzing implementation.
- Reference the exact documents you relied on when proposing changes.
- Surface mismatches instead of silently reconciling them.

## 3. Architectural Discipline

Prefer:

- Object-oriented design (OOAD) and OOP patterns in Python for maintainable, understandable code
- Typed models with clear contracts
- Clear DTO boundaries
- Idempotent functions
- Stateless services
- Explicit dependency injection

Avoid:

- Hidden coupling
- Schema mutation without version bump
- Side effects not logged
- Implicit global state

## 4. Versioning and Change Management

- Record code changes in [docs/CHANGELOG.md](../docs/CHANGELOG.md).
- Bump ingestion SemVer whenever changes affect ingestion, parsing, or stored workout/physiometrics schema, and update [docs/devops/INGESTION_SCHEMA.md](../docs/devops/INGESTION_SCHEMA.md).
- For versioned Markdown files, follow the SemVer policy in that file; otherwise use standard SemVer rules.

## 5. Non-Recursive Edits

- Keep instruction edits scoped to the explicit request; avoid adding meta-rules that govern future edits of these instructions.

---

## 6. Miscellaneous

- This project prioritizes correctness, reproducibility, and long-term maintainability over speed of iteration.
- When in doubt, err on the side of explicitness and clarity, even if it means more verbose code. Human legibility is paramount.
- Provide a concise rationale in chat for non-trivial code changes, especially if they deviate from established patterns or documentation. This helps the user understand the reasoning and learn from the change and steer you more effectively in future interactions.
- In Plan mode, regard questions as queries for information gathering and/or suggestions. Provide detailed answers that reference specific documentation or code sections.
